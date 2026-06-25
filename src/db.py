"""
SQLite schema + connection helper.

Why SQLite and not "just a CSV":
- We need state that survives between runs (what's been actioned, what's been
  sent, what's in cooldown) — a CSV in, CSV out script can't do that without
  re-inventing a database badly.
- Indexed lookups by lead_key/email/phone/handle keep dedup and "is this lead
  already in the system" checks fast even at 30k+ rows, instead of doing
  O(n^2) python loops over every new batch.
- It's a single file with zero infra to stand up, easy to swap for Postgres
  later (same SQL, different connection string) if this became a real service.
"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_intake (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_label     TEXT NOT NULL,
    ingested_at     TEXT NOT NULL,
    raw_lead_id     TEXT,
    raw_json        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
    lead_key                TEXT PRIMARY KEY,
    source_lead_ids         TEXT NOT NULL,   -- comma-joined original lead_ids merged into this entity
    channel                 TEXT NOT NULL,   -- 'direct' (email/phone) or 'instagram_dm' (handle only)
    lead_type                TEXT NOT NULL,   -- 'reseller' or 'store' (independent of channel)
    segment                  TEXT NOT NULL,   -- 'new_reseller' | 'full_time_reseller' | 'business'
    source_label            TEXT,
    store_name              TEXT,
    contact_name            TEXT,
    handle                  TEXT,
    email                   TEXT,
    phone                   TEXT,
    city                    TEXT,
    country                 TEXT,
    followers               REAL,
    active_listings         REAL,
    avg_listing_price_gbp   REAL,
    sales_velocity_30d      REAL,
    est_monthly_spend_gbp   REAL,
    stage                   TEXT NOT NULL,   -- canonicalized stage
    first_seen_date         TEXT,            -- ISO yyyy-mm-dd
    last_touch_date         TEXT,            -- ISO yyyy-mm-dd
    num_touches             INTEGER DEFAULT 0,
    last_inbound_text       TEXT,
    assigned_bdr            TEXT,
    notes                   TEXT,
    data_quality_flags      TEXT,            -- JSON list, e.g. ["malformed_email"]
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_handle ON leads(handle);
CREATE INDEX IF NOT EXISTS idx_leads_channel_stage ON leads(channel, stage);

CREATE TABLE IF NOT EXISTS ingest_log_merges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_label     TEXT NOT NULL,
    ingested_at     TEXT NOT NULL,
    lead_key        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_label     TEXT NOT NULL,
    ingested_at     TEXT NOT NULL,
    rows_seen       INTEGER NOT NULL,
    new_leads       INTEGER NOT NULL,
    merged_leads    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS actions_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_key        TEXT NOT NULL,
    action_date     TEXT NOT NULL,   -- ISO date the action was planned for
    channel         TEXT NOT NULL,
    action_type     TEXT NOT NULL,   -- dm_cold, dm_followup, dm_reengage, email_intro, email_followup, call, visit
    message_draft   TEXT,
    score           REAL,
    status          TEXT NOT NULL DEFAULT 'queued',  -- queued | sent | skipped
    created_at      TEXT NOT NULL,
    FOREIGN KEY (lead_key) REFERENCES leads(lead_key)
);

CREATE INDEX IF NOT EXISTS idx_actions_lead_date ON actions_log(lead_key, action_date);
CREATE INDEX IF NOT EXISTS idx_actions_date_status ON actions_log(action_date, status);
"""


def connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS only creates a table the first time a
    database is built - it does nothing to a leads table that already
    exists from before this column was added. Without this, adding
    github_issue_number to SCHEMA above would silently have zero effect on
    every database created before this change (including the one already
    running in production), and the very first INSERT/UPDATE referencing
    it would throw 'no such column' on a real, already-populated database.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    if "github_issue_number" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN github_issue_number INTEGER")
        conn.commit()
