"""
Ingest a raw batch (the original handover, or a later day's drop) and merge
it into the canonical `leads` table.

Entity resolution: the same real lead can show up under different lead_ids
(scraped twice, re-entered by a different rep, re-appearing in a later
drop). We match on normalized email OR phone OR Instagram handle - any one
match is enough to treat two rows as the same entity, so a row can be
chained into an existing lead `via the handle even if e.g. only the email
matched on a different row of the cluster.

This runs every time you ingest, including the day-2 drop, which is why a
handle/email already in the system gets folded into the existing lead
instead of becoming a duplicate "new" lead.
"""
import json
from datetime import datetime, timezone

import pandas as pd

from . import clean
from .classify import classify_channel, classify_lead_type, classify_segment

RAW_COLUMNS = [
    "lead_id", "source", "handle", "store_name", "contact_name", "email",
    "phone", "city", "country", "followers", "active_listings",
    "avg_listing_price_gbp", "sales_velocity_30d", "est_monthly_spend_gbp",
    "stage", "first_seen_date", "last_touch_date", "num_touches",
    "last_inbound_text", "assigned_bdr", "notes",
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def load_batch(path: str, sheet_name) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet_name)
    for col in RAW_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[RAW_COLUMNS]


def _clean_row(row) -> dict:
    email, email_malformed = clean.clean_email(row["email"])
    phone, phone_malformed, phone_region_guessed = clean.clean_phone(row["phone"])
    handle = clean.clean_handle(row["handle"])
    flags = []
    if email_malformed:
        flags.append("malformed_email_fixed")
    if pd.notna(row["email"]) and email is None:
        flags.append("malformed_email_unrecoverable")
    if phone_malformed:
        flags.append("malformed_phone_unrecoverable")

    return dict(
        lead_id=str(row["lead_id"]).strip(),
        source_label=None if pd.isna(row["source"]) else str(row["source"]).strip(),
        handle=handle,
        store_name=None if pd.isna(row["store_name"]) else str(row["store_name"]).strip(),
        contact_name=None if pd.isna(row["contact_name"]) else str(row["contact_name"]).strip(),
        email=email,
        phone=phone,
        phone_region_guessed=phone_region_guessed,
        city=None if pd.isna(row["city"]) else str(row["city"]).strip(),
        country=None if pd.isna(row["country"]) else str(row["country"]).strip(),
        followers=clean.clean_numeric(row["followers"]),
        active_listings=clean.clean_numeric(row["active_listings"]),
        avg_listing_price_gbp=clean.clean_numeric(row["avg_listing_price_gbp"]),
        sales_velocity_30d=clean.clean_numeric(row["sales_velocity_30d"]),
        est_monthly_spend_gbp=clean.clean_spend(row["est_monthly_spend_gbp"]),
        stage=clean.clean_stage(row["stage"]),
        first_seen_date=clean.clean_date(row["first_seen_date"]),
        last_touch_date=clean.clean_date(row["last_touch_date"]),
        num_touches=int(clean.clean_numeric(row["num_touches"]) or 0),
        last_inbound_text=(None if pd.isna(row["last_inbound_text"])
                            else str(row["last_inbound_text"]).strip()) or None,
        assigned_bdr=None if pd.isna(row["assigned_bdr"]) else str(row["assigned_bdr"]).strip(),
        notes=None if pd.isna(row["notes"]) else str(row["notes"]).strip(),
        flags=flags,
    )


class MatchIndex:
    """In-memory email/phone-key/handle -> lead_key lookup, built once per
    ingest run and updated as we go. This is what keeps ingest O(n) instead
    of O(n^2): without it, matching each new row would mean scanning the
    (growing) leads table on every row, which is fine at 265 rows and falls
    over hard at 30,000+.

    Phone matching is an exact E.164 string match - `clean.clean_phone`
    does real parsing via the `phonenumbers` library, so the same number
    written three different ways already normalizes to one identical
    string, with no fuzzy/heuristic matching needed (and no cross-country
    collision risk from a digits-stripping shortcut).
    """

    def __init__(self, conn):
        self.by_email, self.by_phone, self.by_handle = {}, {}, {}
        for row in conn.execute(
            "SELECT lead_key, email, phone, handle FROM leads"
        ).fetchall():
            if row["email"]:
                self.by_email[row["email"]] = row["lead_key"]
            if row["phone"]:
                self.by_phone[row["phone"]] = row["lead_key"]
            if row["handle"]:
                self.by_handle[row["handle"]] = row["lead_key"]

    def find(self, c: dict):
        """Returns (lead_key, match_type) or (None, None). match_type tells
        the caller *which* field matched - a phone-only match where the
        number's country had to be guessed (no explicit country code in
        the raw data) is still flagged lower-confidence than email/handle,
        since that's the one remaining real ambiguity."""
        if c["email"] and c["email"] in self.by_email:
            return self.by_email[c["email"]], "email"
        if c["phone"] and c["phone"] in self.by_phone:
            return self.by_phone[c["phone"]], "phone"
        if c["handle"] and c["handle"] in self.by_handle:
            return self.by_handle[c["handle"]], "handle"
        return None, None

    def register(self, lead_key: str, c: dict):
        if c["email"]:
            self.by_email[c["email"]] = lead_key
        if c["phone"]:
            self.by_phone[c["phone"]] = lead_key
        if c["handle"]:
            self.by_handle[c["handle"]] = lead_key


