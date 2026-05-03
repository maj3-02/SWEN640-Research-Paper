from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping


FIELD_REPOSITORY_FULL_NAME = "repository_full_name"
FIELD_LANGUAGE_GROUP = "language_group"
FIELD_TARGET_LANGUAGE_SHARE = "target_language_share"
FIELD_COMMIT_COUNT = "default_branch_commit_count_in_window"
FIELD_CLOSED_ISSUE_COUNT = "closed_issue_count_in_window"
FIELD_QUALITY_SCREEN_PASS = "quality_screen_pass"
FIELD_LANGUAGE_THRESHOLD_PASS = "language_threshold_pass"
FIELD_COMMIT_THRESHOLD_PASS = "commit_threshold_pass"
FIELD_CLOSED_ISSUE_THRESHOLD_PASS = "closed_issue_threshold_pass"
FIELD_PRE_SAMPLING_ELIGIBLE = "pre_sampling_eligible"
FIELD_PRE_SAMPLING_EXCLUSION_REASONS = "pre_sampling_exclusion_reasons"

# Intended row-level contract for the final-study pre-sampling eligibility artifact.
# Later screen scripts should write at least these fields for every enriched candidate.
PRE_SAMPLING_ELIGIBILITY_FIELDS = [
    FIELD_REPOSITORY_FULL_NAME,
    FIELD_LANGUAGE_GROUP,
    FIELD_TARGET_LANGUAGE_SHARE,
    FIELD_COMMIT_COUNT,
    FIELD_CLOSED_ISSUE_COUNT,
    FIELD_QUALITY_SCREEN_PASS,
    FIELD_LANGUAGE_THRESHOLD_PASS,
    FIELD_COMMIT_THRESHOLD_PASS,
    FIELD_CLOSED_ISSUE_THRESHOLD_PASS,
    FIELD_PRE_SAMPLING_ELIGIBLE,
    FIELD_PRE_SAMPLING_EXCLUSION_REASONS,
]

REASON_MISSING_REPOSITORY_FULL_NAME = "missing_repository_full_name"
REASON_TARGET_LANGUAGE_SHARE_MISSING = "target_language_share_missing"
REASON_LANGUAGE_THRESHOLD_FAILED = "language_threshold_failed"
REASON_COMMIT_COUNT_MISSING = "default_branch_commit_count_missing"
REASON_COMMIT_THRESHOLD_FAILED = "commit_threshold_failed"
REASON_CLOSED_ISSUE_COUNT_MISSING = "closed_issue_count_missing"
REASON_CLOSED_ISSUE_THRESHOLD_FAILED = "closed_issue_threshold_failed"
REASON_QUALITY_SCREEN_MISSING = "quality_screen_missing"
REASON_QUALITY_SCREEN_FAILED = "quality_screen_failed"


@dataclass(frozen=True)
class PreSamplingEligibilityThresholds:
    language_threshold: float = 0.70
    min_commits_in_window: int = 50
    min_closed_issues_in_window: int = 5


def thresholds_from_config(config: Mapping[str, Any]) -> PreSamplingEligibilityThresholds:
    return PreSamplingEligibilityThresholds(
        language_threshold=float(config.get("language_threshold", 0.70)),
        min_commits_in_window=int(config.get("min_commits_in_window", 50)),
        min_closed_issues_in_window=int(config.get("min_closed_issues_in_window", 5)),
    )


def parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def repository_full_name(row: Mapping[str, Any]) -> str:
    return str(row.get(FIELD_REPOSITORY_FULL_NAME) or row.get("full_name") or "").strip()


def passes_language_threshold(
    row: Mapping[str, Any],
    *,
    language_threshold: float,
) -> bool:
    share = parse_float(row.get(FIELD_TARGET_LANGUAGE_SHARE))
    return share is not None and share >= language_threshold


def passes_commit_threshold(
    row: Mapping[str, Any],
    *,
    min_commits_in_window: int,
) -> bool:
    count = parse_int(row.get(FIELD_COMMIT_COUNT))
    return count is not None and count >= min_commits_in_window


def passes_closed_issue_threshold(
    row: Mapping[str, Any],
    *,
    min_closed_issues_in_window: int,
) -> bool:
    count = parse_int(row.get(FIELD_CLOSED_ISSUE_COUNT))
    return count is not None and count >= min_closed_issues_in_window


def passes_quality_screen(row: Mapping[str, Any]) -> bool:
    return parse_bool(row.get(FIELD_QUALITY_SCREEN_PASS)) is True


