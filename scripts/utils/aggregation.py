from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from scripts.utils.classification import load_csv_rows, load_json, parse_bool, unique_preserve_order


SAMPLE_MANIFEST_FILENAME = "final_sample.csv"


def infer_aggregation_input_kind(manifest_file: str | Path) -> str:
    filename = Path(manifest_file).name.lower()
    if filename == SAMPLE_MANIFEST_FILENAME:
        return "sample_manifest"
    return "custom_manifest"


def infer_aggregation_run_type(manifest_file: str | Path) -> str:
    path = Path(manifest_file)
    normalized_parts = {part.lower() for part in path.parts}
    filename = path.name.lower()
    if filename == SAMPLE_MANIFEST_FILENAME and "final_sample" in normalized_parts:
        return "final_study"
    return "custom"


def build_aggregation_run_provenance(manifest_file: str | Path) -> dict[str, Any]:
    input_kind = infer_aggregation_input_kind(manifest_file)
    provenance = {
        "aggregation_input_file": str(manifest_file),
        "aggregation_input_kind": input_kind,
        "aggregation_run_type": infer_aggregation_run_type(manifest_file),
    }
    if input_kind == "sample_manifest":
        provenance["sample_manifest_file"] = str(manifest_file)
    return provenance


def parse_iso_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def duration_days(created_at: Any, closed_at: Any) -> float | None:
    created_dt = parse_iso_datetime(created_at)
    closed_dt = parse_iso_datetime(closed_at)
    if created_dt is None or closed_dt is None:
        return None
    delta = closed_dt - created_dt
    if delta.total_seconds() < 0:
        return None
    return delta.total_seconds() / 86400.0


def repo_full_name_from_row(row: dict[str, Any]) -> str:
    return str(row.get("repository_full_name") or row.get("full_name") or "").strip()


