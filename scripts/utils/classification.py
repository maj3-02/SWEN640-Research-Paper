from __future__ import annotations

import csv
import json
import random
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from scripts.utils.collection import commit_window_timestamp


SAMPLE_MANIFEST_FILENAME = "final_sample.csv"


def infer_classification_input_kind(manifest_file: str | Path) -> str:
    filename = Path(manifest_file).name.lower()
    if filename == SAMPLE_MANIFEST_FILENAME:
        return "sample_manifest"
    return "custom_manifest"


def infer_classification_run_type(manifest_file: str | Path) -> str:
    path = Path(manifest_file)
    normalized_parts = {part.lower() for part in path.parts}
    filename = path.name.lower()
    if filename == SAMPLE_MANIFEST_FILENAME and "final_sample" in normalized_parts:
        return "final_study"
    return "custom"


def build_classification_run_provenance(manifest_file: str | Path) -> dict[str, Any]:
    input_kind = infer_classification_input_kind(manifest_file)
    provenance = {
        "classification_input_file": str(manifest_file),
        "classification_input_kind": input_kind,
        "classification_run_type": infer_classification_run_type(manifest_file),
    }
    if input_kind == "sample_manifest":
        provenance["sample_manifest_file"] = str(manifest_file)
    return provenance


def sample_manifest_row_trace(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_source_file": row.get("final_sampling_input_file") or row.get("sample_source_file", ""),
        "sample_source_record_index": row.get("final_sampling_input_record_index")
        or row.get("sample_source_record_index", ""),
        "sample_role": row.get("final_sampling_role") or row.get("sample_role", ""),
        "sample_activity_stratum": row.get("activity_stratum", ""),
        "sample_activity_value": row.get("default_branch_commit_count_in_window")
        or row.get("activity_value", ""),
    }


def load_json(path: str | Path) -> dict[str, Any]:
    json_path = Path(path)
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {json_path}")
    return payload


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_csv(path: str | Path, rows: list[dict[str, Any]], *, fieldnames: list[str]) -> None:
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        limit = 10**9
        while True:
            try:
                csv.field_size_limit(limit)
                break
            except OverflowError:
                limit = max(limit // 10, 1024)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized in {"true", "1", "yes", "y"}


def row_lookup(rows: list[dict[str, Any]], *, key_field: str) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get(key_field) or "").strip()
        if key:
            lookup[key] = row
    return lookup


@lru_cache(maxsize=None)
def compile_term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def match_terms(text: str | None, terms: Sequence[str]) -> list[str]:
    haystack = text or ""
    matches: list[str] = []
    for term in terms:
        if compile_term_pattern(term).search(haystack):
            matches.append(term)
    return unique_preserve_order(matches)


def match_terms_in_values(values: Iterable[str | None], terms: Sequence[str]) -> list[str]:
    matches: list[str] = []
    for term in terms:
        pattern = compile_term_pattern(term)
        for value in values:
            if value and pattern.search(value):
                matches.append(term)
                break
    return unique_preserve_order(matches)


def join_terms(values: Iterable[str]) -> str:
    return ";".join(unique_preserve_order([value for value in values if value]))


def sample_rows(rows: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    if count <= 0 or not rows:
        return []
    if count >= len(rows):
        return list(rows)
    rng = random.Random(seed)
    indexes = sorted(rng.sample(range(len(rows)), count))
    return [rows[index] for index in indexes]


def _commit_row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("repository_full_name") or ""),
        str(row.get("commit_sha") or ""),
        str(row.get("source_file") or ""),
        str(row.get("raw_record_index") or ""),
    )


def _issue_row_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("repository_full_name") or ""),
        str(row.get("issue_id") or row.get("issue_number") or ""),
        str(row.get("source_file") or ""),
        str(row.get("raw_record_index") or ""),
    )


def load_sample_manifest_rows(path: str | Path) -> list[dict[str, Any]]:
    return load_csv_rows(path)


def classify_commit_record(
    commit: dict[str, Any],
    *,
    repository_full_name: str,
    language_group: str | None,
    source_file: str,
    record_index: int,
    required_terms: Sequence[str],
    additional_terms: Sequence[str],
) -> dict[str, Any]:
    message = str(((commit.get("commit") or {}).get("message")) or "")
    required_matches = match_terms(message, required_terms)
    additional_matches = match_terms(message, additional_terms)
    provisional_issue_term_used = "issue" in additional_matches
    is_bug_fix = bool(required_matches and additional_matches)

    if is_bug_fix:
        classification_reason = "required_and_additional_term_match"
    elif required_matches and not additional_matches:
        classification_reason = "required_term_without_additional_term"
    elif additional_matches and not required_matches:
        classification_reason = "additional_term_without_required_term"
    else:
        classification_reason = "no_bug_fix_terms"

    author = (commit.get("commit") or {}).get("author") or {}
    committer = (commit.get("commit") or {}).get("committer") or {}
    top_level_author = commit.get("author") or {}

    return {
        "repository_full_name": repository_full_name,
        "language_group": language_group,
        "commit_sha": commit.get("sha"),
        "commit_message": message,
        "commit_date": commit_window_timestamp(commit),
        "commit_author_login": top_level_author.get("login"),
        "commit_author_name": author.get("name"),
        "commit_author_email": author.get("email"),
        "commit_committer_name": committer.get("name"),
        "commit_committer_email": committer.get("email"),
        "is_bug_fix": is_bug_fix,
        "matched_required_term": required_matches[0] if required_matches else "",
        "matched_additional_terms": join_terms(additional_matches),
        "provisional_issue_term_used": provisional_issue_term_used,
        "provisional_issue_term_matched": "issue" if provisional_issue_term_used else "",
        "classification_reason": classification_reason,
        "source_file": source_file,
        "raw_record_index": record_index,
    }


def extract_issue_label_names(issue: dict[str, Any]) -> list[str]:
    labels = issue.get("labels") or []
    label_names: list[str] = []
    if isinstance(labels, dict):
        nodes = labels.get("nodes") or []
        for label in nodes:
            if isinstance(label, dict):
                name = str(label.get("name") or "").strip()
                if name:
                    label_names.append(name)
    elif isinstance(labels, list):
        for label in labels:
            if isinstance(label, dict):
                name = str(label.get("name") or "").strip()
                if name:
                    label_names.append(name)
            elif label:
                label_names.append(str(label).strip())
    return unique_preserve_order([name for name in label_names if name])


def classify_issue_record(
    issue: dict[str, Any],
    *,
    repository_full_name: str,
    language_group: str | None,
    source_file: str,
    record_index: int,
    label_terms: Sequence[str],
    text_terms: Sequence[str],
) -> dict[str, Any]:
    title = str(issue.get("title") or "")
    body = str(issue.get("body") or "")
    label_names = extract_issue_label_names(issue)

    label_matches = match_terms_in_values(label_names, label_terms)
    title_matches = match_terms(title, text_terms)
    body_matches = match_terms(body, text_terms)
    text_matches = unique_preserve_order(title_matches + body_matches)

    match_sources: list[str] = []
    if label_matches:
        match_sources.append("label")
    if title_matches:
        match_sources.append("title")
    if body_matches:
        match_sources.append("body")

    is_bug_related = bool(label_matches or text_matches)
    if label_matches and text_matches:
        classification_reason = "label_and_text_match"
    elif label_matches:
        classification_reason = "label_match"
    elif text_matches:
        classification_reason = "text_match"
    else:
        classification_reason = "no_bug_terms"

    author = issue.get("author") or {}

    return {
        "repository_full_name": repository_full_name,
        "language_group": language_group,
        "issue_id": issue.get("id"),
        "issue_number": issue.get("number"),
        "issue_url": issue.get("url"),
        "title": title,
        "body": body,
        "state": issue.get("state"),
        "closed_at": issue.get("closedAt"),
        "issue_author_login": author.get("login"),
        "label_names": join_terms(label_names),
        "is_bug_related": is_bug_related,
        "matched_label_terms": join_terms(label_matches),
        "matched_text_terms": join_terms(text_matches),
        "match_source": join_terms(match_sources),
        "classification_reason": classification_reason,
        "source_file": source_file,
        "raw_record_index": record_index,
    }


