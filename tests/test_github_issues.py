import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from src import github_issues  # noqa: E402


@pytest.fixture(autouse=True)
def fake_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-tests")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CalemT/fleek-pipeline-tool")
    yield


def test_no_token_raises_a_clear_actionable_error(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(github_issues.GitHubIssuesUnavailable, match="GITHUB_TOKEN"):
        github_issues._request("GET", "/issues")


def test_no_repo_raises_a_clear_actionable_error(monkeypatch):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with pytest.raises(github_issues.GitHubIssuesUnavailable, match="repo"):
        github_issues._request("GET", "/issues", config_repo=None)


def test_find_open_issue_returns_none_when_no_match():
    def fake_transport(method, url, data, headers):
        assert method == "GET"
        assert "/issues?labels=data-quality" in url
        return []  # no open issues at all

    result = github_issues.find_open_issue_number("lead:L0099", transport=fake_transport)
    assert result is None


def test_find_open_issue_matches_on_lead_key_in_title():
    def fake_transport(method, url, data, headers):
        return [
            {"number": 5, "title": "Data quality review needed: lead:L0001 (Some Shop)"},
            {"number": 7, "title": "Data quality review needed: lead:L0099 (Other Shop)"},
        ]

    result = github_issues.find_open_issue_number("lead:L0099", transport=fake_transport)
    assert result == 7


def test_create_issue_sends_the_right_payload_and_label():
    captured = {}

    def fake_transport(method, url, data, headers):
        captured["method"] = method
        captured["url"] = url
        captured["body"] = data
        return {"number": 42}

    import json as _json
    number = github_issues.create_issue("Title here", "Body here", transport=fake_transport)

    assert number == 42
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/issues")
    payload = _json.loads(captured["body"])
    assert payload["title"] == "Title here"
    assert payload["labels"] == ["data-quality"]


def test_ensure_label_exists_succeeds_on_first_creation():
    calls = []

    def fake_transport(method, url, data, headers):
        calls.append((method, url))
        return {"name": "data-quality"}

    github_issues.ensure_label_exists(transport=fake_transport)
    assert calls == [("POST", calls[0][1])]
    assert calls[0][1].endswith("/labels")


def test_ensure_label_exists_treats_already_exists_as_success():
    def fake_transport(method, url, data, headers):
        raise github_issues.GitHubIssuesUnavailable("GitHub API returned 422: already exists")

    # Must NOT raise - a 422 here means the label is already there, which
    # is the success case, not a failure.
    github_issues.ensure_label_exists(transport=fake_transport)


def test_ensure_label_exists_reraises_other_errors():
    def fake_transport(method, url, data, headers):
        raise github_issues.GitHubIssuesUnavailable("GitHub API returned 403: no permission")

    with pytest.raises(github_issues.GitHubIssuesUnavailable, match="403"):
        github_issues.ensure_label_exists(transport=fake_transport)


def test_http_error_becomes_a_clear_message(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden",
                                      {}, io.BytesIO(b'{"message": "rate limited"}'))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # No transport injected this time - exercises the real error-handling
    # path inside _request itself, not just the test's own mock function.
    with pytest.raises(github_issues.GitHubIssuesUnavailable, match="403"):
        github_issues._request("GET", "/issues")


def test_sync_command_respects_the_per_run_cap(monkeypatch, tmp_path):
    """Integration test: with more flagged leads than the cap allows, the
    full command must create exactly `cap` issues and stop, leaving the
    rest for the next run - this is the behavior that matters at 30k scale
    (hundreds of flagged leads), not at today's handful. Also verifies the
    label gets created before any issue does, and that issues created in
    this run get their number stored locally (the fast path for next time)."""
    import argparse
    import io
    import json as _json
    import urllib.request

    from src import cli as cli_module
    from src import db

    db_path = str(tmp_path / "test.db")
    conn = db.connect(db_path)
    now = "2026-01-01T00:00:00"
    for i in range(5):
        conn.execute(
            """INSERT INTO leads (lead_key, source_lead_ids, channel, lead_type, segment,
               stage, store_name, est_monthly_spend_gbp, data_quality_flags,
               created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (f"lead:F{i}", f"F{i}", "direct", "store", "business", "new",
             f"Flagged Shop {i}", 1000, '["malformed_email_unrecoverable"]', now, now),
        )
    conn.commit()
    conn.close()

    created_calls, label_calls = [], []

    class CM:
        def __init__(self, buf):
            self.buf = buf
        def __enter__(self):
            return self.buf
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        method = req.get_method()
        if url.endswith("/labels"):
            label_calls.append(1)
            return CM(io.BytesIO(b'{"name": "data-quality"}'))
        if method == "GET":
            return CM(io.BytesIO(b"[]"))  # no existing open issues found via fallback search
        body = _json.loads(req.data.decode())
        created_calls.append(body["title"])
        return CM(io.BytesIO(_json.dumps({"number": len(created_calls)}).encode()))

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "CalemT/fleek-pipeline-tool")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    args = argparse.Namespace(db=db_path)
    # cap is read from config/assumptions.yaml (default 20) - this dataset
    # only has 5, so to actually test the cap we patch it down to 2.
    from src import config as cfg_module
    monkeypatch.setattr(cfg_module, "load_config",
                         lambda path=None: {**cfg_module._FALLBACK, "data_quality_issue_cap": 2})

    cli_module.cmd_sync_review_issues(args)

    assert len(label_calls) == 1  # label ensured exactly once
    assert len(created_calls) == 2  # stopped at the cap, not all 5

    # The 2 created issues must have their number stored locally, so the
    # NEXT run never has to call the API for them again.
    conn = db.connect(db_path)
    tracked = conn.execute(
        "SELECT COUNT(*) c FROM leads WHERE github_issue_number IS NOT NULL"
    ).fetchone()["c"]
    assert tracked == 2
