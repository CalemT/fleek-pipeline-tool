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


def test_clean_phone_variants_share_a_dedup_key():
    _, key_a = clean.clean_phone("+44 7318 272813")
    _, key_b = clean.clean_phone("07318272813")
    _, key_c = clean.clean_phone("0044 7318 272813")
    assert key_a == key_b == key_c


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
