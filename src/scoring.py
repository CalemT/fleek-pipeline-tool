"""
Who gets messaged today, and why.

The brief's framing of the hard problem is: "with only ~40 DMs a day, who do
you message, where is each person up to, and what do you say next" - and
flags that a lot of leads are sitting half-replied with nobody following up.
That's the design driver here: a lead where the ball is in OUR court (they
replied, they're warm, they're negotiating, a call is booked) outranks a
brand new cold lead, which in turn outranks chasing someone who's gone quiet.
Within a tier, leads are ranked by estimated commercial value so the most
valuable accounts get worked first.

Tiers (highest score first):
  1. waiting_on_us   - replied / warm / negotiating / call_booked. Lead is
                        engaged and waiting on us. Always eligible, no cooldown.
  2. new              - never contacted. Always eligible.
  3. follow_up_due    - contacted, no reply, cooldown has elapsed.
  4. re_engage        - ghosted, longer cooldown between re-attempts.
  (won / lost are excluded entirely - never re-messaged.)

Cooldown exists so the tool doesn't nag the same silent lead every single
day - it waits a sensible number of days before trying again.
"""
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

MAX_SPEND_CAP = 9000.0  # data caps out at £9,000/mo; used to normalize 0-1


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


def value_score(est_monthly_spend_gbp, followers, sales_velocity_30d) -> float:
    """0-1 commercial value estimate. Prefers actual spend; falls back to a
    reach*velocity proxy for the rare row missing spend."""
    if est_monthly_spend_gbp is not None:
        return min(est_monthly_spend_gbp, MAX_SPEND_CAP) / MAX_SPEND_CAP
    f = followers or 0
    v = sales_velocity_30d or 0
    proxy = min(f, 50000) / 50000 * 0.5 + min(v, 200) / 200 * 0.5
    return proxy


def score_lead(lead_row, today: date):
    """lead_row: sqlite3.Row from `leads`. Returns (tier, score) or (None, None)."""
    tier = lead_tier(lead_row["stage"], lead_row["channel"], lead_row["last_touch_date"], today)
    if tier is None:
        return None, None
    v = value_score(lead_row["est_monthly_spend_gbp"], lead_row["followers"], lead_row["sales_velocity_30d"])
    return tier, TIER_SCORE[tier] + v * 100
