from __future__ import annotations

from scripts.utils.classification import (
    build_classification_run_provenance,
    build_commit_validation_sample_rows,
    build_issue_validation_sample_rows,
    classify_commit_record,
    classify_issue_record,
    infer_classification_input_kind,
    infer_classification_run_type,
    parse_bool,
    sample_manifest_row_trace,
    sample_rows,
)


def _commit_record(message: str) -> dict:
    return {
        "sha": "abc123",
        "commit": {
            "message": message,
            "author": {"name": "Alice", "email": "alice@example.com", "date": "2024-01-01T00:00:00Z"},
            "committer": {"name": "Alice", "email": "alice@example.com", "date": "2024-01-01T00:00:00Z"},
        },
        "author": {"login": "alice"},
    }


def _issue_record(*, title: str, body: str, labels: list[dict[str, str]] | None = None) -> dict:
    return {
        "id": "ISSUE-1",
        "number": 1,
        "title": title,
        "body": body,
        "state": "CLOSED",
        "closedAt": "2024-01-02T00:00:00Z",
        "author": {"login": "bob"},
        "labels": {"nodes": labels or []},
    }


def test_classify_commit_record_matches_required_and_provisional_terms() -> None:
    row = classify_commit_record(
        _commit_record("Fix bug issue in parser"),
        repository_full_name="example/repo",
        language_group="JavaScript",
        source_file="raw.json",
        record_index=0,
        required_terms=["fix"],
        additional_terms=["bug", "error", "defect", "crash", "issue"],
    )

    assert row["is_bug_fix"] is True
    assert row["matched_required_term"] == "fix"
    assert row["matched_additional_terms"] == "bug;issue"
    assert row["provisional_issue_term_used"] is True
    assert row["provisional_issue_term_matched"] == "issue"
    assert row["classification_reason"] == "required_and_additional_term_match"


def test_classify_commit_record_respects_word_boundaries() -> None:
    row = classify_commit_record(
        _commit_record("fixes bugs in the parser"),
        repository_full_name="example/repo",
        language_group="JavaScript",
        source_file="raw.json",
        record_index=0,
        required_terms=["fix"],
        additional_terms=["bug", "error", "defect", "crash", "issue"],
    )

    assert row["is_bug_fix"] is False
    assert row["matched_required_term"] == ""
    assert row["matched_additional_terms"] == ""
    assert row["classification_reason"] == "no_bug_fix_terms"


def test_classify_issue_record_matches_label_and_text_sources() -> None:
    row = classify_issue_record(
        _issue_record(
            title="Resolve error in parser",
            body="The bug affects tokenization.",
            labels=[{"name": "bug"}],
        ),
        repository_full_name="example/repo",
        language_group="TypeScript",
        source_file="raw.json",
        record_index=0,
        label_terms=["bug"],
        text_terms=["bug", "error", "crash", "defect", "failure"],
    )

    assert row["is_bug_related"] is True
    assert row["matched_label_terms"] == "bug"
    assert row["matched_text_terms"] == "error;bug"
    assert row["match_source"] == "label;title;body"
    assert row["classification_reason"] == "label_and_text_match"


def test_classify_issue_record_respects_word_boundaries() -> None:
    row = classify_issue_record(
        _issue_record(title="debugging improvements", body="noise", labels=[{"name": "documentation"}]),
        repository_full_name="example/repo",
        language_group="TypeScript",
        source_file="raw.json",
        record_index=0,
        label_terms=["bug"],
        text_terms=["bug", "error", "crash", "defect", "failure"],
    )

    assert row["is_bug_related"] is False
    assert row["matched_label_terms"] == ""
    assert row["matched_text_terms"] == ""
    assert row["classification_reason"] == "no_bug_terms"


def test_parse_bool_handles_common_manifest_values() -> None:
    assert parse_bool("True") is True
    assert parse_bool(True) is True
    assert parse_bool("False") is False
    assert parse_bool(None) is False


def test_classification_run_type_inference_for_final_and_custom_paths(tmp_path) -> None:
    final = tmp_path / "data" / "interim" / "final_sample" / "final_sample.csv"
    custom = tmp_path / "eligibility.csv"

    assert build_classification_run_provenance(final)["classification_run_type"] == "final_study"
    assert build_classification_run_provenance(final)["classification_input_kind"] == "sample_manifest"
    assert infer_classification_input_kind(final) == "sample_manifest"
    assert infer_classification_run_type(custom) == "custom"


