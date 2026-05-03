from __future__ import annotations

from scripts.utils.candidate_filtering import (
    build_exclusion_log_row,
    build_filtered_candidate_row,
    classify_repository_record,
    detect_manual_review_matches,
    can_validate_language_threshold,
)


def make_record(**overrides):
    record = {
        "id": 1,
        "full_name": "example/example",
        "name": "example",
        "description": "A sample repository",
        "language": "JavaScript",
        "archived": False,
        "fork": False,
        "has_issues": True,
        "private": False,
        "owner": {"login": "example", "type": "User"},
        "license": {"spdx_id": "MIT"},
    }
    record.update(overrides)
    return record


def test_classify_repository_record_excludes_archived_repos() -> None:
    reason_code, reason_detail = classify_repository_record(make_record(archived=True), expected_language="JavaScript")

    assert reason_code == "archived"
    assert "archived" in reason_detail


def test_classify_repository_record_excludes_forks() -> None:
    reason_code, reason_detail = classify_repository_record(make_record(fork=True), expected_language="JavaScript")

    assert reason_code == "fork"
    assert "fork" in reason_detail


def test_classify_repository_record_excludes_issues_disabled_repos() -> None:
    reason_code, reason_detail = classify_repository_record(make_record(has_issues=False), expected_language="JavaScript")

    assert reason_code == "issues_disabled"
    assert "has_issues" in reason_detail


def test_classify_repository_record_excludes_language_group_mismatches() -> None:
    reason_code, reason_detail = classify_repository_record(make_record(language="TypeScript"), expected_language="JavaScript")

    assert reason_code == "language_group_mismatch"
    assert "TypeScript" in reason_detail


def test_manual_review_cue_detection_flags_template_like_repos() -> None:
    matches = detect_manual_review_matches(
        make_record(name="starter-template", description="Boilerplate example"),
        cues=["template", "boilerplate", "starter", "tutorial", "example", "awesome"],
    )

    assert {match["matched_cue"] for match in matches} >= {"template", "boilerplate", "starter", "example"}
    assert {match["matched_field"] for match in matches} == {"name", "description", "full_name"}


def test_language_threshold_validation_is_deferred_without_breakdown() -> None:
    assert can_validate_language_threshold({"repositories": [make_record()]}) is False


def test_filtered_candidate_row_includes_manual_review_columns() -> None:
    row = build_filtered_candidate_row(
        make_record(),
        language_group="JavaScript",
        manual_review_matches=[],
        source_file="data/raw/candidate_repos/javascript_candidates_raw.json",
        source_record_index=0,
    )

    assert row["language_group"] == "JavaScript"
    assert row["manual_review_flag"] is False
    assert row["source_file"].endswith("javascript_candidates_raw.json")
    assert row["source_record_index"] == 0


def test_exclusion_log_row_includes_required_fields() -> None:
    row = build_exclusion_log_row(
        make_record(),
        language_group="JavaScript",
        exclusion_reason_code="archived",
        exclusion_reason_detail="archived field is true",
        source_file="data/raw/candidate_repos/javascript_candidates_raw.json",
        source_record_index=2,
        timestamp="2026-04-15T00:00:00Z",
    )

    assert row["exclusion_reason_code"] == "archived"
    assert row["source_record_index"] == 2
