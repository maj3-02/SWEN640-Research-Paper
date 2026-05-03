from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json_payload(path: str | Path) -> dict[str, Any]:
    payload_path = Path(path)
    with payload_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {payload_path}")
    return payload


def extract_repository_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    repositories = payload.get("repositories")
    if isinstance(repositories, list):
        return [record for record in repositories if isinstance(record, dict)]

    extracted: list[dict[str, Any]] = []
    pages = payload.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            items = page.get("items")
            if not isinstance(items, list):
                continue
            extracted.extend([record for record in items if isinstance(record, dict)])
    return extracted


def repository_key(record: dict[str, Any]) -> str | None:
    repo_id = record.get("id")
    full_name = record.get("full_name")
    if repo_id is not None:
        return str(repo_id)
    if full_name:
        return str(full_name)
    return None


def deduplicate_records(
    records: list[dict[str, Any]],
) -> tuple[list[tuple[int, dict[str, Any]]], list[tuple[int, dict[str, Any]]]]:
    seen: OrderedDict[str, dict[str, Any]] = OrderedDict()
    original_indices: dict[str, int] = {}
    duplicate_records: list[tuple[int, dict[str, Any]]] = []
    for index, record in enumerate(records):
        key = repository_key(record)
        if key is None:
            continue
        if key in seen:
            duplicate_records.append((index, record))
            continue
        seen[key] = record
        original_indices[key] = index
    ordered_unique_records = [(original_indices[repository_key(record) or ""], record) for record in seen.values()]
    ordered_unique_records.sort(key=lambda item: item[0])
    return ordered_unique_records, duplicate_records


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(item) for item in value if item is not None)
    return str(value)


def detect_manual_review_matches(record: dict[str, Any], cues: list[str]) -> list[dict[str, str]]:
    fields = {
        "name": normalize_text(record.get("name")),
        "full_name": normalize_text(record.get("full_name")),
        "description": normalize_text(record.get("description")),
    }
    topics = record.get("topics")
    if topics:
        fields["topics"] = normalize_text(topics)

    matches: list[dict[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for cue in cues:
        pattern = re.compile(rf"\b{re.escape(cue)}\b", flags=re.IGNORECASE)
        for field_name, field_value in fields.items():
            if not field_value:
                continue
            if pattern.search(field_value):
                pair = (cue, field_name)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                matches.append({"matched_cue": cue, "matched_field": field_name})
    return matches


def classify_repository_record(
    record: Any,
    *,
    expected_language: str,
) -> tuple[str | None, str | None]:
    if not isinstance(record, dict):
        return "invalid_record", "record is not a JSON object"

    if repository_key(record) is None:
        return "invalid_record", "missing id/full_name"

    if record.get("private") is True:
        return "private_repository", "private field is true"

    if record.get("archived") is True:
        return "archived", "archived field is true"

    if record.get("fork") is True:
        return "fork", "fork field is true"

    if record.get("has_issues") is False:
        return "issues_disabled", "has_issues field is false"

    language = record.get("language")
    if isinstance(language, str) and language and language != expected_language:
        return "language_group_mismatch", f"expected {expected_language!r} but got {language!r}"

    return None, None


def can_validate_language_threshold(payload: dict[str, Any]) -> bool:
    supported_keys = ("language_stats", "language_statistics", "language_breakdown")
    for key in supported_keys:
        value = payload.get(key)
        if isinstance(value, dict) and value:
            return True
    return False


def build_filtered_candidate_row(
    record: dict[str, Any],
    *,
    language_group: str,
    manual_review_matches: list[dict[str, str]],
    source_file: str,
    source_record_index: int | None,
) -> dict[str, Any]:
    owner = record.get("owner") or {}
    license_info = record.get("license") or {}
    return {
        "language_group": language_group,
        "manual_review_flag": bool(manual_review_matches),
        "manual_review_cues": "; ".join(sorted({match["matched_cue"] for match in manual_review_matches})),
        "manual_review_fields": "; ".join(sorted({match["matched_field"] for match in manual_review_matches})),
        "id": record.get("id"),
        "node_id": record.get("node_id"),
        "name": record.get("name"),
        "full_name": record.get("full_name"),
        "html_url": record.get("html_url"),
        "description": record.get("description"),
        "language": record.get("language"),
        "stargazers_count": record.get("stargazers_count"),
        "watchers_count": record.get("watchers_count"),
        "forks_count": record.get("forks_count"),
        "open_issues_count": record.get("open_issues_count"),
        "archived": record.get("archived"),
        "fork": record.get("fork"),
        "has_issues": record.get("has_issues"),
        "private": record.get("private"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "pushed_at": record.get("pushed_at"),
        "default_branch": record.get("default_branch"),
        "owner_login": owner.get("login"),
        "owner_type": owner.get("type"),
        "license_spdx_id": license_info.get("spdx_id"),
        "source_file": source_file,
        "source_record_index": source_record_index,
    }


def build_exclusion_log_row(
    record: Any,
    *,
    language_group: str,
    exclusion_reason_code: str,
    exclusion_reason_detail: str,
    source_file: str,
    source_record_index: int | None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    if isinstance(record, dict):
        repo_id = record.get("id")
        full_name = record.get("full_name")
    else:
        repo_id = None
        full_name = None
    return {
        "timestamp": timestamp,
        "language_group": language_group,
        "repository_id": repo_id,
        "repository_full_name": full_name,
        "exclusion_reason_code": exclusion_reason_code,
        "exclusion_reason_detail": exclusion_reason_detail,
        "source_file": source_file,
        "source_record_index": source_record_index,
    }


def build_manual_review_row(
    record: dict[str, Any],
    *,
    language_group: str,
    manual_review_matches: list[dict[str, str]],
    source_file: str,
    source_record_index: int | None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    return {
        "timestamp": timestamp,
        "language_group": language_group,
        "repository_id": record.get("id"),
        "repository_full_name": record.get("full_name"),
        "matched_cues": "; ".join(sorted({match["matched_cue"] for match in manual_review_matches})),
        "matched_fields": "; ".join(sorted({match["matched_field"] for match in manual_review_matches})),
        "current_inclusion_status": "retained_for_manual_review",
        "review_note": "",
        "source_file": source_file,
        "source_record_index": source_record_index,
    }
