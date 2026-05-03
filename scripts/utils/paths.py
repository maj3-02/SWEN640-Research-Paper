from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(path_value: str | Path, base_dir: str | Path | None = None) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    root = Path(base_dir) if base_dir is not None else repo_root()
    return root / path


def candidate_raw_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "candidate_repos" and root.parent.name == "raw":
        return root
    return root / "data" / "raw" / "candidate_repos"


def candidate_output_paths(language: str, base_dir: str | Path | None = None) -> dict[str, Path]:
    root = candidate_raw_dir(base_dir)
    slug = language.strip().lower().replace(" ", "_")
    return {
        "json": root / f"{slug}_candidates_raw.json",
        "csv": root / f"{slug}_candidates_raw.csv",
    }


def interim_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    return root / "data" / "interim"


def filtered_candidate_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "filtered_candidates" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "filtered_candidates"


def quality_screened_candidates_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "quality_screened_candidates" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "quality_screened_candidates"


def enriched_candidates_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "enriched_candidates" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "enriched_candidates"


def enriched_candidate_paths(base_dir: str | Path | None = None) -> dict[str, Path]:
    root = enriched_candidates_dir(base_dir)
    return {
        "results_csv": root / "candidate_enrichment_results.csv",
        "failures_json": root / "candidate_enrichment_failures.json",
        "closed_issue_count_failures_json": root / "closed_issue_count_failures.json",
        "summary_json": root / "candidate_enrichment_summary.json",
    }


def enriched_candidate_language_path(language: str, base_dir: str | Path | None = None) -> Path:
    root = enriched_candidates_dir(base_dir)
    slug = language.strip().lower().replace(" ", "_")
    return root / f"{slug}_candidates_enriched.csv"


def final_candidate_screen_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "final_candidate_screen" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "final_candidate_screen"


def final_candidate_screen_paths(base_dir: str | Path | None = None) -> dict[str, Path]:
    root = final_candidate_screen_dir(base_dir)
    return {
        "eligibility_csv": root / "candidate_pre_sampling_eligibility.csv",
        "exclusion_log_csv": root / "candidate_pre_sampling_exclusion_log.csv",
        "eligible_pool_csv": root / "final_eligible_candidate_pool.csv",
        "summary_json": root / "candidate_pre_sampling_eligibility_summary.json",
    }


def final_sample_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "final_sample" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "final_sample"


def final_sample_paths(base_dir: str | Path | None = None) -> dict[str, Path]:
    root = final_sample_dir(base_dir)
    return {
        "candidate_pool_with_strata_csv": root / "final_candidate_pool_with_strata.csv",
        "final_sample_csv": root / "final_sample.csv",
        "final_reserves_csv": root / "final_reserves.csv",
        "metadata_json": root / "final_sample_metadata.json",
        "pool_sufficiency_report_json": root / "pool_sufficiency_report.json",
    }


def classified_commits_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "classified_commits" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "classified_commits"


def classified_issues_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "classified_issues" and root.parent.name == "interim":
        return root
    return root / "data" / "interim" / "classified_issues"


def processed_validation_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "validation" and root.parent.name == "processed":
        return root
    return root / "data" / "processed" / "validation"


def repo_metrics_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "repo_metrics" and root.parent.name == "processed":
        return root
    return root / "data" / "processed" / "repo_metrics"


def results_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    return root / "results"


def results_tables_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "tables" and root.parent.name == "results":
        return root
    return root / "results" / "tables"


def results_figures_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "figures" and root.parent.name == "results":
        return root
    return root / "results" / "figures"


def results_final_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "final" and root.parent.name == "results":
        return root
    return root / "results" / "final"


def raw_commits_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "commits" and root.parent.name == "raw":
        return root
    return root / "data" / "raw" / "commits"


def raw_issues_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "issues" and root.parent.name == "raw":
        return root
    return root / "data" / "raw" / "issues"


def raw_repo_metadata_dir(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else repo_root()
    if root.name == "repo_metadata" and root.parent.name == "raw":
        return root
    return root / "data" / "raw" / "repo_metadata"
