"""
Turns a scored lead into "what to do next" + the actual text to send, so
whoever runs the queue can act immediately instead of re-deciding from
scratch for every row.

Stores get a fixed channel sequence (email -> call -> visit), driven off how
many times they've already been touched and whether they've engaged.
Resellers always go out as a DM, but the tone/content changes with tier.
"""

FIRST_NAME_FALLBACK_STORE = "there"


def _greeting(lead) -> str:
    name = lead["contact_name"]
    if name:
        return name.split(" ")[0]
    return FIRST_NAME_FALLBACK_STORE


def next_action_type(lead, tier: str) -> str:
    channel = lead["channel"]
    touches = lead["num_touches"] or 0
    stage = lead["stage"]

    if channel == "instagram_dm":
        return {
            "waiting_on_us": "dm_followup",
            "new": "dm_cold",
            "follow_up_due": "dm_followup",
            "re_engage": "dm_reengage",
        }[tier]

    # direct (store) channel: email -> call -> visit
    if tier == "waiting_on_us":
        return "call_confirm" if stage == "call_booked" else "email_followup"
    if tier == "new":
        return "email_intro"
    if tier == "follow_up_due":
        return "call" if touches >= 1 else "email_followup"
    return "visit" if touches >= 2 else "call"  # re_engage


def draft_message(lead, action_type: str) -> str:
    name = _greeting(lead)
    store = lead["store_name"] or "your shop"
    listings = int(lead["active_listings"]) if lead["active_listings"] else None
    velocity = int(lead["sales_velocity_30d"]) if lead["sales_velocity_30d"] else None
    last_text = lead["last_inbound_text"]
    city = lead["city"]

    if action_type == "dm_cold":
        hook = (f"saw you've got {listings} live listings and moving ~{velocity}/month"
                if listings and velocity else "saw your shop and love the edit")
        return (f"Hey! {hook} - we buy vintage/secondhand in bulk (100+ pieces at a time) "
                f"for resellers like you on a B2B marketplace. Worth a quick chat about "
                f"selling us a batch?")

    if action_type == "dm_followup":
        if last_text:
            return (f"Thanks for the reply - re \"{last_text}\": happy to talk through that. "
                     f"What's a good time this week for a quick call?")
        return "Following up on this - still keen to chat? Happy to work around your schedule."

    if action_type == "dm_reengage":
        return ("Hey, know it's been quiet - we're still keen to buy from you if the timing's "
                "better now. No pressure, just flag if a bulk sale ever makes sense for you.")

    if action_type == "email_intro":
        return (f"Subject: Buying bulk from {store}\n\n"
                f"Hi {name},\n\nWe buy secondhand/vintage stock in bulk (100+ pieces at a time) "
                f"from shops like yours. Would you be open to a short call this week to see if "
                f"it's a fit?\n\nBest,\nFleek")

    if action_type == "email_followup":
        ref = f' You mentioned: "{last_text}".' if last_text else ""
        return (f"Subject: Re: buying from {store}\n\n"
                f"Hi {name},\n\nFollowing up on our last chat.{ref} Keen to find a time this "
                f"week to move things forward - does a quick call work?\n\nBest,\nFleek")

    if action_type == "call":
        ref = f' Last note from them: "{last_text}".' if last_text else ""
        return (f"CALL SCRIPT - {store} ({city}): Confirm interest in selling bulk stock to "
                f"Fleek, agree next step (visit or sample pickup).{ref}")

    if action_type == "call_confirm":
        return (f"CALL SCRIPT - {store} ({city}): Confirm the booked call time and agenda; "
                f"come ready to agree a first batch.")

    if action_type == "visit":
        return (f"VISIT - {store} ({city}): In-person visit to view stock and agree a first "
                f"purchase. Pair with other {city} visits this week to make the trip worth it.")

    return "Review lead manually."
