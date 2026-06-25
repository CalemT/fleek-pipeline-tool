"""
Classifies what a lead's last inbound reply actually means, so the drafted
follow-up responds to it instead of just quoting it back inside a fixed
wrapper sentence - which is exactly the bug this module exists to fix.

Grounded in two pieces of real research, not guesswork:
1. Sales objection-handling practice draws a hard line between an OBJECTION
   ("not interested," "no budget" - low-trust, means "you haven't earned
   the right to keep talking yet") and a QUESTION ("what's the fee
   structure?" - means "I'm engaged, I need a specific answer"). Treating
   both the same way loses both. The right move for an objection is
   Acknowledge -> Align -> Reframe -> a low-friction next step, never
   arguing or pushing for a call immediately. The right move for a
   question is to actually engage with what was asked.
2. Identical phrasing across messages is itself a tell that something was
   AI-generated ("humans are messy; AI packages ideas into uniform
   blocks"). So each bucket below has multiple phrasings, chosen
   deterministically per lead (not randomly - reproducible for testing)
   rather than one fixed sentence reused for every single objection.

This is a deliberately simple, rule-based keyword classifier - not a
model, not an LLM call. That's a real, named tradeoff: it's fast, free,
fully explainable in a debrief, and handles every reply actually seen in
the real dataset (see tests), but it won't gracefully handle genuinely
novel phrasing outside these categories - it falls back to a general,
still-improved reply rather than guessing. The natural next upgrade, once
this needs to handle truly open-ended replies, is routing unclassified
text through an actual LLM call grounded in the same research - that's a
deliberate scope boundary for this build, not an oversight.
"""
import hashlib

# Order matters: checked top-to-bottom, first match wins. Specific
# questions are checked before general sentiment, because a lead asking
# "how much for the whole bundle?" deserves a pricing answer regardless of
# whatever tone surrounds it - the specific ask is the signal worth acting
# on (the research explicitly calls this out: "anchor your reply to the
# prospect's stated priority").
_PRICING_KEYWORDS = [
    "fee", "price", "pricing", "cost", "commission", "how much", "rate structure",
]
_LOGISTICS_KEYWORDS = [
    "ship", "deliver", "payout", "brands", "menswear", "womenswear",
    "bundle list", "one-pager", "catalog", "categories",
]
_POSITIVE_KEYWORDS = [
    "interested", "keen", "sounds good", "happy to", "yeah", "sure,",
    "drop details", "pop in", "when can we talk", "call fri", "call mon",
    "call tue", "call wed", "call thu", "call sat", "call sun",
]
_OBJECTION_KEYWORDS = [
    "not taking", "not interested", "no thanks", "already on", "already sell",
    "already use", "another platform", "catch",
]
_STALL_KEYWORDS = [
    "maybe", "need to think", "next month", "try later", "busy this week",
    "back next week", "call then",
]


def classify_reply_intent(text: str | None) -> str | None:
    """Returns one of 'pricing_question', 'logistics_question', 'objection',
    'positive', 'stall', or None (no reply / nothing recognized).

    Objection phrases are checked before the generic positive keywords on
    purpose: "interested" as a bare substring also matches inside "NOT
    interested," and a naive substring check with positive checked first
    would misread a clear decline as enthusiasm - caught by testing
    against every real reply in the dataset, not assumed safe."""
    if not text:
        return None
    t = text.lower()
    for kw in _PRICING_KEYWORDS:
        if kw in t:
            return "pricing_question"
    for kw in _LOGISTICS_KEYWORDS:
        if kw in t:
            return "logistics_question"
    for kw in _OBJECTION_KEYWORDS:
        if kw in t:
            return "objection"
    for kw in _POSITIVE_KEYWORDS:
        if kw in t:
            return "positive"
    for kw in _STALL_KEYWORDS:
        if kw in t:
            return "stall"
    return None


# Multiple phrasings per intent, deterministically varied by lead_key so
# the same lead always gets the same draft on re-runs (testable,
# reproducible) but different leads in the same bucket don't all receive
# byte-identical messages.
_REPLIES = {
    "pricing_question": [
        "Good question - pricing depends on order size and category, so I'd "
        "rather give you real numbers than guess over email. Want a quick "
        "breakdown, or is a short call easier?",
        "Fair ask - it varies by volume and category, so a quick call or an "
        "emailed breakdown beats me estimating here. Which's easier for you?",
    ],
    "logistics_question": [
        "Happy to walk through that properly - quickest is a short call, or "
        "I can put the basics in writing if that's easier for you.",
        "Good question, there's a bit of detail to it. Tell me what's "
        "easier: a quick call, or I email over the specifics?",
    ],
    "positive": [
        "Great, let's lock in a time - what works for you this week?",
        "Love that - 15 minutes this week to sort the specifics?",
    ],
    "objection": [
        "Totally fair, no pressure. Worth keeping the door open in case "
        "timing shifts - happy to check back in a few weeks?",
        "Understood, that's a reasonable call. If a one-off batch ever makes "
        "sense down the line, just flag it - otherwise I won't keep chasing.",
        "Fair enough. Doesn't have to be either/or - happy to be a backup "
        "option whenever the timing's better for you.",
    ],
    "stall": [
        "No rush at all - I'll check back in a couple of weeks unless "
        "you'd rather pick a date now.",
        "Makes sense, take your time. Just flag whenever's good and I'll "
        "work around it.",
    ],
}

_GENERAL_FALLBACK = [
    "Following up on this - still keen to chat? Happy to work around your schedule.",
    "Circling back on this one - want to find a time this week, or is it "
    "still too soon?",
]


def reply_for(lead_key: str, last_inbound_text: str | None) -> str:
    """The actual responsive reply body, chosen by intent and varied
    deterministically so not every lead in the same bucket reads identically."""
    intent = classify_reply_intent(last_inbound_text)
    variants = _REPLIES.get(intent, _GENERAL_FALLBACK)
    idx = int(hashlib.sha256(lead_key.encode()).hexdigest(), 16) % len(variants)
    return variants[idx]
