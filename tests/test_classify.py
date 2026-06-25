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


def test_draft_message_never_calls_a_reseller_a_shop():
    # A reseller who happens to be on the direct (email/phone) channel
    # doesn't have a "shop" - the fallback should use their real handle,
    # not generic store language that's wrong for who they actually are.
    from src import drafting
    lead = {"contact_name": "Marcus", "store_name": None, "handle": "staticvintage",
            "active_listings": None, "sales_velocity_30d": None, "lead_key": "lead:T1",
            "last_inbound_text": None, "city": None, "segment": "full_time_reseller"}
    msg = drafting.draft_message(lead, "email_followup")
    assert "your shop" not in msg
    assert "@staticvintage" in msg


def test_dm_cold_fallback_never_calls_an_instagram_reseller_a_shop():
    # Same bug, different function: the dm_cold cold-open's defensive
    # fallback (only reachable if segment is somehow unset) previously said
    # "your shop" - an Instagram-only reseller has a page, not a shop.
    from src import drafting
    lead = {"segment": None, "active_listings": None, "sales_velocity_30d": None,
            "contact_name": None, "store_name": None, "handle": "somehandle",
            "last_inbound_text": None, "city": None}
    msg = drafting.draft_message(lead, "dm_cold")
    assert "your shop" not in msg


def test_draft_message_falls_back_to_neutral_when_no_identifier_at_all():
    from src import drafting
    lead = {"contact_name": None, "store_name": None, "handle": None, "lead_key": "lead:T2",
            "active_listings": None, "sales_velocity_30d": None,
            "last_inbound_text": None, "city": None, "segment": None}
    msg = drafting.draft_message(lead, "email_followup")
    assert "your account" in msg
    assert "your shop" not in msg
