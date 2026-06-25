# Development Log

A dated, honest record of how this was actually built: every real issue
found, who/what surfaced it, how it was investigated, and how it was
fixed and verified. This isn't a polished summary written after the fact -
it's a reconstruction of the real working process, including the
mistakes, because that process is the actual substance of how the system
got to its current state, not just the final code.

The short version: most of the genuinely important fixes in this repo
exist because of a direct, specific question or a refusal to accept "it
should work" - not because the build process caught its own problems.
The table below credits that accurately.

---

## Phase 1 - Core build

The first pass: cleaning the raw pipeline, telling resellers and stores
apart by what data they actually have (not the label), prioritizing the
40/day Instagram cap, drafting next actions, and proving the tool can run
twice without double-messaging anyone.

| # | What | How it was verified |
|---|---|---|
| 1.1 | Stage canonicalization (~25 spellings -> 8 real states), 3 date formats parsed, malformed email handling | Checked against the real spreadsheet's actual values, not assumed |
| 1.2 | Entity resolution by email/phone/handle, not `lead_id` | 15 real merges on the actual handover data, specific duplicate pairs manually confirmed |
| 1.3 | Channel decided by contactability, not the `source` label | Verified 31 "reseller"-sourced rows with a real email correctly routed to direct contact |
| 1.4 | Idempotent re-run (same day -> 0 new actions) | Ran `plan` twice on identical data, confirmed 0 new |
| 1.5 | Day-2 drop picks up new leads, merges known overlaps | Ran the real `new_drop_day2` sheet, confirmed the 2 known overlapping leads merged into existing records rather than duplicating |

---

## Phase 2 - "Are we confident?" (user-driven stress test)

**Trigger:** the user asked directly whether everything claimed was
actually true, and explicitly said not to be agreeable about it.

| # | Question / Pushback | Investigation | Outcome |
|---|---|---|---|
| 2.1 | "Is this the best tool possible? Have we covered every base?" | Re-ran the entire test suite and a fresh scale test rather than answering from memory | Found the full `plan` command (not just ingest) had never actually been timed at 30k scale |
| 2.2 | (found while answering 2.1) | Timed the full `plan` command at 30k | 0.6s - fine, but this was previously an *assumption*, not a measured fact |
| 2.3 | "Is there anything further we can optimise?" | Simulated 15 consecutive days of `plan`+`send` at 30k scale to check for degradation over time, not just on day one | Flat performance confirmed; also surfaced the ~341-day Instagram backlog number used throughout `GTM_STRATEGY.md` |
| 2.4 | (found while answering 2.3) | A lead that reached `new` tier and was sent to once never advanced - tier never changed | **Real bug**: `send()` updated touch count but never advanced stage from `new`, so the same top-scored leads would win every single day forever, permanently starving the rest of the queue | Fixed: `send()` now advances `new` -> `contacted`. Added a regression test that proves rotation actually happens over multiple days, not just that a cap exists |

---

## Phase 3 - Grounding in Fleek's actual business

**Trigger:** the user asked whether the scoring research was actually
relevant to this specific company, rather than generic B2B advice.

| # | Issue | Investigation | Fix |
|---|---|---|---|
| 3.1 | Scoring weights were based on generic B2B SaaS lead-scoring research (job titles, content downloads) - not relevant to a wholesale marketplace | Fetched joinfleek.com directly | Found Fleek markets to three explicit, named customer tiers (New Reseller / Full-Time Reseller / Business) with different pitches - rebuilt `classify.py`'s `segment` field around this, personalized drafted messages per segment |
| 3.2 | **Real factual error**, found while doing 3.1: several message templates had the transaction backwards (written as if Fleek buys stock from leads) | Re-read the brief's own wording ("we sell to two very different kinds of lead") next to the live site | Fixed every affected template - Fleek supplies wholesale stock *to* leads, not the reverse |

---

## Phase 4 - Capacity assumptions and the seam for real data

**Trigger:** the user asked what specific number was used for the store
cap, then pointed out that automation changes the real ceiling for some
channels (email) but not others (calls, visits).

