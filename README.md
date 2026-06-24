# Fleek Acquisition Pipeline Tool

A repeatable daily outreach engine for Fleek's new-business pipeline: cleans
and deduplicates the messy inherited lead list, tells online resellers
(Instagram-only) apart from physical shops (full contact details) by what
data they actually have, decides who gets today's ~40 Instagram DMs and
what every other lead's next action is, drafts the actual message, and
re-runs safely every day without re-messaging anyone.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces fit together,
and [`AI_USAGE.md`](AI_USAGE.md) for how this was built.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Load the inherited pipeline (one-off, day 0)
python -m src.cli ingest --file data/pipeline_data.xlsx --sheet pipeline --batch initial_handover

# 2. Build today's outreach queue (run this every morning)
python -m src.cli plan --date 2026-03-01 --dm-cap 40 --email-cap 150 --call-cap 30 --visit-cap 5

# -> output/outreach_instagram_2026-03-01.csv   (today's 40 DMs, prioritized, pre-drafted)
# -> output/outreach_stores_2026-03-01.csv      (today's capped store batch, sequenced + grouped
#                                                 by city, pre-drafted; leftovers roll to tomorrow)

# 3. Sanity-check the pipeline at any point
python -m src.cli status

# 4. Drop in day 2's fresh leads - this is the "doesn't break, doesn't re-message" test
python -m src.cli ingest --file data/pipeline_data.xlsx --sheet new_drop_day2 --batch day2
python -m src.cli plan --date 2026-03-02

# 5. When a DM/email/call actually goes out, mark it sent (advances the cooldown
#    clock so the same lead doesn't get hit again tomorrow)
python -m src.cli send --action-id 17

# 6. Export the data-quality backlog as a sorted worklist (malformed contacts,
#    low-confidence merges) instead of leaving it for someone to notice
python -m src.cli review-queue

# 7. Sanity-check the scoring rubric against real outcomes, once leads have
#    actually resolved won/lost through the tool's own loop
python -m src.cli calibration

