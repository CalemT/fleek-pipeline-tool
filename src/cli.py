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
from . import config as cfg
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

    # Stores don't have a platform-enforced limit the way Instagram does,
    # but each action type they generate has a *different* real-world
    # constraint - email can be automated and scales with sender
    # deliverability, not headcount; calls and visits are still genuinely
    # human time. One flat cap across all three either overstates what a
    # human team can do on calls/visits, or understates how far email could
    # scale with automation. So each category gets its own cap, and
    # next_action_type has to be known *before* applying the cap (it no
    # longer depends only on the cap being met).
    direct_queue = []
    category_caps = {"email": args.email_cap, "call": args.call_cap, "visit": args.visit_cap}
    category_slots_used = {"email": 0, "call": 0, "visit": 0}

    for lead, tier, score, already in direct_candidates:
        if already:
            existing = conn.execute(
                "SELECT action_type FROM actions_log WHERE lead_key=? AND action_date=? "
                "ORDER BY id DESC LIMIT 1",
                (lead["lead_key"], today_iso),
            ).fetchone()
            cat = drafting.ACTION_CATEGORY.get(existing["action_type"], "email") if existing else "email"
            category_slots_used[cat] += 1
            direct_queue.append((lead, tier, score, "already_queued_today"))
            continue
        action_type = drafting.next_action_type(lead, tier)
        cat = drafting.ACTION_CATEGORY[action_type]
        if category_slots_used[cat] >= category_caps[cat]:
            continue
        direct_queue.append((lead, tier, score, "new"))
        category_slots_used[cat] += 1

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

    direct_total_not_already = sum(1 for _, _, _, already in direct_candidates if not already)
    direct_new_today = sum(1 for *_, s in direct_queue if s == "new")
    direct_leftover = direct_total_not_already - direct_new_today

    print(f"[plan] date={today_iso}")
    print(f"  Instagram DM queue: {len(dm_queue)} / cap {args.dm_cap} "
          f"({sum(1 for *_, s in dm_queue if s=='new')} new, "
          f"{sum(1 for *_, s in dm_queue if s!='new')} already queued today)")
    print(f"  Direct (store) queue: {len(direct_queue)} total "
          f"(email {category_slots_used['email']}/{category_caps['email']}, "
          f"call {category_slots_used['call']}/{category_caps['call']}, "
          f"visit {category_slots_used['visit']}/{category_caps['visit']}), "
          f"{direct_leftover} left over for tomorrow")
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
            "segment": lead["segment"],
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
    # A 'new' lead that's just been messaged is no longer "never contacted" -
    # without this, it stays in the 'new' tier forever (which has no
    # cooldown, by design, since a never-contacted lead is always eligible),
    # and permanently starves every other lead behind it in the queue. Any
    # later stage (replied/warm/negotiating/etc.) only ever advances from an
    # actual inbound reply being recorded - sending doesn't change that.
    conn.execute(
        "UPDATE leads SET last_touch_date=?, num_touches=num_touches+1, updated_at=?, "
        "stage = CASE WHEN stage='new' THEN 'contacted' ELSE stage END "
        "WHERE lead_key=?",
        (action["action_date"], datetime.now(timezone.utc).isoformat(), action["lead_key"]),
    )
    conn.commit()
    print(f"[send] marked action {args.action_id} ({action['action_type']}) sent for {action['lead_key']}")
    conn.close()


def cmd_status(args):
    conn = db.connect(args.db)
    total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
    by_channel = conn.execute("SELECT channel, COUNT(*) c FROM leads GROUP BY channel").fetchall()
    by_segment = conn.execute("SELECT segment, COUNT(*) c FROM leads GROUP BY segment ORDER BY c DESC").fetchall()
    by_stage = conn.execute("SELECT stage, COUNT(*) c FROM leads GROUP BY stage ORDER BY c DESC").fetchall()
    flagged = conn.execute(
        "SELECT COUNT(*) c FROM leads WHERE data_quality_flags != '[]'"
    ).fetchone()["c"]
    print(f"Total canonical leads: {total}  (data quality flags on {flagged})")
    print("By channel:")
    for r in by_channel:
        print(f"  {r['channel']:14s} {r['c']}")
    print("By segment:")
    for r in by_segment:
        print(f"  {r['segment']:18s} {r['c']}")
    print("By stage:")
    for r in by_stage:
        print(f"  {r['stage']:14s} {r['c']}")
    conn.close()


