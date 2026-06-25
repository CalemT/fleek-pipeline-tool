import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import classify  # noqa: E402


def test_store_name_means_business_segment_regardless_of_other_fields():
    lead_type = classify.classify_lead_type("Past Cellar", None, None, None, None)
    assert lead_type == "store"
    assert classify.classify_segment(lead_type, None, None) == "business"


def test_low_volume_reseller_is_new_reseller():
    lead_type = classify.classify_lead_type(None, "@smallshop", 500, 10, 5)
    assert lead_type == "reseller"
    assert classify.classify_segment(lead_type, 10, 5) == "new_reseller"


def test_high_volume_reseller_is_full_time():
    lead_type = classify.classify_lead_type(None, "@bigshop", 50000, 300, 150)
    assert lead_type == "reseller"
    assert classify.classify_segment(lead_type, 300, 150) == "full_time_reseller"


def test_hybrid_row_with_both_store_name_and_handle_is_still_a_store():
    # e.g. day-2 lead L0284: has both store_name AND a handle - store_name wins
    lead_type = classify.classify_lead_type("Maison Lab", "@heritageprelovedstudio", None, None, None)
    assert lead_type == "store"


def test_action_categories_split_correctly():
    from src import drafting
    assert drafting.ACTION_CATEGORY["email_intro"] == "email"
    assert drafting.ACTION_CATEGORY["email_followup"] == "email"
    assert drafting.ACTION_CATEGORY["call"] == "call"
    assert drafting.ACTION_CATEGORY["call_confirm"] == "call"
    assert drafting.ACTION_CATEGORY["visit"] == "visit"


def test_store_escalation_ladder_reaches_visit_regardless_of_which_unresponsive_tier():
    # Previously only the re_engage (ghosted) tier could ever escalate to a
    # visit - a store stuck in follow_up_due could be called forever. Both
    # tiers represent "reached out, no reply yet" and should share one ladder.
    from src import drafting
    for tier in ("follow_up_due", "re_engage"):
        lead = {"channel": "direct", "num_touches": 0, "stage": "contacted"}
        assert drafting.next_action_type(lead, tier) == "email_followup"
        lead["num_touches"] = 1
        assert drafting.next_action_type(lead, tier) == "call"
        lead["num_touches"] = 2
        assert drafting.next_action_type(lead, tier) == "visit"
