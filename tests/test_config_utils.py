from __future__ import annotations

from scripts.utils.config import load_study_config


def test_load_study_config_includes_locked_values() -> None:
    config = load_study_config()

    assert config["study_window_start"] == "2024-01-01"
    assert config["study_window_end"] == "2025-12-31"
    assert config["random_seed"] == 640
    assert config["languages"] == ["JavaScript", "TypeScript"]
    assert config["candidate_discovery"]["per_page"] == 100
    assert config["candidate_quality_screen"]["minimum_score"] == 3
    assert config["candidate_quality_screen"]["min_open_issues_count"] == 5
    assert config["candidate_enrichment"]["output_dir"] == "data/interim/enriched_candidates"
    assert config["candidate_enrichment"]["language_threshold"] == 0.70
    assert config["candidate_enrichment"]["activity_field"] == "default_branch_commit_count_in_window"
    assert config["final_sampling"]["output_dir"] == "data/interim/final_sample"
    assert config["final_sampling"]["final_sample_per_language"] == 30
    assert config["final_sampling"]["fallback_final_sample_per_language"] == 20
    assert config["final_sampling"]["reserve_per_language_stratum"] == 3
