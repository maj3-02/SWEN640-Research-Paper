from __future__ import annotations

import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

TEST_DIR_NAMES = {
    "test",
    "tests",
    "spec",
    "specs",
    "__test__",
    "__tests__",
    "cypress",
    "e2e",
    "integration",
    "unit",
}
CI_PATH_PREFIXES = (
    ".github/workflows/",
    ".circleci/",
    ".buildkite/",
)
CI_FILE_NAMES = {
    ".travis.yml",
    "appveyor.yml",
    "azure-pipelines.yml",
    "jenkinsfile",
}
COMMUNITY_FILE_NAMES = {
    "contributing.md",
    "code_of_conduct.md",
    "security.md",
    "support.md",
    "governance.md",
}
COMMUNITY_PATH_PREFIXES = (
    ".github/issue_template/",
    ".github/pull_request_template",
)


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


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


def recent_push_cutoff(study_window_end: str, lookback_days: int) -> date:
    end_date = date.fromisoformat(study_window_end)
    days_back = max(0, lookback_days - 1)
    return end_date - timedelta(days=days_back)


def has_recent_push(pushed_at: Any, *, study_window_end: str, lookback_days: int) -> tuple[bool, str]:
    cutoff = recent_push_cutoff(study_window_end, lookback_days)
    pushed_dt = parse_iso_datetime(pushed_at)
    if pushed_dt is None:
        return False, cutoff.isoformat()
    return pushed_dt.date() >= cutoff, cutoff.isoformat()


def _unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _limit_matches(values: list[str], *, max_items: int = 10) -> list[str]:
    return values[:max_items]


def normalize_tree_paths(tree_payload: dict[str, Any]) -> list[str]:
    tree = tree_payload.get("tree") or []
    paths: list[str] = []
    if not isinstance(tree, list):
        return paths
    for record in tree:
        if not isinstance(record, dict):
            continue
        path = str(record.get("path") or "").strip()
        if path:
            paths.append(path)
    return _unique_preserve_order(paths)


def detect_test_paths(paths: Iterable[str]) -> tuple[bool, list[str]]:
    matches: list[str] = []
    for path in paths:
        lowered = path.lower().strip("/")
        filename = lowered.rsplit("/", 1)[-1]
        parts = lowered.split("/")
        if any(part in TEST_DIR_NAMES for part in parts):
            matches.append(path)
            continue
        if ".test." in filename or ".spec." in filename or filename.endswith("_test.js") or filename.endswith("_test.ts"):
            matches.append(path)
    ordered = _limit_matches(_unique_preserve_order(matches))
    return bool(ordered), ordered


def detect_ci_paths(paths: Iterable[str]) -> tuple[bool, list[str]]:
    matches: list[str] = []
    for path in paths:
        lowered = path.lower().strip("/")
        filename = lowered.rsplit("/", 1)[-1]
        if any(lowered.startswith(prefix) for prefix in CI_PATH_PREFIXES):
            matches.append(path)
            continue
        if filename in CI_FILE_NAMES:
            matches.append(path)
    ordered = _limit_matches(_unique_preserve_order(matches))
    return bool(ordered), ordered


def detect_community_health_paths(paths: Iterable[str]) -> tuple[bool, list[str]]:
    matches: list[str] = []
    for path in paths:
        lowered = path.lower().strip("/")
        filename = lowered.rsplit("/", 1)[-1]
        if filename in COMMUNITY_FILE_NAMES:
            matches.append(path)
            continue
        if any(lowered.startswith(prefix) for prefix in COMMUNITY_PATH_PREFIXES):
            matches.append(path)
    ordered = _limit_matches(_unique_preserve_order(matches))
    return bool(ordered), ordered


def build_quality_signal_snapshot(
    *,
    repository_full_name: str,
    default_branch: str | None,
    tree_payload: dict[str, Any],
) -> dict[str, Any]:
    tree_paths = normalize_tree_paths(tree_payload)
    has_tests, matched_test_paths = detect_test_paths(tree_paths)
    has_ci, matched_ci_paths = detect_ci_paths(tree_paths)
    has_community, matched_community_paths = detect_community_health_paths(tree_paths)
    return {
        "repository_full_name": repository_full_name,
        "default_branch": default_branch,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "tree_sha": tree_payload.get("sha"),
        "tree_truncated": bool(tree_payload.get("truncated")),
        "tree_path_count": len(tree_paths),
        "has_tests": has_tests,
        "matched_test_paths": matched_test_paths,
        "has_ci": has_ci,
        "matched_ci_paths": matched_ci_paths,
        "has_community_health_files": has_community,
        "matched_community_health_paths": matched_community_paths,
    }


def _join_matches(values: list[str]) -> str:
    return ";".join(values)