def build_commit_validation_sample_rows(
    classified_rows: list[dict[str, Any]],
    *,
    sample_size: int = 20,
    positive_target: int = 10,
    seed: int = 640,
) -> list[dict[str, Any]]:
    positive_rows = [row for row in classified_rows if parse_bool(row.get("is_bug_fix"))]
    provisional_positive_rows = [row for row in positive_rows if parse_bool(row.get("provisional_issue_term_used"))]
    standard_positive_rows = [row for row in positive_rows if not parse_bool(row.get("provisional_issue_term_used"))]
    borderline_rows = [
        row
        for row in classified_rows
        if not parse_bool(row.get("is_bug_fix"))
        and (row.get("matched_required_term") or row.get("matched_additional_terms"))
    ]
    control_rows = [
        row
        for row in classified_rows
        if not parse_bool(row.get("is_bug_fix"))
        and not (row.get("matched_required_term") or row.get("matched_additional_terms"))
    ]

    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str, str]] = set()
    provisional_sample = sample_rows(provisional_positive_rows, min(5, positive_target), seed + 1)
    for row in provisional_sample:
        annotated = dict(row)
        annotated["validation_sample_category"] = "positive_provisional"
        annotated["validation_sample_reason"] = "bug-fix positive with provisional issue term evidence"
        selected.append(annotated)
        selected_keys.add(_commit_row_key(row))

    remaining_positive_target = positive_target - len(provisional_sample)
    standard_pool = [row for row in standard_positive_rows if _commit_row_key(row) not in selected_keys]
    standard_sample = sample_rows(standard_pool, remaining_positive_target, seed + 2)
    for row in standard_sample:
        annotated = dict(row)
        annotated["validation_sample_category"] = "positive_standard"
        annotated["validation_sample_reason"] = "bug-fix positive without provisional issue term"
        selected.append(annotated)
        selected_keys.add(_commit_row_key(row))

    if len(selected) < positive_target:
        positive_pool = [row for row in positive_rows if _commit_row_key(row) not in selected_keys]
        filler_positive = sample_rows(positive_pool, positive_target - len(selected), seed + 3)
        for row in filler_positive:
            annotated = dict(row)
            annotated["validation_sample_category"] = "positive_standard"
            annotated["validation_sample_reason"] = "bug-fix positive"
            selected.append(annotated)
            selected_keys.add(_commit_row_key(row))

    remaining_target = sample_size - len(selected)
    borderline_pool = [row for row in borderline_rows if _commit_row_key(row) not in selected_keys]
    borderline_sample = sample_rows(borderline_pool, min(remaining_target, len(borderline_pool)), seed + 4)
    for row in borderline_sample:
        annotated = dict(row)
        annotated["validation_sample_category"] = "borderline_keyword"
        annotated["validation_sample_reason"] = "near-miss commit with keyword evidence but not enough for bug-fix classification"
        selected.append(annotated)
        selected_keys.add(_commit_row_key(row))

    remaining_target = sample_size - len(selected)
    if remaining_target > 0:
        control_pool = [row for row in control_rows if _commit_row_key(row) not in selected_keys]
        control_sample = sample_rows(control_pool, min(remaining_target, len(control_pool)), seed + 5)
        for row in control_sample:
            annotated = dict(row)
            annotated["validation_sample_category"] = "control_negative"
            annotated["validation_sample_reason"] = "negative control commit"
            selected.append(annotated)
            selected_keys.add(_commit_row_key(row))

    if len(selected) < sample_size:
        remaining_rows = [row for row in classified_rows if _commit_row_key(row) not in selected_keys]
        filler = sample_rows(remaining_rows, sample_size - len(selected), seed + 6)
        for row in filler:
            annotated = dict(row)
            annotated["validation_sample_category"] = "control_negative"
            annotated["validation_sample_reason"] = "filled to reach validation sample size"
            selected.append(annotated)
            selected_keys.add(_commit_row_key(row))

    return selected[:sample_size]


