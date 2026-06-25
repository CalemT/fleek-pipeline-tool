import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import reply_intent  # noqa: E402

# Every one of these is a REAL reply from the actual case-study dataset,
# not a hypothetical - pulled directly from pipeline_data.xlsx.
REAL_REPLIES = {
    "Happy to chat, mornings best.": "positive",
    "Interested - send pricing.": "pricing_question",
    "Not taking on new channels currently.": "objection",
    "Owner is back next week, call then.": "stall",
    "Sure, pop in on Thursday.": "positive",
    "Thanks, can you email a one-pager?": "logistics_question",
    "Too busy this season, try later.": "stall",
    "We already sell on Vinted.": "objection",
    "What's the fee structure?": "pricing_question",
    "already on another platform tbh": "objection",
    "can you do a call fri?": "positive",
    "do you ship to EU?": "logistics_question",
    "do you take menswear too": "logistics_question",
    "how does payout work": "logistics_question",
    "how much for the whole bundle?": "pricing_question",
    "interested but busy this week": "positive",
    "maybe next month": "stall",
    "need to think about it": "stall",
    "not interested right now": "objection",
    "ok sounds good when can we talk": "positive",
    "send me the bundle list": "logistics_question",
    "what brands do you take?": "logistics_question",
    "whats the catch lol": "objection",
    "whats your commission?": "pricing_question",
    "yeah keen, drop details": "positive",
}


def test_every_real_reply_in_the_dataset_classifies_correctly():
    for text, expected in REAL_REPLIES.items():
        assert reply_intent.classify_reply_intent(text) == expected, text


def test_negation_does_not_get_read_as_positive():
    # The actual bug found: "interested" as a bare substring also matches
    # inside "NOT interested" - a naive check would misread a clear
    # decline as enthusiasm. This must never regress.
    assert reply_intent.classify_reply_intent("not interested right now") == "objection"
    assert reply_intent.classify_reply_intent("I'm not interested") == "objection"


def test_no_reply_yet_returns_none():
    assert reply_intent.classify_reply_intent(None) is None
    assert reply_intent.classify_reply_intent("") is None


def test_reply_for_is_deterministic_per_lead():
    a = reply_intent.reply_for("lead:L0001", "Not taking on new channels currently.")
    b = reply_intent.reply_for("lead:L0001", "Not taking on new channels currently.")
    assert a == b  # same lead, same input -> same output every time


def test_reply_for_varies_across_leads_in_the_same_bucket():
    # Different leads with the same objection shouldn't all get byte-identical
    # text - that uniformity is itself a tell that the message is templated.
    texts = {reply_intent.reply_for(f"lead:L{i:04d}", "not interested right now") for i in range(20)}
    assert len(texts) > 1


def test_reply_never_fabricates_specific_numbers():
    # Pricing questions must never invent a number we don't actually have.
    for variant in reply_intent._REPLIES["pricing_question"]:
        assert not any(ch.isdigit() for ch in variant)