| # | Issue | Fix |
|---|---|---|
| 4.1 | Instagram had a real, platform-enforced daily cap; stores had none at all - at 30k scale this would silently produce an unworkable queue of thousands | Added a store cap |
| 4.2 | **Caught immediately by the user**: one flat cap conflates email (scales with automation) with calls/visits (genuinely human-time-limited) | Split into separate `--email-cap` / `--call-cap` / `--visit-cap`, each independently defensible |
| 4.3 | Every cap and weight was hardcoded in source, with no path for Fleek to plug in real numbers later | Built `config/assumptions.yaml` - every placeholder lives in one file, plus a `channel_performance` section and a `rebalance-caps` command that recommends shifting capacity once real conversion data exists. Verified both the "refuse, no data yet" path and the "here's the recommendation" path using a deliberately seeded synthetic dataset |

---

## Phase 5 - Real automation (not just a description of it)

**Trigger:** the user asked "does this require someone to press a button
every morning?"

| # | Issue | Investigation | Fix |
|---|---|---|---|
| 5.1 | The brief pictures this running every morning unattended - there was no actual scheduling artifact, just a sentence in a README | Researched GitHub Actions scheduling specifically | Built `auto-ingest`, `run_daily.sh`, and a GitHub Actions workflow on a real cron schedule |
| 5.2 | Researched whether scheduled workflows are *guaranteed* to keep running | Found GitHub auto-disables scheduled workflows after 60 days of zero repo activity (documented platform behavior) | Added a keep-alive step that commits a status file every successful run, which both resets that clock and gives a visible in-repo proof-of-life |
| 5.3 | **Found live, on GitHub's actual infrastructure**, not in local testing: the workflow's cache-restore/save step intermittently failed ("Cache save failed") | Switched from the split restore+save actions to the single combined `actions/cache` action - more battle-tested | Triggered the workflow again, confirmed clean (no warnings) |

---

## Phase 6 - "Have we grouped stores by city for visits?"

**Trigger:** the user re-read the brief line by line and asked specifically
whether city-grouping for shop visits was actually built, or just claimed.

| # | Issue | Investigation | Fix |
|---|---|---|---|
| 6.1 | City grouping was a **sort**, not a decision - the brief asks "group them by city so you can book the most shop visits in a week," which implies deciding whether a city is worth a trip | Checked the real data's city distribution | Built `visit-plan`: a config-driven (`min_visit_cluster`) decision per city, "book this week" vs "not yet" |
| 6.2 | **Found while fixing 6.1**: the email->call->visit escalation ladder only ever reached "visit" for the `re_engage` (ghosted) tier - a store stuck in `follow_up_due` could be called forever and never escalate | Traced the actual `next_action_type` logic | Unified both tiers onto one ladder, keyed on touch count - contradicted the brief's literal sequence otherwise |
| 6.3 | **Found right after**, by checking the actual GitHub Actions artifact contents rather than trusting the command existed: `visit_plan.csv` was missing entirely | `run_daily.sh` never actually called `visit-plan` - it existed and worked standalone but wasn't wired into the daily automation | Added the missing call, verified all three CSVs now generate end to end |

---

## Phase 7 - The clickable dashboard

**Trigger:** the user asked whether the brief's "click into a few leads"
language implied something more than a CSV - and concluded yes, build it.

| # | Issue | Investigation | Fix |
|---|---|---|---|
| 7.1 | No way to click into an individual lead and see its full picture | Built `docs/index.html` (GitHub Pages) + `export-dashboard` command writing the JSON it reads | Verified by executing the actual page JavaScript against real exported data via Node - not just eyeballing the HTML |
| 7.2 | **Found during that verification**, not assumed safe: the dashboard's visit-plan tab disagreed with the standalone `visit-plan` command's numbers | The dashboard was checking which leads got an *actual queued action today* (capped at 5/day) instead of true visit-*eligibility* | Rewrote it to compute eligibility the same way the standalone command does; re-verified the two now match exactly |

---

## Phase 8 - "Why does this look inconsistent?" (live-site questioning)