def build_issue_validation_sample_rows(
    classified_rows: list[dict[str, Any]],
    *,
    sample_size: int = 20,
    positive_target: int = 10,
    seed: int = 640,
) -> list[dict[str, Any]]:
    positive_rows = [row for row in classified_rows if parse_bool(row.get("is_bug_related"))]
    label_only_rows = [
        row
        for row in positive_rows
        if row.get("matched_label_terms") and not row.get("matched_text_terms")
    ]
    text_only_rows = [
        row
        for row in positive_rows
        if row.get("matched_text_terms") and not row.get("matched_label_terms")
    ]
    label_and_text_rows = [
        row
        for row in positive_rows
        if row.get("matched_label_terms") and row.get("matched_text_terms")
    ]
    control_rows = [row for row in classified_rows if not parse_bool(row.get("is_bug_related"))]

    selected: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str, str, str]] = set()

    label_sample = sample_rows(label_only_rows, min(4, positive_target), seed + 1)
    for row in label_sample:
        annotated = dict(row)
        annotated["validation_sample_category"] = "positive_label_only"
        annotated["validation_sample_reason"] = "bug-related issue matched by label only"
        selected.append(annotated)
        selected_keys.add(_issue_row_key(row))

    remaining_positive_target = positive_target - len(label_sample)
    text_pool = [row for row in text_only_rows if _issue_row_key(row) not in selected_keys]
    text_sample = sample_rows(text_pool, min(4, remaining_positive_target), seed + 2)
    for row in text_sample:
        annotated = dict(row)
        annotated["validation_sample_category"] = "positive_text_only"
        annotated["validation_sample_reason"] = "bug-related issue matched by title/body text only"
        selected.append(annotated)
        selected_keys.add(_issue_row_key(row))

    remaining_positive_target = positive_target - len(selected)
    label_and_text_pool = [row for row in label_and_text_rows if _issue_row_key(row) not in selected_keys]
    label_and_text_sample = sample_rows(label_and_text_pool, remaining_positive_target, seed + 3)
    for row in label_and_text_sample:
        annotated = dict(row)
        annotated["validation_sample_category"] = "positive_label_and_text"
        annotated["validation_sample_reason"] = "bug-related issue matched by both label and text"
        selected.append(annotated)
        selected_keys.add(_issue_row_key(row))

    if len(selected) < positive_target:
        positive_pool = [row for row in positive_rows if _issue_row_key(row) not in selected_keys]
        filler_positive = sample_rows(positive_pool, positive_target - len(selected), seed + 4)
        for row in filler_positive:
            annotated = dict(row)
            annotated["validation_sample_category"] = "positive_label_and_text"
            annotated["validation_sample_reason"] = "bug-related issue"
            selected.append(annotated)
            selected_keys.add(_issue_row_key(row))

    remaining_target = sample_size - len(selected)
    if remaining_target > 0:
        control_pool = [row for row in control_rows if _issue_row_key(row) not in selected_keys]
        control_sample = sample_rows(control_pool, min(remaining_target, len(control_pool)), seed + 5)
        for row in control_sample:
            annotated = dict(row)
            annotated["validation_sample_category"] = "control_negative"
            annotated["validation_sample_reason"] = "negative control issue"
            selected.append(annotated)
            selected_keys.add(_issue_row_key(row))

    if len(selected) < sample_size:
        remaining_rows = [row for row in classified_rows if _issue_row_key(row) not in selected_keys]
        filler = sample_rows(remaining_rows, sample_size - len(selected), seed + 6)
        for row in filler:
            annotated = dict(row)
            annotated["validation_sample_category"] = "control_negative"
            annotated["validation_sample_reason"] = "filled to reach validation sample size"
            selected.append(annotated)
            selected_keys.add(_issue_row_key(row))

    return selected[:sample_size]
