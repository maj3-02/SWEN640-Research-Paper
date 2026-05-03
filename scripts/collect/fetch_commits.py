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
    commit_in_window,
    commit_window_timestamp,
    extract_repository_full_name,
    load_sampled_repositories,
    repository_artifact_path,
    sample_row_trace,
    study_window_bounds,
    write_json,
)
from scripts.utils.config import load_study_config
from scripts.utils.github_api import GitHubAPIError, create_github_session, fetch_repository_commits_page
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import final_sample_dir, raw_commits_dir, resolve_repo_path

LOGGER = logging.getLogger(__name__)
COMMITS_PER_PAGE = 100


def default_commit_output_dir(sample_file: Path) -> Path:
    provenance = build_sample_provenance(sample_file)
    if provenance["sample_run_type"] == "final_study":
        return final_sample_dir() / "raw_commits"
    return raw_commits_dir()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch raw commit data for sampled repositories.")
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
        help="Directory for raw commit outputs. Defaults to data/raw/commits.",
    )
    return parser.parse_args()


def collect_repository_commits(
    session,
    *,
    repository_full_name: str,
    sample_row: dict[str, Any],
    study_window_start: str,
    study_window_end: str,
) -> dict[str, Any]:
    start_dt, end_dt = study_window_bounds(study_window_start, study_window_end)
    page = 1
    pages: list[dict[str, Any]] = []
    commits: list[dict[str, Any]] = []
    raw_commit_count = 0
    missing_timestamp_count = 0
    outside_window_count = 0

    # GitHub's commits endpoint is paginated; we keep the raw commit payloads that fall inside the study window.
    while True:
        page_items = fetch_repository_commits_page(
            session,
            repository_full_name=repository_full_name,
            page=page,
            per_page=COMMITS_PER_PAGE,
            since=f"{study_window_start}T00:00:00Z",
            until=f"{study_window_end}T23:59:59Z",
        )

        if not page_items:
            break

        kept_page_count = 0
        for commit in page_items:
            raw_commit_count += 1
            timestamp = commit_window_timestamp(commit)
            if timestamp is None:
                missing_timestamp_count += 1
                continue
            if not commit_in_window(commit, start_dt, end_dt):
                outside_window_count += 1
                continue
            commits.append(commit)
            kept_page_count += 1

        pages.append(
            {
                "page": page,
                "raw_commit_count": len(page_items),
                "kept_commit_count": kept_page_count,
            }
        )

        if len(page_items) < COMMITS_PER_PAGE:
            break
        page += 1

    return {
        "collection_type": "commits",
        "repository_full_name": repository_full_name,
        "sample_row": sample_row,
        "study_window_start": study_window_start,
        "study_window_end": study_window_end,
        "date_field_used_for_windowing": "commit.commit.author.date with fallback to commit.commit.committer.date",
        "api_query": {
            "since": f"{study_window_start}T00:00:00Z",
            "until": f"{study_window_end}T23:59:59Z",
            "per_page": COMMITS_PER_PAGE,
        },
        "page_count": len(pages),
        "pages": pages,
        "raw_commit_count": raw_commit_count,
        "commit_count": len(commits),
        "missing_timestamp_count": missing_timestamp_count,
        "outside_window_count": outside_window_count,
        "commits": commits,
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
        else default_commit_output_dir(sample_file)
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    study_window_start = str(config.get("study_window_start"))
    study_window_end = str(config.get("study_window_end"))
    repositories = load_sampled_repositories(sample_file)
    sample_provenance = build_sample_provenance(sample_file)

    LOGGER.info("Using sampled repository file: %s", sample_file)
    LOGGER.info("Sample run type: %s", sample_provenance["sample_run_type"])
    LOGGER.info("Using raw commit output directory: %s", output_dir)
    LOGGER.info("Study window: %s through %s", study_window_start, study_window_end)
    LOGGER.info("Repositories to process: %s", len(repositories))

    session = create_github_session()
    if "Authorization" not in session.headers:
        LOGGER.warning("GITHUB_TOKEN is not set; proceeding with unauthenticated GitHub API requests.")

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    total_commits = 0

    for index, row in enumerate(repositories, start=1):
        repository_full_name = extract_repository_full_name(row)
        LOGGER.info("Fetching commits for %s (%s/%s)", repository_full_name, index, len(repositories))
        try:
            repo_result = collect_repository_commits(
                session,
                repository_full_name=repository_full_name,
                sample_row=row,
                study_window_start=study_window_start,
                study_window_end=study_window_end,
            )
        except GitHubAPIError as exc:
            LOGGER.error("Commit collection failed for %s: %s", repository_full_name, exc)
            failures.append(
                build_collection_failure_record(
                    stage="commits",
                    repository_full_name=repository_full_name,
                    error=exc,
                    retries_attempted=max(0, (getattr(exc, "attempts", 1) or 1) - 1),
                    language_group=row.get("language_group"),
                    sample_row_trace=sample_row_trace(row),
                )
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
            LOGGER.exception("Unexpected commit collection failure for %s", repository_full_name)
            failures.append(
                build_collection_failure_record(
                    stage="commits",
                    repository_full_name=repository_full_name,
                    error=exc,
                    retries_attempted=0,
                    language_group=row.get("language_group"),
                    sample_row_trace=sample_row_trace(row),
                )
            )
            continue

        output_path = repository_artifact_path(output_dir, repository_full_name, "commits_raw.json")
        write_json(output_path, repo_result)
        LOGGER.info("Saved raw commits for %s to %s", repository_full_name, output_path)
        LOGGER.info(
            "Fetched %s commits for %s (%s raw items, %s missing timestamps, %s outside window)",
            repo_result["commit_count"],
            repository_full_name,
            repo_result["raw_commit_count"],
            repo_result["missing_timestamp_count"],
            repo_result["outside_window_count"],
        )

        total_commits += int(repo_result["commit_count"])
        results.append(
            {
                "repository_full_name": repository_full_name,
                "language_group": row.get("language_group"),
                "sample_run_type": sample_provenance["sample_run_type"],
                "sample_row_trace": sample_row_trace(row),
                "raw_commit_count": repo_result["raw_commit_count"],
                "commit_count": repo_result["commit_count"],
                "missing_timestamp_count": repo_result["missing_timestamp_count"],
                "outside_window_count": repo_result["outside_window_count"],
                "output_file": str(output_path),
            }
        )

    summary = {
        "collection_type": "commits",
        "sample_file": str(sample_file),
        "sample_run_type": sample_provenance["sample_run_type"],
        "output_dir": str(output_dir),
        "study_window_start": study_window_start,
        "study_window_end": study_window_end,
        "repositories_requested": len(repositories),
        "repositories_succeeded": len(results),
        "repositories_failed": len(failures),
        "total_commits_collected": total_commits,
        "results": results,
        "failures": failures,
    }
    summary_path = output_dir / "commit_collection_summary.json"
    write_json(summary_path, summary)
    LOGGER.info("Saved commit collection summary to %s", summary_path)

    failure_log = {
        "collection_type": "commits",
        "sample_file": str(sample_file),
        "sample_run_type": sample_provenance["sample_run_type"],
        "output_dir": str(output_dir),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "failure_count": len(failures),
        "failures": failures,
    }
    failure_log_path = output_dir / "commit_collection_failures.json"
    write_json(failure_log_path, failure_log)
    LOGGER.info("Saved commit failure log to %s", failure_log_path)


if __name__ == "__main__":
    try:
        main()
    except GitHubAPIError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc
