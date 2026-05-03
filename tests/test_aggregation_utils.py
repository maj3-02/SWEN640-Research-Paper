from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.aggregate.compute_repo_metrics import (
    default_classified_commits_file,
    default_classified_issues_file,
    default_repo_metrics_output_dir,
    default_sample_manifest_file,
)
from scripts.utils.aggregation import (
    build_aggregation_run_provenance,
    build_repository_metrics,
    duration_days,
    infer_aggregation_input_kind,
    infer_aggregation_run_type,
    parse_iso_datetime,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_raw_issue_payload(path: Path, issues: list[dict[str, object]]) -> None:
    payload = {
        "collection_type": "issues",
        "repository_full_name": "example/eligible",
        "issues": issues,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_datetime_parsing_and_duration_days() -> None:
    parsed = parse_iso_datetime("2024-01-01T00:00:00Z")
    assert parsed is not None
    assert parsed.isoformat() == "2024-01-01T00:00:00+00:00"

    assert duration_days("2024-01-01T00:00:00Z", "2024-01-03T12:00:00Z") == 2.5
    assert duration_days("bad", "2024-01-03T12:00:00Z") is None
    assert duration_days("2024-01-03T12:00:00Z", "2024-01-01T00:00:00Z") is None


def test_aggregation_run_type_inference_for_final_and_custom_paths(tmp_path) -> None:
    final = tmp_path / "data" / "interim" / "final_sample" / "final_sample.csv"
    custom = tmp_path / "eligibility.csv"

    assert build_aggregation_run_provenance(final)["aggregation_run_type"] == "final_study"
    assert build_aggregation_run_provenance(final)["aggregation_input_kind"] == "sample_manifest"
    assert infer_aggregation_input_kind(final) == "sample_manifest"
    assert infer_aggregation_run_type(custom) == "custom"


def test_aggregation_defaults_use_custom_paths_for_custom_manifest(tmp_path) -> None:
    custom_manifest = tmp_path / "custom_manifest.csv"

    assert default_classified_commits_file(custom_manifest, tmp_path).as_posix().endswith(
        "data/interim/classified_commits/classified_commits.csv"
    )
    assert default_classified_issues_file(custom_manifest, tmp_path).as_posix().endswith(
        "data/interim/classified_issues/classified_issues.csv"
    )
    assert default_repo_metrics_output_dir(custom_manifest, tmp_path).as_posix().endswith("data/processed/repo_metrics")


def test_aggregation_defaults_route_final_study_paths(tmp_path) -> None:
    sample_manifest = tmp_path / "data" / "interim" / "final_sample" / "final_sample.csv"

    assert default_sample_manifest_file(tmp_path).as_posix().endswith("data/interim/final_sample/final_sample.csv")
    assert default_classified_commits_file(sample_manifest, tmp_path).as_posix().endswith(
        "data/interim/final_sample/classified_commits/classified_commits.csv"
    )
    assert default_classified_issues_file(sample_manifest, tmp_path).as_posix().endswith(
        "data/interim/final_sample/classified_issues/classified_issues.csv"
    )
    assert default_repo_metrics_output_dir(sample_manifest, tmp_path).as_posix().endswith(
        "data/processed/repo_metrics/final_sample"
    )


def test_build_repository_metrics_uses_sample_manifest_and_computes_metrics(tmp_path) -> None:
    sample_manifest_path = tmp_path / "final_sample.csv"
    classified_commits_path = tmp_path / "classified_commits.csv"
    classified_issues_path = tmp_path / "classified_issues.csv"
    eligible_raw_issue_path = tmp_path / "data" / "raw" / "issues" / "example_eligible_issues_raw.json"
    eligible_raw_issue_path.parent.mkdir(parents=True, exist_ok=True)

    _write_csv(
        sample_manifest_path,
        [
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "pre_sampling_eligible": "True",
            },
        ],
    )

    _write_csv(
        classified_commits_path,
        [
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "commit_sha": "c1",
                "commit_message": "fix bug in parser",
                "commit_date": "2024-01-01T00:00:00Z",
                "commit_author_login": "alice",
                "commit_author_name": "Alice",
                "commit_author_email": "alice@example.com",
                "commit_committer_name": "Alice",
                "commit_committer_email": "alice@example.com",
                "is_bug_fix": "True",
                "matched_required_term": "fix",
                "matched_additional_terms": "bug",
                "provisional_issue_term_used": "False",
                "provisional_issue_term_matched": "",
                "classification_reason": "required_and_additional_term_match",
                "source_file": str(tmp_path / "data" / "raw" / "commits" / "example_eligible_commits_raw.json"),
                "raw_record_index": "0",
            },
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "commit_sha": "c2",
                "commit_message": "fix crash in parser",
                "commit_date": "2024-01-02T00:00:00Z",
                "commit_author_login": "bob",
                "commit_author_name": "Bob",
                "commit_author_email": "bob@example.com",
                "commit_committer_name": "Bob",
                "commit_committer_email": "bob@example.com",
                "is_bug_fix": "True",
                "matched_required_term": "fix",
                "matched_additional_terms": "crash",
                "provisional_issue_term_used": "False",
                "provisional_issue_term_matched": "",
                "classification_reason": "required_and_additional_term_match",
                "source_file": str(tmp_path / "data" / "raw" / "commits" / "example_eligible_commits_raw.json"),
                "raw_record_index": "1",
            },
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "commit_sha": "c3",
                "commit_message": "fix docs only",
                "commit_date": "2024-01-03T00:00:00Z",
                "commit_author_login": "carol",
                "commit_author_name": "Carol",
                "commit_author_email": "carol@example.com",
                "commit_committer_name": "Carol",
                "commit_committer_email": "carol@example.com",
                "is_bug_fix": "False",
                "matched_required_term": "",
                "matched_additional_terms": "",
                "provisional_issue_term_used": "False",
                "provisional_issue_term_matched": "",
                "classification_reason": "required_term_without_additional_term",
                "source_file": str(tmp_path / "data" / "raw" / "commits" / "example_eligible_commits_raw.json"),
                "raw_record_index": "2",
            },
            {
                "repository_full_name": "example/ineligible",
                "language_group": "TypeScript",
                "commit_sha": "c4",
                "commit_message": "fix bug in parser",
                "commit_date": "2024-01-04T00:00:00Z",
                "commit_author_login": "dana",
                "commit_author_name": "Dana",
                "commit_author_email": "dana@example.com",
                "commit_committer_name": "Dana",
                "commit_committer_email": "dana@example.com",
                "is_bug_fix": "True",
                "matched_required_term": "fix",
                "matched_additional_terms": "bug",
                "provisional_issue_term_used": "False",
                "provisional_issue_term_matched": "",
                "classification_reason": "required_and_additional_term_match",
                "source_file": str(tmp_path / "data" / "raw" / "commits" / "example_ineligible_commits_raw.json"),
                "raw_record_index": "0",
            },
        ],
    )

    _write_raw_issue_payload(
        eligible_raw_issue_path,
        [
            {
                "id": "i1",
                "number": 1,
                "title": "Bug in parser",
                "body": "crash on start",
                "state": "CLOSED",
                "createdAt": "2024-01-01T00:00:00Z",
                "closedAt": "2024-01-03T00:00:00Z",
                "updatedAt": "2024-01-03T00:00:00Z",
                "url": "https://example.com/1",
                "author": {"login": "alice"},
                "labels": {"nodes": [{"name": "bug"}]},
            },
            {
                "id": "i2",
                "number": 2,
                "title": "Crash on load",
                "body": "failure during startup",
                "state": "CLOSED",
                "createdAt": "2024-01-10T00:00:00Z",
                "closedAt": "2024-01-14T00:00:00Z",
                "updatedAt": "2024-01-14T00:00:00Z",
                "url": "https://example.com/2",
                "author": {"login": "bob"},
                "labels": {"nodes": []},
            },
            {
                "id": "i3",
                "number": 3,
                "title": "Bug report without created timestamp",
                "body": "failure in parser",
                "state": "CLOSED",
                "closedAt": "2024-01-20T00:00:00Z",
                "updatedAt": "2024-01-20T00:00:00Z",
                "url": "https://example.com/3",
                "author": {"login": "carol"},
                "labels": {"nodes": [{"name": "bug"}]},
            },
        ],
    )

    _write_csv(
        classified_issues_path,
        [
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "issue_id": "i1",
                "issue_number": "1",
                "issue_url": "https://example.com/1",
                "title": "Bug in parser",
                "body": "crash on start",
                "state": "CLOSED",
                "closed_at": "2024-01-03T00:00:00Z",
                "issue_author_login": "alice",
                "label_names": "bug",
                "is_bug_related": "True",
                "matched_label_terms": "bug",
                "matched_text_terms": "bug;crash",
                "match_source": "label;title",
                "classification_reason": "label_and_text_match",
                "source_file": str(eligible_raw_issue_path),
                "raw_record_index": "0",
            },
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "issue_id": "i2",
                "issue_number": "2",
                "issue_url": "https://example.com/2",
                "title": "Crash on load",
                "body": "failure during startup",
                "state": "CLOSED",
                "closed_at": "2024-01-14T00:00:00Z",
                "issue_author_login": "bob",
                "label_names": "",
                "is_bug_related": "True",
                "matched_label_terms": "",
                "matched_text_terms": "crash;failure",
                "match_source": "title;body",
                "classification_reason": "text_match",
                "source_file": str(eligible_raw_issue_path),
                "raw_record_index": "1",
            },
            {
                "repository_full_name": "example/eligible",
                "language_group": "JavaScript",
                "issue_id": "i3",
                "issue_number": "3",
                "issue_url": "https://example.com/3",
                "title": "Bug report without created timestamp",
                "body": "failure in parser",
                "state": "CLOSED",
                "closed_at": "2024-01-20T00:00:00Z",
                "issue_author_login": "carol",
                "label_names": "bug",
                "is_bug_related": "True",
                "matched_label_terms": "bug",
                "matched_text_terms": "failure",
                "match_source": "label;body",
                "classification_reason": "label_and_text_match",
                "source_file": str(eligible_raw_issue_path),
                "raw_record_index": "2",
            },
            {
                "repository_full_name": "example/ineligible",
                "language_group": "TypeScript",
                "issue_id": "i4",
                "issue_number": "4",
                "issue_url": "https://example.com/4",
                "title": "Bug in parser",
                "body": "crash on start",
                "state": "CLOSED",
                "closed_at": "2024-01-04T00:00:00Z",
                "issue_author_login": "dana",
                "label_names": "bug",
                "is_bug_related": "True",
                "matched_label_terms": "bug",
                "matched_text_terms": "crash",
                "match_source": "label;title",
                "classification_reason": "label_and_text_match",
                "source_file": str(tmp_path / "data" / "raw" / "issues" / "example_ineligible_issues_raw.json"),
                "raw_record_index": "0",
            },
            {
                "repository_full_name": "example/ineligible",
                "language_group": "TypeScript",
                "issue_id": "i5",
                "issue_number": "5",
                "issue_url": "https://example.com/5",
                "title": "Crash on load",
                "body": "failure during startup",
                "state": "CLOSED",
                "closed_at": "2024-01-05T00:00:00Z",
                "issue_author_login": "erin",
                "label_names": "",
                "is_bug_related": "True",
                "matched_label_terms": "",
                "matched_text_terms": "crash;failure",
                "match_source": "title;body",
                "classification_reason": "text_match",
                "source_file": str(tmp_path / "data" / "raw" / "issues" / "example_ineligible_issues_raw.json"),
                "raw_record_index": "1",
            },
        ],
    )

    rows, summary = build_repository_metrics(
        classified_commits_path=classified_commits_path,
        classified_issues_path=classified_issues_path,
        sample_manifest_path=sample_manifest_path,
    )

    by_repo = {row["repository_full_name"]: row for row in rows}

    eligible_row = by_repo["example/eligible"]
    assert eligible_row["eligible_for_rq1"] is True
    assert eligible_row["eligible_for_rq2"] is True
    assert eligible_row["total_commits_in_window"] == 3
    assert eligible_row["bug_fix_commit_count"] == 2
    assert eligible_row["bug_fix_commit_ratio"] == 2 / 3
    assert eligible_row["total_closed_issues_in_window_considered"] == 3
    assert eligible_row["bug_related_issue_count"] == 3
    assert eligible_row["bug_related_issue_duration_count"] == 2
    assert eligible_row["invalid_bug_related_issue_duration_count"] == 1
    assert eligible_row["median_bug_issue_resolution_time_days"] == 3.0

    assert "example/ineligible" not in by_repo
    assert summary["repositories_seen_in_sample_manifest"] == 1
    assert summary["repositories_aggregated_for_rq1_count"] == 1
    assert summary["repositories_aggregated_for_rq2_count"] == 1
    assert summary["commit_rows_used_total"] == 3
    assert summary["issue_rows_used_total"] == 3
    assert summary["commit_rows_excluded_by_sample_manifest"] == 1
    assert summary["issue_rows_excluded_by_sample_manifest"] == 2
    assert summary["invalid_bug_related_issue_duration_rows_total"] == 1
    assert summary["repositories_missing_commit_rows"] == []
    assert summary["repositories_missing_issue_rows"] == []