def _merge_fields(existing, new: dict) -> dict:
    """Most-complete-and-most-advanced merge: fill blanks, keep the more
    advanced funnel stage, the latest touch, the earliest first-seen, and
    don't double-count touches across duplicate snapshots of the same lead."""
    def pick(a, b):
        return a if a not in (None, "", "nan") else b

    merged = dict(existing)
    for key in ("handle", "store_name", "contact_name", "email", "phone", "city",
                "country", "last_inbound_text", "assigned_bdr"):
        merged[key] = pick(existing[key], new[key])

    for key in ("followers", "active_listings", "avg_listing_price_gbp",
                "sales_velocity_30d", "est_monthly_spend_gbp"):
        merged[key] = existing[key] if existing[key] is not None else new[key]

    existing_stage = existing["stage"]
    new_stage = new["stage"]
    merged["stage"] = (new_stage if clean.STAGE_RANK.get(new_stage, 0) >
                        clean.STAGE_RANK.get(existing_stage, 0) else existing_stage)

    dates = [d for d in (existing["first_seen_date"], new["first_seen_date"]) if d]
    merged["first_seen_date"] = min(dates) if dates else None
    dates = [d for d in (existing["last_touch_date"], new["last_touch_date"]) if d]
    merged["last_touch_date"] = max(dates) if dates else None

    merged["num_touches"] = max(existing["num_touches"] or 0, new["num_touches"] or 0)

    notes = [n for n in (existing["notes"], new["notes"]) if n]
    merged["notes"] = " | ".join(dict.fromkeys(notes)) if notes else None

    existing_ids = set(existing["source_lead_ids"].split(",")) if existing["source_lead_ids"] else set()
    merged["source_lead_ids"] = ",".join(sorted(existing_ids | {new["lead_id"]}))

    existing_flags = set(json.loads(existing["data_quality_flags"] or "[]"))
    merged["data_quality_flags"] = clean.flags_to_json(existing_flags | set(new["flags"]))

    return merged


