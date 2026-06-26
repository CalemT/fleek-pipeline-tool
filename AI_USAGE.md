# How I Used AI

I built this with Claude, in a normal chat conversation, not Claude Cowork
or Cursor, a chat and a terminal tab for coding. No autonomous agent running off on its own. I sat with it the
whole way through and checked everything before I accepted it.

`DEVELOPMENT_LOG.md` has the full, dated record of every bug we found and
how. This is the short version, in my own words.

## What I used it for

Claude wrote almost all of the code: the cleaning logic, the dedup
matching, the scoring, the message drafting, the CLI, the dashboard. I
used it to research things I needed real answers on instead of guesses -
Fleek's own website and customer segments, how B2B teams handle
sales objections, what makes text read as AI-written, GitHub's actual API
rules. It also built and ran the test suite, and helped me debug things
live once they were deployed and breaking in ways local testing
hadn't caught. My thoughts on AI are that you don't have to be a genius,
you are allowed the opportunity to pull the puppet strings behind the 
genius, understanding how to pull them correctly defines the outcome.

## Where it saved me time

All the months of coding and building and researching and the parts that are tedious. Going through 295 messy
rows by hand to spot every weird date format or duplicate would have
taken me a long time. Writing the cleaning code, the scoring code, the
dashboard, all from a clear spec, is exactly what it's fast at. It's also
genuinely good at running a lot of tests quickly once I tell it exactly
what to check - running the dashboard's actual code against real data,
or simulating two weeks of the tool running every day to see if anything
broke over time.

## The thing I did, over and over, that made this work

I never took its first answer as final. If it said "this works" or "this
is fixed," I made it prove that before I believed it. Almost every real
fix in this whole project happened because I pushed on something, not
because Claude caught its own mistake on its own. Here's what that looked like in practice:

**I didn't accept generic answers.** The first pass at scoring leads used
standard B2B SaaS advice that had nothing to do with a vintage clothing
marketplace. I told it to go look at Fleek's website instead of
guessing, which is how we found Fleek's real customer segments (New
Reseller, Full-Time Reseller, Business) - and in the same pass, caught
that several drafted messages had the whole deal backwards, written as if
Fleek buys stock from people instead of sells to them.

**I made it run things instead of trusting the logic looked right.**
There was a bug where leads would get stuck in a stage that never
cooled down, which meant the same top leads would win the queue forever
and nobody else would ever get touched. We only found that by running a
proper multi-day simulation and watching the output, not by reading the
code and deciding it was fine.

**I kept checking the live site myself, not just the code.** A few real
bugs - the dashboard showing inconsistent info, drafted messages calling
a reseller's Instagram account "your shop" when they don't have one -
came from me looking at the deployed page and asking why it
looked the way it did. Not from anything the tests caught.

**The biggest fix in the whole thing came from me just reading two replies
and asking if they made sense.** I read a real lead's message side by
side with the reply the tool had drafted back to them, and it was
obviously wrong - it was just quoting their message back inside the same
generic sentence every time, no matter what they'd said. That one
question led to real research on objection handling and on what makes
writing sound like AI, and a proper rebuild that we then tested against
every real reply in the dataset - which is how we found a second bug, a
"not interested" reply getting read as positive because the word
"interested" is technically inside it.

**Even after a fix shipped, I checked again on the live site and it
still wasn't working.** Turned out the message had already been drafted
hours earlier, before the fix went out, and the tool's own
no-double-messaging rule had correctly locked that old text in for the
day. Nothing was broken - it just needed a way to refresh stale
drafts, which we built.

**I kept pushing back when I was told things were finished.** More than
once. Each time, that led to more testing - the 30,000-lead load test, the
multi-day rotation check, an actual live run on GitHub Actions, the
backlog numbers that ended up driving the whole scaling argument in
`GTM_STRATEGY.md`.

**I told it twice not to accept "this is done," and both times it found
something real.** When I asked why we weren't using GitHub Issues instead
of a CSV for flagged leads, it built that - but the first version assumed
GitHub creates a label automatically when you reference it in a new
issue. That's not true. I told it to check GitHub's own docs
instead of guessing, and it found real bug reports confirming the label
has to exist first or the whole thing fails. The same check also found
that the design would've hit GitHub's API rate limit at real scale,
because it was searching the API once per flagged lead every single run.
Both got fixed, and the database change that came out of it got tested
against a copy of an already-running database to make sure it wouldn't
wipe anything.

**I asked a specific question about where new leads would actually come
from day to day, not a vague "is this automated" question.** That led to
checking Google's Places API and Instagram's API side by side instead of
assuming they work the same way. Turns out they don't - Google's API
genuinely supports searching for businesses by category and area, no
scraping needed. Instagram's official API has no general search at all,
confirmed straight from their own docs, and there are real reports of
apps getting banned for trying to get around that with scraping. That's
exactly why the brief calls online resellers "the hard one" - now I have
an actual source for why that's true, not just the brief's own word for
it.

## The honest takeaway

Claude is fast at writing a plausible first draft and fast at running
exhaustive tests once I tell it exactly what to check. It doesn't catch
its own blind spots on its own, especially about specific platforms -
what GitHub's API actually allows, what Instagram's API actually allows,
which Python version something needs. It doesn't know which of its own
assumptions are wrong unless I tell it to go check. Nearly every real fix
in this project came from me asking a specific, sometimes blunt question
and not letting it go until it was actually proven, not from Claude fixing itself.

## What I'd do differently next time

Looking back at this whole project, almost every real bug came from the
same root cause: an assumption about something specific - Fleek's actual
business, GitHub's actual API behavior, a particular Python version, a
specific platform's rate limits - that turned out to be wrong, and we only
caught it because I told it to stop and research that one thing
properly. That happened late, every time, after the fact.

The better way to do this would be to ask for that kind of specific,
company- and platform-level research right at the very start, before
writing a single line of code, instead of finding each gap one expensive
bug at a time as the build went on. That's the real lesson I'm taking
into the next project, not just something I'm noting about this one.

See `DEVELOPMENT_LOG.md` for the full trail, and `GTM_STRATEGY.md` for
the actual commercial reasoning behind how this prioritizes, sequences,
and scales outreach.
