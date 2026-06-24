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
python -m src.cli plan --date 2026-03-01

# -> output/outreach_instagram_2026-03-01.csv   (today's 40 DMs, prioritized, pre-drafted)
# -> output/outreach_stores_2026-03-01.csv      (every store, sequenced + grouped by city, pre-drafted)

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
```

Re-running `plan` on the *same* date is a no-op for anyone already queued
that day - the CSV comes back identical, nothing gets double-drafted or
double-sent. Re-running `ingest` with a new file merges new leads in and
folds duplicates (by email/phone/handle, not by `lead_id`) into the
existing record instead of creating a second one. Both are what make this
safe to run unattended every morning rather than by hand.

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
