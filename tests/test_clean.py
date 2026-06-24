import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import clean  # noqa: E402


def test_clean_stage_variants_collapse():
    assert clean.clean_stage("Reply") == "replied"
    assert clean.clean_stage("replied") == "replied"
    assert clean.clean_stage("Contacted ") is not None  # trailing space variant exists in real data
    assert clean.clean_stage("call-booked") == "call_booked"
    assert clean.clean_stage("Call Booked") == "call_booked"
    assert clean.clean_stage("Closed Won") == "won"
    assert clean.clean_stage(None) == "new"


def test_clean_date_formats():
    assert clean.clean_date("2026-02-19") == "2026-02-19"
    assert clean.clean_date("08/12/2025") == "2025-12-08"
    assert clean.clean_date("Dec 31") == "2025-12-31"
    assert clean.clean_date("Feb 13") == "2026-02-13"
    assert clean.clean_date(None) is None
    assert clean.clean_date("") is None


def test_clean_phone_variants_normalize_to_identical_e164():
    e164_a, malformed_a, guessed_a = clean.clean_phone("+44 7318 272813")
    e164_b, malformed_b, guessed_b = clean.clean_phone("07318272813")
    e164_c, malformed_c, guessed_c = clean.clean_phone("0044 7318 272813")
    assert e164_a == e164_b == e164_c == "+447318272813"
    assert not malformed_a and not malformed_b and not malformed_c
    assert not guessed_a  # explicit +44
    assert guessed_b      # bare digits, no country code - GB assumed
    assert not guessed_c  # explicit 0044


def test_clean_phone_distinguishes_different_countries_exactly():
    # The whole point of real E.164 parsing over a last-9-digits heuristic:
    # numbers from different countries must never collide just because
    # some digits happen to line up.
    uk, *_ = clean.clean_phone("+44 7318 272813")
    us, *_ = clean.clean_phone("+1 731 8272813")
    assert uk != us


def test_clean_phone_rejects_garbage():
    e164, malformed, _ = clean.clean_phone("not a phone number at all")
    assert e164 is None
    assert malformed is True


def test_clean_email_fixes_double_at():
    email, malformed = clean.clean_email("ines@@hotmail.com")
    assert email == "ines@hotmail.com"
    assert malformed is True


def test_clean_email_rejects_garbage():
    email, malformed = clean.clean_email("not-an-email")
    assert email is None
    assert malformed is True


def test_clean_spend_handles_currency_symbols_and_commas():
    assert clean.clean_spend("£9,000") == 9000.0
    assert clean.clean_spend(9000) == 9000.0
    assert clean.clean_spend("1,200") == 1200.0
    assert clean.clean_spend(None) is None


def test_clean_handle_normalizes_url_and_at_forms():
    assert clean.clean_handle("@thrift_co") == "thrift_co"
    assert clean.clean_handle("instagram.com/thrift_co") == "thrift_co"
    assert clean.clean_handle("https://instagram.com/thrift_co/") == "thrift_co"
