from __future__ import annotations

import json
from pathlib import Path

from scripts.collect.audit_final_collection import (
    build_collection_audit_rows,
    build_collection_audit_summary,
)
from scripts.utils.collection import repository_artifact_path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_collection_audit_rows_report_complete_and_incomplete_repositories(tmp_path) -> None:
    commit_raw_dir = tmp_path / "raw_commits"
    issue_raw_dir = tmp_path / "raw_issues"
    complete_commit_file = repository_artifact_path(commit_raw_dir, "example/complete", "commits_raw.json")
    complete_issue_file = repository_artifact_path(issue_raw_dir, "example/complete", "issues_raw.json")
    missing_commit_file = repository_artifact_path(commit_raw_dir, "example/missing", "commits_raw.json")

    _write_json(complete_commit_file, {"commit_count": 3, "commits": [{}, {}, {}]})
    _write_json(complete_issue_file, {"issue_count": 2, "issues": [{}, {}]})
    _write_json(missing_commit_file, {"commit_count": 4, "commits": [{}, {}, {}, {}]})

    sampled_repositories = [
        {"repository_full_name": "example/complete", "language_group": "JavaScript"},
        {"repository_full_name": "example/missing", "language_group": "TypeScript"},
    ]
    commit_summary_payload = {
        "results": [
            {"repository_full_name": "example/complete", "language_group": "JavaScript", "commit_count": 3},
            {"repository_full_name": "example/missing", "language_group": "TypeScript", "commit_count": 5},
        ],
        "failures": [],
    }
    issue_summary_payload = {
        "results": [
            {"repository_full_name": "example/complete", "language_group": "JavaScript", "issue_count": 2},
        ],
        "failures": [],
    }
    commit_failure_payload = {
        "failures": [
            {"repository_full_name": "example/missing", "stage": "commits", "message": "rate limit"},
        ]
    }
    issue_failure_payload = {"failures": []}

    rows = build_collection_audit_rows(
        sampled_repositories=sampled_repositories,
        commit_summary_payload=commit_summary_payload,
        issue_summary_payload=issue_summary_payload,
        commit_failure_payload=commit_failure_payload,
        issue_failure_payload=issue_failure_payload,
        commit_raw_dir=commit_raw_dir,
        issue_raw_dir=issue_raw_dir,
    )

    by_repo = {row["repository_full_name"]: row for row in rows}

    assert by_repo["example/complete"]["collection_complete"] is True
    assert by_repo["example/complete"]["audit_failure_reasons"] == ""
    assert by_repo["example/complete"]["collected_commit_count"] == 3
    assert by_repo["example/complete"]["collected_issue_count"] == 2

    missing_row = by_repo["example/missing"]
    assert missing_row["collection_complete"] is False
    assert missing_row["commit_raw_file_present"] is True
    assert missing_row["issue_raw_file_present"] is False
    assert missing_row["commit_failure_present"] is True
    assert missing_row["issue_summary_present"] is False
    assert "missing_issue_raw_file" in missing_row["audit_failure_reasons"]
    assert "missing_issue_summary_result" in missing_row["audit_failure_reasons"]
    assert "commit_collection_failure_present" in missing_row["audit_failure_reasons"]
    assert "commit_count_mismatch" in missing_row["audit_failure_reasons"]


def test_collection_audit_summary_counts_failure_reasons() -> None:
    rows = [
        {
            "repository_full_name": "example/complete",
            "collection_complete": True,
            "audit_failure_reasons": "",
        },
        {
            "repository_full_name": "example/missing",
            "collection_complete": False,
            "audit_failure_reasons": "missing_commit_raw_file;issue_collection_failure_present",
        },
    ]

    summary = build_collection_audit_summary(
        rows=rows,
        input_paths={"sample_file": "final_sample.csv"},
        input_file_presence={"commit_summary_present": True},
        output_paths={"audit_csv": "collection_completeness_audit.csv"},
    )

    assert summary["intended_use"] == "operational_completeness_audit_not_eligibility_gate"
    assert summary["sampled_repository_count"] == 2
    assert summary["complete_repository_count"] == 1
    assert summary["incomplete_repository_count"] == 1
    assert summary["missing_commit_file_count"] == 1
    assert summary["issue_failure_count"] == 1
    assert "eligible_for_rq1" not in summary
    assert "eligible_for_rq2" not in summary
