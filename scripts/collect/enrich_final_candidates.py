from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.config import load_study_config
from scripts.utils.enrichment import (
    build_enrichment_failure_record,
    build_enrichment_result_row,
    build_enrichment_summary,
    count_closed_issue_nodes_in_window,
    parse_default_branch_commit_count,
    serialize_enrichment_row,
)
from scripts.utils.github_api import (
    GitHubAPIError,
    create_github_session,
    fetch_default_branch_commit_history,
    fetch_closed_issues_page,
    fetch_repository_languages,
)
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import (
    enriched_candidate_language_path,
    enriched_candidate_paths,
    enriched_candidates_dir,
    quality_screened_candidates_dir,
    resolve_repo_path,
)

LOGGER = logging.getLogger(__name__)


class CandidateEnrichmentStepError(RuntimeError):
    def __init__(self, stage: str, error: Exception) -> None:
        super().__init__(f"{stage} failed: {error}")
        self.stage = stage
        self.original_error = error
        self.error_type = getattr(error, "error_type", error.__class__.__name__)
        self.status_code = getattr(error, "status_code", None)
        self.retryable = getattr(error, "retryable", None)
        self.attempts = getattr(error, "attempts", None)
        self.retry_after_seconds = getattr(error, "retry_after_seconds", None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich quality-screened final-study candidates with language and activity metadata."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Override for the quality-screened candidate input directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override for enriched final-study candidate outputs.",
    )
    return parser.parse_args()


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: str | Path, rows: list[Mapping[str, Any]], fieldnames: list[str]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _language_slug(language: str) -> str:
    return language.strip().lower().replace(" ", "_")


def load_quality_screened_candidate_rows(input_dir: Path, languages: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    input_files: list[str] = []

    for language in languages:
        path = input_dir / f"{_language_slug(language)}_candidates_filtered.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing quality-screened candidate file for {language}: {path}")

        LOGGER.info("Loading quality-screened candidates for %s from %s", language, path)
        language_rows = read_csv_rows(path)
        for index, row in enumerate(language_rows, start=1):
            row.setdefault("language_group", language)
            row["enrichment_input_file"] = str(path)
            row["enrichment_input_record_index"] = index
        LOGGER.info("Loaded %s quality-screened candidates for %s", len(language_rows), language)

        rows.extend(language_rows)
        input_files.append(str(path))

    return rows, input_files


def enrichment_fieldnames(base_rows: list[Mapping[str, Any]]) -> list[str]:
    base_fields: list[str] = []
    for row in base_rows:
        for field in row.keys():
            if field not in base_fields:
                base_fields.append(field)

    extra_fields = [
        "repository_full_name",
        "language_group",
        "target_language",
        "language_stats",
        "target_language_bytes",
        "total_language_bytes",
        "target_language_share",
        "language_threshold",
        "language_threshold_pass",
        "default_branch_commit_count_in_window",
        "closed_issue_count_in_window",
        "closed_issue_count_available",
        "enrichment_status",
        "enrichment_failure_reason",
    ]
    return base_fields + [field for field in extra_fields if field not in base_fields]


def threshold_pass_rows_by_language(
    result_rows: list[Mapping[str, Any]],
    languages: list[str],
) -> dict[str, list[Mapping[str, Any]]]:
    rows_by_language: dict[str, list[Mapping[str, Any]]] = {language: [] for language in languages}
    normalized_lookup = {language.lower(): language for language in languages}

    for row in result_rows:
        if row.get("language_threshold_pass") is not True:
            continue
        language = str(row.get("language_group") or row.get("target_language") or "").strip()
        output_language = normalized_lookup.get(language.lower(), language)
        rows_by_language.setdefault(output_language, []).append(row)

    return rows_by_language


def _graphql_timestamp(date_value: str, *, end_of_day: bool = False) -> str:
    suffix = "T23:59:59Z" if end_of_day else "T00:00:00Z"
    return f"{date_value}{suffix}" if "T" not in date_value else date_value


