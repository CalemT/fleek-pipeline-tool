"""
Command-line entry point.

    python -m src.cli ingest  --file data/pipeline_data.xlsx --sheet pipeline --batch initial_handover
    python -m src.cli ingest  --file data/pipeline_data.xlsx --sheet new_drop_day2 --batch day2
    python -m src.cli plan    --date 2026-03-01
    python -m src.cli send    --action-id 17
    python -m src.cli status

Designed to be run every morning (cron / GitHub Action / agent). Running
`plan` again on the same day is a no-op for leads already queued today -
nothing gets messaged twice. Running `ingest` again with a new file merges
new leads in (and folds in any that turn out to already exist) without
touching what's already in the pipeline.
"""
import argparse
import csv
from datetime import date, datetime, timezone
from pathlib import Path

from . import db
from . import ingest as ingest_mod
from . import scoring
from . import drafting

DB_PATH = "output/fleek.db"
OUTPUT_DIR = Path("output")


def cmd_ingest(args):
    conn = db.connect(args.db)
    stats = ingest_mod.ingest_batch(conn, args.file, args.sheet, args.batch)
    print(f"[ingest] batch='{args.batch}' file='{args.file}' sheet='{args.sheet}'")
    print(f"  rows seen:            {stats['rows_seen']}")
    print(f"  new leads created:    {stats['new_leads']}")
    print(f"  merged into existing: {stats['merged_into_existing']}")
    conn.close()


def _already_queued_today(conn, lead_key, today_iso):
    return conn.execute(
        "SELECT 1 FROM actions_log WHERE lead_key=? AND action_date=? AND status IN ('queued','sent')",
        (lead_key, today_iso),
    ).fetchone() is not None