def test_build_repository_metrics_routes_by_sample_manifest_and_reports_missing_rows(tmp_path) -> None:
    sample_manifest_path = tmp_path / "final_sample.csv"
    classified_commits_path = tmp_path / "classified_commits.csv"
    classified_issues_path = tmp_path / "classified_issues.csv"

    _write_csv(
        sample_manifest_path,
        [
            {
                "repository_full_name": "example/sampled",
                "language_group": "JavaScript",
                "pre_sampling_eligible": "True",
                "activity_stratum": "low",
                "default_branch_commit_count_in_window": "50",
            },
            {
                "repository_full_name": "example/missing",
                "language_group": "TypeScript",
                "pre_sampling_eligible": "True",
                "activity_stratum": "high",
                "default_branch_commit_count_in_window": "150",
            },
        ],
    )
    _write_csv(
        classified_commits_path,
        [
            {
                "repository_full_name": "example/sampled",
                "language_group": "JavaScript",
                "is_bug_fix": "True",
                "source_file": "sampled_commits.json",
            },
            {
                "repository_full_name": "example/outside-sample",
                "language_group": "JavaScript",
                "is_bug_fix": "True",
                "source_file": "outside_commits.json",
            },
        ],
    )
    _write_csv(
        classified_issues_path,
        [
            {
                "repository_full_name": "example/sampled",
                "language_group": "JavaScript",
                "issue_id": "i1",
                "issue_number": "1",
                "is_bug_related": "False",
                "source_file": "sampled_issues.json",
                "raw_record_index": "0",
            },
            {
                "repository_full_name": "example/outside-sample",
                "language_group": "JavaScript",
                "issue_id": "i2",
                "issue_number": "2",
                "is_bug_related": "False",
                "source_file": "outside_issues.json",
                "raw_record_index": "0",
            },
        ],
    )

    rows, summary = build_repository_metrics(
        classified_commits_path=classified_commits_path,
        classified_issues_path=classified_issues_path,
        sample_manifest_path=sample_manifest_path,
    )

    by_repo = {row["repository_full_name"]: row for row in rows}

    assert set(by_repo) == {"example/sampled", "example/missing"}
    assert by_repo["example/sampled"]["eligible_for_rq1"] is True
    assert by_repo["example/sampled"]["eligible_for_rq2"] is True
    assert by_repo["example/sampled"]["total_commits_in_window"] == 1
    assert by_repo["example/sampled"]["bug_fix_commit_count"] == 1
    assert by_repo["example/missing"]["total_commits_in_window"] == 0
    assert by_repo["example/missing"]["total_closed_issues_in_window_considered"] == 0
    assert by_repo["example/sampled"]["sample_manifest_file"] == str(sample_manifest_path)

    assert summary["aggregation_input_kind"] == "sample_manifest"
    assert summary["sample_manifest_file"] == str(sample_manifest_path)
    assert summary["repositories_seen_in_sample_manifest"] == 2
    assert summary["commit_rows_excluded_by_sample_manifest"] == 1
    assert summary["issue_rows_excluded_by_sample_manifest"] == 1
    assert summary["repositories_missing_commit_rows"] == ["example/missing"]
    assert summary["repositories_missing_issue_rows"] == ["example/missing"]