def ingest_batch(conn, path: str, sheet_name, batch_label: str) -> dict:
    """Returns a small summary dict: rows seen, new entities, merged entities."""
    df = load_batch(path, sheet_name)
    now = _now()
    stats = {"rows_seen": len(df), "new_leads": 0, "merged_into_existing": 0}

    raw_intake_rows = [
        (batch_label, now, str(r["lead_id"]), json.dumps(r.to_dict(), default=str))
        for _, r in df.iterrows()
    ]
    conn.executemany(
        "INSERT INTO raw_intake (batch_label, ingested_at, raw_lead_id, raw_json) VALUES (?,?,?,?)",
        raw_intake_rows,
    )

    index = MatchIndex(conn)
    # Cache full existing lead rows we touch so repeat matches within the
    # same batch (a row matching another row from this same file) merge
    # against the latest in-memory state, not a stale DB read.
    leads_cache = {}
    merge_events = []  # which existing lead_keys got merged into during this batch

    for _, raw_row in df.iterrows():
        c = _clean_row(raw_row)
        match_key, match_type = index.find(c)
        existing = leads_cache.get(match_key) if match_key else None
        if match_key and existing is None:
            row = conn.execute("SELECT * FROM leads WHERE lead_key=?", (match_key,)).fetchone()
            existing = dict(row)
            leads_cache[match_key] = existing

        if existing:
            # With real E.164 phone parsing, a phone-only match is exact-string
            # equality, not a fuzzy heuristic - the residual risk isn't
            # cross-country collision anymore, it's the GB region guess applied
            # to numbers with no explicit country code (every non-UK number
            # actually seen in this data carries an explicit +CC, so this is a
            # forward-looking safeguard against a future bad batch, not a known
            # live issue). Flag only that narrower case for review.
            if match_type == "phone" and c.get("phone_region_guessed"):
                c["flags"].append("low_confidence_phone_merge")

            merged = _merge_fields(existing, c)
            merged["channel"] = classify_channel(merged["email"], merged["phone"], merged["handle"])
            merged["lead_type"] = classify_lead_type(merged["store_name"], merged["handle"],
                                                       merged["followers"], merged["active_listings"],
                                                       merged["sales_velocity_30d"])
            merged["segment"] = classify_segment(merged["lead_type"], merged["active_listings"],
                                                  merged["sales_velocity_30d"])
            merged["updated_at"] = now
            leads_cache[existing["lead_key"]] = merged
            index.register(existing["lead_key"], c)
            stats["merged_into_existing"] += 1
            merge_events.append(existing["lead_key"])
        else:
            lead_key = f"lead:{c['lead_id']}"
            channel = classify_channel(c["email"], c["phone"], c["handle"])
            lead_type = classify_lead_type(c["store_name"], c["handle"], c["followers"],
                                            c["active_listings"], c["sales_velocity_30d"])
            segment = classify_segment(lead_type, c["active_listings"], c["sales_velocity_30d"])
            new_lead = {
                "lead_key": lead_key,
                "source_lead_ids": c["lead_id"],
                "channel": channel,
                "lead_type": lead_type,
                "segment": segment,
                "source_label": c["source_label"],
                "store_name": c["store_name"],
                "contact_name": c["contact_name"],
                "handle": c["handle"],
                "email": c["email"],
                "phone": c["phone"],
                "city": c["city"],
                "country": c["country"],
                "followers": c["followers"],
                "active_listings": c["active_listings"],
                "avg_listing_price_gbp": c["avg_listing_price_gbp"],
                "sales_velocity_30d": c["sales_velocity_30d"],
                "est_monthly_spend_gbp": c["est_monthly_spend_gbp"],
                "stage": c["stage"],
                "first_seen_date": c["first_seen_date"],
                "last_touch_date": c["last_touch_date"],
                "num_touches": c["num_touches"],
                "last_inbound_text": c["last_inbound_text"],
                "assigned_bdr": c["assigned_bdr"],
                "notes": c["notes"],
                "data_quality_flags": clean.flags_to_json(c["flags"]),
                "created_at": now,
                "updated_at": now,
            }
            leads_cache[lead_key] = new_lead
            index.register(lead_key, c)
            stats["new_leads"] += 1

    upsert_sql = """
        INSERT INTO leads (
            lead_key, source_lead_ids, channel, lead_type, segment, source_label, store_name,
            contact_name, handle, email, phone, city, country, followers,
            active_listings, avg_listing_price_gbp, sales_velocity_30d,
            est_monthly_spend_gbp, stage, first_seen_date, last_touch_date,
            num_touches, last_inbound_text, assigned_bdr, notes,
            data_quality_flags, created_at, updated_at
        ) VALUES (
            :lead_key, :source_lead_ids, :channel, :lead_type, :segment, :source_label, :store_name,
            :contact_name, :handle, :email, :phone, :city, :country, :followers,
            :active_listings, :avg_listing_price_gbp, :sales_velocity_30d,
            :est_monthly_spend_gbp, :stage, :first_seen_date, :last_touch_date,
            :num_touches, :last_inbound_text, :assigned_bdr, :notes,
            :data_quality_flags, :created_at, :updated_at
        )
        ON CONFLICT(lead_key) DO UPDATE SET
            source_lead_ids=excluded.source_lead_ids, channel=excluded.channel,
            lead_type=excluded.lead_type, segment=excluded.segment,
            handle=excluded.handle, store_name=excluded.store_name,
            contact_name=excluded.contact_name, email=excluded.email,
            phone=excluded.phone, city=excluded.city, country=excluded.country,
            followers=excluded.followers, active_listings=excluded.active_listings,
            avg_listing_price_gbp=excluded.avg_listing_price_gbp,
            sales_velocity_30d=excluded.sales_velocity_30d,
            est_monthly_spend_gbp=excluded.est_monthly_spend_gbp, stage=excluded.stage,
            first_seen_date=excluded.first_seen_date, last_touch_date=excluded.last_touch_date,
            num_touches=excluded.num_touches, last_inbound_text=excluded.last_inbound_text,
            assigned_bdr=excluded.assigned_bdr, notes=excluded.notes,
            data_quality_flags=excluded.data_quality_flags, updated_at=excluded.updated_at
    """
    conn.executemany(upsert_sql, list(leads_cache.values()))
    conn.execute(
        "INSERT INTO ingest_log (batch_label, ingested_at, rows_seen, new_leads, merged_leads) "
        "VALUES (?,?,?,?,?)",
        (batch_label, now, stats["rows_seen"], stats["new_leads"], stats["merged_into_existing"]),
    )
    if merge_events:
        conn.executemany(
            "INSERT INTO ingest_log_merges (batch_label, ingested_at, lead_key) VALUES (?,?,?)",
            [(batch_label, now, lk) for lk in merge_events],
        )
    conn.commit()
    return stats
