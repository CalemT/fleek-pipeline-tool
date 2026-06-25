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

**7. Even after being told the project was essentially finished - twice -
that was rejected, and it found two more real, would-have-shipped bugs.**
Asked directly "why would we not turn this into GitHub Issues instead of
a CSV" led to building a GitHub Issues integration. The first version of
it assumed GitHub auto-creates a label when a new issue references it -
untrue, confirmed against GitHub's own documentation and real bug reports
once actually told to research GitHub's specific platform behavior rather
than write code from general knowledge. That version would have failed
outright the first time it ran against a real repository. The same
research pass also surfaced that the design didn't actually scale the way
it was claimed to (one API search call per flagged lead, against a
platform rate limit that's a real, documented number, not a guess) -
leading to a proper redesign and a database migration that was then
separately verified against a simulated already-existing database to
make sure it wouldn't silently corrupt real data.

## The honest pattern

AI is fast at producing a plausible first draft and at running
exhaustive, falsifiable tests once told exactly what to check. It does
not reliably catch its own generic defaults, blind spots, or
content-level mistakes by reviewing its own work - and it especially does
not reliably know which of its own assumptions about a specific platform
(GitHub's API behavior, Instagram's rate limits, a specific Python
version) are actually true versus just plausible-sounding, unless directed
to go and check. In this build, nearly every meaningful fix traces back to
a specific, sometimes blunt question about whether something was actually
true - asked, checked, and not let go of until it was either proven or
fixed. That discipline is the actual reason this system is in the state
it's in, and it's worth being straightforward about rather than
presenting the result as something more automatic than it was.

## The lesson worth carrying forward

The clearest pattern across this entire build: almost every real bug
traced back to an assumption about something specific - Fleek's actual
business model, GitHub's actual platform behavior, a particular Python
version, a specific API's rate limits - that turned out to be wrong, and
was only caught because of a direct instruction to go research it
properly rather than reason from general knowledge. The fix that came out
of that pattern, late, every time, was always "research this specific
thing properly first." The better version of this process would have
front-loaded that instruction at the very start - asking for
company-specific, industry-specific, and platform-specific research
*before* writing the first line of code, rather than discovering each gap
reactively, one expensive bug at a time, over the course of the build.
That's a genuine process improvement worth carrying into the next project,
not just a note about this one.

See `DEVELOPMENT_LOG.md` for the complete trail, and `GTM_STRATEGY.md`
for the commercial reasoning behind how the system prioritizes, sequences,
and scales outreach.

