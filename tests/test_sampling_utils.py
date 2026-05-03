from __future__ import annotations

from scripts.utils.sampling import (
    ACTIVITY_STRATA,
    allocate_targets,
    assign_activity_strata,
    assign_numeric_activity_strata,
    build_sampling_metadata,
    draw_reserves_by_language_stratum,
    draw_stratified_sample_numeric_activity,
    draw_stratified_sample,
    parse_numeric_activity_value,
)


def make_row(language_group: str, full_name: str, pushed_at: str) -> dict[str, object]:
    return {
        "language_group": language_group,
        "full_name": full_name,
        "pushed_at": pushed_at,
        "name": full_name.split("/")[-1],
        "manual_review_flag": False,
        "manual_review_cues": "",
        "manual_review_fields": "",
    }


def test_assign_activity_strata_creates_three_buckets_per_language() -> None:
    rows = [
        make_row("JavaScript", f"js/repo-{index}", f"2026-04-{index:02d}T00:00:00Z")
        for index in range(1, 7)
    ]
    rows.extend(
        make_row("TypeScript", f"ts/repo-{index}", f"2026-03-{index:02d}T00:00:00Z")
        for index in range(1, 7)
    )

    stratified = assign_activity_strata(rows, activity_field="pushed_at", activity_field_is_proxy=True)

    js_counts = {stratum: 0 for stratum in ACTIVITY_STRATA}
    ts_counts = {stratum: 0 for stratum in ACTIVITY_STRATA}
    for row in stratified:
        if row["language_group"] == "JavaScript":
            js_counts[row["activity_stratum"]] += 1
        else:
            ts_counts[row["activity_stratum"]] += 1

    assert list(js_counts.values()) == [2, 2, 2]
    assert list(ts_counts.values()) == [2, 2, 2]


def test_assign_numeric_activity_strata_uses_commit_counts_without_datetime_parsing() -> None:
    rows = [
        {"language_group": "JavaScript", "repository_full_name": "js/high", "default_branch_commit_count_in_window": "90"},
        {"language_group": "JavaScript", "repository_full_name": "js/medium", "default_branch_commit_count_in_window": "50"},
        {"language_group": "JavaScript", "repository_full_name": "js/low", "default_branch_commit_count_in_window": "10"},
    ]

    stratified = assign_numeric_activity_strata(
        rows,
        activity_field="default_branch_commit_count_in_window",
        activity_field_is_proxy=False,
    )

    strata_by_repo = {row["repository_full_name"]: row["activity_stratum"] for row in stratified}
    assert strata_by_repo == {"js/high": "high", "js/medium": "medium", "js/low": "low"}
    assert all(row["activity_field_is_proxy"] is False for row in stratified)
    assert all(isinstance(row["activity_value"], int) for row in stratified)


def test_parse_numeric_activity_value_rejects_malformed_values() -> None:
    assert parse_numeric_activity_value("42") == 42

    for value in ["", "not-a-number", "-1", None]:
        try:
            parse_numeric_activity_value(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected {value!r} to be rejected")


def test_allocate_targets_prefers_balance_with_extra_sample() -> None:
    targets = allocate_targets({"high": 4, "medium": 4, "low": 4}, 4)

    assert sum(targets.values()) == 4
    assert sorted(targets.values(), reverse=True) == [2, 1, 1]


def test_draw_stratified_sample_is_reproducible_and_language_balanced() -> None:
    rows = []
    for language_group, prefix in [("JavaScript", "js"), ("TypeScript", "ts")]:
        for index in range(1, 7):
            rows.append(make_row(language_group, f"{prefix}/repo-{index}", f"2026-04-{index:02d}T00:00:00Z"))

    stratified = assign_activity_strata(rows, activity_field="pushed_at", activity_field_is_proxy=True)
    selected_a, metadata_a = draw_stratified_sample(stratified, sample_per_language=4, random_seed=640)
    selected_b, metadata_b = draw_stratified_sample(stratified, sample_per_language=4, random_seed=640)

    assert [row["full_name"] for row in selected_a] == [row["full_name"] for row in selected_b]
    assert metadata_a["selected_counts_by_language"] == {"JavaScript": 4, "TypeScript": 4}
    assert metadata_b["selected_counts_by_language"] == {"JavaScript": 4, "TypeScript": 4}


def test_draw_numeric_sample_and_reserves_do_not_overlap() -> None:
    rows = []
    for language_group, prefix in [("JavaScript", "js"), ("TypeScript", "ts")]:
        for index in range(1, 10):
            rows.append(
                {
                    "language_group": language_group,
                    "repository_full_name": f"{prefix}/repo-{index}",
                    "default_branch_commit_count_in_window": str(100 - index),
                }
            )

    stratified = assign_numeric_activity_strata(
        rows,
        activity_field="default_branch_commit_count_in_window",
        activity_field_is_proxy=False,
    )
    selected, selection_metadata = draw_stratified_sample_numeric_activity(
        stratified,
        sample_per_language=3,
        random_seed=640,
    )
    reserves, reserve_metadata = draw_reserves_by_language_stratum(
        stratified,
        selected_rows=selected,
        reserve_per_language_stratum=1,
        random_seed=640,
    )

    selected_names = {row["repository_full_name"] for row in selected}
    reserve_names = {row["repository_full_name"] for row in reserves}
    assert selected_names.isdisjoint(reserve_names)
    assert selection_metadata["selected_counts_by_language"] == {"JavaScript": 3, "TypeScript": 3}
    assert reserve_metadata["reserve_repository_count"] == 6
    assert reserve_metadata["reserve_shortfalls_by_language_and_stratum"]["JavaScript"] == {"high": 0, "medium": 0, "low": 0}


def test_build_sampling_metadata_records_proxy_and_balancing_notes() -> None:
    rows = [make_row("JavaScript", "js/repo-1", "2026-04-01T00:00:00Z")]
    stratified = assign_activity_strata(rows, activity_field="pushed_at", activity_field_is_proxy=True)
    metadata = build_sampling_metadata(
        input_files=["data/interim/filtered_candidates/javascript_candidates_filtered.csv"],
        activity_field_used="pushed_at",
        activity_field_is_proxy=True,
        activity_field_note="Used pushed_at as a proxy for recent activity.",
        sample_per_language=4,
        random_seed=640,
        stratified_rows=stratified,
        selected_rows=stratified,
        selection_metadata={
            "selected_counts_by_language": {"JavaScript": 1},
            "selected_counts_by_stratum": {"high": 1, "medium": 0, "low": 0},
            "selected_counts_by_language_and_stratum": {"JavaScript": {"high": 1, "medium": 0, "low": 0}},
        },
    )

    assert metadata["activity_field_used"] == "pushed_at"
    assert metadata["activity_field_is_proxy"] is True
    assert metadata["language_balance_rule"] == "exact"
    assert metadata["strata_balance_rule"] == "as balanced as possible"