def evaluate_quality_screen(
    candidate_row: dict[str, Any],
    *,
    signal_snapshot: dict[str, Any],
    study_window_end: str,
    recent_push_lookback_days: int,
    min_open_issues_count: int,
    minimum_score: int,
    signal_snapshot_file: str,
) -> dict[str, Any]:
    row = dict(candidate_row)
    manual_review_flag = parse_bool(row.get("manual_review_flag"))
    not_manual_review_flagged = not manual_review_flag
    recent_maintenance, recent_push_cutoff_date = has_recent_push(
        row.get("pushed_at"),
        study_window_end=study_window_end,
        lookback_days=recent_push_lookback_days,
    )
    open_issues_count = parse_int(row.get("open_issues_count"))
    issue_usage_signal = (open_issues_count or 0) >= min_open_issues_count
    has_tests = bool(signal_snapshot.get("has_tests"))
    has_ci = bool(signal_snapshot.get("has_ci"))
    has_community_health_files = bool(signal_snapshot.get("has_community_health_files"))
    engineering_workflow_signal = has_tests or has_ci or has_community_health_files

    checks = {
        "not_manual_review_flagged": not_manual_review_flagged,
        "recent_maintenance": recent_maintenance,
        "issue_usage": issue_usage_signal,
        "engineering_workflow": engineering_workflow_signal,
    }
    score = sum(1 for passed in checks.values() if passed)
    passed_quality_screen = score >= minimum_score
    failure_reasons = (
        [f"quality_check_failed:{name}" for name, passed in checks.items() if not passed]
        if not passed_quality_screen
        else []
    )

    row.update(
        {
            "quality_screen_status": "screened",
            "quality_screen_intended_use": "final_sample_only",
            "quality_screen_pass": passed_quality_screen,
            "quality_screen_score": score,
            "quality_screen_threshold": minimum_score,
            "quality_screen_failure_reasons": ";".join(failure_reasons),
            "quality_check_not_manual_review_flagged": not_manual_review_flagged,
            "quality_check_recent_maintenance": recent_maintenance,
            "quality_check_issue_usage": issue_usage_signal,
            "quality_check_engineering_workflow": engineering_workflow_signal,
            "quality_recent_push_cutoff_date": recent_push_cutoff_date,
            "quality_open_issues_threshold": min_open_issues_count,
            "quality_signal_has_tests": has_tests,
            "quality_signal_has_ci": has_ci,
            "quality_signal_has_community_health_files": has_community_health_files,
            "quality_signal_matched_test_paths": _join_matches(
                list(signal_snapshot.get("matched_test_paths") or [])
            ),
            "quality_signal_matched_ci_paths": _join_matches(
                list(signal_snapshot.get("matched_ci_paths") or [])
            ),
            "quality_signal_matched_community_health_paths": _join_matches(
                list(signal_snapshot.get("matched_community_health_paths") or [])
            ),
            "quality_tree_truncated": bool(signal_snapshot.get("tree_truncated")),
            "quality_tree_path_count": signal_snapshot.get("tree_path_count"),
            "quality_signal_snapshot_file": signal_snapshot_file,
        }
    )
    return row


def build_quality_screen_failure_result(
    candidate_row: dict[str, Any],
    *,
    error: Exception,
    study_window_end: str,
    recent_push_lookback_days: int,
    min_open_issues_count: int,
    minimum_score: int,
) -> dict[str, Any]:
    row = dict(candidate_row)
    _, recent_push_cutoff_date = has_recent_push(
        row.get("pushed_at"),
        study_window_end=study_window_end,
        lookback_days=recent_push_lookback_days,
    )
    row.update(
        {
            "quality_screen_status": "metadata_fetch_failed",
            "quality_screen_intended_use": "final_sample_only",
            "quality_screen_pass": False,
            "quality_screen_score": "",
            "quality_screen_threshold": minimum_score,
            "quality_screen_failure_reasons": "quality_metadata_fetch_failed",
            "quality_check_not_manual_review_flagged": not parse_bool(row.get("manual_review_flag")),
            "quality_check_recent_maintenance": "",
            "quality_check_issue_usage": "",
            "quality_check_engineering_workflow": "",
            "quality_recent_push_cutoff_date": recent_push_cutoff_date,
            "quality_open_issues_threshold": min_open_issues_count,
            "quality_signal_has_tests": "",
            "quality_signal_has_ci": "",
            "quality_signal_has_community_health_files": "",
            "quality_signal_matched_test_paths": "",
            "quality_signal_matched_ci_paths": "",
            "quality_signal_matched_community_health_paths": "",
            "quality_tree_truncated": "",
            "quality_tree_path_count": "",
            "quality_signal_snapshot_file": "",
            "quality_screen_error_type": error.__class__.__name__,
            "quality_screen_error_message": str(error),
            "quality_screen_error_status_code": getattr(error, "status_code", ""),
            "quality_screen_error_retryable": getattr(error, "retryable", ""),
            "quality_screen_error_attempts": getattr(error, "attempts", ""),
        }
    )
    return row


def build_quality_screen_exclusion_row(result_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "language_group": result_row.get("language_group"),
        "repository_full_name": result_row.get("full_name") or result_row.get("repository_full_name"),
        "quality_screen_status": result_row.get("quality_screen_status"),
        "quality_screen_pass": result_row.get("quality_screen_pass"),
        "quality_screen_score": result_row.get("quality_screen_score"),
        "quality_screen_threshold": result_row.get("quality_screen_threshold"),
        "quality_screen_failure_reasons": result_row.get("quality_screen_failure_reasons"),
        "quality_signal_snapshot_file": result_row.get("quality_signal_snapshot_file"),
        "source_file": result_row.get("source_file"),
        "source_record_index": result_row.get("source_record_index"),
    }
