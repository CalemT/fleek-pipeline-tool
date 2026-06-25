"""Proves the exact bug found live: once an action is queued for a lead
today, the message text was permanently stuck even after the underlying
drafting logic was fixed, because the no-double-messaging guarantee
correctly skips re-queuing an already-handled lead - it just had no way to
refresh stale text for something not yet actually sent. `redraft` is the
fix: it updates text for anything still 'queued', and must never touch
anything already 'sent'."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db, drafting  # noqa: E402


def _make_lead(conn, lead_key):
    now = "2026-01-01T00:00:00"
    conn.execute(
        """INSERT INTO leads (lead_key, source_lead_ids, channel, lead_type, segment,
           stage, contact_name, store_name, handle, last_inbound_text, num_touches,
           created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)""",
        (lead_key, lead_key, "direct", "store", "business", "replied",
         "Felix", "Maison Emporium", None, "Not taking on new channels currently.", now, now),
    )


def test_redraft_updates_stale_queued_text_but_never_touches_sent(tmp_path):
    from src.cli import cmd_redraft
    import argparse

    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    _make_lead(conn, "lead:A")
    _make_lead(conn, "lead:B")
    now = "2026-06-25T07:00:00"
    today = "2026-06-25"

    # lead:A - stale text, still queued (should get refreshed)
    conn.execute(
        "INSERT INTO actions_log (lead_key, action_date, channel, action_type, "
        "message_draft, score, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        ("lead:A", today, "direct", "email_followup", "STALE OLD TEXT", 1000, "queued", now),
    )
    # lead:B - same stale text, but already SENT (must never change)
    conn.execute(
        "INSERT INTO actions_log (lead_key, action_date, channel, action_type, "
        "message_draft, score, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        ("lead:B", today, "direct", "email_followup", "STALE OLD TEXT", 1000, "sent", now),
    )
    conn.commit()

    args = argparse.Namespace(db=db_path)
    import datetime
    real_date = datetime.date
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return real_date(2026, 6, 25)
    import src.cli as cli_module
    cli_module.date = FakeDate
    cmd_redraft(args)
    cli_module.date = real_date

    queued = conn.execute("SELECT message_draft FROM actions_log WHERE lead_key='lead:A'").fetchone()
    sent = conn.execute("SELECT message_draft FROM actions_log WHERE lead_key='lead:B'").fetchone()

    assert queued["message_draft"] != "STALE OLD TEXT"
    assert "Totally fair" in queued["message_draft"] or "Understood" in queued["message_draft"] \
        or "Fair enough" in queued["message_draft"]
    assert sent["message_draft"] == "STALE OLD TEXT"  # never touched - already sent for real