def cmd_review_queue(args):
    """Export flagged leads as an actual worklist, sorted by commercial
    value, instead of leaving 'someone notices the flag' implicit. At 265
    rows a couple of flags are trivial to spot; at 30,000 the same ~1% flag
    rate is a few hundred rows that need to be triaged like any other queue."""
    conn = db.connect(args.db)
    rows = conn.execute(
        "SELECT * FROM leads WHERE data_quality_flags != '[]' ORDER BY "
        "COALESCE(est_monthly_spend_gbp, 0) DESC"
    ).fetchall()

    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / "data_quality_review.csv"
    out_rows = [{
        "lead_key": r["lead_key"],
        "store_name": r["store_name"],
        "handle": r["handle"],
        "email": r["email"],
        "phone": r["phone"],
        "flags": r["data_quality_flags"],
        "est_monthly_spend_gbp": r["est_monthly_spend_gbp"],
        "stage": r["stage"],
        "source_lead_ids": r["source_lead_ids"],
    } for r in rows]

    if out_rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)
    else:
        path.write_text("")

    print(f"[review-queue] {len(out_rows)} flagged leads -> {path}")
    conn.close()


def cmd_calibration(args):
    """Sanity-check the scoring rubric against real outcomes: for leads that
    have actually resolved (won/lost), what score did they have at the time
    of their last action? This is the seed of a real feedback loop - with
    only 9 won / 14 lost today there isn't enough signal to retrain
    anything, but every action's score is already logged in `actions_log`,
    so the moment there's enough outcome data this check tells you whether
    the rubric is actually predictive or just a plausible guess."""
    conn = db.connect(args.db)
    rows = conn.execute(
        """SELECT l.stage, a.score FROM leads l
           JOIN actions_log a ON a.lead_key = l.lead_key
           WHERE l.stage IN ('won','lost')"""
    ).fetchall()
    if not rows:
        print("[calibration] No actions logged yet for resolved (won/lost) leads.\n"
              "This is expected on a freshly-ingested handover: the leads that are "
              "already won/lost arrived at that stage before this tool existed, so "
              "there's no scored action in `actions_log` tracing how they got there.\n"
              "This check only becomes meaningful for leads that resolve to won/lost "
              "*after* going through the tool's own plan/send loop - i.e. check back "
              "in a few weeks of real usage, not on day one.")
        return
    won = [r["score"] for r in rows if r["stage"] == "won"]
    lost = [r["score"] for r in rows if r["stage"] == "lost"]
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    print(f"[calibration] won leads (n={len(won)}): avg last-action score = {avg(won)}")
    print(f"[calibration] lost leads (n={len(lost)}): avg last-action score = {avg(lost)}")
    print("If 'won' scores aren't meaningfully higher than 'lost' scores once n is "
          "large enough, the rubric's weights need revisiting - not just more data.")
    conn.close()


def cmd_recalibrate(args):
    """Check whether there's enough real outcome data to responsibly fit
    actual weights (instead of the reasoned-but-unproven starting weights in
    scoring.py), and if so, fit them and write a recommendation file - never
    silently overwrite the live weights. This is the 'instrumented now,
    self-corrects once there's enough data' piece: it's honest about not
    running until there's a statistically defensible amount of data."""
    import json as _json
    from datetime import date as _date

    from . import scoring as sc

    conn = db.connect(args.db)
    rows = conn.execute("SELECT * FROM leads WHERE stage IN ('won','lost')").fetchall()

    feature_names = ["spend", "velocity", "listings", "followers", "touches", "replied", "recency"]
    today = _date.today()

    def featurize(r):
        days = sc._days_since(r["last_touch_date"], today)
        recency = max(0.0, 1.0 - (days / sc.RECENCY_HORIZON_DAYS)) if days is not None else 0.0
        return [
            sc._norm(r["est_monthly_spend_gbp"], sc.MAX_SPEND_CAP) or 0.0,
            sc._norm(r["sales_velocity_30d"], sc.MAX_VELOCITY_CAP) or 0.0,
            sc._norm(r["active_listings"], sc.MAX_LISTINGS_CAP) or 0.0,
            sc._norm(r["followers"], sc.MAX_FOLLOWERS_CAP) or 0.0,
            sc._norm(r["num_touches"], sc.MAX_TOUCHES_CAP) or 0.0,
            1.0 if r["last_inbound_text"] else 0.0,
            recency,
        ]

    X = [featurize(r) for r in rows]
    y = [1 if r["stage"] == "won" else 0 for r in rows]
    n_won, n_lost = sum(y), len(y) - sum(y)
    n_minority = min(n_won, n_lost) if y else 0

    # Rule of thumb from applied statistics (events-per-variable, EPV): you
    # want roughly 10+ outcome events per input feature in the SMALLER
    # outcome class, or coefficients become unstable / overfit to noise.
    epv_target = cfg.load_config()["recalibration"]["epv_target"]
    required = epv_target * len(feature_names)

    print(f"[recalibrate] resolved leads: {n_won} won, {n_lost} lost "
          f"(smaller class = {n_minority})")
    print(f"[recalibrate] need ~{required} ({epv_target} x {len(feature_names)} features) "
          f"in the smaller class to fit responsibly")

    if n_minority < required:
        print(f"[recalibrate] NOT ENOUGH DATA YET ({n_minority}/{required}). "
              f"Keeping the reasoned starting weights in scoring.py as-is. "
              f"This is expected this early - re-run after more leads have "
              f"resolved won/lost through real usage.")
        conn.close()
        return

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    model = LogisticRegression(class_weight="balanced", max_iter=1000)
    cv_scores = cross_val_score(model, X, y, cv=5, scoring="roc_auc")
    model.fit(X, y)

    recommendation = {
        "n_won": n_won, "n_lost": n_lost,
        "cross_val_auc_mean": round(float(cv_scores.mean()), 3),
        "coefficients": {name: round(float(c), 3) for name, c in zip(feature_names, model.coef_[0])},
        "intercept": round(float(model.intercept_[0]), 3),
        "note": "Positive coefficient = higher values of this feature correlate with "
                "winning. Review against scoring.py's FIT_WEIGHTS / ENGAGEMENT_WEIGHTS "
                "and update by hand if these are stable across multiple runs - this "
                "file is a recommendation, not an automatic change.",
    }
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / "recalibration_recommendation.json"
    path.write_text(_json.dumps(recommendation, indent=2))
    print(f"[recalibrate] fitted on {len(y)} resolved leads, mean CV ROC-AUC={cv_scores.mean():.3f}")
    print(f"[recalibrate] -> {path} (review before changing scoring.py)")
    conn.close()


