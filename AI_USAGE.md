# How AI Was Used

**Tool:** Claude (chat) - not Claude Code or Cursor. No autonomous agent
loop; a long, direct conversation with shell/file access, where every
significant decision was reviewed, questioned, or redirected before being
treated as final.

This file is the short version. **`DEVELOPMENT_LOG.md` is the complete,
dated record** of every real issue found during the build, how it was
found, and how it was fixed - read that for the full picture. The honest
summary of the pattern across all of it:

## What AI was used for

Writing essentially all the code (cleaning, entity resolution, scoring,
drafting, the CLI, the GitHub Pages dashboard); running real research when
specifically asked to (Fleek's actual website and customer segments, B2B
lead-scoring practice, signs of AI-generated writing, sales
objection-handling technique); building and running the test suite;
debugging issues live, including ones that only surfaced after deploying
to GitHub Actions.

## Where it genuinely sped things up

The boring-but-essential parts: surveying every messy field combination
across 295 real rows by hand would be slow; writing the
cleaning/scoring/CLI/dashboard code from a clear spec is exactly what AI
is fast at. Also fast at running real, falsifiable tests - executing the
actual dashboard JavaScript against real exported data via Node, or
simulating 15 days of plan+send cycles at 30,000-lead scale to check for
performance degradation over time, rather than just asserting things work.

## Where it got things wrong, and - importantly - how that got caught

AI's first pass at almost everything needed a harder second look, and
that second look came from direct, specific questioning, not from AI
reviewing its own output:

- The first scoring research was generic B2B SaaS advice - irrelevant to
  this business. Caught by being asked directly whether it was actually
  relevant, which led to reading joinfleek.com properly.
- That same pass produced a real factual error: several message drafts
  had the transaction backwards. Caught by re-reading the brief's own
  wording against the live site - not spotted by AI re-checking itself.
- A real bug (leads stuck in a no-cooldown tier forever, silently
  starving the rest of the daily queue) was only found by actually
  simulating multiple days of sends and watching the queue fail to
  rotate - not by code review.
- The most significant content bug - drafted replies that quoted a
  lead's message back inside one fixed wrapper sentence regardless of
  what they'd actually said - was caught by reading two real examples
  side-by-side with what was sent and asking whether it made sense as a
  reply. That question led to real research (AI-writing tells, B2B
  objection-handling practice) and a properly tested fix.
- Even after that fix shipped, it didn't visibly take effect on the live
  site - a real production bug (a message drafted hours earlier, before
  the fix, was correctly locked in by the tool's own no-double-messaging
  guarantee). Found by checking the actual live result again rather than
  assuming a passing test suite meant it worked end to end.

**The honest pattern:** AI is fast at producing a plausible first draft
and at running exhaustive, falsifiable tests once told exactly what to
check. It does not reliably catch its own generic defaults, blind spots,
or content-level mistakes by reviewing its own work - in this build,
nearly every meaningful fix traces back to a specific, sometimes blunt
question, not to AI self-correction. That's worth being honest about
rather than dressing up as something more automatic than it was.

See `DEVELOPMENT_LOG.md` for the complete trail, and `GTM_STRATEGY.md`
for the commercial reasoning behind how the system prioritizes, sequences,
and scales outreach.
