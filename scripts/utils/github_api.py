from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_BRANCH_COMMIT_COUNT_QUERY = """
query($owner: String!, $name: String!, $since: GitTimestamp!, $until: GitTimestamp!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      name
      target {
        ... on Commit {
          history(since: $since, until: $until) {
            totalCount
          }
        }
      }
    }
  }
}
"""
CLOSED_ISSUE_COUNT_PAGE_QUERY = """
query($owner: String!, $name: String!, $after: String, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    issues(
      first: 100
      after: $after
      orderBy: {field: UPDATED_AT, direction: DESC}
      filterBy: {states: CLOSED, since: $since}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        closedAt
      }
    }
  }
}
"""


class GitHubAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        attempts: int | None = None,
        retryable: bool | None = None,
        error_type: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts
        self.retryable = retryable
        self.error_type = error_type
        self.retry_after_seconds = retry_after_seconds


def create_github_session(token: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "research-study-github-client",
        }
    )

    github_token = token or os.getenv("GITHUB_TOKEN")
    if github_token:
        session.headers["Authorization"] = f"Bearer {github_token}"

    return session


def _retry_after_seconds(headers: Any) -> float | None:
    retry_after = headers.get("Retry-After")
    if not retry_after:
        return None

    retry_after = retry_after.strip()
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        try:
            retry_after_at = parsedate_to_datetime(retry_after)
        except (TypeError, ValueError):
            return None

        if retry_after_at.tzinfo is None:
            retry_after_at = retry_after_at.replace(tzinfo=timezone.utc)
        seconds = (retry_after_at - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, seconds)


