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
from .classify import classify_channel

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
    phone_disp, phone_key = clean.clean_phone(row["phone"])
    handle = clean.clean_handle(row["handle"])
    flags = []
    if email_malformed:
        flags.append("malformed_email_fixed")
    if pd.notna(row["email"]) and email is None:
        flags.append("malformed_email_unrecoverable")

    return dict(
        lead_id=str(row["lead_id"]).strip(),
        source_label=None if pd.isna(row["source"]) else str(row["source"]).strip(),
        handle=handle,
        store_name=None if pd.isna(row["store_name"]) else str(row["store_name"]).strip(),
        contact_name=None if pd.isna(row["contact_name"]) else str(row["contact_name"]).strip(),
        email=email,
        phone=phone_disp,
        phone_key=phone_key,
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
    """

    def __init__(self, conn):
        self.by_email, self.by_phone_key, self.by_handle = {}, {}, {}
        for row in conn.execute(
            "SELECT lead_key, email, phone, handle FROM leads"
        ).fetchall():
            if row["email"]:
                self.by_email[row["email"]] = row["lead_key"]
            if row["phone"]:
                digits = "".join(ch for ch in row["phone"] if ch.isdigit())
                if digits:
                    self.by_phone_key[digits[-9:]] = row["lead_key"]
            if row["handle"]:
                self.by_handle[row["handle"]] = row["lead_key"]

    def find(self, c: dict):
        """Returns (lead_key, match_type) or (None, None). match_type tells
        the caller *which* field matched, so a phone-only match (the
        riskiest one - last-9-digits collisions get more likely, not less,
        as the table grows past 30k) can be flagged for human review instead
        of silently trusted like an email or handle match."""
        if c["email"] and c["email"] in self.by_email:
            return self.by_email[c["email"]], "email"
        if c["phone_key"] and c["phone_key"] in self.by_phone_key:
            return self.by_phone_key[c["phone_key"]], "phone"
        if c["handle"] and c["handle"] in self.by_handle:
            return self.by_handle[c["handle"]], "handle"
        return None, None

    def register(self, lead_key: str, c: dict):
        if c["email"]:
            self.by_email[c["email"]] = lead_key
        if c["phone_key"]:
            self.by_phone_key[c["phone_key"]] = lead_key
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

    for _, raw_row in df.iterrows():
        c = _clean_row(raw_row)
        match_key, match_type = index.find(c)
        existing = leads_cache.get(match_key) if match_key else None
        if match_key and existing is None:
            row = conn.execute("SELECT * FROM leads WHERE lead_key=?", (match_key,)).fetchone()
            existing = dict(row)
            leads_cache[match_key] = existing

        if existing:
            # A phone-only match with no corroborating email or handle on
            # either side is the case most likely to be a false merge
            # (different people, same last-9-digits) - flag it rather than
            # silently trusting it, especially as this becomes more likely
            # at scale.
            corroborated = bool(
                (c["email"] and existing["email"] and c["email"] == existing["email"])
                or (c["handle"] and existing["handle"] and c["handle"] == existing["handle"])
            )
            if match_type == "phone" and not corroborated:
                c["flags"].append("low_confidence_phone_merge")

            merged = _merge_fields(existing, c)
            merged["channel"] = classify_channel(merged["email"], merged["phone"], merged["handle"])
            merged["updated_at"] = now
            leads_cache[existing["lead_key"]] = merged
            index.register(existing["lead_key"], c)
            stats["merged_into_existing"] += 1
        else:
            lead_key = f"lead:{c['lead_id']}"
            channel = classify_channel(c["email"], c["phone"], c["handle"])
            new_lead = {
                "lead_key": lead_key,
                "source_lead_ids": c["lead_id"],
                "channel": channel,
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
            lead_key, source_lead_ids, channel, source_label, store_name,
            contact_name, handle, email, phone, city, country, followers,
            active_listings, avg_listing_price_gbp, sales_velocity_30d,
            est_monthly_spend_gbp, stage, first_seen_date, last_touch_date,
            num_touches, last_inbound_text, assigned_bdr, notes,
            data_quality_flags, created_at, updated_at
        ) VALUES (
            :lead_key, :source_lead_ids, :channel, :source_label, :store_name,
            :contact_name, :handle, :email, :phone, :city, :country, :followers,
            :active_listings, :avg_listing_price_gbp, :sales_velocity_30d,
            :est_monthly_spend_gbp, :stage, :first_seen_date, :last_touch_date,
            :num_touches, :last_inbound_text, :assigned_bdr, :notes,
            :data_quality_flags, :created_at, :updated_at
        )
        ON CONFLICT(lead_key) DO UPDATE SET
            source_lead_ids=excluded.source_lead_ids, channel=excluded.channel,
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
    conn.commit()
    return stats
