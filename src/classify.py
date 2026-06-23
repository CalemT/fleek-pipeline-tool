"""
Tell the two kinds of lead apart from the data they actually have.

The brief is explicit: some Instagram-sourced leads have an email attached,
and the tool should notice. So channel is derived from contactability, not
from the `source` column:

  - 'direct'        -> has a real email and/or phone. We can email/call/visit.
                        (this is most physical stores, plus the ~12% of
                        "reseller" sourced rows that turn out to have an email)
  - 'instagram_dm'   -> no email/phone, only a handle. The only way in is a DM,
                        which is rate-limited to ~40/day.

`followers == 0` on store-labelled rows is a placeholder, not a signal — we
ignore reseller metrics entirely when deciding channel.
"""


def classify_channel(email: str | None, phone: str | None, handle: str | None) -> str:
    if email or phone:
        return "direct"
    if handle:
        return "instagram_dm"
    return "direct"  # no usable identifier at all; falls back to whatever contact we can dig up manually
