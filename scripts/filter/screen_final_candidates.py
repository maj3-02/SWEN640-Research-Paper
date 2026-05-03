from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.config import load_study_config
from scripts.utils.github_api import GitHubAPIError, create_github_session, fetch_repository_tree
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import (
    filtered_candidate_dir,
    quality_screened_candidates_dir,
    raw_repo_metadata_dir,
    resolve_repo_path,
)
from scripts.utils.quality_screen import (
    build_quality_screen_exclusion_row,
    build_quality_screen_failure_result,
    build_quality_signal_snapshot,
    evaluate_quality_screen,
    read_csv_rows,
    write_csv,
    write_json,
)
from scripts.utils.collection import repository_artifact_path

LOGGER = logging.getLogger(__name__)

RESULTS_FILENAME = "candidate_quality_screen_results.csv"
EXCLUSIONS_FILENAME = "candidate_quality_screen_exclusion_log.csv"
SUMMARY_FILENAME = "candidate_quality_screen_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a lightweight quality/maturity screen to the filtered candidate pool for final-sample use."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Override for the filtered candidate input directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override for the quality-screened candidate output directory.",
    )
    parser.add_argument(
        "--repo-metadata-dir",
        default=None,
        help="Override for the raw repo metadata snapshot directory.",
    )
    return parser.parse_args()


def load_filtered_candidate_rows(input_dir: Path, languages: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    input_files: list[str] = []
    for language in languages:
        slug = language.strip().lower().replace(" ", "_")
        path = input_dir / f"{slug}_candidates_filtered.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing filtered candidate file for {language}: {path}")
        LOGGER.info("Loading filtered candidates for %s from %s", language, path)
        language_rows = read_csv_rows(path)
        LOGGER.info("Loaded %s filtered candidates for %s", len(language_rows), language)
        rows.extend(language_rows)
        input_files.append(str(path))
    return rows, input_files


def result_fieldnames(base_rows: list[dict[str, str]]) -> list[str]:
    if not base_rows:
        raise ValueError("Cannot determine output schema from an empty candidate pool.")
    base_fields = list(base_rows[0].keys())
    extra_fields = [
        "quality_screen_status",
        "quality_screen_intended_use",
        "quality_screen_pass",
        "quality_screen_score",
        "quality_screen_threshold",
        "quality_screen_failure_reasons",
        "quality_check_not_manual_review_flagged",
        "quality_check_recent_maintenance",
        "quality_check_issue_usage",
        "quality_check_engineering_workflow",
        "quality_recent_push_cutoff_date",
        "quality_open_issues_threshold",
        "quality_signal_has_tests",
        "quality_signal_has_ci",
        "quality_signal_has_community_health_files",
        "quality_signal_matched_test_paths",
        "quality_signal_matched_ci_paths",
        "quality_signal_matched_community_health_paths",
        "quality_tree_truncated",
        "quality_tree_path_count",
        "quality_signal_snapshot_file",
        "quality_screen_error_type",
        "quality_screen_error_message",
        "quality_screen_error_status_code",
        "quality_screen_error_retryable",
        "quality_screen_error_attempts",
    ]
    return base_fields + [field for field in extra_fields if field not in base_fields]


