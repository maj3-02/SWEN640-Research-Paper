from __future__ import annotations

import csv

from scripts.collect.enrich_final_candidates import (
    build_candidate_enrichment_summary,
    collect_closed_issue_count_in_window,
    enrich_candidate_row,
    enrichment_fieldnames,
    load_quality_screened_candidate_rows,
    threshold_pass_rows_by_language,
)
from scripts.utils.enrichment import build_enrichment_failure_record, build_enrichment_result_row


def write_candidate_csv(path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["full_name", "language_group", "default_branch"])
        writer.writeheader()
        writer.writerows(rows)


def test_load_quality_screened_candidate_rows_preserves_enrichment_traceability(tmp_path) -> None:
    input_dir = tmp_path / "data" / "interim" / "quality_screened_candidates"
    write_candidate_csv(
        input_dir / "javascript_candidates_filtered.csv",
        [{"full_name": "owner/js", "language_group": "JavaScript", "default_branch": "main"}],
    )
    write_candidate_csv(
        input_dir / "typescript_candidates_filtered.csv",
        [{"full_name": "owner/ts", "language_group": "TypeScript", "default_branch": "main"}],
    )

    rows, input_files = load_quality_screened_candidate_rows(input_dir, ["JavaScript", "TypeScript"])

    assert len(rows) == 2
    assert len(input_files) == 2
    assert rows[0]["enrichment_input_file"].endswith("javascript_candidates_filtered.csv")
    assert rows[0]["enrichment_input_record_index"] == 1
    assert rows[1]["enrichment_input_file"].endswith("typescript_candidates_filtered.csv")


def test_enrichment_fieldnames_include_new_contract_fields() -> None:
    fieldnames = enrichment_fieldnames([{"full_name": "owner/repo", "language_group": "JavaScript"}])

    assert "full_name" in fieldnames
    assert "language_stats" in fieldnames
    assert "language_threshold_pass" in fieldnames
    assert "default_branch_commit_count_in_window" in fieldnames
    assert "closed_issue_count_in_window" in fieldnames


def test_threshold_pass_rows_by_language_keeps_only_language_validated_rows() -> None:
    rows = [
        build_enrichment_result_row(
            {"full_name": "owner/js-pass", "language_group": "JavaScript"},
            language_bytes={"JavaScript": 80, "TypeScript": 20},
            target_language="JavaScript",
            language_threshold=0.70,
            default_branch_commit_count=55,
        ),
        build_enrichment_result_row(
            {"full_name": "owner/js-fail", "language_group": "JavaScript"},
            language_bytes={"JavaScript": 40, "TypeScript": 60},
            target_language="JavaScript",
            language_threshold=0.70,
            default_branch_commit_count=55,
        ),
        build_enrichment_result_row(
            {"full_name": "owner/ts-pass", "language_group": "TypeScript"},
            language_bytes={"TypeScript": 90, "JavaScript": 10},
            target_language="TypeScript",
            language_threshold=0.70,
            default_branch_commit_count=75,
        ),
    ]

    grouped = threshold_pass_rows_by_language(rows, ["JavaScript", "TypeScript"])

    assert [row["repository_full_name"] for row in grouped["JavaScript"]] == ["owner/js-pass"]
    assert [row["repository_full_name"] for row in grouped["TypeScript"]] == ["owner/ts-pass"]


