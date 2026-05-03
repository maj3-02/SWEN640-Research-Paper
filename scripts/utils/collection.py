from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def infer_sample_run_type(sample_file: str | Path) -> str:
    path = Path(sample_file)
    normalized_parts = {part.lower() for part in path.parts}
    filename = path.name.lower()
    if filename == "final_sample.csv" and "final_sample" in normalized_parts:
        return "final_study"
    return "custom"


def build_sample_provenance(sample_file: str | Path) -> dict[str, Any]:
    return {
        "sample_file": str(sample_file),
        "sample_run_type": infer_sample_run_type(sample_file),
    }


def sample_row_trace(row: dict[str, Any]) -> dict[str, Any]:
    trace_fields = [
        "source_file",
        "source_record_index",
        "enrichment_input_file",
        "enrichment_input_record_index",
        "final_sampling_input_file",
        "final_sampling_input_record_index",
        "final_sampling_stage",
        "final_sampling_role",
        "activity_field_used",
        "activity_value",
        "activity_stratum",
        "activity_stratum_rank",
        "activity_rank_within_stratum",
    ]
    return {field: row.get(field) for field in trace_fields if field in row}


def load_sampled_repositories(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    repositories: list[dict[str, Any]] = []
    seen_full_names: set[str] = set()
    for row in rows:
        full_name = extract_repository_full_name(row)
        if full_name in seen_full_names:
            continue
        seen_full_names.add(full_name)
        repositories.append(row)

    return repositories


def extract_repository_full_name(row: dict[str, Any]) -> str:
    full_name = row.get("full_name") or row.get("repository_full_name") or row.get("repo_full_name")
    if not full_name:
        raise ValueError(f"Sampled repository row is missing a repository full name: {row!r}")
    normalized = str(full_name).strip()
    if "/" not in normalized:
        raise ValueError(f"Invalid repository full name {full_name!r}; expected owner/name format.")
    return normalized


def repository_slug(full_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", full_name.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    if not slug:
        raise ValueError(f"Unable to derive a slug from repository full name {full_name!r}.")
    return slug


def repository_artifact_path(output_dir: str | Path, full_name: str, suffix: str) -> Path:
    return Path(output_dir) / f"{repository_slug(full_name)}_{suffix}"


def parse_iso_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("Timestamp value is empty.")
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def study_window_bounds(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    start = datetime.fromisoformat(f"{start_date}T00:00:00+00:00")
    end = datetime.fromisoformat(f"{end_date}T23:59:59+00:00")
    return start, end


def timestamp_inclusive_window(value: str | None, start: datetime, end: datetime) -> bool:
    if not value:
        return False
    parsed = parse_iso_datetime(value)
    return start <= parsed <= end


def commit_window_timestamp(commit: dict[str, Any]) -> str | None:
    commit_payload = commit.get("commit") or {}
    author = commit_payload.get("author") or {}
    committer = commit_payload.get("committer") or {}
    timestamp = author.get("date") or committer.get("date")
    if not timestamp:
        return None
    normalized = str(timestamp).strip()
    return normalized or None


def commit_in_window(commit: dict[str, Any], start: datetime, end: datetime) -> bool:
    return timestamp_inclusive_window(commit_window_timestamp(commit), start, end)


def issue_is_pull_request(issue: dict[str, Any]) -> bool:
    return issue.get("pull_request") is not None


def build_collection_failure_record(
    *,
    stage: str,
    repository_full_name: str,
    error: Exception,
    retries_attempted: int,
    language_group: str | None = None,
    pagination_mode: str | None = None,
    sample_row_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attempts = getattr(error, "attempts", None)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "repository_full_name": repository_full_name,
        "language_group": language_group,
        "error_type": error.__class__.__name__,
        "message": str(error),
        "status_code": getattr(error, "status_code", None),
        "retryable": getattr(error, "retryable", None),
        "attempts": attempts,
        "retries_attempted": retries_attempted,
        "retry_after_seconds": getattr(error, "retry_after_seconds", None),
        "pagination_mode": pagination_mode,
        "sample_row_trace": sample_row_trace or {},
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