def cmd_plan(args):
    today = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    today_iso = today.isoformat()
    conn = db.connect(args.db)

    leads = conn.execute(
        "SELECT * FROM leads WHERE stage NOT IN ('won','lost')"
    ).fetchall()

    scored = []
    for lead in leads:
        tier, score = scoring.score_lead(lead, today)
        if tier is None:
            continue
        already = _already_queued_today(conn, lead["lead_key"], today_iso)
        scored.append((lead, tier, score, already))

    dm_candidates = sorted(
        [s for s in scored if s[0]["channel"] == "instagram_dm"],
        key=lambda s: s[2], reverse=True,
    )
    direct_candidates = sorted(
        [s for s in scored if s[0]["channel"] == "direct"],
        key=lambda s: s[2], reverse=True,
    )

    dm_queue = []
    slots_used = sum(1 for _, _, _, already in dm_candidates if already)
    for lead, tier, score, already in dm_candidates:
        if already:
            dm_queue.append((lead, tier, score, "already_queued_today"))
            continue
        if slots_used >= args.dm_cap:
            continue
        dm_queue.append((lead, tier, score, "new"))
        slots_used += 1

    direct_queue = [(lead, tier, score, "already_queued_today" if already else "new")
                     for lead, tier, score, already in direct_candidates]

    now = datetime.now(timezone.utc).isoformat()
    for lead, tier, score, status in dm_queue + direct_queue:
        if status != "new":
            continue
        action_type = drafting.next_action_type(lead, tier)
        message = drafting.draft_message(lead, action_type)
        conn.execute(
            """INSERT INTO actions_log (lead_key, action_date, channel, action_type,
               message_draft, score, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (lead["lead_key"], today_iso, lead["channel"], action_type, message,
             score, "queued", now),
        )
    conn.commit()

    OUTPUT_DIR.mkdir(exist_ok=True)
    _write_csv(OUTPUT_DIR / f"outreach_instagram_{today_iso}.csv", dm_queue, conn, today_iso)
    _write_csv(OUTPUT_DIR / f"outreach_stores_{today_iso}.csv", direct_queue, conn, today_iso, group_by_city=True)

    print(f"[plan] date={today_iso}")
    print(f"  Instagram DM queue: {len(dm_queue)} / cap {args.dm_cap} "
          f"({sum(1 for *_, s in dm_queue if s=='new')} new, "
          f"{sum(1 for *_, s in dm_queue if s!='new')} already queued today)")
    print(f"  Direct (store) queue: {len(direct_queue)} leads")
    print(f"  -> output/outreach_instagram_{today_iso}.csv")
    print(f"  -> output/outreach_stores_{today_iso}.csv")
    conn.close()


def _write_csv(path, queue, conn, today_iso, group_by_city=False):
    rows = []
    for lead, tier, score, status in queue:
        action_row = conn.execute(
            "SELECT action_type, message_draft FROM actions_log "
            "WHERE lead_key=? AND action_date=? ORDER BY id DESC LIMIT 1",
            (lead["lead_key"], today_iso),
        ).fetchone()
        rows.append({
            "lead_key": lead["lead_key"],
            "store_name": lead["store_name"],
            "handle": lead["handle"],
            "contact_name": lead["contact_name"],
            "email": lead["email"],
            "phone": lead["phone"],
            "city": lead["city"] or "",
            "stage": lead["stage"],
            "tier": tier,
            "score": round(score, 1),
            "action_type": action_row["action_type"] if action_row else "",
            "message_draft": action_row["message_draft"] if action_row else "",
            "est_monthly_spend_gbp": lead["est_monthly_spend_gbp"],
            "status": status,
        })
    if group_by_city:
        rows.sort(key=lambda r: (r["city"], -r["score"]))
    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("")


def cmd_send(args):
    conn = db.connect(args.db)
    action = conn.execute("SELECT * FROM actions_log WHERE id=?", (args.action_id,)).fetchone()
    if not action:
        print(f"No action with id={args.action_id}")
        return
    conn.execute("UPDATE actions_log SET status='sent' WHERE id=?", (args.action_id,))
    conn.execute(
        "UPDATE leads SET last_touch_date=?, num_touches=num_touches+1, updated_at=? WHERE lead_key=?",
        (action["action_date"], datetime.now(timezone.utc).isoformat(), action["lead_key"]),
    )
    conn.commit()
    print(f"[send] marked action {args.action_id} ({action['action_type']}) sent for {action['lead_key']}")
    conn.close()


def cmd_status(args):
    conn = db.connect(args.db)
    total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
    by_channel = conn.execute("SELECT channel, COUNT(*) c FROM leads GROUP BY channel").fetchall()
    by_stage = conn.execute("SELECT stage, COUNT(*) c FROM leads GROUP BY stage ORDER BY c DESC").fetchall()
    flagged = conn.execute(
        "SELECT COUNT(*) c FROM leads WHERE data_quality_flags != '[]'"
    ).fetchone()["c"]
    print(f"Total canonical leads: {total}  (data quality flags on {flagged})")
    print("By channel:")
    for r in by_channel:
        print(f"  {r['channel']:14s} {r['c']}")
    print("By stage:")
    for r in by_stage:
        print(f"  {r['stage']:14s} {r['c']}")
    conn.close()


def main():
    p = argparse.ArgumentParser(description="Fleek pipeline outreach tool")
    p.add_argument("--db", default=DB_PATH)
    sub = p.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Load a raw batch (sheet) into the canonical leads table")
    p_ingest.add_argument("--file", required=True)
    p_ingest.add_argument("--sheet", required=True)
    p_ingest.add_argument("--batch", required=True, help="Label for this batch, e.g. 'initial_handover'")
    p_ingest.set_defaults(func=cmd_ingest)

    p_plan = sub.add_parser("plan", help="Build today's outreach queue (idempotent per day)")
    p_plan.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today")
    p_plan.add_argument("--dm-cap", type=int, default=40)
    p_plan.set_defaults(func=cmd_plan)

    p_send = sub.add_parser("send", help="Mark a queued action as sent")
    p_send.add_argument("--action-id", type=int, required=True)
    p_send.set_defaults(func=cmd_send)

    p_status = sub.add_parser("status", help="Summary of the canonical pipeline")
    p_status.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