**Trigger:** after the dashboard went live, the user asked three specific,
pointed questions about what they were actually looking at.

| # | User's question | Real issue found | Fix |
|---|---|---|---|
| 8.1 | "Why do some rows show a city, some show nothing, some show a handle in the Store tab?" | The subtitle line silently swapped a handle in *instead of* a city, rather than showing both - and there was no visible indicator that "Store Outreach" groups leads by *contact method*, not by what they actually are | Fixed the subtitle to show both when both exist; added an explicit Reseller/Business badge to every row |
| 8.2 | (asked in the same breath) "What is the drafted reply based on?" | Exposed that several templates defaulted to "your shop" even for resellers with no actual shop | Replaced the fallback with the lead's real handle, or a neutral "your account" |
| 8.3 | (caught while fixing 8.2, a **false alarm correctly ruled out**) | My own verification script flagged "your shop" appearing elsewhere too | Checked it directly: that occurrence was the correct, intentional Business-segment copy ("your shop's calendar") for a genuine real shop - not a bug. Distinguishing the real bug from this false positive was itself part of the verification, not assumed either way |

---

## Phase 9 - "Doesn't overly make sense as a reply, does it?" (the big one)

**Trigger:** the user read two real drafted messages next to the actual
replies they were supposedly answering, and pointed out they didn't
actually respond to what was said.

| # | Step | Detail |
|---|---|---|
| 9.1 | Question asked | "Are you just making up replies based on nothing? ... base it on research and what works" |
| 9.2 | Research done | Pulled real findings on AI-writing tells (overused phrases, identical phrasing across messages being itself a tell) and real B2B objection-handling practice (the hard distinction between an *objection* and a *question* - they need different replies) |
| 9.3 | Data pulled | All 25 actual unique replies in the real dataset, to ground the fix in what people really said, not hypotheticals |
| 9.4 | Built | `src/reply_intent.py` - a rule-based classifier (pricing / logistics / objection / positive / stall) with research-backed responses per category, and deterministic variety per lead so identical objections don't all read identically |
| 9.5 | **Real bug found while testing against all 25 real replies**: "not interested right now" classified as *positive* | Root cause: the word "interested" is a literal substring of "**not** interested" - a naive keyword check ignored the negation entirely | Fixed by checking explicit objection phrases before the generic positive keywords; added a permanent regression test specifically for this |
| 9.6 | Verified | Re-ran both of the user's exact two flagged examples through the fixed system and confirmed the new replies actually engage with what was said |

---

## Phase 10 - The production bug that only showed up live

**Trigger:** after Phase 9 shipped, the user reported the dashboard still
showed the old, broken reply text.

| # | Step | Detail |
|---|---|---|
| 10.1 | First (wrong) hypothesis | Assumed it was a deployment/caching issue and gave incorrect git guidance ("always take `--theirs`" on a merge conflict) without accounting for *when* each version was generated |
| 10.2 | Real root cause found | The lead's message had been drafted hours earlier, **before** the fix was pushed - and the tool's own no-double-messaging guarantee (built and tested back in Phase 1) correctly locked that text in for the day, with no way to know the only thing that changed was the *wording*, not the lead selection |
| 10.3 | Fix | Built `redraft`: refreshes message text for anything still `status='queued'` today using current code, while provably never touching anything already `status='sent'`. Wired permanently into `run_daily.sh` |
| 10.4 | Verification | A test that proves both halves explicitly: stale queued text gets corrected, already-sent text is byte-for-byt unchanged |
| 10.5 | Process correction | The earlier wrong git advice (10.1) was corrected once the real cause was understood - worth recording that the first explanation given was wrong, not just the eventual fix |

---

## What this log is for

Anyone reading this top to bottom should be able to see exactly which
decisions were deliberate engineering choices versus real mistakes that
got caught and fixed, and *how* each was caught. Almost none of the
entries marked "found while testing" or "found by the user" were things
the build process surfaced on its own - they came from someone refusing
to accept "this should work" as good enough, and checking the real, live
result instead. That's the part of this process worth being honest about,
not just the finished commit history.
