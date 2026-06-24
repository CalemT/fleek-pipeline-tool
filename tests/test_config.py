import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402


def test_loads_real_config_file_with_placeholders_as_none():
    cfg = config.load_config()
    assert cfg["daily_caps"]["instagram_dm"] == 40
    assert cfg["channel_performance"]["email"]["conversion_rate"] is None


def test_missing_file_falls_back_to_safe_defaults(tmp_path):
    cfg = config.load_config(tmp_path / "does_not_exist.yaml")
    assert cfg["daily_caps"]["call"] == 30
    assert cfg["recalibration"]["epv_target"] == 10


def test_partial_file_merges_over_fallback_without_crashing(tmp_path):
    p = tmp_path / "partial.yaml"
    p.write_text("daily_caps:\n  visit: 8\n")
    cfg = config.load_config(p)
    assert cfg["daily_caps"]["visit"] == 8        # overridden
    assert cfg["daily_caps"]["email"] == 150       # fallback still present
    assert cfg["channel_performance"]["call"]["conversion_rate"] is None
