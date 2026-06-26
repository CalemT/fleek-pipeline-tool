# Fleek Acquisition Pipeline Tool

A repeatable daily outreach engine for Fleek's new-business pipeline: cleans
and deduplicates the messy inherited lead list, tells online resellers
(Instagram-only) apart from physical shops (full contact details) by what
data they actually have, decides who gets today's ~40 Instagram DMs and
what every other lead's next action is, drafts the actual message, and
re-runs safely every day without re-messaging anyone.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces fit together,
and [`AI_USAGE.md`](AI_USAGE.md) for how this was built. Two more worth
reading for the full picture:

- **[`GTM_STRATEGY.md`](GTM_STRATEGY.md)** - the commercial reasoning
  behind the system: how scoring and prioritization actually work, how
  the 40 daily Instagram DMs get picked (with real numbers from running
  it), how this scales to 30,000 leads, and how the two lead types are
  handled differently.
- **[`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md)** - a dated, honest record
  of every real bug found while building this, how it was found, and how
  it was fixed - including a production issue that only showed up after
  going live on GitHub Pages.

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

# 6b. Turn those same flagged leads into real, clickable GitHub Issues
#     (works automatically in GitHub Actions; needs GITHUB_TOKEN locally)
python -m src.cli sync-review-issues

# 7. Sanity-check the scoring rubric against real outcomes, once leads have
#    actually resolved won/lost through the tool's own loop
python -m src.cli calibration

# 8. Check whether there's enough real outcome data to fit actual scoring
#    weights instead of the reasoned starting weights (gated on a standard
#    statistics threshold - won't do anything until there genuinely is enough)
python -m src.cli recalibrate

# 9. Decide which cities have enough visit-ready stores to justify a trip this week
python -m src.cli visit-plan

# 10. Recommend shifting capacity toward whichever channel is actually
#     converting best, once real channel performance data exists
python -m src.cli rebalance-caps

# 11. Estimate days-to-clear the current backlog at today's caps - the real
#     number behind "how do you scale without quality falling off"
python -m src.cli backlog-forecast

# 12. Write the JSON snapshot the GitHub Pages dashboard reads
python -m src.cli export-dashboard

# 13. If drafting logic changes mid-day, refresh text for anything still
#     queued (not yet sent) so it reflects the latest wording
python -m src.cli redraft
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

## Grouping stores by city for visits - a real decision, not just a sort

The daily store CSV sorts by city so same-city leads sit together, but a
sort isn't a decision. `python -m src.cli visit-plan` is the actual
decision the brief asks for: which cities have enough visit-ready stores
(`min_visit_cluster` in `config/assumptions.yaml`, default 3) to justify
booking a dedicated trip this week, versus which should stay on calls until
more accumulate there. Outputs a clear "book this week" vs "not yet"
breakdown plus `output/visit_plan.csv` with real contact details, sorted
trip-worthy cities first.

Also fixed while building this: the email->call->visit escalation ladder
previously only ever reached "visit" for the `re_engage` (ghosted) tier -
a store stuck in `follow_up_due` could be called indefinitely and never
escalate, which contradicted the brief's literal sequence for *any*
unresponsive store. Both tiers now share one ladder, keyed on touch count.

## A clickable viewer, not just CSVs

The brief's in-person stage talks about clicking into individual leads -
a flat CSV doesn't really support that. `docs/index.html` is a small,
dependency-free dashboard that reads `docs/data/latest.json` (written by
`python -m src.cli export-dashboard`, wired into the daily run) and lets
you click into any lead to see its full picture: score, stage, segment,
the actual drafted message, and the last thing they said to us. Visit plan
gets its own tab showing which cities are flagged trip-worthy.

**The dashboard is also the operational front end, not just a viewer.**
Two buttons sit right in the header:
- **"Add new leads"** - opens GitHub's own file-upload page, scoped to
  `data/incoming/`. Drag a file in, commit it, no terminal involved.
- **"Run today's plan"** - opens the Actions tab for the daily workflow,
  where the existing "Run workflow" button triggers a fresh run on
  demand, also with no terminal involved.

A **"Recent imports"** panel under the header shows the last 10 batches
ingested - batch name, when, exactly how many leads were new versus
merged, **and which specific leads were merged** (e.g. "merged:
heritagefinds") - so the day-1-vs-day-2 distinction the brief asks to
demonstrate isn't just a number, it's a name you can point at. Click into
any individual lead and, if it was ever merged from duplicate records,
its detail panel permanently shows "Originally listed as 2 separate
records (L0224, L0254)" - not just during the import window, but for as
long as that lead exists.

To make it live on GitHub Pages (so it updates every morning along with
everything else, no download required):
1. Repo **Settings** → **Pages** → under "Build and deployment," set
   **Source** to "Deploy from a branch," branch **main**, folder **/docs**
2. Save - GitHub gives you a URL like `https://<username>.github.io/<repo>/`
3. The daily workflow already commits a fresh `docs/data/latest.json` every
   run, so the page reflects today's actual output without any extra step

## Drafted replies actually respond to what was said

Earlier versions of the follow-up templates quoted the lead's last message
back inside a fixed wrapper sentence ("You mentioned: 'X'. Keen to find a
time...") regardless of what X actually said - so "Not taking on new
channels currently" and "What's the fee structure?" got the identical
generic push for a call. `src/reply_intent.py` fixes this with a small,
rule-based classifier grounded in real objection-handling practice:
objections (a decline) get acknowledged with no pressure and a low-friction
next step; genuine questions (pricing, logistics) get actually answered
without fabricating numbers we don't have; positive signals move straight
to booking a time. Verified against every one of the 25 real replies that
actually appear in the case-study data (`tests/test_reply_intent.py`), not
hypothetical examples - and a real classification bug was caught in the
process: "not interested" was initially misread as positive sentiment
because "interested" is a substring of it, ignoring the negation.

Each bucket also has multiple phrasings, chosen deterministically per lead
rather than one fixed sentence reused everywhere - identical phrasing
across messages is itself a documented signal of AI-generated text, so
variety isn't cosmetic here. This is a deliberately simple, explainable,
zero-cost rule-based classifier, not an LLM call - a real, named scope
boundary: it handles every reply actually seen in the data, but genuinely
novel phrasing outside these categories falls back to a general (still
improved) reply rather than guessing. Routing unclassified replies through
an actual LLM call, grounded in the same research, is the natural next
upgrade once messages need to handle truly open-ended replies.

## Flagged leads become real GitHub Issues, not a CSV nobody opens

`python -m src.cli sync-review-issues` turns every data-quality-flagged
lead into an actual, clickable, closeable GitHub Issue (labeled
`data-quality`), instead of a CSV export that sits in a folder. Wired
into `run_daily.sh`, so this happens automatically every morning.

**Two real things were found and fixed by actually researching GitHub's
API behavior, not assuming it:**
1. GitHub does **not** auto-create a label just because a new issue
   references it - confirmed against GitHub's own docs ("the label(s)
   must exist for your repository") and multiple real bug reports of
   "Label does not exist" errors. The first version of this feature would
   have failed outright the first time it ran against a real repo, since
   a brand-new repo only has GitHub's defaults. Fixed with
   `ensure_label_exists()`, which creates the label once (idempotently -
   a 422 "already exists" response is treated as success, not an error).
2. `GITHUB_TOKEN` is capped at 1,000 requests/hour per repo. The first
   version searched the API once *per flagged lead, every single run* to
   check for duplicates - fine at today's ~16 flagged leads, but wasteful
   and fragile as that count grows toward 30,000-lead scale. Redesigned
   so each lead's own GitHub issue number is stored locally
   (`leads.github_issue_number`, added via a real migration so it doesn't
   break already-populated databases) - the steady-state cost of this
   command is then a handful of API calls for genuinely *new* flagged
   leads only, not one search per lead forever. Verified with a real
   integration test asserting the exact call counts, and verified the
   migration separately against a simulated pre-existing database to
   confirm no data loss.

It also:
- Caps how many *new* issues get created per run
  (`data_quality_issue_cap` in `config/assumptions.yaml`, default 20) -
  the highest-value flagged leads get an issue first, the rest wait
- Uses only Python's standard library (`urllib`) to talk to the GitHub
  API - no new dependency, no version-mismatch risk

**Authentication:** inside GitHub Actions this works automatically - the
workflow's own token gets `issues: write` permission and is passed to the
script as an environment variable, no secret to create. Running it
locally requires `export GITHUB_TOKEN=<a personal access token with the
"issues" scope>` first; without it, the command skips with a clear
message rather than crashing or silently doing nothing - verified this
exact path locally.

**Verified live, not just with mocks:** the request-building,
deduplication, label-creation, and cap logic are all tested with a mocked
GitHub API (`tests/test_github_issues.py`, 10 tests including two full
integration tests) - and then confirmed against the real, live repo: the
`data-quality` label was created automatically (it didn't exist before),
16 real Issues were opened by the workflow with correct titles, labels,
and bodies (flags, contact details, estimated spend, source record IDs),
and clicking into one showed the content rendering exactly as designed,
including GitHub auto-linking the email as a clickable `mailto:`. Still a
deliberate scope boundary, not an oversight: issues aren't auto-closed
when the underlying flag clears - a person closes it once they've
actually verified the fix, which is safer than auto-closing something
that might have an ongoing discussion on it.

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
  db.py            SQLite schema + connection
  clean.py         field normalization (dates, phone, email, spend, stage, handle)
  ingest.py        entity resolution / dedup-and-merge
  classify.py      channel + lead-type + segment classification
  scoring.py       prioritization tiers, Fit+Engagement scoring, cooldown
  drafting.py      next-action decisioning + message templates
  reply_intent.py  classifies a lead's reply (objection/question/etc) and
                   drafts an actually-responsive follow-up, not a generic wrapper
  config.py        loads config/assumptions.yaml - the seam for real Fleek data
  github_issues.py talks to the GitHub Issues API (stdlib urllib only)
  cli.py           every command (ingest, plan, send, status, review-queue,
                   calibration, recalibrate, rebalance-caps, backlog-forecast,
                   visit-plan, export-dashboard, redraft, auto-ingest)
tests/
  test_clean.py, test_scoring.py, test_classify.py,
  test_config.py, test_reply_intent.py, test_redraft.py,
  test_send_rotation.py             unit + integration tests
  scale_test.py                     30k-row synthetic load test (run separately)
docs/
  index.html       the GitHub Pages dashboard
  data/latest.json the daily snapshot it reads, written by export-dashboard
config/
  assumptions.yaml every capacity number and conversion-rate placeholder,
                   in one place so Fleek can swap in real numbers later
data/
  pipeline_data.xlsx   the provided case-study data
  incoming/            where new lead-drop files land for auto-ingest
.github/workflows/
  daily_plan.yml   runs run_daily.sh on a schedule, fully unattended
```
