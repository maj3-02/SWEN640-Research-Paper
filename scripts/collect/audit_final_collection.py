from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.collection import extract_repository_full_name, load_sampled_repositories, repository_artifact_path
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import final_sample_dir, resolve_repo_path

LOGGER = logging.getLogger(__name__)

AUDIT_CSV_FILENAME = "collection_completeness_audit.csv"
AUDIT_JSON_FILENAME = "collection_completeness_audit.json"

AUDIT_FIELDNAMES = [
    "repository_full_name",
    "language_group",
    "commit_raw_file_present",
    "issue_raw_file_present",
    "commit_summary_present",
    "issue_summary_present",
    "commit_failure_present",
    "issue_failure_present",
    "collected_commit_count",
    "collected_issue_count",
    "commit_raw_file",
    "issue_raw_file",
    "collection_complete",
    "audit_failure_reasons",
    "collection_audit_notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit final-study raw collection completeness without eligibility gating.")
    parser.add_argument(
        "--sample-file",
        default=None,
        help="Path to the locked final sample manifest. Defaults to data/interim/final_sample/final_sample.csv.",
    )
    parser.add_argument(
        "--commit-summary",
        default=None,
        help="Path to commit_collection_summary.json.",
    )
    parser.add_argument(
        "--issue-summary",
        default=None,
        help="Path to issue_collection_summary.json.",
    )
    parser.add_argument(
        "--commit-failures",
        default=None,
        help="Path to commit_collection_failures.json.",
    )
    parser.add_argument(
        "--issue-failures",
        default=None,
        help="Path to issue_collection_failures.json.",
    )
    parser.add_argument(
        "--commit-raw-dir",
        default=None,
        help="Directory containing raw commit artifacts.",
    )
    parser.add_argument(
        "--issue-raw-dir",
        default=None,
        help="Directory containing raw issue artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for audit outputs. Defaults to data/interim/final_sample.",
    )
    return parser.parse_args()


def default_sample_file() -> Path:
    return final_sample_dir() / "final_sample.csv"


def default_commit_raw_dir() -> Path:
    return final_sample_dir() / "raw_commits"


def default_issue_raw_dir() -> Path:
    return final_sample_dir() / "raw_issues"


def default_commit_summary_path() -> Path:
    return default_commit_raw_dir() / "commit_collection_summary.json"


def default_issue_summary_path() -> Path:
    return default_issue_raw_dir() / "issue_collection_summary.json"


def default_commit_failures_path() -> Path:
    return default_commit_raw_dir() / "commit_collection_failures.json"


def default_issue_failures_path() -> Path:
    return default_issue_raw_dir() / "issue_collection_failures.json"


def _load_json_object(path: str | Path) -> tuple[dict[str, Any], bool]:
    json_path = Path(path)
    if not json_path.exists():
        return {}, False
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {json_path}")
    return payload, True


def _repo_name(row: dict[str, Any]) -> str:
    return extract_repository_full_name(row)


def _index_results_by_repository(summary_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    results = summary_payload.get("results") or []
    if not isinstance(results, list):
        return index
    for row in results:
        if not isinstance(row, dict):
            continue
        repository_full_name = str(row.get("repository_full_name") or "").strip()
        if repository_full_name and repository_full_name not in index:
            index[repository_full_name] = row
    return index


def _failure_repositories(*payloads: dict[str, Any]) -> set[str]:
    repositories: set[str] = set()
    for payload in payloads:
        failures = payload.get("failures") or []
        if not isinstance(failures, list):
            continue
        for row in failures:
            if not isinstance(row, dict):
                continue
            repository_full_name = str(row.get("repository_full_name") or "").strip()
            if repository_full_name:
                repositories.add(repository_full_name)
    return repositories


def _json_count_from_artifact(
    path: Path,
    *,
    count_field: str,
    records_field: str,
) -> tuple[int | None, list[str]]:
    if not path.exists():
        return None, []
    try:
        payload, _ = _load_json_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None, [f"{records_field}_raw_file_unreadable"]

    value = payload.get(count_field)
    try:
        return int(value), []
    except (TypeError, ValueError):
        records = payload.get(records_field)
        if isinstance(records, list):
            return len(records), []
    return None, [f"{records_field}_raw_count_missing"]


def _summary_count(row: dict[str, Any] | None, count_field: str) -> int | None:
    if row is None:
        return None
    try:
        return int(row.get(count_field))
    except (TypeError, ValueError):
        return None


def _join(values: list[str]) -> str:
    return ";".join(value for value in values if value)


def build_collection_audit_rows(
    *,
    sampled_repositories: list[dict[str, Any]],
    commit_summary_payload: dict[str, Any],
    issue_summary_payload: dict[str, Any],
    commit_failure_payload: dict[str, Any],
    issue_failure_payload: dict[str, Any],
    commit_raw_dir: Path,
    issue_raw_dir: Path,
) -> list[dict[str, Any]]:
    commit_results = _index_results_by_repository(commit_summary_payload)
    issue_results = _index_results_by_repository(issue_summary_payload)
    commit_failures = _failure_repositories(commit_summary_payload, commit_failure_payload)
    issue_failures = _failure_repositories(issue_summary_payload, issue_failure_payload)

    rows: list[dict[str, Any]] = []
    for sample_row in sampled_repositories:
        repository_full_name = _repo_name(sample_row)
        language_group = sample_row.get("language_group")
        commit_summary_row = commit_results.get(repository_full_name)
        issue_summary_row = issue_results.get(repository_full_name)
        commit_raw_file = repository_artifact_path(commit_raw_dir, repository_full_name, "commits_raw.json")
        issue_raw_file = repository_artifact_path(issue_raw_dir, repository_full_name, "issues_raw.json")
        commit_raw_present = commit_raw_file.exists()
        issue_raw_present = issue_raw_file.exists()
        commit_summary_count = _summary_count(commit_summary_row, "commit_count")
        issue_summary_count = _summary_count(issue_summary_row, "issue_count")
        commit_raw_count, commit_raw_notes = _json_count_from_artifact(
            commit_raw_file,
            count_field="commit_count",
            records_field="commits",
        )
        issue_raw_count, issue_raw_notes = _json_count_from_artifact(
            issue_raw_file,
            count_field="issue_count",
            records_field="issues",
        )

        reasons: list[str] = []
        notes: list[str] = []
        if not commit_raw_present:
            reasons.append("missing_commit_raw_file")
        if not issue_raw_present:
            reasons.append("missing_issue_raw_file")
        if commit_summary_row is None:
            reasons.append("missing_commit_summary_result")
        if issue_summary_row is None:
            reasons.append("missing_issue_summary_result")
        if repository_full_name in commit_failures:
            reasons.append("commit_collection_failure_present")
        if repository_full_name in issue_failures:
            reasons.append("issue_collection_failure_present")

        notes.extend(commit_raw_notes)
        notes.extend(issue_raw_notes)
        if commit_summary_count is not None and commit_raw_count is not None and commit_summary_count != commit_raw_count:
            reasons.append("commit_count_mismatch")
            notes.append(f"commit_summary_count={commit_summary_count},commit_raw_count={commit_raw_count}")
        if issue_summary_count is not None and issue_raw_count is not None and issue_summary_count != issue_raw_count:
            reasons.append("issue_count_mismatch")
            notes.append(f"issue_summary_count={issue_summary_count},issue_raw_count={issue_raw_count}")

        row = {
            "repository_full_name": repository_full_name,
            "language_group": language_group,
            "commit_raw_file_present": commit_raw_present,
            "issue_raw_file_present": issue_raw_present,
            "commit_summary_present": commit_summary_row is not None,
            "issue_summary_present": issue_summary_row is not None,
            "commit_failure_present": repository_full_name in commit_failures,
            "issue_failure_present": repository_full_name in issue_failures,
            "collected_commit_count": commit_summary_count if commit_summary_count is not None else commit_raw_count,
            "collected_issue_count": issue_summary_count if issue_summary_count is not None else issue_raw_count,
            "commit_raw_file": str(commit_raw_file),
            "issue_raw_file": str(issue_raw_file),
            "collection_complete": not reasons,
            "audit_failure_reasons": _join(reasons),
            "collection_audit_notes": _join(notes),
        }
        rows.append(row)

    return rows


def build_collection_audit_summary(
    *,
    rows: list[dict[str, Any]],
    input_paths: dict[str, str],
    input_file_presence: dict[str, bool],
    output_paths: dict[str, str],
) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    for row in rows:
        for reason in str(row.get("audit_failure_reasons") or "").split(";"):
            if reason:
                reason_counts[reason] += 1

    complete_count = sum(1 for row in rows if bool(row.get("collection_complete")))
    return {
        "audit_type": "final_collection_completeness",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "operational_completeness_audit_not_eligibility_gate",
        "input_paths": input_paths,
        "input_file_presence": input_file_presence,
        "sampled_repository_count": len(rows),
        "complete_repository_count": complete_count,
        "incomplete_repository_count": len(rows) - complete_count,
        "missing_commit_file_count": reason_counts.get("missing_commit_raw_file", 0),
        "missing_issue_file_count": reason_counts.get("missing_issue_raw_file", 0),
        "commit_failure_count": reason_counts.get("commit_collection_failure_present", 0),
        "issue_failure_count": reason_counts.get("issue_collection_failure_present", 0),
        "missing_commit_summary_result_count": reason_counts.get("missing_commit_summary_result", 0),
        "missing_issue_summary_result_count": reason_counts.get("missing_issue_summary_result", 0),
        "commit_count_mismatch_count": reason_counts.get("commit_count_mismatch", 0),
        "issue_count_mismatch_count": reason_counts.get("issue_count_mismatch", 0),
        "audit_failure_reason_counts": dict(reason_counts),
        "output_paths": output_paths,
    }


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def main() -> None:
    args = parse_args()
    configure_logging()

    sample_file = resolve_repo_path(args.sample_file) if args.sample_file is not None else default_sample_file()
    commit_summary_path = (
        resolve_repo_path(args.commit_summary) if args.commit_summary is not None else default_commit_summary_path()
    )
    issue_summary_path = (
        resolve_repo_path(args.issue_summary) if args.issue_summary is not None else default_issue_summary_path()
    )
    commit_failures_path = (
        resolve_repo_path(args.commit_failures) if args.commit_failures is not None else default_commit_failures_path()
    )
    issue_failures_path = (
        resolve_repo_path(args.issue_failures) if args.issue_failures is not None else default_issue_failures_path()
    )
    commit_raw_dir = resolve_repo_path(args.commit_raw_dir) if args.commit_raw_dir is not None else default_commit_raw_dir()
    issue_raw_dir = resolve_repo_path(args.issue_raw_dir) if args.issue_raw_dir is not None else default_issue_raw_dir()
    output_dir = resolve_repo_path(args.output_dir) if args.output_dir is not None else final_sample_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Using final sample manifest: %s", sample_file)
    LOGGER.info("Using commit collection summary: %s", commit_summary_path)
    LOGGER.info("Using issue collection summary: %s", issue_summary_path)
    LOGGER.info("Using commit collection failures: %s", commit_failures_path)
    LOGGER.info("Using issue collection failures: %s", issue_failures_path)
    LOGGER.info("Using commit raw directory: %s", commit_raw_dir)
    LOGGER.info("Using issue raw directory: %s", issue_raw_dir)

    sampled_repositories = load_sampled_repositories(sample_file)
    commit_summary_payload, commit_summary_present = _load_json_object(commit_summary_path)
    issue_summary_payload, issue_summary_present = _load_json_object(issue_summary_path)
    commit_failure_payload, commit_failures_present = _load_json_object(commit_failures_path)
    issue_failure_payload, issue_failures_present = _load_json_object(issue_failures_path)

    rows = build_collection_audit_rows(
        sampled_repositories=sampled_repositories,
        commit_summary_payload=commit_summary_payload,
        issue_summary_payload=issue_summary_payload,
        commit_failure_payload=commit_failure_payload,
        issue_failure_payload=issue_failure_payload,
        commit_raw_dir=commit_raw_dir,
        issue_raw_dir=issue_raw_dir,
    )
    output_csv = output_dir / AUDIT_CSV_FILENAME
    output_json = output_dir / AUDIT_JSON_FILENAME
    input_paths = {
        "sample_file": str(sample_file),
        "commit_summary_path": str(commit_summary_path),
        "issue_summary_path": str(issue_summary_path),
        "commit_failure_path": str(commit_failures_path),
        "issue_failure_path": str(issue_failures_path),
        "commit_raw_dir": str(commit_raw_dir),
        "issue_raw_dir": str(issue_raw_dir),
    }
    output_paths = {
        "audit_csv": str(output_csv),
        "audit_json": str(output_json),
    }
    summary = build_collection_audit_summary(
        rows=rows,
        input_paths=input_paths,
        input_file_presence={
            "commit_summary_present": commit_summary_present,
            "issue_summary_present": issue_summary_present,
            "commit_failures_present": commit_failures_present,
            "issue_failures_present": issue_failures_present,
        },
        output_paths=output_paths,
    )

    write_csv(output_csv, rows)
    write_json(output_json, {"summary": summary, "rows": rows})

    LOGGER.info("Audited sampled repositories: %s", summary["sampled_repository_count"])
    LOGGER.info("Collection-complete repositories: %s", summary["complete_repository_count"])
    LOGGER.info("Collection-incomplete repositories: %s", summary["incomplete_repository_count"])
    LOGGER.info("Saved collection completeness audit CSV to %s", output_csv)
    LOGGER.info("Saved collection completeness audit JSON to %s", output_json)


if __name__ == "__main__":
    main()