def cmd_auto_ingest(args):
    """Scan a folder for lead-drop files and ingest any that haven't been
    seen before - this is the piece that makes 'run every morning'
    meaningful instead of just a sentence in the README. In production this
    folder is wherever new exports land (a scheduled CRM export, an
    Instagram-scraper output, etc); here it's `data/incoming/` for the demo.
    Idempotent by checking `raw_intake` for a matching batch_label before
    touching a file twice, the same way `ingest` is idempotent per-row."""
    import glob

    import pandas as pd

    conn = db.connect(args.db)
    folder = Path(args.folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = sorted(glob.glob(str(folder / "*.xlsx")))

    if not files:
        print(f"[auto-ingest] no files found in {folder}")
        conn.close()
        return

    total_new, total_merged, batches_run = 0, 0, 0
    for filepath in files:
        try:
            sheet_names = pd.ExcelFile(filepath).sheet_names
        except Exception as e:
            print(f"[auto-ingest] could not read {filepath}: {e}")
            continue
        for sheet in sheet_names:
            if sheet.lower() == "readme":
                continue
            batch_label = f"{Path(filepath).name}:{sheet}"
            already_seen = conn.execute(
                "SELECT 1 FROM raw_intake WHERE batch_label=? LIMIT 1", (batch_label,)
            ).fetchone()
            if already_seen:
                continue
            stats = ingest_mod.ingest_batch(conn, filepath, sheet, batch_label)
            print(f"[auto-ingest] new batch '{batch_label}': "
                  f"{stats['new_leads']} new, {stats['merged_into_existing']} merged")
            total_new += stats["new_leads"]
            total_merged += stats["merged_into_existing"]
            batches_run += 1

    if batches_run == 0:
        print(f"[auto-ingest] {len(files)} file(s) in {folder}, nothing new to ingest")
    else:
        print(f"[auto-ingest] {batches_run} new batch(es): {total_new} new leads, "
              f"{total_merged} merged")
    conn.close()


def cmd_rebalance_caps(args):
    """The actual point of `config/assumptions.yaml`'s channel_performance
    section: once Fleek has real reply/conversion data per channel, this
    recommends how to redistribute the email/call/visit caps toward
    whichever channel is actually converting best - rather than treating
    all capacity as equally valuable, which is what the tool assumes by
    default. Instagram is excluded from rebalancing since its cap is a
    platform limit, not a choice. Same posture as `recalibrate`: checks
    honestly whether there's real data before recommending anything, and
    never auto-applies a change."""
    perf = cfg.load_config()["channel_performance"]
    rebalanceable = {"email": perf["email"]["conversion_rate"],
                      "call": perf["call"]["conversion_rate"],
                      "visit": perf["visit"]["conversion_rate"]}
    filled_in = {k: v for k, v in rebalanceable.items() if v is not None}

    if len(filled_in) < 2:
        missing = [k for k in rebalanceable if rebalanceable[k] is None]
        print("[rebalance-caps] Not enough real channel performance data yet.")
        print(f"[rebalance-caps] Need conversion_rate for at least 2 of "
              f"email/call/visit to compare - currently have {len(filled_in)}.")
        print(f"[rebalance-caps] Fill in channel_performance.<channel>.conversion_rate "
              f"for: {', '.join(missing)} in config/assumptions.yaml, then re-run.")
        print("[rebalance-caps] Keeping the current daily_caps as-is.")
        return

    best = max(filled_in, key=filled_in.get)
    print(f"[rebalance-caps] Real conversion rates on file: "
          + ", ".join(f"{k}={v:.1%}" for k, v in filled_in.items()))
    print(f"[rebalance-caps] '{best}' is converting best of the channels with data.")
    caps = cfg.load_config()["daily_caps"]
    for channel, rate in filled_in.items():
        if channel == best:
            continue
        ratio = rate / filled_in[best] if filled_in[best] else 0
        print(f"[rebalance-caps]   '{channel}' converts at {ratio:.0%} of '{best}''s rate "
              f"(current cap: {caps.get(channel)}/day) - consider shifting capacity toward "
              f"'{best}' where the underlying constraint (team size, travel time) allows it.")
    print("[rebalance-caps] This is a recommendation only - edit daily_caps in "
          "config/assumptions.yaml by hand if you agree with it.")


def cmd_backlog_forecast(args):
    """How long would it take to work through everything currently eligible,
    at today's caps? This came out of actually testing the tool at 30,000
    leads rather than just trusting the caps were reasonable - the backlog
    turned out to be measured in months, not days, which is exactly the
    kind of number that should be surfaced automatically every time you
    check status, not discovered by hand once."""
    today = date.today()
    conn = db.connect(args.db)
    leads = conn.execute("SELECT * FROM leads WHERE stage NOT IN ('won','lost')").fetchall()

    dm_backlog, direct_backlog = 0, 0
    for lead in leads:
        tier, _ = scoring.score_lead(lead, today)
        if tier is None:
            continue
        if lead["channel"] == "instagram_dm":
            dm_backlog += 1
        else:
            direct_backlog += 1

    caps = cfg.load_config()["daily_caps"]
    direct_daily_throughput = caps["email"] + caps["call"] + caps["visit"]

    dm_days = dm_backlog / caps["instagram_dm"] if caps["instagram_dm"] else float("inf")
    direct_days = direct_backlog / direct_daily_throughput if direct_daily_throughput else float("inf")

    print(f"[backlog-forecast] {dm_backlog} Instagram-eligible leads, "
          f"{direct_backlog} store-eligible leads right now")
    print(f"[backlog-forecast] Instagram: {dm_backlog} / {caps['instagram_dm']} per day "
          f"= ~{dm_days:.0f} days to clear at current cap")
    print(f"[backlog-forecast] Stores: {direct_backlog} / {direct_daily_throughput} per day "
          f"(email+call+visit combined) = ~{direct_days:.0f} days to clear at current caps")
    if max(dm_days, direct_days) > 14:
        print("[backlog-forecast] NOTE: this exceeds two weeks at current capacity - this is "
              "the number to bring to a conversation about hiring, multiple Instagram "
              "accounts, or automation, before the backlog itself becomes the bottleneck "
              "rather than lead quality.")
    conn.close()


def cmd_visit_plan(args):
    """The brief asks specifically to 'group [stores] by city so you can
    book the most shop visits in a week' - the daily store CSV sorts by
    city, but a sort isn't a decision. This is the actual decision: which
    cities have enough visit-ready stores to justify a dedicated trip this
    week, vs which should keep being called until more accumulate there.
    A single store in a city probably isn't worth flying out for; five is."""
    today = date.today()
    conn = db.connect(args.db)
    leads = conn.execute(
        "SELECT * FROM leads WHERE channel='direct' AND stage NOT IN ('won','lost')"
    ).fetchall()

    visit_ready = []
    for lead in leads:
        tier, score = scoring.score_lead(lead, today)
        if tier is None:
            continue
        action_type = drafting.next_action_type(lead, tier)
        if action_type == "visit":
            visit_ready.append((lead, score))

    by_city = {}
    for lead, score in visit_ready:
        city = lead["city"] or "(unknown city)"
        by_city.setdefault(city, []).append((lead, score))

    min_cluster = cfg.load_config()["min_visit_cluster"]
    visit_cap = cfg.load_config()["daily_caps"]["visit"]

    worthy = {c: leads_ for c, leads_ in by_city.items() if len(leads_) >= min_cluster}
    not_yet = {c: leads_ for c, leads_ in by_city.items() if len(leads_) < min_cluster}

    print(f"[visit-plan] {len(visit_ready)} stores are visit-ready across {len(by_city)} cities "
          f"(need {min_cluster}+ in a city to justify a dedicated trip)")
    print()
    if worthy:
        print("BOOK THIS WEEK:")
        for city, leads_ in sorted(worthy.items(), key=lambda kv: -len(kv[1])):
            days_needed = -(-len(leads_) // visit_cap)  # ceil division
            print(f"  {city}: {len(leads_)} stores ready -> ~{days_needed} day(s) of visits "
                  f"at {visit_cap}/day cap")
    else:
        print("BOOK THIS WEEK: nothing meets the threshold yet.")
    print()
    if not_yet:
        print("NOT YET WORTH A DEDICATED TRIP (keep calling until more accumulate):")
        for city, leads_ in sorted(not_yet.items(), key=lambda kv: -len(kv[1])):
            print(f"  {city}: {len(leads_)} store(s)")

    OUTPUT_DIR.mkdir(exist_ok=True)
    rows = []
    for city, leads_ in by_city.items():
        for lead, score in leads_:
            rows.append({
                "city": city, "trip_worthy": city in worthy,
                "store_name": lead["store_name"], "contact_name": lead["contact_name"],
                "phone": lead["phone"], "email": lead["email"],
                "score": round(score, 1), "num_touches": lead["num_touches"],
            })
    rows.sort(key=lambda r: (not r["trip_worthy"], r["city"], -r["score"]))
    if rows:
        path = OUTPUT_DIR / "visit_plan.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n-> {path}")
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

    p_auto = sub.add_parser("auto-ingest", help="Pick up any new file dropped in a watched folder")
    p_auto.add_argument("--folder", default="data/incoming")
    p_auto.set_defaults(func=cmd_auto_ingest)

    p_plan = sub.add_parser("plan", help="Build today's outreach queue (idempotent per day)")
    p_plan.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today")
    _caps = cfg.load_config()["daily_caps"]
    p_plan.add_argument("--dm-cap", type=int, default=_caps["instagram_dm"])
    p_plan.add_argument("--email-cap", type=int, default=_caps["email"],
                         help="Max store emails/day. Email is the one channel that genuinely "
                              "scales with automation (API into Gmail/an ESP, AI-drafted, sent "
                              "in bulk) - this number is a conservative placeholder pending real "
                              "sender deliverability limits, not a team-headcount constraint. "
                              "Default comes from config/assumptions.yaml.")
    p_plan.add_argument("--call-cap", type=int, default=_caps["call"],
                         help="Max store calls/day - a real human-capacity assumption "
                              "(~30-40 dials/day is a typical single-BDR benchmark), not a "
                              "platform rule. Default comes from config/assumptions.yaml.")
    p_plan.add_argument("--visit-cap", type=int, default=_caps["visit"],
                         help="Max store visits/day - the most genuinely constrained action "
                              "(travel time, not just willingness). Default comes from "
                              "config/assumptions.yaml.")
    p_plan.set_defaults(func=cmd_plan)

    p_send = sub.add_parser("send", help="Mark a queued action as sent")
    p_send.add_argument("--action-id", type=int, required=True)
    p_send.set_defaults(func=cmd_send)

    p_status = sub.add_parser("status", help="Summary of the canonical pipeline")
    p_status.set_defaults(func=cmd_status)

    p_review = sub.add_parser("review-queue", help="Export flagged leads as a sorted worklist")
    p_review.set_defaults(func=cmd_review_queue)

    p_calib = sub.add_parser("calibration", help="Check whether the scoring rubric matches real outcomes")
    p_calib.set_defaults(func=cmd_calibration)

    p_recal = sub.add_parser("recalibrate", help="Fit real weights from outcome data, if there's enough of it")
    p_recal.set_defaults(func=cmd_recalibrate)

    p_rebal = sub.add_parser("rebalance-caps", help="Recommend cap changes from real channel performance data")
    p_rebal.set_defaults(func=cmd_rebalance_caps)

    p_backlog = sub.add_parser("backlog-forecast", help="Estimate days to clear the current backlog at today's caps")
    p_backlog.set_defaults(func=cmd_backlog_forecast)

    p_visit = sub.add_parser("visit-plan", help="Decide which cities have enough visit-ready stores for a dedicated trip")
    p_visit.set_defaults(func=cmd_visit_plan)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
