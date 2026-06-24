"""
Normalization for the messy raw fields. Each function takes a raw value and
returns a clean one (or None), and is intentionally pure/stateless so it's
trivial to unit test and to run over 30k rows with a vectorized pandas .apply
instead of a python for-loop.
"""
import re
import json
from datetime import datetime
import pandas as pd
import phonenumbers

# ---- stage canonicalization -------------------------------------------------

_STAGE_MAP = {
    "new": "new", "new lead": "new",
    "contacted": "contacted",
    "reply": "replied", "replied": "replied",
    "warm": "warm",
    "negotiating": "negotiating", "in negotiation": "negotiating",
    "call booked": "call_booked", "call-booked": "call_booked",
    "ghosted": "ghosted", "no response": "ghosted",
    "lost": "lost",
    "won": "won", "closed won": "won",
}

# Funnel order used for picking the "most advanced" stage when merging
# duplicate rows of the same real-world lead.
STAGE_RANK = {
    "lost": 0, "ghosted": 1, "new": 2, "contacted": 3,
    "replied": 4, "warm": 5, "negotiating": 6, "call_booked": 7, "won": 8,
}

ACTIVE_STAGES = {"new", "contacted", "replied", "warm", "negotiating", "call_booked", "ghosted"}
CLOSED_STAGES = {"won", "lost"}


def clean_stage(raw):
    if pd.isna(raw):
        return "new"
    key = str(raw).strip().lower()
    return _STAGE_MAP.get(key, "new")


# ---- dates -------------------------------------------------------------------

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def clean_date(raw, default_year=2026):
    """Parse the handful of date shapes seen in the sheet into ISO yyyy-mm-dd.
    Handles: '2026-02-19' (ISO), '08/12/2025' (DD/MM/YYYY), 'Dec 31' / 'Feb 13'
    (month-day, year missing -> inferred from context window Dec 2025-Feb 2026:
    Dec maps to 2025, Jan/Feb map to 2026), and real datetime/Timestamp objects
    from Excel.
    """
    if pd.isna(raw) or raw == "":
        return None
    if isinstance(raw, (datetime, pd.Timestamp)):
        return raw.strftime("%Y-%m-%d")

    s = str(raw).strip()

    # ISO yyyy-mm-dd
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s

    # DD/MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(y, mo, d).strftime("%Y-%m-%d")
        except ValueError:
            return None

    # 'Mon D' e.g. 'Dec 31', 'Feb 13'
    m = re.match(r"^([A-Za-z]{3})\s+(\d{1,2})$", s)
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        day = int(m.group(2))
        if mon:
            year = 2025 if mon == 12 else 2026
            try:
                return datetime(year, mon, day).strftime("%Y-%m-%d")
            except ValueError:
                return None

    return None


# ---- phone / email -----------------------------------------------------------

def clean_phone(raw):
    """Normalize to a real, canonical E.164 number using Google's actual
    libphonenumber (via the `phonenumbers` package) - not a digits-stripping
    heuristic. This matters for de-dup correctness: a previous version
    matched phones on their last 9 digits to tolerate +44/0044/0-prefix
    formatting differences, which works for the SAME UK number written
    three ways, but could in principle collide two DIFFERENT real numbers
    from different countries that happen to share their last 9 digits
    (e.g. a UK and a US number). Real E.164 parsing normalizes formatting
    variance to an identical string for the same number, while keeping
    genuinely different numbers (different country) distinct - so the
    de-dup key can be an exact string match instead of a fuzzy one.

    Returns (e164_or_None, malformed_bool, was_region_guessed_bool).
    `was_region_guessed` is True when the raw string had no explicit
    country code (no leading '+' or '00') and we assumed GB, since that's
    the only real residual ambiguity: a future batch with a bare-digit
    non-UK number would be misparsed. Every non-UK number actually seen in
    this dataset carries an explicit '+CC', so this is a forward-looking
    safeguard, not a known live bug - but it's why the caller still flags
    these matches as lower-confidence than an explicit-country-code match.
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return None, False, False
    s = str(raw).strip()
    region_guessed = not (s.startswith("+") or re.match(r"^00\d", s))
    # phonenumbers needs an explicit '+' for international format - it
    # doesn't infer that a leading '00' is the international dialing
    # prefix without already knowing the calling region, so normalize it
    # here rather than let a perfectly fine '0044...' number fail to parse.
    if re.match(r"^00\d", s):
        s = "+" + s[2:]
    try:
        parsed = phonenumbers.parse(s, "GB" if region_guessed else None)
        # is_valid_number() checks against real-world *assigned* number
        # ranges, which is the wrong tool here - it would reject perfectly
        # well-formed numbers that simply aren't in current real-world use
        # (including this case study's own data, parts of which appear to
        # be synthetic/generated). is_possible_number() checks structural
        # plausibility (length, format) without that real-world database
        # lookup, which is the right bar for cleaning CRM-style data.
        if not phonenumbers.is_possible_number(parsed):
            return None, True, region_guessed
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return e164, False, region_guessed
    except phonenumbers.NumberParseException:
        return None, True, region_guessed


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_email(raw):
    """Returns (clean_email_or_None, is_malformed_bool)."""
    if pd.isna(raw) or str(raw).strip() == "":
        return None, False
    s = str(raw).strip().lower()
    s_fixed = re.sub(r"@+", "@", s)  # collapse 'name@@hotmail.com' -> 'name@hotmail.com'
    if _EMAIL_RE.match(s_fixed):
        return s_fixed, (s_fixed != s)
    return None, True


def clean_handle(raw):
    if pd.isna(raw) or str(raw).strip() == "":
        return None
    h = str(raw).strip().lower()
    h = re.sub(r"^https?://", "", h)
    h = h.replace("instagram.com/", "")
    h = h.lstrip("@").rstrip("/")
    return h or None


def clean_spend(raw):
    if pd.isna(raw):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = re.sub(r"[^\d.]", "", str(raw))
    return float(s) if s else None


def clean_numeric(raw):
    if pd.isna(raw):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        s = re.sub(r"[^\d.]", "", str(raw))
        return float(s) if s else None


def flags_to_json(flags):
    return json.dumps(sorted(flags)) if flags else "[]"