def test_sample_manifest_row_trace_uses_final_sampling_fields() -> None:
    trace = sample_manifest_row_trace(
        {
            "final_sampling_input_file": "data/interim/final_candidate_screen/final_eligible_candidate_pool.csv",
            "final_sampling_input_record_index": "9",
            "final_sampling_role": "final_sample",
            "activity_stratum": "medium",
            "default_branch_commit_count_in_window": "120",
        }
    )

    assert trace["sample_source_file"].endswith("final_eligible_candidate_pool.csv")
    assert trace["sample_source_record_index"] == "9"
    assert trace["sample_role"] == "final_sample"
    assert trace["sample_activity_stratum"] == "medium"
    assert trace["sample_activity_value"] == "120"


def test_sample_rows_is_deterministic() -> None:
    rows = [{"index": str(index)} for index in range(10)]
    first = sample_rows(rows, 4, seed=640)
    second = sample_rows(rows, 4, seed=640)

    assert first == second


def test_build_commit_validation_sample_rows_includes_positive_and_borderline_rows() -> None:
    classified_rows = [
        {
            "repository_full_name": "example/repo",
            "commit_sha": "p1",
            "source_file": "raw.json",
            "raw_record_index": 0,
            "is_bug_fix": True,
            "matched_required_term": "fix",
            "matched_additional_terms": "bug;issue",
            "provisional_issue_term_used": True,
        },
        {
            "repository_full_name": "example/repo",
            "commit_sha": "p2",
            "source_file": "raw.json",
            "raw_record_index": 1,
            "is_bug_fix": True,
            "matched_required_term": "fix",
            "matched_additional_terms": "bug",
            "provisional_issue_term_used": False,
        },
        {
            "repository_full_name": "example/repo",
            "commit_sha": "b1",
            "source_file": "raw.json",
            "raw_record_index": 2,
            "is_bug_fix": False,
            "matched_required_term": "fix",
            "matched_additional_terms": "",
            "provisional_issue_term_used": False,
        },
        {
            "repository_full_name": "example/repo",
            "commit_sha": "c1",
            "source_file": "raw.json",
            "raw_record_index": 3,
            "is_bug_fix": False,
            "matched_required_term": "",
            "matched_additional_terms": "",
            "provisional_issue_term_used": False,
        },
    ]

    sample = build_commit_validation_sample_rows(classified_rows, sample_size=4, positive_target=2, seed=640)
    categories = {row["validation_sample_category"] for row in sample}

    assert len(sample) == 4
    assert "positive_provisional" in categories
    assert "positive_standard" in categories
    assert "borderline_keyword" in categories
    assert "control_negative" in categories


def test_build_issue_validation_sample_rows_includes_positive_sources_and_controls() -> None:
    classified_rows = [
        {
            "repository_full_name": "example/repo",
            "issue_id": "i1",
            "issue_number": 1,
            "source_file": "raw.json",
            "raw_record_index": 0,
            "is_bug_related": True,
            "matched_label_terms": "bug",
            "matched_text_terms": "",
            "match_source": "label",
        },
        {
            "repository_full_name": "example/repo",
            "issue_id": "i2",
            "issue_number": 2,
            "source_file": "raw.json",
            "raw_record_index": 1,
            "is_bug_related": True,
            "matched_label_terms": "",
            "matched_text_terms": "error",
            "match_source": "title",
        },
        {
            "repository_full_name": "example/repo",
            "issue_id": "i3",
            "issue_number": 3,
            "source_file": "raw.json",
            "raw_record_index": 2,
            "is_bug_related": True,
            "matched_label_terms": "bug",
            "matched_text_terms": "failure",
            "match_source": "label;body",
        },
        {
            "repository_full_name": "example/repo",
            "issue_id": "i4",
            "issue_number": 4,
            "source_file": "raw.json",
            "raw_record_index": 3,
            "is_bug_related": False,
            "matched_label_terms": "",
            "matched_text_terms": "",
            "match_source": "",
        },
    ]

    sample = build_issue_validation_sample_rows(classified_rows, sample_size=4, positive_target=4, seed=640)
    categories = {row["validation_sample_category"] for row in sample}

    assert len(sample) == 4
    assert "positive_label_only" in categories
    assert "positive_text_only" in categories
    assert "positive_label_and_text" in categories
    assert "control_negative" in categories
