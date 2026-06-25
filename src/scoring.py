"""
Who gets messaged today, and why.

The brief's framing of the hard problem is: "with only ~40 DMs a day, who do
you message, where is each person up to, and what do you say next" - and
flags that a lot of leads are sitting half-replied with nobody following up.
That's the design driver here: a lead where the ball is in OUR court (they
replied, they're warm, they're negotiating, a call is booked) outranks a
brand new cold lead, which in turn outranks chasing someone who's gone quiet.

This is intentionally aligned with how B2B lead scoring is actually built in
practice, not invented from scratch: most models split into three buckets -
Fit (does this account look like a real, sizable business), Engagement
(are they actually interacting with us), and Intent (explicit buying
signals). Research on this also confirms funnel stage/status is one of the
strongest individual predictors of conversion - which is why STAGE is the
primary gate here (the tier system below), and Fit+Engagement only break
ties *within* a tier rather than overriding it.

Tiers (highest score first):
  1. waiting_on_us   - replied / warm / negotiating / call_booked. Lead is
                        engaged and waiting on us. Always eligible, no cooldown.
  2. new              - never contacted. Always eligible.
  3. follow_up_due    - contacted, no reply, cooldown has elapsed.
  4. re_engage        - ghosted, longer cooldown between re-attempts.
  (won / lost are excluded entirely - never re-messaged.)

IMPORTANT - these starting weights are a reasoned best guess, not a fitted
model. We only have 9 won / 14 lost leads to learn from - nowhere near
enough to trust a trained model (a common statistics rule of thumb wants
roughly 10+ outcome examples per input feature; with ~7 features here that's
70+ won examples, not 9). `python -m src.cli recalibrate` checks this
threshold honestly every time it's run, and only ever *recommends* new
weights for a human to review - it never silently rewrites this file.
"""

# Compatibility: Python 3.9 does not support `X | None` type-hint syntax
# at runtime (that needs 3.10+). This defers annotation evaluation so the
# same code runs on 3.9-3.12+ without changing any actual logic.
from __future__ import annotations
from datetime import date, datetime

WAITING_ON_US = {"replied", "warm", "negotiating", "call_booked"}
EXCLUDED = {"won", "lost"}

TIER_SCORE = {
    "waiting_on_us": 1000,
    "new": 500,
    "follow_up_due": 200,
    "re_engage": 50,
}

COOLDOWN_DAYS = {
    ("instagram_dm", "contacted"): 3,
    ("instagram_dm", "ghosted"): 7,
    ("direct", "contacted"): 4,
    ("direct", "ghosted"): 10,
}

# Normalization caps - chosen from the actual range seen in the data
# (est_monthly_spend_gbp tops out at £9,000; sales_velocity_30d at ~200;
# followers in the tens of thousands for the biggest reseller accounts).
MAX_SPEND_CAP = 9000.0
MAX_FOLLOWERS_CAP = 50000.0
MAX_VELOCITY_CAP = 200.0
MAX_LISTINGS_CAP = 500.0
MAX_TOUCHES_CAP = 5.0          # diminishing returns past ~5 touches
RECENCY_HORIZON_DAYS = 30.0    # a touch 30+ days ago counts as "not recent"

# Starting weights for the Fit and Engagement composites. Fit leans hardest
# on actual £ spend because it's the most direct value signal we have;
# sales velocity next because an account that's *actively selling* is a
# better signal of a real, ongoing business than raw follower count, which
# is easy to inflate and doesn't itself indicate willingness to sell to us.
FIT_WEIGHTS = {"spend": 0.50, "velocity": 0.25, "listings": 0.15, "followers": 0.10}
# Engagement leans hardest on having actually replied at all - a real reply
# is a much stronger signal than touch count or recency alone.
ENGAGEMENT_WEIGHTS = {"replied": 0.50, "touches": 0.30, "recency": 0.20}
# How much the tie-break composite (Fit+Engagement) can matter relative to
# tier. Fit matters slightly more than Engagement for *ranking within a
# tier* because tier itself already captures most of the engagement signal
# (whether they replied, are new, gone quiet, etc.) - this avoids double
# counting "replied" both in the tier gate and dominating the tie-break too.
FIT_VS_ENGAGEMENT = {"fit": 0.6, "engagement": 0.4}


