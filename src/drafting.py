"""
Turns a scored lead into "what to do next" + the actual text to send, so
whoever runs the queue can act immediately instead of re-deciding from
scratch for every row.

Stores get a fixed channel sequence (email -> call -> visit), driven off how
many times they've already been touched and whether they've engaged.
Resellers always go out as a DM, but the tone/content changes with tier
*and* with which of Fleek's own customer segments they're in (new_reseller /
full_time_reseller / business - see classify.py) - a beginner testing their
first bundle and a full-time reseller doing 200 sales/month don't want the
same pitch, and joinfleek.com itself markets to them differently.
"""

FIRST_NAME_FALLBACK_STORE = "there"

# Which real-world resource each store action type consumes. Email is the
# one that genuinely scales with automation (an API into Gmail/an email
# tool, AI-drafted, sent in bulk) - the real constraint there is sender
# deliverability, not headcount. Calls and visits are still fundamentally
# human time (or a deliberate, separate decision to use an AI voice agent,
# which Fleek would need to choose to do, not something to assume here).
# Lumping all three into one daily number either overstates what a human
# team can do on calls/visits or understates how far email could scale.
ACTION_CATEGORY = {
    "email_intro": "email",
    "email_followup": "email",
    "call": "call",
    "call_confirm": "call",
    "visit": "visit",
}

SEGMENT_HOOK = {
    "new_reseller": ("you're just getting going - we do small minimum order "
                      "quantities (10-20 pieces) so you can test what sells "
                      "without overcommitting"),
    "full_time_reseller": ("you're already moving real volume - we can get you "
                            "better pricing on bigger orders and help keep "
                            "stock consistent so growth doesn't stall on supply"),
    "business": ("we supply wholesale vintage stock planned around your "
                 "shop's calendar, so restocking doesn't depend on luck"),
}


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

    # direct (store) channel: email -> call -> visit, escalating by how many
    # times we've already tried. Previously this only escalated to "visit"
    # for the re_engage (ghosted) tier specifically - a store stuck in
    # follow_up_due could be called forever and never escalate, which
    # contradicts the brief's literal sequence ("email, then a call, then a
    # visit") for ANY unresponsive store, not just ones formally ghosted.
    if tier == "waiting_on_us":
        return "call_confirm" if stage == "call_booked" else "email_followup"
    if tier == "new":
        return "email_intro"
    # follow_up_due and re_engage are both "we've reached out, no reply yet"
    # - just different elapsed-time buckets - so they share one ladder.
    if touches >= 2:
        return "visit"
    if touches >= 1:
        return "call"
    return "email_followup"


def draft_message(lead, action_type: str) -> str:
    name = _greeting(lead)
    store = lead["store_name"] or "your shop"
    listings = int(lead["active_listings"]) if lead["active_listings"] else None
    velocity = int(lead["sales_velocity_30d"]) if lead["sales_velocity_30d"] else None
    last_text = lead["last_inbound_text"]
    city = lead["city"]

    if action_type == "dm_cold":
        hook = SEGMENT_HOOK.get(lead["segment"])
        if not hook:
            hook = (f"saw you've got {listings} live listings and moving ~{velocity}/month"
                    if listings and velocity else "saw your shop and love the edit")
        return (f"Hey! We supply vintage/secondhand stock in bulk (100+ pieces at a time) "
                f"so resellers don't have to source piece-by-piece - {hook}. Worth a quick chat?")

    if action_type == "dm_followup":
        if last_text:
            return (f"Thanks for the reply - re \"{last_text}\": happy to talk through that. "
                     f"What's a good time this week for a quick call?")
        return "Following up on this - still keen to chat? Happy to work around your schedule."

    if action_type == "dm_reengage":
        return ("Hey, know it's been quiet - happy to get you set up with a bulk batch "
                "whenever the timing's right. No pressure, just flag if restocking ever "
                "makes sense for you.")

    if action_type == "email_intro":
        hook = SEGMENT_HOOK.get(lead["segment"], "we supply wholesale vintage stock in bulk")
        return (f"Subject: Wholesale vintage supply for {store}\n\n"
                f"Hi {name},\n\n{hook[0].upper() + hook[1:]}. Would you be open to a "
                f"short call this week to see if it's a fit?\n\nBest,\nFleek")

    if action_type == "email_followup":
        ref = f' You mentioned: "{last_text}".' if last_text else ""
        return (f"Subject: Re: wholesale supply for {store}\n\n"
                f"Hi {name},\n\nFollowing up on our last chat.{ref} Keen to find a time this "
                f"week to move things forward - does a quick call work?\n\nBest,\nFleek")

    if action_type == "call":
        ref = f' Last note from them: "{last_text}".' if last_text else ""
        return (f"CALL SCRIPT - {store} ({city}): Confirm interest in stocking up via "
                f"Fleek, agree next step (sample bundle or visit).{ref}")

    if action_type == "call_confirm":
        return (f"CALL SCRIPT - {store} ({city}): Confirm the booked call time and agenda; "
                f"come ready to agree a first order.")

    if action_type == "visit":
        return (f"VISIT - {store} ({city}): In-person visit to show sample stock and agree "
                f"a first order. Pair with other {city} visits this week to make the trip worth it.")

    return "Review lead manually."
