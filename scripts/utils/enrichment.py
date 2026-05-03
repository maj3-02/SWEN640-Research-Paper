from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from scripts.utils.collection import study_window_bounds, timestamp_inclusive_window


def parse_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def normalize_language_bytes(language_bytes: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(language_bytes, Mapping):
        return {}

    normalized: dict[str, int] = {}
    for language, byte_count in language_bytes.items():
        language_name = str(language).strip()
        parsed_count = parse_count(byte_count)
        if not language_name or parsed_count is None:
            continue
        normalized[language_name] = parsed_count
    return normalized


def total_language_bytes(language_bytes: Mapping[str, Any] | None) -> int:
    return sum(normalize_language_bytes(language_bytes).values())


def target_language_bytes(language_bytes: Mapping[str, Any] | None, target_language: str) -> int:
    normalized = normalize_language_bytes(language_bytes)
    target = target_language.strip().lower()
    for language, byte_count in normalized.items():
        if language.lower() == target:
            return byte_count
    return 0


def language_share(language_bytes: Mapping[str, Any] | None, target_language: str) -> float | None:
    total_bytes = total_language_bytes(language_bytes)
    if total_bytes <= 0:
        return None
    return target_language_bytes(language_bytes, target_language) / total_bytes


def passes_language_threshold(
    language_bytes: Mapping[str, Any] | None,
    *,
    target_language: str,
    threshold: float,
) -> bool:
    share = language_share(language_bytes, target_language)
    return share is not None and share >= threshold


def parse_graphql_total_count(connection_payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(connection_payload, Mapping):
        return None
    return parse_count(connection_payload.get("totalCount"))


def parse_default_branch_commit_count(graphql_payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(graphql_payload, Mapping):
        return None
    data = graphql_payload.get("data")
    if not isinstance(data, Mapping):
        return None
    repository = data.get("repository")
    if not isinstance(repository, Mapping):
        return None
    default_branch_ref = repository.get("defaultBranchRef")
    if not isinstance(default_branch_ref, Mapping):
        return None
    target = default_branch_ref.get("target")
    if not isinstance(target, Mapping):
        return None
    return parse_graphql_total_count(target.get("history"))


def count_closed_issue_nodes_in_window(
    issue_nodes: list[Mapping[str, Any]] | Any,
    *,
    study_window_start: str,
    study_window_end: str,
) -> dict[str, int]:
    if not isinstance(issue_nodes, list):
        return {
            "raw_issue_count": 0,
            "closed_issue_count_in_window": 0,
            "missing_closed_at_count": 0,
            "outside_window_count": 0,
        }

    start_dt, end_dt = study_window_bounds(study_window_start, study_window_end)
    closed_issue_count = 0
    missing_closed_at_count = 0
    outside_window_count = 0

    for issue in issue_nodes:
        if not isinstance(issue, Mapping):
            continue
        closed_at = issue.get("closedAt")
        if not closed_at:
            missing_closed_at_count += 1
            continue
        try:
            in_window = timestamp_inclusive_window(str(closed_at), start_dt, end_dt)
        except ValueError:
            missing_closed_at_count += 1
            continue
        if in_window:
            closed_issue_count += 1
        else:
            outside_window_count += 1

    return {
        "raw_issue_count": len(issue_nodes),
        "closed_issue_count_in_window": closed_issue_count,
        "missing_closed_at_count": missing_closed_at_count,
        "outside_window_count": outside_window_count,
    }


def serialize_language_stats(language_bytes: Mapping[str, Any] | None) -> str:
    return json.dumps(normalize_language_bytes(language_bytes), sort_keys=True, separators=(",", ":"))


def serialize_enrichment_row(row: Mapping[str, Any]) -> dict[str, Any]:
    serialized = dict(row)
    serialized["language_stats"] = serialize_language_stats(row.get("language_stats"))
    return serialized


def _candidate_repository_full_name(candidate_row: Mapping[str, Any]) -> str:
    return str(
        candidate_row.get("full_name")
        or candidate_row.get("repository_full_name")
        or ""
    ).strip()


def build_enrichment_result_row(
    candidate_row: Mapping[str, Any],
    *,
    language_bytes: Mapping[str, Any] | None,
    target_language: str,
    language_threshold: float,
    default_branch_commit_count: Any,
    closed_issue_count: Any = None,
    enrichment_status: str = "enriched",
) -> dict[str, Any]:
    normalized_languages = normalize_language_bytes(language_bytes)
    total_bytes = sum(normalized_languages.values())
    target_bytes = target_language_bytes(normalized_languages, target_language)
    share = language_share(normalized_languages, target_language)
    commit_count = parse_count(default_branch_commit_count)
    issue_count = parse_count(closed_issue_count)

    row = dict(candidate_row)
    row.update(
        {
            "repository_full_name": _candidate_repository_full_name(candidate_row),
            "language_group": candidate_row.get("language_group") or target_language,
            "target_language": target_language,
            "language_stats": normalized_languages,
            "target_language_bytes": target_bytes,
            "total_language_bytes": total_bytes,
            "target_language_share": share,
            "language_threshold": language_threshold,
            "language_threshold_pass": share is not None and share >= language_threshold,
            "default_branch_commit_count_in_window": commit_count,
            "closed_issue_count_in_window": issue_count,
            "closed_issue_count_available": issue_count is not None,
            "enrichment_status": enrichment_status,
            "enrichment_failure_reason": "",
        }
    )
    return row


def build_enrichment_failure_record(
    *,
    candidate_row: Mapping[str, Any],
    stage: str,
    error: Exception,
    target_language: str | None = None,
) -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "repository_full_name": _candidate_repository_full_name(candidate_row),
        "language_group": candidate_row.get("language_group"),
        "target_language": target_language or candidate_row.get("language_group"),
        "error_type": getattr(error, "error_type", error.__class__.__name__),
        "message": str(error),
        "status_code": getattr(error, "status_code", None),
        "retryable": getattr(error, "retryable", None),
        "attempts": getattr(error, "attempts", None),
        "source_file": candidate_row.get("source_file"),
        "source_record_index": candidate_row.get("source_record_index"),
        "enrichment_input_file": candidate_row.get("enrichment_input_file"),
        "enrichment_input_record_index": candidate_row.get("enrichment_input_record_index"),
    }


def build_enrichment_summary(
    *,
    input_files: list[str],
    output_files: Mapping[str, str],
    result_rows: list[Mapping[str, Any]],
    failure_records: list[Mapping[str, Any]],
    language_threshold: float,
) -> dict[str, Any]:
    enriched_count = sum(1 for row in result_rows if row.get("enrichment_status") == "enriched")
    threshold_pass_count = sum(1 for row in result_rows if row.get("language_threshold_pass") is True)
    issue_count_available_count = sum(1 for row in result_rows if row.get("closed_issue_count_available") is True)

    counts_by_language: dict[str, int] = {}
    threshold_pass_by_language: dict[str, int] = {}
    for row in result_rows:
        language = str(row.get("language_group") or row.get("target_language") or "").strip()
        if not language:
            continue
        counts_by_language[language] = counts_by_language.get(language, 0) + 1
        if row.get("language_threshold_pass") is True:
            threshold_pass_by_language[language] = threshold_pass_by_language.get(language, 0) + 1

    return {
        "enrichment_type": "final_candidate_enrichment",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "final_sample_only",
        "input_files": input_files,
        "output_files": dict(output_files),
        "language_threshold": language_threshold,
        "repositories_seen": len(result_rows) + len(failure_records),
        "repositories_enriched": enriched_count,
        "repositories_failed": len(failure_records),
        "language_threshold_pass_count": threshold_pass_count,
        "closed_issue_count_available_count": issue_count_available_count,
        "counts_by_language": counts_by_language,
        "language_threshold_pass_by_language": threshold_pass_by_language,
        "failure_count": len(failure_records),
    }
