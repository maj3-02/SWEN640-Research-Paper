from __future__ import annotations

from scripts.utils.pre_sampling_eligibility import (
    FIELD_CLOSED_ISSUE_THRESHOLD_PASS,
    FIELD_COMMIT_THRESHOLD_PASS,
    FIELD_LANGUAGE_THRESHOLD_PASS,
    FIELD_PRE_SAMPLING_ELIGIBLE,
    FIELD_PRE_SAMPLING_EXCLUSION_REASONS,
    REASON_CLOSED_ISSUE_COUNT_MISSING,
    REASON_CLOSED_ISSUE_THRESHOLD_FAILED,
    REASON_COMMIT_COUNT_MISSING,
    REASON_COMMIT_THRESHOLD_FAILED,
    REASON_LANGUAGE_THRESHOLD_FAILED,
    REASON_QUALITY_SCREEN_FAILED,
    REASON_QUALITY_SCREEN_MISSING,
    REASON_TARGET_LANGUAGE_SHARE_MISSING,
    PreSamplingEligibilityThresholds,
    build_pre_sampling_eligibility_row,
    build_pre_sampling_eligibility_summary,
    build_pre_sampling_exclusion_reasons,
    passes_closed_issue_threshold,
    passes_commit_threshold,
    passes_language_threshold,
    passes_quality_screen,
    thresholds_from_config,
)


def make_enriched_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "repository_full_name": "example/repo",
        "language_group": "JavaScript",
        "target_language_share": 0.72,
        "default_branch_commit_count_in_window": 60,
        "closed_issue_count_in_window": 8,
        "quality_screen_pass": True,
    }
    row.update(overrides)
    return row


def test_threshold_helpers_pass_at_inclusive_boundaries() -> None:
    row = make_enriched_row(
        target_language_share="0.70",
        default_branch_commit_count_in_window="50",
        closed_issue_count_in_window="5",
        quality_screen_pass="true",
    )

    assert passes_language_threshold(row, language_threshold=0.70) is True
    assert passes_commit_threshold(row, min_commits_in_window=50) is True
    assert passes_closed_issue_threshold(row, min_closed_issues_in_window=5) is True
    assert passes_quality_screen(row) is True


def test_threshold_helpers_fail_below_thresholds() -> None:
    row = make_enriched_row(
        target_language_share=0.69,
        default_branch_commit_count_in_window=49,
        closed_issue_count_in_window=4,
        quality_screen_pass=False,
    )

    assert passes_language_threshold(row, language_threshold=0.70) is False
    assert passes_commit_threshold(row, min_commits_in_window=50) is False
    assert passes_closed_issue_threshold(row, min_closed_issues_in_window=5) is False
    assert passes_quality_screen(row) is False


def test_thresholds_from_config_uses_existing_study_threshold_names() -> None:
    thresholds = thresholds_from_config(
        {
            "language_threshold": 0.75,
            "min_commits_in_window": 80,
            "min_closed_issues_in_window": 12,
        }
    )

    assert thresholds == PreSamplingEligibilityThresholds(
        language_threshold=0.75,
        min_commits_in_window=80,
        min_closed_issues_in_window=12,
    )


def test_exclusion_reasons_distinguish_below_thresholds() -> None:
    thresholds = PreSamplingEligibilityThresholds()
    row = make_enriched_row(
        target_language_share=0.42,
        default_branch_commit_count_in_window=10,
        closed_issue_count_in_window=1,
        quality_screen_pass=False,
    )

    reasons = build_pre_sampling_exclusion_reasons(row, thresholds=thresholds)

    assert reasons == [
        REASON_LANGUAGE_THRESHOLD_FAILED,
        REASON_COMMIT_THRESHOLD_FAILED,
        REASON_CLOSED_ISSUE_THRESHOLD_FAILED,
        REASON_QUALITY_SCREEN_FAILED,
    ]


def test_missing_values_fail_cleanly_with_explicit_reasons() -> None:
    thresholds = PreSamplingEligibilityThresholds()
    row = {
        "repository_full_name": "example/missing",
        "language_group": "TypeScript",
    }

    reasons = build_pre_sampling_exclusion_reasons(row, thresholds=thresholds)

    assert reasons == [
        REASON_TARGET_LANGUAGE_SHARE_MISSING,
        REASON_COMMIT_COUNT_MISSING,
        REASON_CLOSED_ISSUE_COUNT_MISSING,
        REASON_QUALITY_SCREEN_MISSING,
    ]


def test_full_eligibility_row_sets_pass_flags_and_semicolon_reasons() -> None:
    thresholds = PreSamplingEligibilityThresholds()
    row = build_pre_sampling_eligibility_row(
        make_enriched_row(
            full_name="example/fallback-name",
            repository_full_name="",
            target_language_share=0.80,
            default_branch_commit_count_in_window=55,
            closed_issue_count_in_window=3,
            quality_screen_pass="yes",
        ),
        thresholds=thresholds,
    )

    assert row["repository_full_name"] == "example/fallback-name"
    assert row[FIELD_LANGUAGE_THRESHOLD_PASS] is True
    assert row[FIELD_COMMIT_THRESHOLD_PASS] is True
    assert row[FIELD_CLOSED_ISSUE_THRESHOLD_PASS] is False
    assert row["quality_screen_pass"] is True
    assert row[FIELD_PRE_SAMPLING_ELIGIBLE] is False
    assert row[FIELD_PRE_SAMPLING_EXCLUSION_REASONS] == REASON_CLOSED_ISSUE_THRESHOLD_FAILED


def test_full_eligibility_row_passes_when_all_checks_pass() -> None:
    row = build_pre_sampling_eligibility_row(
        make_enriched_row(),
        thresholds=PreSamplingEligibilityThresholds(),
    )

    assert row[FIELD_PRE_SAMPLING_ELIGIBLE] is True
    assert row[FIELD_PRE_SAMPLING_EXCLUSION_REASONS] == ""


def test_summary_counts_rows_and_exclusion_reasons() -> None:
    thresholds = PreSamplingEligibilityThresholds()
    rows = [
        make_enriched_row(language_group="JavaScript"),
        make_enriched_row(
            repository_full_name="example/low-commits",
            language_group="JavaScript",
            default_branch_commit_count_in_window=20,
        ),
        make_enriched_row(
            repository_full_name="example/low-language-and-issues",
            language_group="TypeScript",
            target_language_share=0.4,
            closed_issue_count_in_window=2,
        ),
        make_enriched_row(
            repository_full_name="example/quality-missing",
            language_group="TypeScript",
            quality_screen_pass=None,
        ),
    ]

    summary = build_pre_sampling_eligibility_summary(rows, thresholds=thresholds)

    assert summary["rows_seen"] == 4
    assert summary["language_threshold_pass_count"] == 3
    assert summary["commit_threshold_pass_count"] == 3
    assert summary["closed_issue_threshold_pass_count"] == 3
    assert summary["quality_screen_pass_count"] == 3
    assert summary["pre_sampling_eligible_count"] == 1
    assert summary["pre_sampling_eligible_by_language"] == {"JavaScript": 1}
    assert summary["exclusion_reason_counts"] == {
        REASON_COMMIT_THRESHOLD_FAILED: 1,
        REASON_LANGUAGE_THRESHOLD_FAILED: 1,
        REASON_CLOSED_ISSUE_THRESHOLD_FAILED: 1,
        REASON_QUALITY_SCREEN_MISSING: 1,
    }
