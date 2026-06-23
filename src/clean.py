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
    """Normalize to a comparable digits-only form with a best-guess leading
    country code, used both for display and for de-dup matching.
    Returns (normalized_display, digits_key) or (None, None).
    """
    if pd.isna(raw) or str(raw).strip() == "":
        return None, None
    s = str(raw).strip()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None, None

    if s.startswith("+"):
        e164 = "+" + digits
    elif digits.startswith("00"):
        e164 = "+" + digits[2:]
    elif digits.startswith("0"):
        # UK-style local format e.g. 07318 272813 -> assume UK +44
        e164 = "+44" + digits[1:]
    else:
        # bare digits, e.g. '7366811166' -> assume UK mobile missing leading 0
        e164 = "+44" + digits if len(digits) == 10 else "+" + digits

    # dedup key: last 9 significant digits, strips country-code/leading-zero ambiguity
    key = digits[-9:] if len(digits) >= 9 else digits
    return e164, key


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
