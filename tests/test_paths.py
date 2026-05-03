from __future__ import annotations

from scripts.utils.paths import (
    candidate_output_paths,
    candidate_raw_dir,
    enriched_candidate_language_path,
    enriched_candidate_paths,
    enriched_candidates_dir,
    final_candidate_screen_dir,
    final_candidate_screen_paths,
    final_sample_dir,
    final_sample_paths,
    quality_screened_candidates_dir,
    repo_metrics_dir,
    results_figures_dir,
    results_final_dir,
    results_tables_dir,
    raw_repo_metadata_dir,
)


def test_candidate_raw_dir_points_to_expected_location(tmp_path) -> None:
    assert candidate_raw_dir(tmp_path) == tmp_path / "data" / "raw" / "candidate_repos"


def test_candidate_output_paths_use_expected_filenames(tmp_path) -> None:
    paths = candidate_output_paths("JavaScript", tmp_path)

    assert paths["json"].name == "javascript_candidates_raw.json"
    assert paths["csv"].name == "javascript_candidates_raw.csv"


def test_repo_metrics_dir_points_to_expected_location(tmp_path) -> None:
    assert repo_metrics_dir(tmp_path) == tmp_path / "data" / "processed" / "repo_metrics"


def test_results_directory_helpers_point_to_expected_locations(tmp_path) -> None:
    assert results_tables_dir(tmp_path) == tmp_path / "results" / "tables"
    assert results_figures_dir(tmp_path) == tmp_path / "results" / "figures"
    assert results_final_dir(tmp_path) == tmp_path / "results" / "final"


def test_quality_screen_and_repo_metadata_helpers_point_to_expected_locations(tmp_path) -> None:
    assert quality_screened_candidates_dir(tmp_path) == tmp_path / "data" / "interim" / "quality_screened_candidates"
    assert raw_repo_metadata_dir(tmp_path) == tmp_path / "data" / "raw" / "repo_metadata"


def test_enriched_candidate_helpers_point_to_expected_locations(tmp_path) -> None:
    assert enriched_candidates_dir(tmp_path) == tmp_path / "data" / "interim" / "enriched_candidates"

    paths = enriched_candidate_paths(tmp_path)
    assert paths["results_csv"] == tmp_path / "data" / "interim" / "enriched_candidates" / "candidate_enrichment_results.csv"
    assert paths["failures_json"].name == "candidate_enrichment_failures.json"
    assert paths["summary_json"].name == "candidate_enrichment_summary.json"
    assert enriched_candidate_language_path("TypeScript", tmp_path).name == "typescript_candidates_enriched.csv"


def test_final_sample_helpers_point_to_expected_locations(tmp_path) -> None:
    assert final_sample_dir(tmp_path) == tmp_path / "data" / "interim" / "final_sample"

    paths = final_sample_paths(tmp_path)
    assert paths["candidate_pool_with_strata_csv"].name == "final_candidate_pool_with_strata.csv"
    assert paths["final_sample_csv"].name == "final_sample.csv"
    assert paths["final_reserves_csv"].name == "final_reserves.csv"
    assert paths["metadata_json"].name == "final_sample_metadata.json"
    assert paths["pool_sufficiency_report_json"].name == "pool_sufficiency_report.json"


def test_final_candidate_screen_helpers_point_to_expected_locations(tmp_path) -> None:
    assert final_candidate_screen_dir(tmp_path) == tmp_path / "data" / "interim" / "final_candidate_screen"

    paths = final_candidate_screen_paths(tmp_path)
    assert paths["eligibility_csv"].name == "candidate_pre_sampling_eligibility.csv"
    assert paths["exclusion_log_csv"].name == "candidate_pre_sampling_exclusion_log.csv"
    assert paths["eligible_pool_csv"].name == "final_eligible_candidate_pool.csv"
    assert paths["summary_json"].name == "candidate_pre_sampling_eligibility_summary.json"