def collect_closed_issue_count_in_window(
    session,
    *,
    repository_full_name: str,
    study_window_start: str,
    study_window_end: str,
) -> int:
    closed_issue_count = 0
    after: str | None = None

    while True:
        page_payload = fetch_closed_issues_page(
            session,
            repository_full_name=repository_full_name,
            after=after,
            since=_graphql_timestamp(study_window_start),
        )
        issues_connection = page_payload["issues_connection"]
        nodes = issues_connection.get("nodes") or []
        page_counts = count_closed_issue_nodes_in_window(
            nodes,
            study_window_start=study_window_start,
            study_window_end=study_window_end,
        )
        closed_issue_count += page_counts["closed_issue_count_in_window"]

        page_info = issues_connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        after = str(page_info.get("endCursor") or "")
        if not after:
            break

    return closed_issue_count


def enrich_candidate_row(
    session,
    *,
    candidate_row: Mapping[str, Any],
    target_language: str,
    language_threshold: float,
    study_window_start: str,
    study_window_end: str,
) -> dict[str, Any]:
    repository_full_name = str(
        candidate_row.get("full_name")
        or candidate_row.get("repository_full_name")
        or ""
    ).strip()
    if not repository_full_name:
        raise ValueError("Candidate row is missing full_name/repository_full_name")

    try:
        language_bytes = fetch_repository_languages(
            session,
            repository_full_name=repository_full_name,
        )
    except Exception as exc:
        raise CandidateEnrichmentStepError("language_stats", exc) from exc

    try:
        commit_history_payload = fetch_default_branch_commit_history(
            session,
            repository_full_name=repository_full_name,
            since=_graphql_timestamp(study_window_start),
            until=_graphql_timestamp(study_window_end, end_of_day=True),
        )
        commit_count = parse_default_branch_commit_count(commit_history_payload)
        if commit_count is None:
            raise ValueError(
                "GitHub GraphQL payload did not include default-branch commit history totalCount"
            )
    except Exception as exc:
        raise CandidateEnrichmentStepError("commit_count", exc) from exc

    try:
        closed_issue_count = collect_closed_issue_count_in_window(
            session,
            repository_full_name=repository_full_name,
            study_window_start=study_window_start,
            study_window_end=study_window_end,
        )
    except Exception as exc:
        raise CandidateEnrichmentStepError("closed_issue_count", exc) from exc

    return build_enrichment_result_row(
        candidate_row,
        language_bytes=language_bytes,
        target_language=target_language,
        language_threshold=language_threshold,
        default_branch_commit_count=commit_count,
        closed_issue_count=closed_issue_count,
    )