def load_manifest_index(path: str | Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    rows = load_csv_rows(path)
    ordered_repositories: list[str] = []
    by_repository: dict[str, dict[str, Any]] = {}
    for row in rows:
        repository_full_name = repo_full_name_from_row(row)
        if repository_full_name and repository_full_name not in by_repository:
            by_repository[repository_full_name] = row
            ordered_repositories.append(repository_full_name)
    return ordered_repositories, by_repository


def load_raw_issue_index(path: str | Path) -> dict[str, Any]:
    payload = load_json(path)
    issues = payload.get("issues") or []
    if not isinstance(issues, list):
        raise ValueError(f"Expected 'issues' to be a list in {path}")

    by_index: dict[int, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    by_number: dict[str, dict[str, Any]] = {}
    for index, issue in enumerate(issues):
        if not isinstance(issue, dict):
            continue
        by_index[index] = issue
        issue_id = str(issue.get("id") or "").strip()
        if issue_id:
            by_id[issue_id] = issue
        issue_number = str(issue.get("number") or "").strip()
        if issue_number:
            by_number[issue_number] = issue

    return {
        "source_file": str(path),
        "issues": issues,
        "by_index": by_index,
        "by_id": by_id,
        "by_number": by_number,
    }


def resolve_raw_issue_record(raw_issue_index: dict[str, Any], classified_row: dict[str, Any]) -> dict[str, Any] | None:
    raw_record_index = classified_row.get("raw_record_index")
    try:
        raw_index = int(str(raw_record_index).strip())
    except (TypeError, ValueError):
        raw_index = None

    if raw_index is not None:
        indexed_record = raw_issue_index.get("by_index", {}).get(raw_index)
        if indexed_record is not None:
            return indexed_record

    issue_id = str(classified_row.get("issue_id") or "").strip()
    if issue_id:
        record = raw_issue_index.get("by_id", {}).get(issue_id)
        if record is not None:
            return record

    issue_number = str(classified_row.get("issue_number") or "").strip()
    if issue_number:
        record = raw_issue_index.get("by_number", {}).get(issue_number)
        if record is not None:
            return record

    return None


def _join_unique(values: list[str]) -> str:
    return ";".join(unique_preserve_order([value for value in values if value]))


def _load_raw_issue_index_cached(
    source_file: str,
    *,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if not source_file:
        return None
    if source_file in cache:
        return cache[source_file]
    source_path = Path(source_file)
    if not source_path.exists():
        return None
    cache[source_file] = load_raw_issue_index(source_path)
    return cache[source_file]


def _collect_commit_metrics(
    classified_commit_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total_commits_in_window = len(classified_commit_rows)
    bug_fix_commit_count = sum(1 for row in classified_commit_rows if parse_bool(row.get("is_bug_fix")))
    bug_fix_commit_ratio = (
        bug_fix_commit_count / total_commits_in_window if total_commits_in_window else None
    )
    source_files = _join_unique([str(row.get("source_file") or "").strip() for row in classified_commit_rows])
    return {
        "commit_source_file": source_files,
        "total_commits_in_window": total_commits_in_window,
        "bug_fix_commit_count": bug_fix_commit_count,
        "bug_fix_commit_ratio": bug_fix_commit_ratio,
    }


def _collect_issue_metrics(
    classified_issue_rows: list[dict[str, Any]],
    *,
    raw_issue_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    total_closed_issues_in_window_considered = len(classified_issue_rows)
    bug_related_rows = [row for row in classified_issue_rows if parse_bool(row.get("is_bug_related"))]
    bug_related_issue_count = len(bug_related_rows)
    bug_related_issue_resolution_days: list[float] = []
    invalid_bug_related_issue_duration_count = 0
    source_files = _join_unique([str(row.get("source_file") or "").strip() for row in classified_issue_rows])

    for row in bug_related_rows:
        source_file = str(row.get("source_file") or "").strip()
        raw_issue_index = _load_raw_issue_index_cached(source_file, cache=raw_issue_cache)
        if raw_issue_index is None:
            invalid_bug_related_issue_duration_count += 1
            continue
        raw_record = resolve_raw_issue_record(raw_issue_index, row)
        if raw_record is None:
            invalid_bug_related_issue_duration_count += 1
            continue
        created_at = raw_record.get("createdAt")
        closed_at = raw_record.get("closedAt")
        days = duration_days(created_at, closed_at)
        if days is None:
            invalid_bug_related_issue_duration_count += 1
            continue
        bug_related_issue_resolution_days.append(days)

    median_bug_issue_resolution_time_days = (
        median(bug_related_issue_resolution_days) if bug_related_issue_resolution_days else None
    )
    return {
        "issue_source_file": source_files,
        "total_closed_issues_in_window_considered": total_closed_issues_in_window_considered,
        "bug_related_issue_count": bug_related_issue_count,
        "bug_related_issue_duration_count": len(bug_related_issue_resolution_days),
        "invalid_bug_related_issue_duration_count": invalid_bug_related_issue_duration_count,
        "median_bug_issue_resolution_time_days": median_bug_issue_resolution_time_days,
    }


def build_repository_metrics(
    *,
    classified_commits_path: str | Path,
    classified_issues_path: str | Path,
    sample_manifest_path: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate repository-level metrics from classified commit and issue data.

    Issue resolution time is measured in days as (closed_at - created_at) / 86400.
    """

    active_manifest_path = Path(sample_manifest_path)
    input_kind = infer_aggregation_input_kind(active_manifest_path)

    ordered_repositories, manifest_index = load_manifest_index(active_manifest_path)
    classified_commit_rows = load_csv_rows(classified_commits_path)
    classified_issue_rows = load_csv_rows(classified_issues_path)

    eligible_for_rq1 = set(ordered_repositories)
    eligible_for_rq2 = set(ordered_repositories)

    commit_rows_by_repository: dict[str, list[dict[str, Any]]] = defaultdict(list)
    issue_rows_by_repository: dict[str, list[dict[str, Any]]] = defaultdict(list)
    commit_rows_excluded_by_gate = 0
    issue_rows_excluded_by_gate = 0

    for row in classified_commit_rows:
        repository_full_name = repo_full_name_from_row(row)
        if repository_full_name in eligible_for_rq1:
            commit_rows_by_repository[repository_full_name].append(row)
        else:
            commit_rows_excluded_by_gate += 1

    for row in classified_issue_rows:
        repository_full_name = repo_full_name_from_row(row)
        if repository_full_name in eligible_for_rq2:
            issue_rows_by_repository[repository_full_name].append(row)
        else:
            issue_rows_excluded_by_gate += 1

    rows: list[dict[str, Any]] = []
    commit_rows_used_total = 0
    issue_rows_used_total = 0
    rq1_aggregated_repositories: list[str] = []
    rq2_aggregated_repositories: list[str] = []
    repositories_missing_commit_rows: list[str] = []
    repositories_missing_issue_rows: list[str] = []
    invalid_bug_related_issue_duration_rows_total = 0
    raw_issue_cache: dict[str, dict[str, Any]] = {}

    for repository_full_name in ordered_repositories:
        manifest_row = manifest_index[repository_full_name]
        language_group = manifest_row.get("language_group")
        eligible_rq1 = True
        eligible_rq2 = True

        commit_rows = commit_rows_by_repository.get(repository_full_name, [])
        issue_rows = issue_rows_by_repository.get(repository_full_name, [])

        row: dict[str, Any] = {
            "repository_full_name": repository_full_name,
            "language_group": language_group,
            "eligible_for_rq1": eligible_rq1,
            "eligible_for_rq2": eligible_rq2,
            "sample_manifest_file": str(active_manifest_path),
            "commit_source_file": "",
            "issue_source_file": "",
            "total_commits_in_window": None,
            "bug_fix_commit_count": None,
            "bug_fix_commit_ratio": None,
            "total_closed_issues_in_window_considered": None,
            "bug_related_issue_count": None,
            "bug_related_issue_duration_count": None,
            "invalid_bug_related_issue_duration_count": None,
            "median_bug_issue_resolution_time_days": None,
        }

        if eligible_rq1:
            commit_metrics = _collect_commit_metrics(commit_rows)
            row.update(commit_metrics)
            commit_rows_used_total += len(commit_rows)
            if not commit_rows:
                repositories_missing_commit_rows.append(repository_full_name)
            else:
                rq1_aggregated_repositories.append(repository_full_name)

        if eligible_rq2:
            issue_metrics = _collect_issue_metrics(issue_rows, raw_issue_cache=raw_issue_cache)
            row.update(issue_metrics)
            issue_rows_used_total += len(issue_rows)
            invalid_bug_related_issue_duration_rows_total += int(
                issue_metrics["invalid_bug_related_issue_duration_count"] or 0
            )
            if not issue_rows:
                repositories_missing_issue_rows.append(repository_full_name)
            else:
                rq2_aggregated_repositories.append(repository_full_name)

        rows.append(row)

    summary = {
        "aggregation_type": "repository_metrics",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "duration_unit": "days",
        "aggregation_input_file": str(active_manifest_path),
        "aggregation_input_kind": input_kind,
        "classified_commits_file": str(classified_commits_path),
        "classified_issues_file": str(classified_issues_path),
        "repositories_seen_in_manifest": len(ordered_repositories),
        "repositories_eligible_for_rq1": len(eligible_for_rq1),
        "repositories_eligible_for_rq2": len(eligible_for_rq2),
        "repositories_aggregated_for_rq1": rq1_aggregated_repositories,
        "repositories_aggregated_for_rq2": rq2_aggregated_repositories,
        "repositories_aggregated_for_rq1_count": len(rq1_aggregated_repositories),
        "repositories_aggregated_for_rq2_count": len(rq2_aggregated_repositories),
        "commit_rows_used_total": commit_rows_used_total,
        "issue_rows_used_total": issue_rows_used_total,
        "invalid_bug_related_issue_duration_rows_total": invalid_bug_related_issue_duration_rows_total,
        "repositories_missing_commit_rows": repositories_missing_commit_rows,
        "repositories_missing_issue_rows": repositories_missing_issue_rows,
        "output_record_count": len(rows),
    }
    summary.update(
        {
            "sample_manifest_file": str(active_manifest_path),
            "repositories_seen_in_sample_manifest": len(ordered_repositories),
            "commit_rows_excluded_by_sample_manifest": commit_rows_excluded_by_gate,
            "issue_rows_excluded_by_sample_manifest": issue_rows_excluded_by_gate,
        }
    )
    return rows, summary
