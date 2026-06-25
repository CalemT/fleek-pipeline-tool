"""
Talks to the GitHub Issues API so data-quality problems become real,
clickable, closeable items in the repo's Issues tab - not a CSV export
that sits in a folder nobody opens. This is the GitHub-native answer to
"every part of this process should be runnable and visible from GitHub
itself."

Uses only Python's standard library (urllib) deliberately - no new
dependency to install, no version-mismatch risk, works anywhere Python
itself works.

Authentication: inside GitHub Actions, the workflow's own GITHUB_TOKEN
already has permission to create issues once the workflow declares
`permissions: issues: write` (see .github/workflows/daily_plan.yml) - no
extra secret to set up. Running this locally requires exporting a
personal access token with the 'issues' scope as GITHUB_TOKEN first; if
it's not set, this module fails clearly and visibly rather than silently
doing nothing or crashing with a raw network error.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_BASE = "https://api.github.com"
LABEL = "data-quality"


class GitHubIssuesUnavailable(Exception):
    """Raised with a clear, actionable message - never a raw network traceback."""


def _repo_slug(config_repo=None):
    return os.environ.get("GITHUB_REPOSITORY") or config_repo


def _token():
    return os.environ.get("GITHUB_TOKEN")


def _request(method, path, payload=None, config_repo=None, transport=None):
    """transport is injectable for testing - defaults to a real HTTP call."""
    token = _token()
    if not token:
        raise GitHubIssuesUnavailable(
            "No GITHUB_TOKEN set. Inside GitHub Actions this is automatic "
            "(see the workflow's 'env:' block); running locally, export a "
            "personal access token with the 'issues' scope first: "
            "export GITHUB_TOKEN=<your token>"
        )
    repo = _repo_slug(config_repo)
    if not repo:
        raise GitHubIssuesUnavailable(
            "No repo to talk to. Set 'github_repo' in config/assumptions.yaml "
            "(format: owner/repo-name) for local runs - GitHub Actions sets "
            "this automatically via GITHUB_REPOSITORY."
        )

    url = f"{API_BASE}/repos/{repo}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fleek-pipeline-tool",
    }

    if transport:
        return transport(method, url, data, headers)

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        raise GitHubIssuesUnavailable(f"GitHub API returned {e.code}: {body}")
    except urllib.error.URLError as e:
        raise GitHubIssuesUnavailable(f"Could not reach GitHub API: {e}")


def find_open_issue_number(lead_key: str, config_repo=None, transport=None) -> int | None:
    """Searches open, labeled issues for one already tracking this lead, so
    re-running this every day doesn't create duplicate issues for the same
    unresolved problem."""
    results = _request("GET", f"/issues?labels={LABEL}&state=open&per_page=100",
                        config_repo=config_repo, transport=transport)
    for issue in results or []:
        if lead_key in (issue.get("title") or ""):
            return issue["number"]
    return None


def ensure_label_exists(config_repo=None, transport=None) -> None:
    """GitHub does NOT auto-create a label just because an issue references
    it - confirmed against GitHub's own docs ('The label(s) must exist for
    your repository') and multiple real bug reports of 'Label does not
    exist' errors when this assumption is made. A brand-new repo only has
    GitHub's defaults (bug, enhancement, etc.) - 'data-quality' has to be
    created explicitly first, once, before it can ever be attached to an
    issue. A 422 here means it already exists, which is success, not an
    error."""
    payload = {"name": LABEL, "color": "A8502E",
               "description": "Flagged by the pipeline tool for manual review"}
    try:
        _request("POST", "/labels", payload, config_repo=config_repo, transport=transport)
    except GitHubIssuesUnavailable as e:
        if "422" not in str(e):
            raise


def create_issue(title: str, body: str, config_repo=None, transport=None) -> int:
    result = _request("POST", "/issues", {"title": title, "body": body, "labels": [LABEL]},
                       config_repo=config_repo, transport=transport)
    return result["number"]