def build_candidate_enrichment_summary(
    *,
    input_files: list[str],
    output_files: Mapping[str, str],
    result_rows: list[Mapping[str, Any]],
    failure_records: list[Mapping[str, Any]],
    language_threshold: float,
) -> dict[str, Any]:
    summary = build_enrichment_summary(
        input_files=input_files,
        output_files=output_files,
        result_rows=result_rows,
        failure_records=failure_records,
        language_threshold=language_threshold,
    )
    enriched_count = int(summary["repositories_enriched"])
    threshold_pass_count = int(summary["language_threshold_pass_count"])
    closed_issue_count_available_count = int(summary["closed_issue_count_available_count"])
    summary.update(
        {
            "activity_field": "default_branch_commit_count_in_window",
            "activity_field_is_proxy": False,
            "language_threshold_failed_count": enriched_count - threshold_pass_count,
            "closed_issue_count_field": "closed_issue_count_in_window",
            "closed_issue_count_status": "available",
            "closed_issue_count_missing_count": enriched_count - closed_issue_count_available_count,
            "closed_issue_count_failure_count": sum(
                1 for record in failure_records if record.get("stage") == "closed_issue_count"
            ),
            "closed_issue_count_method": "graphql_repository_issues_cursor_pagination_closedAt_window",
        }
    )
    return summary


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    enrichment_config = config.get("candidate_enrichment", {})

    input_dir = (
        resolve_repo_path(args.input_dir)
        if args.input_dir is not None
        else resolve_repo_path(enrichment_config.get("input_dir", quality_screened_candidates_dir()))
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else resolve_repo_path(enrichment_config.get("output_dir", enriched_candidates_dir()))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    languages = [str(language) for language in config.get("languages", ["JavaScript", "TypeScript"])]
    language_threshold = float(enrichment_config.get("language_threshold", config.get("language_threshold", 0.70)))
    study_window_start = str(config.get("study_window_start"))
    study_window_end = str(config.get("study_window_end"))

    LOGGER.info("Using quality-screened candidate input directory: %s", input_dir)
    LOGGER.info("Using enriched candidate output directory: %s", output_dir)
    LOGGER.info("Study window: %s through %s", study_window_start, study_window_end)
    LOGGER.info("Language threshold: %.2f", language_threshold)
    LOGGER.info("Closed-issue pre-sampling count: exact GraphQL cursor count by closedAt window")

    candidate_rows, input_files = load_quality_screened_candidate_rows(input_dir, languages)
    fieldnames = enrichment_fieldnames(candidate_rows)

    session = create_github_session()
    if "Authorization" not in session.headers:
        LOGGER.warning("GITHUB_TOKEN is not set; proceeding with unauthenticated GitHub API requests.")

    result_rows: list[dict[str, Any]] = []
    failure_records: list[dict[str, Any]] = []

    for index, row in enumerate(candidate_rows, start=1):
        repository_full_name = str(row.get("full_name") or row.get("repository_full_name") or "").strip()
        target_language = str(row.get("language_group") or "").strip()
        LOGGER.info(
            "Enriching final-study candidate %s (%s/%s)",
            repository_full_name or "<missing repository>",
            index,
            len(candidate_rows),
        )

        try:
            result_row = enrich_candidate_row(
                session,
                candidate_row=row,
                target_language=target_language,
                language_threshold=language_threshold,
                study_window_start=study_window_start,
                study_window_end=study_window_end,
            )
        except Exception as exc:  # pragma: no cover - defensive guard for unexpected failures
            stage = getattr(exc, "stage", "candidate_enrichment")
            if isinstance(exc, CandidateEnrichmentStepError):
                LOGGER.error("Candidate enrichment step %s failed for %s: %s", stage, repository_full_name, exc)
            else:
                LOGGER.exception("Unexpected candidate enrichment failure for %s", repository_full_name)
            failure_records.append(
                build_enrichment_failure_record(
                    candidate_row=row,
                    stage=str(stage),
                    error=exc,
                    target_language=target_language,
                )
            )
            continue

        result_rows.append(result_row)
        LOGGER.info(
            "Enriched %s: language threshold pass=%s, default-branch commits=%s, closed issues=%s",
            repository_full_name,
            result_row.get("language_threshold_pass"),
            result_row.get("default_branch_commit_count_in_window"),
            result_row.get("closed_issue_count_in_window"),
        )

    paths = enriched_candidate_paths(output_dir)
    per_language_rows = threshold_pass_rows_by_language(result_rows, languages)

    serialized_results = [serialize_enrichment_row(row) for row in result_rows]
    write_csv_rows(paths["results_csv"], serialized_results, fieldnames)

    per_language_output_files: dict[str, str] = {}
    for language in languages:
        language_path = enriched_candidate_language_path(language, output_dir)
        per_language_output_files[language] = str(language_path)
        serialized_language_rows = [
            serialize_enrichment_row(row) for row in per_language_rows.get(language, [])
        ]
        write_csv_rows(language_path, serialized_language_rows, fieldnames)

    failure_log = {
        "enrichment_type": "final_candidate_enrichment",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "final_sample_only",
        "failure_count": len(failure_records),
        "failures": failure_records,
    }
    write_json(paths["failures_json"], failure_log)
    closed_issue_count_failures = [
        record for record in failure_records if record.get("stage") == "closed_issue_count"
    ]
    write_json(
        paths["closed_issue_count_failures_json"],
        {
            "enrichment_type": "closed_issue_count",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "intended_use": "final_sample_only",
            "failure_count": len(closed_issue_count_failures),
            "failures": closed_issue_count_failures,
        },
    )

    output_files = {
        "results_csv": str(paths["results_csv"]),
        "failures_json": str(paths["failures_json"]),
        "closed_issue_count_failures_json": str(paths["closed_issue_count_failures_json"]),
        "summary_json": str(paths["summary_json"]),
        "per_language_enriched_candidates": per_language_output_files,
    }
    summary = build_candidate_enrichment_summary(
        input_files=input_files,
        output_files=output_files,
        result_rows=result_rows,
        failure_records=failure_records,
        language_threshold=language_threshold,
    )
    write_json(paths["summary_json"], summary)

    LOGGER.info("Saved candidate enrichment results to %s", paths["results_csv"])
    LOGGER.info("Saved candidate enrichment failures to %s", paths["failures_json"])
    LOGGER.info("Saved candidate enrichment summary to %s", paths["summary_json"])


if __name__ == "__main__":
    try:
        main()
    except GitHubAPIError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc
