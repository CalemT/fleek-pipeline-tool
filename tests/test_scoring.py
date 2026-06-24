import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import scoring  # noqa: E402

TODAY = date(2026, 3, 1)


def test_won_and_lost_are_excluded():
    assert scoring.lead_tier("won", "direct", "2026-02-01", TODAY) is None
    assert scoring.lead_tier("lost", "instagram_dm", "2026-02-01", TODAY) is None


def test_waiting_on_us_always_eligible_no_cooldown():
    for stage in scoring.WAITING_ON_US:
        assert scoring.lead_tier(stage, "instagram_dm", "2026-02-28", TODAY) == "waiting_on_us"


def test_new_lead_always_eligible():
    assert scoring.lead_tier("new", "instagram_dm", None, TODAY) == "new"


def test_contacted_in_cooldown_is_skipped_then_eligible_after():
    recent = scoring.lead_tier("contacted", "instagram_dm", "2026-02-28", TODAY)  # 1 day ago, cooldown=3
    assert recent is None
    older = scoring.lead_tier("contacted", "instagram_dm", "2026-02-20", TODAY)  # 9 days ago
    assert older == "follow_up_due"


def test_waiting_on_us_outranks_new_outranks_followup():
    assert scoring.TIER_SCORE["waiting_on_us"] > scoring.TIER_SCORE["new"]
    assert scoring.TIER_SCORE["new"] > scoring.TIER_SCORE["follow_up_due"]
    assert scoring.TIER_SCORE["follow_up_due"] > scoring.TIER_SCORE["re_engage"]


def test_value_score_prefers_actual_spend_and_is_bounded():
    assert scoring.fit_score(9000, None, None, None) == 1.0
    assert scoring.fit_score(18000, None, None, None) == 1.0  # capped, doesn't exceed 1
    assert 0 <= scoring.fit_score(None, 150, None, 40000) <= 1.0


def test_fit_score_missing_fields_dont_unfairly_drag_score_down():
    # A store with only spend populated should be judged purely on spend,
    # not penalized for not having a follower count (which doesn't apply to it).
    assert scoring.fit_score(9000, None, None, None) == scoring.fit_score(9000, 0, 0, 0) == 1.0 or \
        scoring.fit_score(9000, None, None, None) >= scoring.fit_score(9000, 0, 0, 0)


def test_engagement_score_rewards_a_real_reply_most():
    no_reply = scoring.engagement_score(None, 1, "2026-02-28", TODAY)
    with_reply = scoring.engagement_score("yes please send details", 1, "2026-02-28", TODAY)
    assert with_reply > no_reply


def test_higher_value_never_crosses_a_tier_boundary():
    # A maxed-out "new" lead must never outscore a low-value "waiting_on_us" lead -
    # tier always dominates value, by design.
    low_value_waiting = scoring.TIER_SCORE["waiting_on_us"] + 0 * 100
    high_value_new = scoring.TIER_SCORE["new"] + scoring.fit_score(9000, 200, 500, 50000) * 100
    assert low_value_waiting > high_value_new
