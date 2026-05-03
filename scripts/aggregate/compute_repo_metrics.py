from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.aggregation import build_aggregation_run_provenance, build_repository_metrics
from scripts.utils.classification import write_csv, write_json
from scripts.utils.config import repo_root
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import repo_metrics_dir


LOGGER = logging.getLogger(__name__)

OUTPUT_FIELDNAMES = [
    "repository_full_name",
    "language_group",
    "eligible_for_rq1",
    "eligible_for_rq2",
    "sample_manifest_file",
    "commit_source_file",
    "issue_source_file",
    "total_commits_in_window",
    "bug_fix_commit_count",
    "bug_fix_commit_ratio",
    "total_closed_issues_in_window_considered",
    "bug_related_issue_count",
    "bug_related_issue_duration_count",
    "invalid_bug_related_issue_duration_count",
    "median_bug_issue_resolution_time_days",
]


def default_sample_manifest_file(root: Path) -> Path:
    return root / "data" / "interim" / "final_sample" / "final_sample.csv"


def default_classified_commits_file(manifest_file: Path, root: Path) -> Path:
    provenance = build_aggregation_run_provenance(manifest_file)
    if provenance["aggregation_run_type"] == "final_study":
        return root / "data" / "interim" / "final_sample" / "classified_commits" / "classified_commits.csv"
    return root / "data" / "interim" / "classified_commits" / "classified_commits.csv"


def default_classified_issues_file(manifest_file: Path, root: Path) -> Path:
    provenance = build_aggregation_run_provenance(manifest_file)
    if provenance["aggregation_run_type"] == "final_study":
        return root / "data" / "interim" / "final_sample" / "classified_issues" / "classified_issues.csv"
    return root / "data" / "interim" / "classified_issues" / "classified_issues.csv"


def default_repo_metrics_output_dir(manifest_file: Path, root: Path) -> Path:
    provenance = build_aggregation_run_provenance(manifest_file)
    if provenance["aggregation_run_type"] == "final_study":
        return repo_metrics_dir(root) / "final_sample"
    return repo_metrics_dir(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Aggregate repository-level metrics from classified data.")
    parser.add_argument(
        "--classified-commits",
        default=None,
        help="Path to the classified commits CSV. Defaults to the final-study classified commits path when the final sample manifest is used.",
    )
    parser.add_argument(
        "--classified-issues",
        default=None,
        help="Path to the classified issues CSV. Defaults to the final-study classified issues path when the final sample manifest is used.",
    )
    parser.add_argument(
        "--manifest-file",
        default=None,
        help="Optional alias for --sample-file.",
    )
    parser.add_argument(
        "--sample-file",
        default=None,
        help="Path to the final sample manifest CSV. Final-study routing should use data/interim/final_sample/final_sample.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory where aggregated repository metrics will be written. Defaults to the final-study metrics path when the final sample manifest is used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging()

    root = repo_root()
    sample_file = (
        Path(args.sample_file)
        if args.sample_file is not None
        else Path(args.manifest_file)
        if args.manifest_file is not None
        else default_sample_manifest_file(root)
    )
    active_manifest_file = sample_file
    classified_commits = (
        Path(args.classified_commits)
        if args.classified_commits is not None
        else default_classified_commits_file(active_manifest_file, root)
    )
    classified_issues = (
        Path(args.classified_issues)
        if args.classified_issues is not None
        else default_classified_issues_file(active_manifest_file, root)
    )
    output_dir = (
        Path(args.output_dir)
        if args.output_dir is not None
        else default_repo_metrics_output_dir(active_manifest_file, root)
    )
    run_provenance = build_aggregation_run_provenance(active_manifest_file)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = output_dir / "repository_metrics.csv"
    output_json = output_dir / "repository_metrics_summary.json"

    LOGGER.info("Starting repository metric aggregation")
    LOGGER.info("Aggregation run type: %s", run_provenance["aggregation_run_type"])
    LOGGER.info("Aggregation input kind: %s", run_provenance["aggregation_input_kind"])
    LOGGER.info("Classified commits input: %s", classified_commits)
    LOGGER.info("Classified issues input: %s", classified_issues)
    LOGGER.info("Active aggregation manifest: %s", active_manifest_file)
    LOGGER.info("Output directory: %s", output_dir)

    rows, summary = build_repository_metrics(
        classified_commits_path=classified_commits,
        classified_issues_path=classified_issues,
        sample_manifest_path=sample_file,
    )
    summary.update(
        {
            "aggregation_run_type": run_provenance["aggregation_run_type"],
            "output_dir": str(output_dir),
            "output_csv": str(output_csv),
            "output_json": str(output_json),
        }
    )

    write_csv(output_csv, rows, fieldnames=OUTPUT_FIELDNAMES)
    write_json(output_json, summary)

    LOGGER.info("Repositories seen in active manifest: %s", summary["repositories_seen_in_manifest"])
    LOGGER.info("Repositories aggregated for RQ1: %s", summary["repositories_aggregated_for_rq1_count"])
    LOGGER.info("Repositories aggregated for RQ2: %s", summary["repositories_aggregated_for_rq2_count"])
    LOGGER.info("Classified commit rows used: %s", summary["commit_rows_used_total"])
    LOGGER.info("Classified issue rows used: %s", summary["issue_rows_used_total"])
    LOGGER.info("Output CSV: %s", output_csv)
    LOGGER.info("Output JSON: %s", output_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