def build_pre_sampling_exclusion_reasons(
    row: Mapping[str, Any],
    *,
    thresholds: PreSamplingEligibilityThresholds,
) -> list[str]:
    reasons: list[str] = []

    if not repository_full_name(row):
        reasons.append(REASON_MISSING_REPOSITORY_FULL_NAME)

    language_share = parse_float(row.get(FIELD_TARGET_LANGUAGE_SHARE))
    if language_share is None:
        reasons.append(REASON_TARGET_LANGUAGE_SHARE_MISSING)
    elif language_share < thresholds.language_threshold:
        reasons.append(REASON_LANGUAGE_THRESHOLD_FAILED)

    commit_count = parse_int(row.get(FIELD_COMMIT_COUNT))
    if commit_count is None:
        reasons.append(REASON_COMMIT_COUNT_MISSING)
    elif commit_count < thresholds.min_commits_in_window:
        reasons.append(REASON_COMMIT_THRESHOLD_FAILED)

    closed_issue_count = parse_int(row.get(FIELD_CLOSED_ISSUE_COUNT))
    if closed_issue_count is None:
        reasons.append(REASON_CLOSED_ISSUE_COUNT_MISSING)
    elif closed_issue_count < thresholds.min_closed_issues_in_window:
        reasons.append(REASON_CLOSED_ISSUE_THRESHOLD_FAILED)

    quality_pass = parse_bool(row.get(FIELD_QUALITY_SCREEN_PASS))
    if quality_pass is None:
        reasons.append(REASON_QUALITY_SCREEN_MISSING)
    elif quality_pass is not True:
        reasons.append(REASON_QUALITY_SCREEN_FAILED)

    return reasons


def is_pre_sampling_eligible(
    row: Mapping[str, Any],
    *,
    thresholds: PreSamplingEligibilityThresholds,
) -> bool:
    return not build_pre_sampling_exclusion_reasons(row, thresholds=thresholds)


def build_pre_sampling_eligibility_row(
    row: Mapping[str, Any],
    *,
    thresholds: PreSamplingEligibilityThresholds,
) -> dict[str, Any]:
    reasons = build_pre_sampling_exclusion_reasons(row, thresholds=thresholds)
    quality_pass = passes_quality_screen(row)
    return {
        FIELD_REPOSITORY_FULL_NAME: repository_full_name(row),
        FIELD_LANGUAGE_GROUP: row.get(FIELD_LANGUAGE_GROUP, ""),
        FIELD_TARGET_LANGUAGE_SHARE: parse_float(row.get(FIELD_TARGET_LANGUAGE_SHARE)),
        FIELD_COMMIT_COUNT: parse_int(row.get(FIELD_COMMIT_COUNT)),
        FIELD_CLOSED_ISSUE_COUNT: parse_int(row.get(FIELD_CLOSED_ISSUE_COUNT)),
        FIELD_QUALITY_SCREEN_PASS: quality_pass,
        FIELD_LANGUAGE_THRESHOLD_PASS: passes_language_threshold(
            row,
            language_threshold=thresholds.language_threshold,
        ),
        FIELD_COMMIT_THRESHOLD_PASS: passes_commit_threshold(
            row,
            min_commits_in_window=thresholds.min_commits_in_window,
        ),
        FIELD_CLOSED_ISSUE_THRESHOLD_PASS: passes_closed_issue_threshold(
            row,
            min_closed_issues_in_window=thresholds.min_closed_issues_in_window,
        ),
        FIELD_PRE_SAMPLING_ELIGIBLE: not reasons,
        FIELD_PRE_SAMPLING_EXCLUSION_REASONS: ";".join(reasons),
    }


def build_pre_sampling_eligibility_summary(
    rows: list[Mapping[str, Any]],
    *,
    thresholds: PreSamplingEligibilityThresholds,
) -> dict[str, Any]:
    eligibility_rows = [
        build_pre_sampling_eligibility_row(row, thresholds=thresholds)
        for row in rows
    ]
    reason_counts: Counter[str] = Counter()
    eligible_by_language: Counter[str] = Counter()

    for row in eligibility_rows:
        reasons = str(row[FIELD_PRE_SAMPLING_EXCLUSION_REASONS] or "")
        for reason in [value for value in reasons.split(";") if value]:
            reason_counts[reason] += 1
        if row[FIELD_PRE_SAMPLING_ELIGIBLE] is True:
            eligible_by_language[str(row.get(FIELD_LANGUAGE_GROUP) or "")] += 1

    return {
        "summary_type": "pre_sampling_eligibility",
        "intended_use": "final_sample_only",
        "thresholds": {
            "language_threshold": thresholds.language_threshold,
            "min_commits_in_window": thresholds.min_commits_in_window,
            "min_closed_issues_in_window": thresholds.min_closed_issues_in_window,
        },
        "rows_seen": len(eligibility_rows),
        "language_threshold_pass_count": sum(
            1 for row in eligibility_rows if row[FIELD_LANGUAGE_THRESHOLD_PASS] is True
        ),
        "commit_threshold_pass_count": sum(
            1 for row in eligibility_rows if row[FIELD_COMMIT_THRESHOLD_PASS] is True
        ),
        "closed_issue_threshold_pass_count": sum(
            1 for row in eligibility_rows if row[FIELD_CLOSED_ISSUE_THRESHOLD_PASS] is True
        ),
        "quality_screen_pass_count": sum(
            1 for row in eligibility_rows if row[FIELD_QUALITY_SCREEN_PASS] is True
        ),
        "pre_sampling_eligible_count": sum(
            1 for row in eligibility_rows if row[FIELD_PRE_SAMPLING_ELIGIBLE] is True
        ),
        "pre_sampling_eligible_by_language": dict(eligible_by_language),
        "exclusion_reason_counts": dict(reason_counts),
    }
