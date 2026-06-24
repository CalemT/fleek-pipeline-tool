import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import classify  # noqa: E402


def test_store_name_means_business_segment_regardless_of_other_fields():
    lead_type = classify.classify_lead_type("Past Cellar", None, None, None, None)
    assert lead_type == "store"
    assert classify.classify_segment(lead_type, None, None) == "business"


def test_low_volume_reseller_is_new_reseller():
    lead_type = classify.classify_lead_type(None, "@smallshop", 500, 10, 5)
    assert lead_type == "reseller"
    assert classify.classify_segment(lead_type, 10, 5) == "new_reseller"


def test_high_volume_reseller_is_full_time():
    lead_type = classify.classify_lead_type(None, "@bigshop", 50000, 300, 150)
    assert lead_type == "reseller"
    assert classify.classify_segment(lead_type, 300, 150) == "full_time_reseller"


def test_hybrid_row_with_both_store_name_and_handle_is_still_a_store():
    # e.g. day-2 lead L0284: has both store_name AND a handle - store_name wins
    lead_type = classify.classify_lead_type("Maison Lab", "@heritageprelovedstudio", None, None, None)
    assert lead_type == "store"