def _is_retryable_response(response: requests.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code >= 500:
        return True
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        body = (response.text or "").lower()
        if remaining == "0":
            return True
        if "rate limit" in body or "secondary rate limit" in body:
            return True
        if response.headers.get("Retry-After"):
            return True
    return False


def _request_json_with_retry(
    session: requests.Session,
    *,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> Any:
    attempt = 0
    while True:
        attempt += 1
        try:
            response = session.request(method, url, params=params, json=json_body, timeout=30)
        except requests.exceptions.RequestException as exc:
            if attempt > max_retries:
                raise GitHubAPIError(
                    f"GitHub API request failed after {attempt} attempts for {url}: {exc}",
                    attempts=attempt,
                    retryable=True,
                    error_type=exc.__class__.__name__,
                ) from exc

            sleep_seconds = base_backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning(
                "Transient network error for %s (attempt %s/%s); retrying in %.1fs: %s",
                url,
                attempt,
                max_retries + 1,
                sleep_seconds,
                exc,
            )
            time.sleep(sleep_seconds)
            continue

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise GitHubAPIError(
                    f"GitHub API returned invalid JSON for {url}",
                    status_code=response.status_code,
                    attempts=attempt,
                    retryable=False,
                    error_type=exc.__class__.__name__,
                ) from exc
            return payload

        retry_after_seconds = _retry_after_seconds(response.headers)
        if _is_retryable_response(response):
            if attempt > max_retries:
                message = response.text.strip() or response.reason
                raise GitHubAPIError(
                    f"GitHub API request failed after {attempt} attempts for {url}: "
                    f"status {response.status_code}: {message}",
                    status_code=response.status_code,
                    attempts=attempt,
                    retryable=True,
                    error_type="HTTPStatusError",
                    retry_after_seconds=retry_after_seconds,
                )

            sleep_seconds = retry_after_seconds if retry_after_seconds is not None else base_backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning(
                "Transient GitHub response %s for %s (attempt %s/%s); retrying in %.1fs",
                response.status_code,
                url,
                attempt,
                max_retries + 1,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            continue

        message = response.text.strip() or response.reason
        raise GitHubAPIError(
            f"GitHub API request failed with status {response.status_code} for {url}: {message}",
            status_code=response.status_code,
            attempts=attempt,
            retryable=False,
            error_type="HTTPStatusError",
            retry_after_seconds=retry_after_seconds,
        )


def fetch_github_json(
    session: requests.Session,
    *,
    url: str,
    params: dict[str, Any] | None = None,
) -> Any:
    return _request_json_with_retry(session, method="GET", url=url, params=params)


def post_github_json(
    session: requests.Session,
    *,
    url: str,
    json_body: dict[str, Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> Any:
    return _request_json_with_retry(
        session,
        method="POST",
        url=url,
        json_body=json_body,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
    )


def _graphql_error_messages(errors: Any) -> list[str]:
    messages: list[str] = []
    if not isinstance(errors, list):
        return messages
    for error in errors:
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                messages.append(str(message))
    return messages


def _graphql_errors_retryable(errors: Any) -> bool:
    if not isinstance(errors, list):
        return False

    for error in errors:
        if not isinstance(error, dict):
            continue
        extensions = error.get("extensions") or {}
        code = str(extensions.get("code") or "").upper()
        message = str(error.get("message") or "").lower()
        if code in {"RATE_LIMITED", "ABUSE_DETECTED", "SECONDARY_RATE_LIMIT"}:
            return True
        if "rate limit" in message or "secondary rate limit" in message or "temporarily unavailable" in message:
            return True
    return False


def post_github_graphql(
    session: requests.Session,
    *,
    query: str,
    variables: dict[str, Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict[str, Any]:
    attempt = 0
    while True:
        attempt += 1
        try:
            payload = post_github_json(
                session,
                url="https://api.github.com/graphql",
                json_body={"query": query, "variables": variables},
                max_retries=0,
                base_backoff_seconds=base_backoff_seconds,
            )
        except GitHubAPIError as exc:
            if attempt > max_retries or not getattr(exc, "retryable", False):
                raise GitHubAPIError(
                    str(exc),
                    status_code=exc.status_code,
                    attempts=attempt,
                    retryable=getattr(exc, "retryable", None),
                    error_type=exc.error_type,
                    retry_after_seconds=exc.retry_after_seconds,
                ) from exc
            sleep_seconds = exc.retry_after_seconds if exc.retry_after_seconds is not None else base_backoff_seconds * (2 ** (attempt - 1))
            LOGGER.warning(
                "Transient GraphQL request failure (attempt %s/%s); retrying in %.1fs: %s",
                attempt,
                max_retries + 1,
                sleep_seconds,
                exc,
            )
            time.sleep(sleep_seconds)
            continue

        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub GraphQL API returned an unexpected payload", error_type="GraphQLPayloadError")

        errors = payload.get("errors")
        if errors:
            retryable = _graphql_errors_retryable(errors)
            message = "; ".join(_graphql_error_messages(errors)) or "GraphQL query returned errors"
            if retryable and attempt <= max_retries:
                LOGGER.warning(
                    "Transient GraphQL error for %s (attempt %s/%s); retrying in %.1fs: %s",
                    "https://api.github.com/graphql",
                    attempt,
                    max_retries + 1,
                    base_backoff_seconds * (2 ** (attempt - 1)),
                    message,
                )
                time.sleep(base_backoff_seconds * (2 ** (attempt - 1)))
                continue
            raise GitHubAPIError(
                message,
                attempts=attempt,
                retryable=retryable,
                error_type="GraphQLError",
            )

        return payload


def fetch_repository_search_page(
    session: requests.Session,
    *,
    query: str,
    page: int,
    per_page: int,
    sort: str,
    order: str,
) -> dict[str, Any]:
    payload = _request_json_with_retry(
        session,
        method="GET",
        url="https://api.github.com/search/repositories",
        params={
            "q": query,
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "order": order,
        },
    )

    if not isinstance(payload, dict):
        raise GitHubAPIError(f"GitHub repository search returned an unexpected payload on page {page}")

    return payload


def _repository_api_url(repository_full_name: str, suffix: str) -> str:
    if "/" not in repository_full_name:
        raise GitHubAPIError(f"Invalid repository full name: {repository_full_name!r}")
    owner, repo = repository_full_name.split("/", 1)
    base_url = f"https://api.github.com/repos/{owner}/{repo}"
    return f"{base_url}/{suffix.lstrip('/')}" if suffix else base_url


def _split_repository_full_name(repository_full_name: str) -> tuple[str, str]:
    if "/" not in repository_full_name:
        raise GitHubAPIError(f"Invalid repository full name: {repository_full_name!r}")
    owner, repo = repository_full_name.split("/", 1)
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        raise GitHubAPIError(f"Invalid repository full name: {repository_full_name!r}")
    return owner, repo


def fetch_repository_languages(
    session: requests.Session,
    *,
    repository_full_name: str,
) -> dict[str, Any]:
    payload = fetch_github_json(
        session,
        url=_repository_api_url(repository_full_name, "languages"),
    )

    if not isinstance(payload, dict):
        raise GitHubAPIError(f"GitHub languages endpoint returned an unexpected payload for {repository_full_name}")

    return payload


def fetch_default_branch_commit_history(
    session: requests.Session,
    *,
    repository_full_name: str,
    since: str,
    until: str,
) -> dict[str, Any]:
    owner, repo = _split_repository_full_name(repository_full_name)
    return post_github_graphql(
        session,
        query=DEFAULT_BRANCH_COMMIT_COUNT_QUERY,
        variables={
            "owner": owner,
            "name": repo,
            "since": since,
            "until": until,
        },
    )


def fetch_closed_issues_page(
    session: requests.Session,
    *,
    repository_full_name: str,
    after: str | None,
    since: str,
) -> dict[str, Any]:
    owner, repo = _split_repository_full_name(repository_full_name)
    payload = post_github_graphql(
        session,
        query=CLOSED_ISSUE_COUNT_PAGE_QUERY,
        variables={
            "owner": owner,
            "name": repo,
            "after": after,
            "since": since,
        },
    )

    repository = ((payload.get("data") or {}).get("repository")) if isinstance(payload, dict) else None
    if repository is None:
        raise GitHubAPIError(
            f"GitHub GraphQL repository lookup returned no repository for {repository_full_name}",
            error_type="GraphQLRepositoryMissing",
        )

    issues_connection = repository.get("issues") or {}
    if not isinstance(issues_connection, dict):
        raise GitHubAPIError(
            f"GitHub GraphQL issues connection returned an unexpected payload for {repository_full_name}",
            error_type="GraphQLPayloadError",
        )

    return {
        "repository": repository,
        "issues_connection": issues_connection,
        "query": CLOSED_ISSUE_COUNT_PAGE_QUERY,
        "variables": {
            "owner": owner,
            "name": repo,
            "after": after,
            "since": since,
        },
    }


def fetch_repository_commits_page(
    session: requests.Session,
    *,
    repository_full_name: str,
    page: int,
    per_page: int,
    since: str,
    until: str,
) -> list[dict[str, Any]]:
    payload = fetch_github_json(
        session,
        url=_repository_api_url(repository_full_name, "commits"),
        params={
            "since": since,
            "until": until,
            "page": page,
            "per_page": per_page,
        },
    )

    if not isinstance(payload, list):
        raise GitHubAPIError(
            f"GitHub commit collection returned an unexpected payload for {repository_full_name} page {page}"
        )

    return payload


def fetch_repository_issues_page(
    session: requests.Session,
    *,
    repository_full_name: str,
    page: int,
    per_page: int,
    state: str,
    since: str,
) -> list[dict[str, Any]]:
    payload = fetch_github_json(
        session,
        url=_repository_api_url(repository_full_name, "issues"),
        params={
            "state": state,
            "since": since,
            "page": page,
            "per_page": per_page,
            "sort": "updated",
            "direction": "desc",
        },
    )

    if not isinstance(payload, list):
        raise GitHubAPIError(
            f"GitHub issue collection returned an unexpected payload for {repository_full_name} page {page}"
        )

    return payload


def fetch_repository_tree(
    session: requests.Session,
    *,
    repository_full_name: str,
    tree_ref: str,
    recursive: bool = True,
) -> dict[str, Any]:
    payload = fetch_github_json(
        session,
        url=_repository_api_url(repository_full_name, f"git/trees/{tree_ref}"),
        params={"recursive": 1} if recursive else None,
    )

    if not isinstance(payload, dict):
        raise GitHubAPIError(
            f"GitHub repository tree collection returned an unexpected payload for {repository_full_name}"
        )

    return payload
