"""
Loads config/assumptions.yaml - the one file Fleek would actually edit with
real numbers, instead of every placeholder being buried in code. CLI flags
still override these per-run; this just sets the defaults.

If the file is missing or a value isn't set, falls back to the same
reasoned placeholders that were previously hardcoded directly in cli.py -
so the tool still works out of the box, it just becomes easy to override in
one place instead of several.
"""
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "assumptions.yaml"

_FALLBACK = {
    "daily_caps": {"instagram_dm": 40, "email": 150, "call": 30, "visit": 5},
    "min_visit_cluster": 3,
    "channel_performance": {
        "instagram_dm": {"reply_rate": None, "conversion_rate": None},
        "email": {"reply_rate": None, "conversion_rate": None},
        "call": {"connect_rate": None, "conversion_rate": None},
        "visit": {"conversion_rate": None},
    },
    "recalibration": {"epv_target": 10},
}


def load_config(path=None) -> dict:
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return _FALLBACK
    try:
        with open(path) as f:
            loaded = yaml.safe_load(f) or {}
    except Exception:
        return _FALLBACK

    # Shallow-merge over the fallback so a partially-filled-in file (missing
    # a section entirely) doesn't crash the tool.
    merged = {**_FALLBACK, **loaded}
    for key in ("daily_caps", "recalibration"):
        merged[key] = {**_FALLBACK[key], **(loaded.get(key) or {})}
    merged["channel_performance"] = {
        ch: {**_FALLBACK["channel_performance"][ch], **((loaded.get("channel_performance") or {}).get(ch) or {})}
        for ch in _FALLBACK["channel_performance"]
    }
    return merged
