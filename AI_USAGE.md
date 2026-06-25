# How AI Was Used

**Tool:** Claude (chat) - not Claude Code or Cursor. No autonomous agent
loop; a long, direct conversation with shell/file access, where every
significant claim was checked rather than taken on trust.

This file is the short version. **`DEVELOPMENT_LOG.md` is the complete,
dated record** of every issue found, how it was found, and how it was
fixed - read that for the full picture.

## What AI was used for

Writing essentially all the code (cleaning, entity resolution, scoring,
drafting, the CLI, the GitHub Pages dashboard); running real research
when specifically directed to (Fleek's actual website and customer
segments, B2B lead-scoring practice, signs of AI-generated writing, sales
objection-handling technique); building and running the test suite;
debugging issues live, including ones that only surfaced after deploying
to GitHub Actions.

## Where it genuinely sped things up

The boring-but-essential parts: surveying every messy field combination
across 295 real rows by hand would be slow; writing the
cleaning/scoring/CLI/dashboard code from a clear spec is exactly what AI
is fast at. Also fast at running real, falsifiable tests once told
precisely what to check - executing the actual dashboard JavaScript
against real exported data via Node, or simulating 15 days of plan+send
cycles at 30,000-lead scale to check for performance degradation over
time.

## The verification discipline that actually shaped this build

The single most important thing about this process: **AI's first answer
was never treated as the final one.** Every claim - "this works," "this
scales," "this is fixed" - was tested before it was accepted, and almost
every meaningful fix in this repo exists because that testing was
insisted on, not because the build caught its own problems. Specifically:

**1. Generic output was never accepted as good enough.** The first scoring
research was standard B2B SaaS material - largely irrelevant to a
wholesale vintage marketplace. Pushed back on directly, which led to
properly researching Fleek's own site and finding its actual customer
segments (New Reseller / Full-Time Reseller / Business) - and, in the
same pass, catching a real factual error where several drafted messages
had the entire transaction backwards.

**2. "It should work" was never accepted without running it.** A bug
where leads got stuck in a no-cooldown tier forever - silently starving
the entire daily queue - was only found by demanding an actual multi-day
simulation be run and the output checked, not by accepting that the logic
looked correct on paper.

**3. The live, deployed product was checked directly, repeatedly - not
just the code.** Several real bugs (inconsistent display logic on the
dashboard, generic "your shop" language sent to resellers who don't have
a shop) were found by looking at the actual deployed page and asking
specific, pointed questions about exactly what was on screen and why it
looked the way it did - not by trusting that passing tests meant the
product was right.

**4. The most significant fix in this build came from refusing to accept
a plausible-looking answer at face value.** Reading two real drafted
replies next to the actual messages they were supposedly responding to,
and asking directly whether they made sense, surfaced that the system was
quoting messages back inside a fixed wrapper regardless of content. That
single question led to real research (AI-writing-detection signs, B2B
objection-handling practice) and a properly tested rebuild - which, in
turn, was checked against all 25 real replies in the dataset and caught a
genuine classification bug (a negation being read as positive sentiment).

**5. Even after a fix shipped, "done" was checked again on the live
site.** When that fix didn't visibly take effect, the cause wasn't
assumed - it was traced to a real interaction between two correct
features (the no-double-messaging guarantee locking in text drafted
before the fix), found by checking the actual live result a second time
rather than accepting that a passing test suite meant it worked end to
end.

**6. Confidence claims were repeatedly challenged, not accepted.** Several
points in this build where the natural answer would have been "yes, this
is finished" were instead met with "are you sure - have you actually
checked," which is the direct reason for the 30,000-lead scale tests, the
multi-day rotation simulation, the GitHub Actions live verification, and
the backlog-forecast numbers that ended up driving the scaling reasoning
in `GTM_STRATEGY.md`.

## The honest pattern

AI is fast at producing a plausible first draft and at running
exhaustive, falsifiable tests once told exactly what to check. It does
not reliably catch its own generic defaults, blind spots, or
content-level mistakes by reviewing its own work. In this build, nearly
every meaningful fix traces back to a specific, sometimes blunt question
about whether something was actually true - asked, checked, and not let
go of until it was either proven or fixed. That discipline is the actual
reason this system is in the state it's in, and it's worth being
straightforward about rather than presenting the result as something
more automatic than it was.

See `DEVELOPMENT_LOG.md` for the complete trail, and `GTM_STRATEGY.md`
for the commercial reasoning behind how the system prioritizes, sequences,
and scales outreach.

