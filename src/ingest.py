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


def _find_existing_match(conn, c: dict):
    """Look up an existing lead by email, phone_key, or handle. Phone is
    matched on the last-9-digits key to tolerate +44/0044/0-prefix variants."""
    if c["email"]:
        row = conn.execute("SELECT * FROM leads WHERE email = ?", (c["email"],)).fetchone()
        if row:
            return row
    if c["phone_key"]:
        row = conn.execute(
            "SELECT * FROM leads WHERE phone IS NOT NULL AND "
            "substr(replace(replace(replace(phone,'+',''),' ',''),'-',''), -9) = ?",
            (c["phone_key"],),
        ).fetchone()
        if row:
            return row
    if c["handle"]:
        row = conn.execute("SELECT * FROM leads WHERE handle = ?", (c["handle"],)).fetchone()
        if row:
            return row
    return None


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

    for _, raw_row in df.iterrows():
        conn.execute(
            "INSERT INTO raw_intake (batch_label, ingested_at, raw_lead_id, raw_json) VALUES (?,?,?,?)",
            (batch_label, now, str(raw_row["lead_id"]), json.dumps(raw_row.to_dict(), default=str)),
        )
        c = _clean_row(raw_row)
        existing = _find_existing_match(conn, c)

        if existing:
            merged = _merge_fields(existing, c)
            merged["channel"] = classify_channel(merged["email"], merged["phone"], merged["handle"])
            merged["updated_at"] = now
            conn.execute(
                """UPDATE leads SET source_lead_ids=:source_lead_ids, channel=:channel,
                   handle=:handle, store_name=:store_name, contact_name=:contact_name,
                   email=:email, phone=:phone, city=:city, country=:country,
                   followers=:followers, active_listings=:active_listings,
                   avg_listing_price_gbp=:avg_listing_price_gbp,
                   sales_velocity_30d=:sales_velocity_30d,
                   est_monthly_spend_gbp=:est_monthly_spend_gbp, stage=:stage,
                   first_seen_date=:first_seen_date, last_touch_date=:last_touch_date,
                   num_touches=:num_touches, last_inbound_text=:last_inbound_text,
                   assigned_bdr=:assigned_bdr, notes=:notes,
                   data_quality_flags=:data_quality_flags, updated_at=:updated_at
                   WHERE lead_key=:lead_key""",
                {**merged, "lead_key": existing["lead_key"]},
            )
            stats["merged_into_existing"] += 1
        else:
            lead_key = f"lead:{c['lead_id']}"
            channel = classify_channel(c["email"], c["phone"], c["handle"])
            conn.execute(
                """INSERT INTO leads (
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
                )""",
                {
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
                },
            )
            stats["new_leads"] += 1

    conn.commit()
    return stats
