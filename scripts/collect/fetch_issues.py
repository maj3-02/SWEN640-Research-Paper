from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.collection import (
    build_collection_failure_record,
    build_sample_provenance,
    extract_repository_full_name,
    load_sampled_repositories,
    repository_artifact_path,
    sample_row_trace,
    study_window_bounds,
    timestamp_inclusive_window,
    write_json,
)
from scripts.utils.config import load_study_config
from scripts.utils.github_api import GitHubAPIError, create_github_session, post_github_graphql
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import final_sample_dir, raw_issues_dir, resolve_repo_path

LOGGER = logging.getLogger(__name__)
ISSUES_PER_PAGE = 100
ISSUE_PAGINATION_MODE = "graphql_cursor"
ISSUE_GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $after: String, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    issues(
      first: 100
      after: $after
      orderBy: {field: UPDATED_AT, direction: DESC}
      filterBy: {states: CLOSED, since: $since}
    ) {
      totalCount
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        id
        number
        title
        body
        state
        createdAt
        closedAt
        updatedAt
        url
        author {
          __typename
          login
        }
        labels(first: 100) {
          totalCount
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            id
            name
            color
            description
          }
        }
      }
    }
  }
}
"""


def default_issue_output_dir(sample_file: Path) -> Path:
    provenance = build_sample_provenance(sample_file)
    if provenance["sample_run_type"] == "final_study":
        return final_sample_dir() / "raw_issues"
    return raw_issues_dir()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch raw issue data for sampled repositories.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--sample-file",
        default=None,
        help="Path to the sampled repositories CSV. Defaults to data/interim/final_sample/final_sample.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for raw issue outputs. Defaults to data/raw/issues.",
    )
    return parser.parse_args()


def _repository_owner_and_name(repository_full_name: str) -> tuple[str, str]:
    if "/" not in repository_full_name:
        raise GitHubAPIError(f"Invalid repository full name: {repository_full_name!r}")
    owner, name = repository_full_name.split("/", 1)
    return owner, name


def fetch_repository_issues_page_graphql(
    session,
    *,
    repository_full_name: str,
    after: str | None,
    study_window_start: str,
) -> dict[str, Any]:
    owner, name = _repository_owner_and_name(repository_full_name)
    payload = post_github_graphql(
        session,
        query=ISSUE_GRAPHQL_QUERY,
        variables={
            "owner": owner,
            "name": name,
            "after": after,
            "since": f"{study_window_start}T00:00:00Z",
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
        "query": ISSUE_GRAPHQL_QUERY,
        "variables": {
            "owner": owner,
            "name": name,
            "after": after,
            "since": f"{study_window_start}T00:00:00Z",
        },
    }


def collect_repository_issues(
    session,
    *,
    repository_full_name: str,
    sample_row: dict[str, Any],
    study_window_start: str,
    study_window_end: str,
) -> dict[str, Any]:
    start_dt, end_dt = study_window_bounds(study_window_start, study_window_end)
    page = 1
    after: str | None = None
    pages: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    raw_issue_count = 0
    missing_closed_at_count = 0
    outside_window_count = 0

    # GraphQL cursor pagination is used here because large repositories can reject page-based pagination.
    # The repository issues connection returns issues only, so pull requests are excluded by construction.
    while True:
        page_payload = fetch_repository_issues_page_graphql(
            session,
            repository_full_name=repository_full_name,
            after=after,
            study_window_start=study_window_start,
        )
        issues_connection = page_payload["issues_connection"]
        page_items = issues_connection.get("nodes") or []
        page_page_info = issues_connection.get("pageInfo") or {}
        page_total_count = issues_connection.get("totalCount")
        kept_page_count = 0
        page_outside_window_count = 0
        page_missing_closed_at_count = 0

        for issue in page_items:
            raw_issue_count += 1
            closed_at = issue.get("closedAt")
            if not closed_at:
                missing_closed_at_count += 1
                page_missing_closed_at_count += 1
                continue

            if not timestamp_inclusive_window(closed_at, start_dt, end_dt):
                outside_window_count += 1
                page_outside_window_count += 1
                continue

            issues.append(issue)
            kept_page_count += 1

        pages.append(
            {
                "page": page,
                "raw_issue_count": len(page_items),
                "kept_issue_count": kept_page_count,
                "missing_closed_at_count": page_missing_closed_at_count,
                "outside_window_count": page_outside_window_count,
                "has_next_page": page_page_info.get("hasNextPage"),
                "end_cursor": page_page_info.get("endCursor"),
                "total_count": page_total_count,
            }
        )

        if not page_page_info.get("hasNextPage"):
            break
        after = str(page_page_info.get("endCursor") or "")
        if not after:
            break
        page += 1

    return {
        "collection_type": "issues",
        "repository_full_name": repository_full_name,
        "sample_row": sample_row,
        "study_window_start": study_window_start,
        "study_window_end": study_window_end,
        "date_field_used_for_windowing": "closedAt",
        "pagination_mode": ISSUE_PAGINATION_MODE,
        "pr_exclusion_mode": "repository_issues_connection_excludes_pull_requests",
        "api_query": {
            "graphql_query_name": "repositoryIssues",
            "since": f"{study_window_start}T00:00:00Z",
            "orderBy": {"field": "UPDATED_AT", "direction": "DESC"},
            "states": ["CLOSED"],
            "page_size": ISSUES_PER_PAGE,
        },
        "page_count": len(pages),
        "pages": pages,
        "raw_issue_count": raw_issue_count,
        "issue_count": len(issues),
        "excluded_pull_request_count": 0,
        "missing_closed_at_count": missing_closed_at_count,
        "outside_window_count": outside_window_count,
        "issues": issues,
    }


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    sample_file = (
        resolve_repo_path(args.sample_file)
        if args.sample_file is not None
        else resolve_repo_path(final_sample_dir() / "final_sample.csv")
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else default_issue_output_dir(sample_file)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    study_window_start = str(config.get("study_window_start"))
    study_window_end = str(config.get("study_window_end"))
    repositories = load_sampled_repositories(sample_file)
    sample_provenance = build_sample_provenance(sample_file)

    LOGGER.info("Using sampled repository file: %s", sample_file)
    LOGGER.info("Sample run type: %s", sample_provenance["sample_run_type"])
    LOGGER.info("Using raw issue output directory: %s", output_dir)
    LOGGER.info("Study window: %s through %s", study_window_start, study_window_end)
    LOGGER.info("Repositories to process: %s", len(repositories))
    LOGGER.info("Issue pagination mode: %s", ISSUE_PAGINATION_MODE)

    session = create_github_session()
    if "Authorization" not in session.headers:
        LOGGER.warning("GITHUB_TOKEN is not set; proceeding with unauthenticated GitHub API requests.")

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    total_issues = 0
    total_pr_excluded = 0

    for index, row in enumerate(repositories, start=1):
        repository_full_name = extract_repository_full_name(row)
        LOGGER.info("Fetching issues for %s (%s/%s)", repository_full_name, index, len(repositories))
        try:
            repo_result = collect_repository_issues(
                session,
                repository_full_name=repository_full_name,
                sample_row=row,
                study_window_start=study_window_start,
                study_window_end=study_window_end,
            )
        except GitHubAPIError as exc:
            LOGGER.error("Issue collection failed for %s: %s", repository_full_name, exc)
            failures.append(
                build_collection_failure_record(
                    stage="issues",
                    repository_full_name=repository_full_name,
                    error=exc,
                    retries_attempted=max(0, (getattr(exc, "attempts", 1) or 1) - 1),
                    language_group=row.get("language_group"),
                    pagination_mode=ISSUE_PAGINATION_MODE,
                    sample_row_trace=sample_row_trace(row),
                )
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
            LOGGER.exception("Unexpected issue collection failure for %s", repository_full_name)
            failures.append(
                build_collection_failure_record(
                    stage="issues",
                    repository_full_name=repository_full_name,
                    error=exc,
                    retries_attempted=0,
                    language_group=row.get("language_group"),
                    pagination_mode=ISSUE_PAGINATION_MODE,
                    sample_row_trace=sample_row_trace(row),
                )
            )
            continue

        output_path = repository_artifact_path(output_dir, repository_full_name, "issues_raw.json")
        write_json(output_path, repo_result)
        LOGGER.info("Saved raw issues for %s to %s", repository_full_name, output_path)
        LOGGER.info(
            "Fetched %s issues for %s (%s raw items, %s missing closedAt, %s outside window)",
            repo_result["issue_count"],
            repository_full_name,
            repo_result["raw_issue_count"],
            repo_result["missing_closed_at_count"],
            repo_result["outside_window_count"],
        )

        total_issues += int(repo_result["issue_count"])
        total_pr_excluded += int(repo_result["excluded_pull_request_count"])
        results.append(
            {
                "repository_full_name": repository_full_name,
                "language_group": row.get("language_group"),
                "sample_run_type": sample_provenance["sample_run_type"],
                "sample_row_trace": sample_row_trace(row),
                "pagination_mode": repo_result["pagination_mode"],
                "raw_issue_count": repo_result["raw_issue_count"],
                "issue_count": repo_result["issue_count"],
                "excluded_pull_request_count": repo_result["excluded_pull_request_count"],
                "missing_closed_at_count": repo_result["missing_closed_at_count"],
                "outside_window_count": repo_result["outside_window_count"],
                "output_file": str(output_path),
            }
        )

    summary = {
        "collection_type": "issues",
        "sample_file": str(sample_file),
        "sample_run_type": sample_provenance["sample_run_type"],
        "output_dir": str(output_dir),
        "study_window_start": study_window_start,
        "study_window_end": study_window_end,
        "pagination_mode": ISSUE_PAGINATION_MODE,
        "repositories_requested": len(repositories),
        "repositories_succeeded": len(results),
        "repositories_failed": len(failures),
        "total_issues_collected": total_issues,
        "total_pull_requests_excluded": total_pr_excluded,
        "results": results,
        "failures": failures,
    }
    summary_path = output_dir / "issue_collection_summary.json"
    write_json(summary_path, summary)
    LOGGER.info("Saved issue collection summary to %s", summary_path)

    failure_log = {
        "collection_type": "issues",
        "sample_file": str(sample_file),
        "sample_run_type": sample_provenance["sample_run_type"],
        "output_dir": str(output_dir),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pagination_mode": ISSUE_PAGINATION_MODE,
        "failure_count": len(failures),
        "failures": failures,
    }
    failure_log_path = output_dir / "issue_collection_failures.json"
    write_json(failure_log_path, failure_log)
    LOGGER.info("Saved issue failure log to %s", failure_log_path)


if __name__ == "__main__":
    try:
        main()
    except GitHubAPIError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc
