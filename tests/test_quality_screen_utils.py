from __future__ import annotations

from scripts.utils.quality_screen import (
    build_quality_signal_snapshot,
    detect_ci_paths,
    detect_community_health_paths,
    detect_test_paths,
    evaluate_quality_screen,
    has_recent_push,
    recent_push_cutoff,
)


def make_candidate_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "language_group": "JavaScript",
        "manual_review_flag": False,
        "full_name": "example/repo",
        "pushed_at": "2025-08-01T00:00:00Z",
        "open_issues_count": 12,
        "source_file": "data/interim/filtered_candidates/javascript_candidates_filtered.csv",
        "source_record_index": 0,
        "default_branch": "main",
    }
    row.update(overrides)
    return row


def test_recent_push_cutoff_uses_last_year_of_study_window() -> None:
    assert recent_push_cutoff("2025-12-31", 365).isoformat() == "2025-01-01"

    recent, cutoff = has_recent_push(
        "2025-01-01T00:00:00Z",
        study_window_end="2025-12-31",
        lookback_days=365,
    )
    assert recent is True
    assert cutoff == "2025-01-01"


def test_signal_detection_finds_tests_ci_and_community_files() -> None:
    paths = [
        "src/index.ts",
        "tests/unit/example.test.ts",
        ".github/workflows/ci.yml",
        "CONTRIBUTING.md",
    ]

    has_tests, matched_tests = detect_test_paths(paths)
    has_ci, matched_ci = detect_ci_paths(paths)
    has_community, matched_community = detect_community_health_paths(paths)

    assert has_tests is True
    assert matched_tests == ["tests/unit/example.test.ts"]
    assert has_ci is True
    assert matched_ci == [".github/workflows/ci.yml"]
    assert has_community is True
    assert matched_community == ["CONTRIBUTING.md"]


def test_evaluate_quality_screen_passes_when_three_of_four_checks_are_met() -> None:
    snapshot = build_quality_signal_snapshot(
        repository_full_name="example/repo",
        default_branch="main",
        tree_payload={
            "sha": "abc123",
            "truncated": False,
            "tree": [
                {"path": "tests/unit/example.test.ts"},
                {"path": ".github/workflows/ci.yml"},
            ],
        },
    )

    result = evaluate_quality_screen(
        make_candidate_row(open_issues_count=1),
        signal_snapshot=snapshot,
        study_window_end="2025-12-31",
        recent_push_lookback_days=365,
        min_open_issues_count=5,
        minimum_score=3,
        signal_snapshot_file="data/raw/repo_metadata/example_repo_quality_screen_snapshot.json",
    )

    assert result["quality_screen_pass"] is True
    assert result["quality_screen_score"] == 3
    assert result["quality_check_not_manual_review_flagged"] is True
    assert result["quality_check_recent_maintenance"] is True
    assert result["quality_check_issue_usage"] is False
    assert result["quality_check_engineering_workflow"] is True


def test_evaluate_quality_screen_fails_when_only_two_checks_are_met() -> None:
    snapshot = build_quality_signal_snapshot(
        repository_full_name="example/repo",
        default_branch="main",
        tree_payload={
            "sha": "abc123",
            "truncated": False,
            "tree": [
                {"path": "README.md"},
            ],
        },
    )

    result = evaluate_quality_screen(
        make_candidate_row(manual_review_flag=True, open_issues_count=2),
        signal_snapshot=snapshot,
        study_window_end="2025-12-31",
        recent_push_lookback_days=365,
        min_open_issues_count=5,
        minimum_score=3,
        signal_snapshot_file="data/raw/repo_metadata/example_repo_quality_screen_snapshot.json",
    )

    assert result["quality_screen_pass"] is False
    assert result["quality_screen_score"] == 1
    assert "quality_check_failed:not_manual_review_flagged" in result["quality_screen_failure_reasons"]
    assert "quality_check_failed:issue_usage" in result["quality_screen_failure_reasons"]
    assert "quality_check_failed:engineering_workflow" in result["quality_screen_failure_reasons"]