def build_summary(
    *,
    input_files: list[str],
    output_dir: Path,
    repo_metadata_dir: Path,
    result_rows: list[dict[str, object]],
    exclusion_rows: list[dict[str, object]],
    languages: list[str],
    minimum_score: int,
    min_open_issues_count: int,
    recent_push_lookback_days: int,
) -> dict[str, object]:
    passed_by_language: Counter[str] = Counter()
    failed_by_language: Counter[str] = Counter()
    screened_by_language: Counter[str] = Counter()
    metadata_failures = 0

    for row in result_rows:
        language = str(row.get("language_group") or "")
        screened_by_language[language] += 1
        if row.get("quality_screen_status") == "metadata_fetch_failed":
            metadata_failures += 1
        if row.get("quality_screen_pass") is True:
            passed_by_language[language] += 1
        else:
            failed_by_language[language] += 1

    screened_pool_files = {
        language: str(output_dir / f"{language.strip().lower().replace(' ', '_')}_candidates_filtered.csv")
        for language in languages
    }

    return {
        "screen_type": "candidate_quality_screen",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "final_sample_only",
        "input_files": input_files,
        "output_dir": str(output_dir),
        "repo_metadata_dir": str(repo_metadata_dir),
        "screened_pool_files": screened_pool_files,
        "result_file": str(output_dir / RESULTS_FILENAME),
        "exclusion_log_file": str(output_dir / EXCLUSIONS_FILENAME),
        "configuration": {
            "minimum_score": minimum_score,
            "min_open_issues_count": min_open_issues_count,
            "recent_push_lookback_days": recent_push_lookback_days,
        },
        "repositories_screened": len(result_rows),
        "repositories_passed": sum(1 for row in result_rows if row.get("quality_screen_pass") is True),
        "repositories_failed": len(exclusion_rows),
        "metadata_fetch_failures": metadata_failures,
        "screened_by_language": dict(screened_by_language),
        "passed_by_language": dict(passed_by_language),
        "failed_by_language": dict(failed_by_language),
    }


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    quality_config = config.get("candidate_quality_screen", {})
    input_dir = (
        resolve_repo_path(args.input_dir)
        if args.input_dir is not None
        else resolve_repo_path(quality_config.get("input_dir", filtered_candidate_dir()))
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else resolve_repo_path(quality_config.get("output_dir", quality_screened_candidates_dir()))
    )
    repo_metadata_dir = (
        resolve_repo_path(args.repo_metadata_dir)
        if args.repo_metadata_dir is not None
        else resolve_repo_path(quality_config.get("repo_metadata_dir", raw_repo_metadata_dir()))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    repo_metadata_dir.mkdir(parents=True, exist_ok=True)

    languages = [str(language) for language in config.get("languages", ["JavaScript", "TypeScript"])]
    minimum_score = int(quality_config.get("minimum_score", 3))
    min_open_issues_count = int(quality_config.get("min_open_issues_count", 5))
    recent_push_lookback_days = int(quality_config.get("recent_push_lookback_days", 365))
    study_window_end = str(config.get("study_window_end"))

    LOGGER.info("Using filtered candidate input directory: %s", input_dir)
    LOGGER.info("Using quality-screen output directory: %s", output_dir)
    LOGGER.info("Using raw repo metadata directory: %s", repo_metadata_dir)
    LOGGER.info("Quality screen intended use: final sample only")

    base_rows, input_files = load_filtered_candidate_rows(input_dir, languages)
    output_fieldnames = result_fieldnames(base_rows)

    session = create_github_session()
    if "Authorization" not in session.headers:
        LOGGER.warning("GITHUB_TOKEN is not set; proceeding with unauthenticated GitHub API requests.")

    result_rows: list[dict[str, object]] = []
    exclusion_rows: list[dict[str, object]] = []
    passed_rows_by_language: dict[str, list[dict[str, object]]] = defaultdict(list)

    for index, row in enumerate(base_rows, start=1):
        repository_full_name = str(row.get("full_name") or "").strip()
        language_group = str(row.get("language_group") or "")
        default_branch = str(row.get("default_branch") or "").strip()
        LOGGER.info("Quality screening %s (%s/%s)", repository_full_name, index, len(base_rows))

        if not repository_full_name:
            failure_result = build_quality_screen_failure_result(
                row,
                error=ValueError("Candidate row is missing full_name"),
                study_window_end=study_window_end,
                recent_push_lookback_days=recent_push_lookback_days,
                min_open_issues_count=min_open_issues_count,
                minimum_score=minimum_score,
            )
            result_rows.append(failure_result)
            exclusion_rows.append(build_quality_screen_exclusion_row(failure_result))
            continue

        if not default_branch:
            failure_result = build_quality_screen_failure_result(
                row,
                error=ValueError(f"Candidate row is missing default_branch for {repository_full_name}"),
                study_window_end=study_window_end,
                recent_push_lookback_days=recent_push_lookback_days,
                min_open_issues_count=min_open_issues_count,
                minimum_score=minimum_score,
            )
            result_rows.append(failure_result)
            exclusion_rows.append(build_quality_screen_exclusion_row(failure_result))
            continue

        try:
            tree_payload = fetch_repository_tree(
                session,
                repository_full_name=repository_full_name,
                tree_ref=default_branch,
                recursive=True,
            )
            signal_snapshot = build_quality_signal_snapshot(
                repository_full_name=repository_full_name,
                default_branch=default_branch,
                tree_payload=tree_payload,
            )
            signal_snapshot_path = repository_artifact_path(
                repo_metadata_dir,
                repository_full_name,
                "quality_screen_snapshot.json",
            )
            write_json(signal_snapshot_path, signal_snapshot)
            result_row = evaluate_quality_screen(
                row,
                signal_snapshot=signal_snapshot,
                study_window_end=study_window_end,
                recent_push_lookback_days=recent_push_lookback_days,
                min_open_issues_count=min_open_issues_count,
                minimum_score=minimum_score,
                signal_snapshot_file=str(signal_snapshot_path),
            )
        except GitHubAPIError as exc:
            LOGGER.error("Quality metadata fetch failed for %s: %s", repository_full_name, exc)
            result_row = build_quality_screen_failure_result(
                row,
                error=exc,
                study_window_end=study_window_end,
                recent_push_lookback_days=recent_push_lookback_days,
                min_open_issues_count=min_open_issues_count,
                minimum_score=minimum_score,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.exception("Unexpected quality screening failure for %s", repository_full_name)
            result_row = build_quality_screen_failure_result(
                row,
                error=exc,
                study_window_end=study_window_end,
                recent_push_lookback_days=recent_push_lookback_days,
                min_open_issues_count=min_open_issues_count,
                minimum_score=minimum_score,
            )

        result_rows.append(result_row)
        if result_row.get("quality_screen_pass") is True:
            passed_rows_by_language[language_group].append(result_row)
        else:
            exclusion_rows.append(build_quality_screen_exclusion_row(result_row))

    for language in languages:
        slug = language.strip().lower().replace(" ", "_")
        screened_pool_path = output_dir / f"{slug}_candidates_filtered.csv"
        screened_rows = passed_rows_by_language.get(language, [])
        write_csv(screened_pool_path, screened_rows, output_fieldnames)
        LOGGER.info("Saved %s screened candidate pool to %s", language, screened_pool_path)

    results_path = output_dir / RESULTS_FILENAME
    exclusions_path = output_dir / EXCLUSIONS_FILENAME
    write_csv(results_path, result_rows, output_fieldnames)
    exclusion_fieldnames = list(exclusion_rows[0].keys()) if exclusion_rows else [
        "timestamp_utc",
        "language_group",
        "repository_full_name",
        "quality_screen_status",
        "quality_screen_pass",
        "quality_screen_score",
        "quality_screen_threshold",
        "quality_screen_failure_reasons",
        "quality_signal_snapshot_file",
        "source_file",
        "source_record_index",
    ]
    write_csv(exclusions_path, exclusion_rows, exclusion_fieldnames)

    summary = build_summary(
        input_files=input_files,
        output_dir=output_dir,
        repo_metadata_dir=repo_metadata_dir,
        result_rows=result_rows,
        exclusion_rows=exclusion_rows,
        languages=languages,
        minimum_score=minimum_score,
        min_open_issues_count=min_open_issues_count,
        recent_push_lookback_days=recent_push_lookback_days,
    )
    summary_path = output_dir / SUMMARY_FILENAME
    write_json(summary_path, summary)

    LOGGER.info("Repositories screened: %s", summary["repositories_screened"])
    LOGGER.info("Repositories passed: %s", summary["repositories_passed"])
    LOGGER.info("Repositories failed: %s", summary["repositories_failed"])
    LOGGER.info("Saved quality screen results to %s", results_path)
    LOGGER.info("Saved quality screen exclusions to %s", exclusions_path)
    LOGGER.info("Saved quality screen summary to %s", summary_path)


if __name__ == "__main__":
    main()
