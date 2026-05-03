from __future__ import annotations

from scripts.sample.draw_final_sample import (
    build_final_sample_metadata,
    build_pool_sufficiency_report,
    load_eligible_candidate_pool_rows,
    select_sample_size_from_sufficiency,
)
from scripts.utils.sampling import assign_numeric_activity_strata, draw_reserves_by_language_stratum, draw_stratified_sample_numeric_activity


def make_enriched_row(language: str, index: int, commits: int) -> dict[str, object]:
    slug = "js" if language == "JavaScript" else "ts"
    return {
        "repository_full_name": f"{slug}/repo-{index}",
        "language_group": language,
        "enrichment_status": "enriched",
        "language_threshold_pass": "True",
        "pre_sampling_eligible": "True",
        "default_branch_commit_count_in_window": str(commits),
    }


def test_pool_sufficiency_uses_fallback_when_target_plus_reserves_is_not_clean() -> None:
    rows = []
    for language in ["JavaScript", "TypeScript"]:
        for index in range(1, 10):
            rows.append(make_enriched_row(language, index, 100 - index))
    stratified = assign_numeric_activity_strata(
        rows,
        activity_field="default_branch_commit_count_in_window",
        activity_field_is_proxy=False,
    )

    report = build_pool_sufficiency_report(
        stratified_rows=stratified,
        invalid_rows=[],
        languages=["JavaScript", "TypeScript"],
        target_sample_per_language=7,
        fallback_sample_per_language=3,
        reserve_per_language_stratum=1,
        activity_field="default_branch_commit_count_in_window",
        input_files=["javascript_candidates_enriched.csv", "typescript_candidates_enriched.csv"],
    )

    selected_size, fallback_used = select_sample_size_from_sufficiency(
        report,
        target_sample_per_language=7,
        fallback_sample_per_language=3,
    )

    assert report["target"]["sample_possible"] is True
    assert report["target"]["sample_plus_reserves_possible"] is False
    assert report["fallback"]["sample_plus_reserves_possible"] is True
    assert report["selected_plan"] == "fallback"
    assert selected_size == 3
    assert fallback_used is True


def test_pool_sufficiency_rejects_pool_below_fallback() -> None:
    rows = [
        make_enriched_row("JavaScript", 1, 10),
        make_enriched_row("TypeScript", 1, 10),
    ]
    stratified = assign_numeric_activity_strata(
        rows,
        activity_field="default_branch_commit_count_in_window",
        activity_field_is_proxy=False,
    )
    report = build_pool_sufficiency_report(
        stratified_rows=stratified,
        invalid_rows=[],
        languages=["JavaScript", "TypeScript"],
        target_sample_per_language=3,
        fallback_sample_per_language=2,
        reserve_per_language_stratum=1,
        activity_field="default_branch_commit_count_in_window",
        input_files=[],
    )

    try:
        select_sample_size_from_sufficiency(
            report,
            target_sample_per_language=3,
            fallback_sample_per_language=2,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected too-small fallback pool to be rejected")


def test_load_eligible_candidate_pool_rows_filters_invalid_activity_rows(tmp_path) -> None:
    input_dir = tmp_path / "data" / "interim" / "final_candidate_screen"
    input_dir.mkdir(parents=True)
    (input_dir / "final_eligible_candidate_pool.csv").write_text(
        "repository_full_name,language_group,pre_sampling_eligible,default_branch_commit_count_in_window\n"
        "js/good,JavaScript,True,50\n"
        "js/bad,JavaScript,True,not-a-number\n"
        "ts/good,TypeScript,True,60\n",
        encoding="utf-8",
    )

    rows, invalid_rows, input_files = load_eligible_candidate_pool_rows(
        input_dir,
        ["JavaScript", "TypeScript"],
        activity_field="default_branch_commit_count_in_window",
    )

    assert [row["repository_full_name"] for row in rows] == ["js/good", "ts/good"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0]["repository_full_name"] == "js/bad"
    assert input_files == [str(input_dir / "final_eligible_candidate_pool.csv")]


def test_load_eligible_candidate_pool_rows_requires_contract_fields(tmp_path) -> None:
    input_dir = tmp_path / "data" / "interim" / "final_candidate_screen"
    input_dir.mkdir(parents=True)
    (input_dir / "final_eligible_candidate_pool.csv").write_text(
        "repository_full_name,language_group,default_branch_commit_count_in_window\n"
        "js/good,JavaScript,50\n",
        encoding="utf-8",
    )

    try:
        load_eligible_candidate_pool_rows(
            input_dir,
            ["JavaScript", "TypeScript"],
            activity_field="default_branch_commit_count_in_window",
        )
    except ValueError as exc:
        assert "pre_sampling_eligible" in str(exc)
    else:
        raise AssertionError("Expected missing pre_sampling_eligible field to be rejected")


def test_load_eligible_candidate_pool_rows_requires_pre_sampling_eligible_true(tmp_path) -> None:
    input_dir = tmp_path / "data" / "interim" / "final_candidate_screen"
    input_dir.mkdir(parents=True)
    (input_dir / "final_eligible_candidate_pool.csv").write_text(
        "repository_full_name,language_group,pre_sampling_eligible,default_branch_commit_count_in_window\n"
        "js/bad,JavaScript,False,50\n",
        encoding="utf-8",
    )

    try:
        load_eligible_candidate_pool_rows(
            input_dir,
            ["JavaScript", "TypeScript"],
            activity_field="default_branch_commit_count_in_window",
        )
    except ValueError as exc:
        assert "non-eligible row" in str(exc)
        assert "js/bad" in str(exc)
    else:
        raise AssertionError("Expected non-eligible row to be rejected")


def test_final_sample_metadata_records_sample_and_reserve_counts() -> None:
    rows = []
    for language in ["JavaScript", "TypeScript"]:
        for index in range(1, 10):
            rows.append(make_enriched_row(language, index, 100 - index))
    stratified = assign_numeric_activity_strata(
        rows,
        activity_field="default_branch_commit_count_in_window",
        activity_field_is_proxy=False,
    )
    sample_rows, selection_metadata = draw_stratified_sample_numeric_activity(
        stratified,
        sample_per_language=3,
        random_seed=640,
    )
    reserve_rows, reserve_metadata = draw_reserves_by_language_stratum(
        stratified,
        selected_rows=sample_rows,
        reserve_per_language_stratum=1,
        random_seed=640,
    )

    metadata = build_final_sample_metadata(
        input_files=["final_eligible_candidate_pool.csv"],
        output_files={"final_sample_csv": "final_sample.csv"},
        activity_field="default_branch_commit_count_in_window",
        target_sample_per_language=7,
        fallback_sample_per_language=3,
        selected_sample_per_language=3,
        fallback_used=True,
        reserve_per_language_stratum=1,
        random_seed=640,
        stratified_rows=stratified,
        selected_rows=sample_rows,
        reserve_rows=reserve_rows,
        selection_metadata=selection_metadata,
        reserve_metadata=reserve_metadata,
        sufficiency_report={"selected_plan": "fallback"},
    )

    assert metadata["sampling_type"] == "final_study_sample"
    assert metadata["input_source"] == "pre_sampling_eligible_candidate_pool"
    assert metadata["fallback_used"] is True
    assert metadata["actual_sample_size"] == 6
    assert metadata["actual_reserve_size"] == 6
    assert metadata["sample_counts_by_language"] == {"JavaScript": 3, "TypeScript": 3}