def _days_since(last_touch_date: str | None, today: date) -> int | None:
    if not last_touch_date:
        return None
    d = datetime.strptime(last_touch_date, "%Y-%m-%d").date()
    return (today - d).days


def lead_tier(stage: str, channel: str, last_touch_date: str | None, today: date) -> str | None:
    """Returns the tier name, or None if the lead should not be actioned today."""
    if stage in EXCLUDED:
        return None
    if stage in WAITING_ON_US:
        return "waiting_on_us"
    if stage == "new":
        return "new"

    days = _days_since(last_touch_date, today)
    cooldown = COOLDOWN_DAYS.get((channel, stage), 3)
    if days is None or days >= cooldown:
        return "follow_up_due" if stage == "contacted" else "re_engage"
    return None  # still in cooldown


def _norm(value, cap):
    if value is None:
        return None
    return max(0.0, min(float(value), cap)) / cap


def fit_score(est_monthly_spend_gbp, sales_velocity_30d, active_listings, followers) -> float:
    """0-1. 'Does this account look like a real, sizable business worth
    pursuing' - the firmographic bucket of a standard B2B scoring model.
    Missing components (e.g. a store has no follower count) are simply
    excluded and the remaining weights re-normalized, rather than treated
    as a zero that unfairly drags the score down."""
    components = {
        "spend": _norm(est_monthly_spend_gbp, MAX_SPEND_CAP),
        "velocity": _norm(sales_velocity_30d, MAX_VELOCITY_CAP),
        "listings": _norm(active_listings, MAX_LISTINGS_CAP),
        "followers": _norm(followers, MAX_FOLLOWERS_CAP),
    }
    present = {k: v for k, v in components.items() if v is not None}
    if not present:
        return 0.0
    weight_sum = sum(FIT_WEIGHTS[k] for k in present)
    return sum(FIT_WEIGHTS[k] * v for k, v in present.items()) / weight_sum


def engagement_score(last_inbound_text, num_touches, last_touch_date, today: date) -> float:
    """0-1. 'Are they actually interacting with us' - the behavioral bucket.
    A real reply is the strongest single signal; touch count and recency
    are secondary."""
    replied = 1.0 if last_inbound_text else 0.0
    touches_norm = _norm(num_touches, MAX_TOUCHES_CAP) or 0.0
    days = _days_since(last_touch_date, today)
    recency_norm = max(0.0, 1.0 - (days / RECENCY_HORIZON_DAYS)) if days is not None else 0.0
    return (ENGAGEMENT_WEIGHTS["replied"] * replied
            + ENGAGEMENT_WEIGHTS["touches"] * touches_norm
            + ENGAGEMENT_WEIGHTS["recency"] * recency_norm)


def value_score(lead_row, today: date) -> float:
    """0-1 composite of Fit and Engagement - the tie-breaker *within* a tier."""
    fit = fit_score(lead_row["est_monthly_spend_gbp"], lead_row["sales_velocity_30d"],
                     lead_row["active_listings"], lead_row["followers"])
    eng = engagement_score(lead_row["last_inbound_text"], lead_row["num_touches"],
                            lead_row["last_touch_date"], today)
    return FIT_VS_ENGAGEMENT["fit"] * fit + FIT_VS_ENGAGEMENT["engagement"] * eng


def score_lead(lead_row, today: date):
    """lead_row: sqlite3.Row from `leads`. Returns (tier, score) or (None, None)."""
    tier = lead_tier(lead_row["stage"], lead_row["channel"], lead_row["last_touch_date"], today)
    if tier is None:
        return None, None
    v = value_score(lead_row, today)
    return tier, TIER_SCORE[tier] + v * 100

