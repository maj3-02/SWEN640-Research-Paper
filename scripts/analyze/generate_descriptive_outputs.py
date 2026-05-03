from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.config import repo_root
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import results_figures_dir, results_final_dir, results_tables_dir
from scripts.utils.reporting import (
    build_descriptive_summary_table,
    build_reporting_run_provenance,
    build_reporting_summary,
    load_repository_metrics,
    plot_metric_by_language,
    render_markdown_summary,
)

LOGGER = logging.getLogger(__name__)

SUMMARY_TABLE_CSV = "descriptive_summary_by_language.csv"
SUMMARY_TABLE_MD = "descriptive_summary_by_language.md"
BUG_FIX_FIGURE = "bug_fix_commit_ratio_by_language.png"
ISSUE_RESOLUTION_FIGURE = "median_bug_issue_resolution_time_days_by_language.png"
REPORTING_SUMMARY_JSON = "reporting_summary.json"


def default_repo_metrics_file(root: Path) -> Path:
    return root / "data" / "processed" / "repo_metrics" / "repository_metrics.csv"


def default_reporting_tables_dir(repo_metrics_path: Path, root: Path) -> Path:
    provenance = build_reporting_run_provenance(repo_metrics_path)
    if provenance["reporting_run_type"] == "final_study":
        return root / "results" / "final_sample" / "tables"
    return results_tables_dir(root)


def default_reporting_figures_dir(repo_metrics_path: Path, root: Path) -> Path:
    provenance = build_reporting_run_provenance(repo_metrics_path)
    if provenance["reporting_run_type"] == "final_study":
        return root / "results" / "final_sample" / "figures"
    return results_figures_dir(root)


def default_reporting_final_dir(repo_metrics_path: Path, root: Path) -> Path:
    provenance = build_reporting_run_provenance(repo_metrics_path)
    if provenance["reporting_run_type"] == "final_study":
        return root / "results" / "final_sample"
    return results_final_dir(root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate descriptive outputs from repository metrics.")
    parser.add_argument(
        "--repo-metrics",
        default=None,
        help="Path to the repository-level metrics CSV. Defaults to data/processed/repo_metrics/repository_metrics.csv.",
    )
    parser.add_argument(
        "--tables-dir",
        default=None,
        help="Directory for descriptive summary tables. Defaults to the final-study path when final-study metrics are used.",
    )
    parser.add_argument(
        "--figures-dir",
        default=None,
        help="Directory for reporting figures. Defaults to the final-study path when final-study metrics are used.",
    )
    parser.add_argument(
        "--final-dir",
        default=None,
        help="Directory for machine-readable reporting summary output. Defaults to the final-study path when final-study metrics are used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging()

    root = repo_root()
    repo_metrics_path = Path(args.repo_metrics) if args.repo_metrics is not None else default_repo_metrics_file(root)
    tables_dir = (
        Path(args.tables_dir)
        if args.tables_dir is not None
        else default_reporting_tables_dir(repo_metrics_path, root)
    )
    figures_dir = (
        Path(args.figures_dir)
        if args.figures_dir is not None
        else default_reporting_figures_dir(repo_metrics_path, root)
    )
    final_dir = (
        Path(args.final_dir)
        if args.final_dir is not None
        else default_reporting_final_dir(repo_metrics_path, root)
    )
    run_provenance = build_reporting_run_provenance(repo_metrics_path)
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Starting descriptive reporting")
    LOGGER.info("Reporting run type: %s", run_provenance["reporting_run_type"])
    LOGGER.info("Repository metrics input: %s", repo_metrics_path)

    repository_metrics = load_repository_metrics(repo_metrics_path)
    summary_table = build_descriptive_summary_table(repository_metrics)

    output_csv = tables_dir / SUMMARY_TABLE_CSV
    output_md = tables_dir / SUMMARY_TABLE_MD
    output_bug_fix_figure = figures_dir / BUG_FIX_FIGURE
    output_issue_figure = figures_dir / ISSUE_RESOLUTION_FIGURE
    output_summary_json = final_dir / REPORTING_SUMMARY_JSON

    summary_table.to_csv(output_csv, index=False)
    output_md.write_text(render_markdown_summary(summary_table), encoding="utf-8")

    plot_metric_by_language(
        repository_metrics,
        metric_field="bug_fix_commit_ratio",
        metric_label="Bug-fix commit ratio",
        output_path=output_bug_fix_figure,
        y_label="Bug-fix commit ratio",
    )
    plot_metric_by_language(
        repository_metrics,
        metric_field="median_bug_issue_resolution_time_days",
        metric_label="Median bug issue resolution time (days)",
        output_path=output_issue_figure,
        y_label="Median bug issue resolution time (days)",
        y_clip_max=150.0,
        clipped_label="Repositories >150 days (clipped)",
    )

    reporting_summary = build_reporting_summary(
        repository_metrics,
        summary_table,
        input_file=repo_metrics_path,
        output_files={
            "tables_csv": str(output_csv),
            "tables_md": str(output_md),
            "bug_fix_figure": str(output_bug_fix_figure),
            "issue_resolution_figure": str(output_issue_figure),
            "summary_json": str(output_summary_json),
        },
    )
    output_summary_json.write_text(json.dumps(reporting_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    LOGGER.info("Repository rows loaded: %s", reporting_summary["repository_row_count_loaded"])
    LOGGER.info("RQ1 contributing repository rows: %s", reporting_summary["rq1_contributing_repository_rows"])
    LOGGER.info("RQ2 contributing repository rows: %s", reporting_summary["rq2_contributing_repository_rows"])
    LOGGER.info("Output table CSV: %s", output_csv)
    LOGGER.info("Output table MD: %s", output_md)
    LOGGER.info("Output figure: %s", output_bug_fix_figure)
    LOGGER.info("Output figure: %s", output_issue_figure)
    LOGGER.info("Output summary JSON: %s", output_summary_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
