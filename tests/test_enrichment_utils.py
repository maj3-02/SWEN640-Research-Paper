from __future__ import annotations

from scripts.utils.enrichment import (
    build_enrichment_failure_record,
    build_enrichment_result_row,
    build_enrichment_summary,
    count_closed_issue_nodes_in_window,
    language_share,
    normalize_language_bytes,
    parse_count,
    parse_default_branch_commit_count,
    parse_graphql_total_count,
    passes_language_threshold,
    serialize_enrichment_row,
    serialize_language_stats,
    target_language_bytes,
    total_language_bytes,
)


def make_candidate_row(**overrides):
    row = {
        "language_group": "TypeScript",
        "full_name": "example/repo",
        "source_file": "data/interim/quality_screened_candidates/typescript_candidates_filtered.csv",
        "source_record_index": "7",
    }
    row.update(overrides)
    return row


def test_language_share_for_multi_language_repository() -> None:
    language_bytes = {"TypeScript": 700, "JavaScript": 200, "CSS": 100}

    assert total_language_bytes(language_bytes) == 1000
    assert target_language_bytes(language_bytes, "TypeScript") == 700
    assert language_share(language_bytes, "TypeScript") == 0.7


def test_language_share_for_single_language_repository() -> None:
    language_bytes = {"JavaScript": 1234}

    assert language_share(language_bytes, "JavaScript") == 1.0
    assert passes_language_threshold(language_bytes, target_language="JavaScript", threshold=0.70) is True


def test_language_share_handles_empty_or_malformed_language_mappings() -> None:
    assert normalize_language_bytes(None) == {}
    assert normalize_language_bytes({"TypeScript": "bad", "": 50, "CSS": -1}) == {}
    assert language_share({}, "TypeScript") is None
    assert passes_language_threshold({}, target_language="TypeScript", threshold=0.70) is False


def test_threshold_pass_fail_logic() -> None:
    assert passes_language_threshold({"TypeScript": 69, "JavaScript": 31}, target_language="TypeScript", threshold=0.70) is False
    assert passes_language_threshold({"TypeScript": 70, "JavaScript": 30}, target_language="TypeScript", threshold=0.70) is True


def test_graphql_count_parsing() -> None:
    assert parse_count(12) == 12
    assert parse_count("12") == 12
    assert parse_count(-1) is None
    assert parse_count("not-a-count") is None
    assert parse_graphql_total_count({"totalCount": "42"}) == 42
    assert parse_graphql_total_count({"nodes": []}) is None
    assert parse_graphql_total_count(None) is None


def test_default_branch_commit_count_parsing() -> None:
    payload = {
        "data": {
            "repository": {
                "defaultBranchRef": {
                    "target": {
                        "history": {
                            "totalCount": "81",
                        }
                    }
                }
            }
        }
    }

    assert parse_default_branch_commit_count(payload) == 81
    assert parse_default_branch_commit_count({"data": {"repository": {"defaultBranchRef": None}}}) is None
    assert parse_default_branch_commit_count(None) is None


def test_count_closed_issue_nodes_in_window_counts_closed_at_only() -> None:
    counts = count_closed_issue_nodes_in_window(
        [
            {"closedAt": "2024-01-01T00:00:00Z"},
            {"closedAt": "2025-12-31T23:59:59Z"},
            {"closedAt": "2026-01-01T00:00:00Z"},
            {"closedAt": None},
            {"closedAt": "not-a-date"},
        ],
        study_window_start="2024-01-01",
        study_window_end="2025-12-31",
    )

    assert counts == {
        "raw_issue_count": 5,
        "closed_issue_count_in_window": 2,
        "missing_closed_at_count": 2,
        "outside_window_count": 1,
    }


def test_language_stats_serialization_is_json_and_normalized() -> None:
    serialized = serialize_language_stats({"TypeScript": "700", "CSS": 300, "Bad": "NaN"})

    assert serialized == '{"CSS":300,"TypeScript":700}'


def test_build_enrichment_result_row_normalizes_contract_fields() -> None:
    row = build_enrichment_result_row(
        make_candidate_row(),
        language_bytes={"TypeScript": 800, "JavaScript": 200},
        target_language="TypeScript",
        language_threshold=0.70,
        default_branch_commit_count="55",
        closed_issue_count="9",
    )

    assert row["repository_full_name"] == "example/repo"
    assert row["target_language_bytes"] == 800
    assert row["total_language_bytes"] == 1000
    assert row["target_language_share"] == 0.8
    assert row["language_threshold_pass"] is True
    assert row["default_branch_commit_count_in_window"] == 55
    assert row["closed_issue_count_in_window"] == 9
    assert row["closed_issue_count_available"] is True
    assert row["enrichment_status"] == "enriched"


def test_serialize_enrichment_row_converts_language_stats_for_csv() -> None:
    row = build_enrichment_result_row(
        make_candidate_row(),
        language_bytes={"TypeScript": 800, "JavaScript": 200},
        target_language="TypeScript",
        language_threshold=0.70,
        default_branch_commit_count=55,
    )

    serialized = serialize_enrichment_row(row)

    assert serialized["language_stats"] == '{"JavaScript":200,"TypeScript":800}'
    assert serialized["closed_issue_count_in_window"] is None
    assert serialized["closed_issue_count_available"] is False


def test_build_enrichment_failure_record_preserves_traceability() -> None:
    record = build_enrichment_failure_record(
        candidate_row=make_candidate_row(),
        stage="language_stats",
        error=ValueError("missing language payload"),
        target_language="TypeScript",
    )

    assert record["stage"] == "language_stats"
    assert record["repository_full_name"] == "example/repo"
    assert record["language_group"] == "TypeScript"
    assert record["target_language"] == "TypeScript"
    assert record["error_type"] == "ValueError"
    assert record["message"] == "missing language payload"
    assert record["source_record_index"] == "7"


def test_build_enrichment_summary_counts_results_and_failures() -> None:
    result_rows = [
        build_enrichment_result_row(
            make_candidate_row(full_name="example/pass"),
            language_bytes={"TypeScript": 800, "JavaScript": 200},
            target_language="TypeScript",
            language_threshold=0.70,
            default_branch_commit_count=80,
            closed_issue_count=6,
        ),
        build_enrichment_result_row(
            make_candidate_row(full_name="example/fail"),
            language_bytes={"TypeScript": 500, "JavaScript": 500},
            target_language="TypeScript",
            language_threshold=0.70,
            default_branch_commit_count=40,
        ),
    ]
    failures = [
        build_enrichment_failure_record(
            candidate_row=make_candidate_row(full_name="example/error"),
            stage="commit_count",
            error=RuntimeError("temporary failure"),
        )
    ]

    summary = build_enrichment_summary(
        input_files=["typescript_candidates_filtered.csv"],
        output_files={"results_csv": "candidate_enrichment_results.csv"},
        result_rows=result_rows,
        failure_records=failures,
        language_threshold=0.70,
    )

    assert summary["repositories_seen"] == 3
    assert summary["repositories_enriched"] == 2
    assert summary["repositories_failed"] == 1
    assert summary["language_threshold_pass_count"] == 1
    assert summary["closed_issue_count_available_count"] == 1
    assert summary["counts_by_language"] == {"TypeScript": 2}
    assert summary["language_threshold_pass_by_language"] == {"TypeScript": 1}