# 8. Check whether there's enough real outcome data to fit actual scoring
#    weights instead of the reasoned starting weights (gated on a standard
#    statistics threshold - won't do anything until there genuinely is enough)
python -m src.cli recalibrate
```

## Running this every morning, unattended

This is the part of the brief worth taking literally: "picture it running
every morning." Two pieces make that real instead of a sentence in a README:

- **`run_daily.sh`** - picks up any new lead-drop file sitting in
  `data/incoming/` (via the new `auto-ingest` command, idempotent the same
  way `ingest` is) and then builds the day's plan. Safe to run more than
  once a day or schedule via local cron.
- **`.github/workflows/daily_plan.yml`** - runs `run_daily.sh` on a schedule
  (7am UTC) on GitHub's infrastructure, with zero dependency on anyone's
  laptop being on. The SQLite DB persists between runs via GitHub's cache
  (a reasonable trick for a lightweight scheduled bot like this one; a real
  production setup at Fleek's actual scale would point this at a hosted
  Postgres instance instead - see `ARCHITECTURE.md`). Today's CSVs come out
  as a downloadable workflow artifact every run.

If you'd rather have a visible morning briefing than dig through GitHub,
Claude Cowork's Scheduled Tasks can run the same commands and summarize the
output - worth knowing it only runs while your computer is awake and the
desktop app is open (it catches up on wake if you miss a run), so it's a
good complement to the GitHub Actions workflow for visibility, not a
replacement for the part that needs to run with zero dependencies.

## Will this actually keep up at scale?

`python -m src.cli backlog-forecast` answers this directly instead of
leaving it to guesswork: it counts everyone currently eligible for outreach
and divides by today's caps to estimate days-to-clear per channel. At the
265-lead handover this is a non-issue (clears in 1-3 days). At a synthetic
30,000-lead test, it's not: ~341 days for Instagram (the platform's fixed
40/day cap is brutal at scale) and ~66 days for stores. That's the real
number behind "how do you get to 30,000 without quality falling off" -
the honest answer involves running multiple Instagram accounts and/or
deprioritizing it relative to automatable channels, not just "the code
handles it" (the code does handle it - the backlog is a business problem,
not a performance one, and this command is what surfaces that distinction).

## Plugging in Fleek's real numbers

Every capacity number and conversion rate in this tool is currently a
reasoned placeholder, not something Fleek told us. They all live in one
file - `config/assumptions.yaml` - specifically so that swapping in real
data later is a config edit, not a code change:

- `daily_caps` - the email/call/visit caps (Instagram's 40 is the one real
  platform number; the rest are starting assumptions about team capacity).
- `channel_performance` - currently all `null`. The moment Fleek has even a
  few weeks of real reply/connect/conversion data per channel (from a CRM,
  dialer, or email tool), fill in `conversion_rate` for at least two
  channels and run:

  ```bash
  python -m src.cli rebalance-caps
  ```

  It checks honestly whether there's enough filled in to say anything
  useful, and if so, recommends which channel to shift capacity toward
  based on which is actually converting - rather than the tool's default
  assumption that all capacity is equally valuable. Like `recalibrate`, it
  only ever recommends; it never edits the config file for you.

Re-running `plan` on the *same* date is a no-op for anyone already queued
that day - the CSV comes back identical, nothing gets double-drafted or
double-sent. Re-running `ingest` with a new file merges new leads in and
folds duplicates (by email/phone/handle, not by `lead_id`) into the
existing record instead of creating a second one. Both are what make this
safe to run unattended every morning rather than by hand.

**Important: `send` is what makes the queue rotate, not `plan` alone.**
Both daily caps (40 DMs, 60 stores by default) only free up tomorrow's slots
for leads that were actually marked `sent` - if you only ever run `plan`
without `send`, the same highest-scored leads will keep winning every day
(correctly - if you haven't reached out yet, of course they're still top
priority) and the rest of the queue won't move. Leads in the `waiting_on_us`
tier (replied/warm/negotiating/call_booked) are *meant* to keep reappearing
every day regardless - they're not capped out by sending, only by actually
resolving to won/lost.

## What it actually does, in order

1. **Ingest** (`src/ingest.py`) - reads a sheet, logs every raw row to
   `raw_intake` for audit, cleans each field (`src/clean.py`), and resolves
   it to a real-world entity by matching on normalized email / phone / handle
   against everything already in the system. Matches get merged (most
   complete + most advanced stage wins); non-matches become a new canonical
   lead.
2. **Classify** (`src/classify.py`) - channel is decided by what contact
   info actually exists (`email`/`phone` present -> `direct`; handle-only ->
   `instagram_dm`), not by the `source` label. This is what catches the
   resellers who happen to have an email on file.
3. **Score & prioritize** (`src/scoring.py`) - every active lead gets a
   tier (leads waiting on us > brand new > follow-up due > gone quiet;
   won/lost excluded) and a value score from estimated spend, with a
   cooldown so the same silent lead isn't re-attempted every single day.
4. **Draft** (`src/drafting.py`) - turns tier + channel + stage into a
   concrete next action (DM / email / call / visit) and writes the actual
   message text, personalized from the lead's own data and last reply.
5. **Plan** (`src/cli.py: plan`) - the daily orchestrator: scores everyone,
   takes the top ~40 Instagram candidates, takes every eligible store
   lead (grouped by city for visit planning), writes both to
   `actions_log` (so it's idempotent) and to CSV.

## Design decisions worth knowing about

- **SQLite, not flat CSVs.** The whole point is state that survives between
  runs - who's been actioned, what's in cooldown, what's already queued
  today. A pure CSV-in/CSV-out script can't do that without re-inventing a
  database badly.
- **Entity resolution is by contact fields, not `lead_id`.** The handover
  data proves `lead_id` isn't a reliable key (duplicate people show up under
  different IDs); email/phone/handle are.
- **Channel and segment are two different questions, and the code keeps
  them separate.** `channel` is "how do we contact this lead" (email/phone
  vs DM-only). `segment` is "which of Fleek's own marketed customer tiers
  are they in" (New Reseller / Full-Time Reseller / Business - straight
  from joinfleek.com, not invented). A reseller can be `direct`-contactable
  (happens to have an email) while still being a `new_reseller` for
  messaging purposes - conflating the two would mean a beginner gets the
  same pitch as a 200-sale/month full-time reseller just because of how we
  happen to be able to reach them.
- **Tier always dominates value.** A maxed-out brand-new lead can never
  outrank a low-value lead who's actively waiting on a reply, by design -
  see `tests/test_scoring.py::test_higher_value_never_crosses_a_tier_boundary`.
- **Scale**: matching is done with in-memory dict lookups built once per
  ingest, not per-row table scans, which is what keeps ingest roughly linear
  instead of quadratic. `tests/scale_test.py` generates 30,000 synthetic
  leads and ingests them in ~9-10s on a single laptop core with zero schema
  changes. See `ARCHITECTURE.md` for what would change first beyond that
  (Postgres swap-in, queue-based DM sending to respect the platform rate
  limit in real time, etc).

## Tests

```bash
python -m pytest tests/ -q          # unit tests for cleaning + scoring
python tests/scale_test.py          # 30k-row synthetic load test
```

## Repo layout

```
src/
  db.py        SQLite schema + connection
  clean.py     field normalization (dates, phone, email, spend, stage, handle)
  ingest.py    entity resolution / dedup-and-merge
  classify.py  channel classification (direct vs instagram_dm)
  scoring.py   prioritization tiers + cooldown
  drafting.py  next-action decisioning + message templates
  cli.py       ingest / plan / send / status commands
tests/
  test_clean.py, test_scoring.py     unit tests
  scale_test.py                      30k-row synthetic load test
data/
  pipeline_data.xlsx                 the provided case-study data
```
