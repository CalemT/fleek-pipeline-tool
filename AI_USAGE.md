# How AI was used to build this

*(Draft based on the actual build session - personalize this before you submit it, since you'll be asked to speak to it directly in the debrief.)*

**Tool:** Claude (chat), used conversationally rather than Claude Code/Cursor
- no IDE agent loop, just iterating in a chat session with direct shell/file
access to inspect the data and write/run/fix code.

## What it was used for

- **Exploring the messy data before writing any code.** Rather than guessing
  at the dirtiness, every cleaning rule in `src/clean.py` and `src/classify.py`
  came from actually querying the spreadsheet first: counting stage-label
  variants, checking which "reseller" rows had an email, checking whether
  `followers` was ever genuinely populated on store rows (it wasn't - it's a
  placeholder `0`), and confirming duplicate entities by email/phone/handle
  before deciding the merge key. The classification rule ("channel = what
  contact info actually exists, not the source label") came directly out of
  that inspection, not a guess.
- **Writing the cleaning / dedup / scoring / drafting code.** Most of the
  module code was written by Claude based on a spec worked out in
  conversation, then run immediately against the real data to check the
  output counts made sense (e.g. confirming dedup collapsed exactly the
  duplicate clusters found during inspection, confirming the channel split
  roughly matched the README's stated 60/40).
- **Catching a real performance bug.** The first version of `ingest.py`
  matched each new row against the database with a per-row SQL query
  (including a `substr()` scan for phone matching). It worked fine on 265
  rows. Running the 30k-row scale test exposed it taking 54 seconds - too
  slow to credibly claim "still works at 30,000." Claude diagnosed the
  per-row table scan as the cause and rewrote matching around an in-memory
  index built once per ingest, which brought it down to ~9.5s. This is the
  kind of thing that's easy to miss without actually generating a large
  synthetic batch and timing it, which is why `tests/scale_test.py` exists
  as a real check rather than just a comment claiming it scales.
- **Writing tests and the architecture diagram/doc.**

## Where it sped things up

Mainly the boring-but-essential parts: surveying every messy field
combination across 265+30 rows by hand would be slow and error-prone;
writing the cleaning/normalization functions, the CLI plumbing, and the
test scaffolding from a clear spec is exactly what AI is fast at.

## Where it needed a human call

- **The prioritization rubric itself is a business judgement, not something
  to default to.** Deciding that "waiting on us" always outranks a bigger
  but cold new lead, and what the cooldown windows should be by channel/stage,
  are calls about how Fleek's reps actually work - they came from reasoning
  through the brief's own framing ("a lot of these leads are sitting
  half-replied... getting those going again is most of the job"), not from
  an AI default.
- **Message tone.** The drafted templates are deliberately plain and
  short - a human should still skim before anything goes out, especially on
  Instagram where a tone that reads as spammy risks the account, not just
  the lead.
- **Anything client-facing should be sanity-checked against the actual
  conversation history** (`last_inbound_text`) before sending - the draft
  references it, but doesn't reason about *what kind of reply it actually
  needs*, which is a step I read manually for the live walkthrough.
