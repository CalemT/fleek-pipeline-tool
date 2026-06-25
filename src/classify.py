"""
Tell the two kinds of lead apart from the data they actually have, and
(separately) work out which of Fleek's own customer segments they're in.

`channel` answers "how do we contact this lead" (email/phone vs DM only).
`lead_type` and `segment` answer a different question: "which of Fleek's
own customer tiers does this lead fit" - because joinfleek.com explicitly
markets to three different segments with three different pitches:
  - New Reseller: small minimum order quantities (10-20 pieces), low risk,
    "test what sells" - beginner-friendly.
  - Full-Time Reseller: bigger orders for better pricing, high-demand
    categories, building supplier relationships to scale.
  - Business (shops / multi-channel retailers): consistent wholesale supply
    planned around a store's seasonal calendar.
A lead's `source`/`store_name`/`handle` tells us which of these they
actually are, and the right outreach message is a different pitch for each
- not the same generic DM to a hobbyist and a full-time reseller doing 200
sales/month.

The reseller vs full-time-reseller cutoff below is a starting judgment
call, the same way the scoring weights are - there's no Fleek-internal
threshold to go on, just a reasonable read of "test what sells" (new,
low-volume) vs "scale my existing business" (already moving real volume).
Worth recalibrating against real data the same way scoring is, once segment
correlates with anything measurable.
"""

# Compatibility: Python 3.9 does not support `X | None` type-hint syntax
# at runtime (that needs 3.10+). This defers annotation evaluation so the
# same code runs on 3.9-3.12+ without changing any actual logic.
from __future__ import annotations

NEW_RESELLER_LISTINGS_CAP = 50
NEW_RESELLER_VELOCITY_CAP = 20


def classify_channel(email: str | None, phone: str | None, handle: str | None) -> str:
    if email or phone:
        return "direct"
    if handle:
        return "instagram_dm"
    return "direct"  # no usable identifier at all; falls back to whatever contact we can dig up manually


def classify_lead_type(store_name, handle, followers, active_listings, sales_velocity_30d) -> str:
    """'store' or 'reseller' - independent of `channel`. A reseller can still
    be 'direct'-contactable (they happen to have an email on file) while
    remaining a reseller for the purposes of which pitch to use."""
    if store_name:
        return "store"
    if handle or followers or active_listings or sales_velocity_30d:
        return "reseller"
    return "store"


def classify_segment(lead_type, active_listings, sales_velocity_30d) -> str:
    """Maps onto Fleek's own marketed customer tiers - 'new_reseller',
    'full_time_reseller', or 'business'."""
    if lead_type == "store":
        return "business"
    listings = active_listings or 0
    velocity = sales_velocity_30d or 0
    if listings < NEW_RESELLER_LISTINGS_CAP and velocity < NEW_RESELLER_VELOCITY_CAP:
        return "new_reseller"
    return "full_time_reseller"