def test_enrich_candidate_row_uses_language_and_commit_helpers(monkeypatch) -> None:
    def fake_fetch_languages(session, *, repository_full_name):
        assert repository_full_name == "owner/repo"
        return {"TypeScript": 750, "JavaScript": 250}

    def fake_fetch_commit_history(session, *, repository_full_name, since, until):
        assert repository_full_name == "owner/repo"
        assert since == "2024-01-01T00:00:00Z"
        assert until == "2025-12-31T23:59:59Z"
        return {
            "data": {
                "repository": {
                    "defaultBranchRef": {
                        "target": {
                            "history": {
                                "totalCount": 64,
                            }
                        }
                    }
                }
            }
        }

    def fake_collect_closed_issue_count(session, *, repository_full_name, study_window_start, study_window_end):
        assert repository_full_name == "owner/repo"
        assert study_window_start == "2024-01-01"
        assert study_window_end == "2025-12-31"
        return 7

    monkeypatch.setattr(
        "scripts.collect.enrich_final_candidates.fetch_repository_languages",
        fake_fetch_languages,
    )
    monkeypatch.setattr(
        "scripts.collect.enrich_final_candidates.fetch_default_branch_commit_history",
        fake_fetch_commit_history,
    )
    monkeypatch.setattr(
        "scripts.collect.enrich_final_candidates.collect_closed_issue_count_in_window",
        fake_collect_closed_issue_count,
    )

    row = enrich_candidate_row(
        object(),
        candidate_row={"full_name": "owner/repo", "language_group": "TypeScript"},
        target_language="TypeScript",
        language_threshold=0.70,
        study_window_start="2024-01-01",
        study_window_end="2025-12-31",
    )

    assert row["target_language_share"] == 0.75
    assert row["language_threshold_pass"] is True
    assert row["default_branch_commit_count_in_window"] == 64
    assert row["closed_issue_count_in_window"] == 7


def test_collect_closed_issue_count_in_window_uses_cursor_pagination(monkeypatch) -> None:
    pages = {
        None: {
            "issues_connection": {
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                "nodes": [
                    {"closedAt": "2024-02-01T00:00:00Z"},
                    {"closedAt": "2023-12-31T23:59:59Z"},
                ],
            }
        },
        "cursor-1": {
            "issues_connection": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {"closedAt": "2025-12-31T23:59:59Z"},
                    {"closedAt": "2026-01-01T00:00:00Z"},
                ],
            }
        },
    }
    calls = []

    def fake_fetch_closed_issues_page(session, *, repository_full_name, after, since):
        calls.append((repository_full_name, after, since))
        return pages[after]

    monkeypatch.setattr(
        "scripts.collect.enrich_final_candidates.fetch_closed_issues_page",
        fake_fetch_closed_issues_page,
    )

    count = collect_closed_issue_count_in_window(
        object(),
        repository_full_name="owner/repo",
        study_window_start="2024-01-01",
        study_window_end="2025-12-31",
    )

    assert count == 2
    assert calls == [
        ("owner/repo", None, "2024-01-01T00:00:00Z"),
        ("owner/repo", "cursor-1", "2024-01-01T00:00:00Z"),
    ]


def test_candidate_enrichment_summary_records_closed_issue_count_status() -> None:
    result_rows = [
        build_enrichment_result_row(
            {"full_name": "owner/pass", "language_group": "TypeScript"},
            language_bytes={"TypeScript": 90, "JavaScript": 10},
            target_language="TypeScript",
            language_threshold=0.70,
            default_branch_commit_count=80,
            closed_issue_count=6,
        ),
        build_enrichment_result_row(
            {"full_name": "owner/fail", "language_group": "TypeScript"},
            language_bytes={"TypeScript": 50, "JavaScript": 50},
            target_language="TypeScript",
            language_threshold=0.70,
            default_branch_commit_count=80,
            closed_issue_count=2,
        ),
    ]
    failures = [
        build_enrichment_failure_record(
            candidate_row={"full_name": "owner/error", "language_group": "TypeScript"},
            stage="closed_issue_count",
            error=RuntimeError("boom"),
        )
    ]

    summary = build_candidate_enrichment_summary(
        input_files=["typescript_candidates_filtered.csv"],
        output_files={"results_csv": "candidate_enrichment_results.csv"},
        result_rows=result_rows,
        failure_records=failures,
        language_threshold=0.70,
    )

    assert summary["repositories_seen"] == 3
    assert summary["repositories_enriched"] == 2
    assert summary["language_threshold_pass_count"] == 1
    assert summary["language_threshold_failed_count"] == 1
    assert summary["activity_field"] == "default_branch_commit_count_in_window"
    assert summary["closed_issue_count_field"] == "closed_issue_count_in_window"
    assert summary["closed_issue_count_status"] == "available"
    assert summary["closed_issue_count_missing_count"] == 0
    assert summary["closed_issue_count_failure_count"] == 1
