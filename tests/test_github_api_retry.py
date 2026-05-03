from __future__ import annotations

from unittest.mock import Mock

from scripts.utils.github_api import (
    fetch_closed_issues_page,
    fetch_default_branch_commit_history,
    fetch_repository_languages,
    _request_json_with_retry,
    _retry_after_seconds,
)


class FakeResponse:
    def __init__(self, status_code: int, *, headers: dict[str, str] | None = None, text: str = "", payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.reason = "OK"
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no payload")
        return self._payload


def test_retry_after_seconds_parses_header() -> None:
    headers = {"Retry-After": "7"}

    assert _retry_after_seconds(headers) == 7.0


def test_request_json_with_retry_retries_on_rate_limit(monkeypatch) -> None:
    responses = [
        FakeResponse(429, headers={"Retry-After": "0"}, text="rate limited"),
        FakeResponse(200, payload={"ok": True}),
    ]
    session = Mock()
    session.request.side_effect = responses
    sleeps: list[float] = []
    monkeypatch.setattr("scripts.utils.github_api.time.sleep", lambda seconds: sleeps.append(seconds))

    payload = _request_json_with_retry(session, method="GET", url="https://api.github.com/test")

    assert payload == {"ok": True}
    assert len(sleeps) == 1
    assert sleeps[0] == 0.0
    assert session.request.call_count == 2


def test_fetch_repository_languages_uses_rest_languages_endpoint(monkeypatch) -> None:
    calls = []

    def fake_fetch_json(session, *, url, params=None):
        calls.append((session, url, params))
        return {"TypeScript": 100}

    session = Mock()
    monkeypatch.setattr("scripts.utils.github_api.fetch_github_json", fake_fetch_json)

    payload = fetch_repository_languages(session, repository_full_name="owner/repo")

    assert payload == {"TypeScript": 100}
    assert calls == [(session, "https://api.github.com/repos/owner/repo/languages", None)]


def test_fetch_default_branch_commit_history_uses_lightweight_graphql_query(monkeypatch) -> None:
    calls = []

    def fake_post_graphql(session, *, query, variables):
        calls.append((session, query, variables))
        return {"data": {"repository": {"defaultBranchRef": {"target": {"history": {"totalCount": 12}}}}}}

    session = Mock()
    monkeypatch.setattr("scripts.utils.github_api.post_github_graphql", fake_post_graphql)

    payload = fetch_default_branch_commit_history(
        session,
        repository_full_name="owner/repo",
        since="2024-01-01T00:00:00Z",
        until="2025-12-31T23:59:59Z",
    )

    assert payload["data"]["repository"]["defaultBranchRef"]["target"]["history"]["totalCount"] == 12
    assert calls[0][2] == {
        "owner": "owner",
        "name": "repo",
        "since": "2024-01-01T00:00:00Z",
        "until": "2025-12-31T23:59:59Z",
    }
    assert "history" in calls[0][1]


def test_fetch_closed_issues_page_uses_count_level_graphql_query(monkeypatch) -> None:
    calls = []

    def fake_post_graphql(session, *, query, variables):
        calls.append((session, query, variables))
        return {
            "data": {
                "repository": {
                    "issues": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": [{"closedAt": "2024-02-01T00:00:00Z"}],
                    }
                }
            }
        }

    session = Mock()
    monkeypatch.setattr("scripts.utils.github_api.post_github_graphql", fake_post_graphql)

    payload = fetch_closed_issues_page(
        session,
        repository_full_name="owner/repo",
        after="cursor-1",
        since="2024-01-01T00:00:00Z",
    )

    assert payload["issues_connection"]["nodes"] == [{"closedAt": "2024-02-01T00:00:00Z"}]
    assert calls[0][2] == {
        "owner": "owner",
        "name": "repo",
        "after": "cursor-1",
        "since": "2024-01-01T00:00:00Z",
    }
    assert "body" not in calls[0][1]
    assert "closedAt" in calls[0][1]
