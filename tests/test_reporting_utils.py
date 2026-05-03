from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.analyze.generate_descriptive_outputs import (
    default_reporting_figures_dir,
    default_reporting_final_dir,
    default_reporting_tables_dir,
)
from scripts.utils.reporting import (
    build_reporting_run_provenance,
    build_descriptive_summary_table,
    build_reporting_summary,
    infer_reporting_run_type,
    load_repository_metrics,
    plot_metric_by_language,
    render_markdown_summary,
)


def _write_repo_metrics_csv(path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "repository_full_name": "example/js-a",
                "language_group": "JavaScript",
                "eligible_for_rq1": True,
                "eligible_for_rq2": True,
                "eligibility_source_file": "eligibility.csv",
                "commit_source_file": "commits-a.json",
                "issue_source_file": "issues-a.json",
                "total_commits_in_window": 10,
                "bug_fix_commit_count": 1,
                "bug_fix_commit_ratio": 0.1,
                "total_closed_issues_in_window_considered": 4,
                "bug_related_issue_count": 2,
                "bug_related_issue_duration_count": 2,
                "invalid_bug_related_issue_duration_count": 0,
                "median_bug_issue_resolution_time_days": 3.0,
            },
            {
                "repository_full_name": "example/js-b",
                "language_group": "JavaScript",
                "eligible_for_rq1": True,
                "eligible_for_rq2": True,
                "eligibility_source_file": "eligibility.csv",
                "commit_source_file": "commits-b.json",
                "issue_source_file": "issues-b.json",
                "total_commits_in_window": 20,
                "bug_fix_commit_count": 2,
                "bug_fix_commit_ratio": None,
                "total_closed_issues_in_window_considered": 8,
                "bug_related_issue_count": 4,
                "bug_related_issue_duration_count": 4,
                "invalid_bug_related_issue_duration_count": 0,
                "median_bug_issue_resolution_time_days": 5.0,
            },
            {
                "repository_full_name": "example/ts-a",
                "language_group": "TypeScript",
                "eligible_for_rq1": True,
                "eligible_for_rq2": True,
                "eligibility_source_file": "eligibility.csv",
                "commit_source_file": "commits-c.json",
                "issue_source_file": "issues-c.json",
                "total_commits_in_window": 30,
                "bug_fix_commit_count": 3,
                "bug_fix_commit_ratio": 0.1,
                "total_closed_issues_in_window_considered": 10,
                "bug_related_issue_count": 6,
                "bug_related_issue_duration_count": 6,
                "invalid_bug_related_issue_duration_count": 0,
                "median_bug_issue_resolution_time_days": 7.0,
            },
            {
                "repository_full_name": "example/ineligible",
                "language_group": "TypeScript",
                "eligible_for_rq1": False,
                "eligible_for_rq2": False,
                "eligibility_source_file": "eligibility.csv",
                "commit_source_file": "",
                "issue_source_file": "",
                "total_commits_in_window": None,
                "bug_fix_commit_count": None,
                "bug_fix_commit_ratio": None,
                "total_closed_issues_in_window_considered": None,
                "bug_related_issue_count": None,
                "bug_related_issue_duration_count": None,
                "invalid_bug_related_issue_duration_count": None,
                "median_bug_issue_resolution_time_days": None,
            },
        ]
    )
    frame.to_csv(path, index=False)


def test_build_descriptive_summary_table_groups_by_language_and_skips_missing_values(tmp_path) -> None:
    metrics_path = tmp_path / "repository_metrics.csv"
    _write_repo_metrics_csv(metrics_path)
    repository_metrics = load_repository_metrics(metrics_path)

    summary = build_descriptive_summary_table(repository_metrics)

    assert list(summary.columns) == [
        "rq_section",
        "language_group",
        "metric_name",
        "metric_label",
        "metric_field",
        "eligible_repository_count",
        "contributing_repository_count",
        "count",
        "mean",
        "median",
        "min",
        "max",
        "stddev",
        "iqr",
    ]
    assert len(summary) == 12

    rq1_ratio_js = summary[
        (summary["rq_section"] == "RQ1")
        & (summary["language_group"] == "JavaScript")
        & (summary["metric_name"] == "bug_fix_commit_ratio")
    ].iloc[0]
    assert rq1_ratio_js["eligible_repository_count"] == 2
    assert rq1_ratio_js["contributing_repository_count"] == 1
    assert rq1_ratio_js["count"] == 1
    assert rq1_ratio_js["mean"] == 0.1
    assert rq1_ratio_js["median"] == 0.1

    rq2_median_js = summary[
        (summary["rq_section"] == "RQ2")
        & (summary["language_group"] == "JavaScript")
        & (summary["metric_name"] == "median_bug_issue_resolution_time_days")
    ].iloc[0]
    assert rq2_median_js["eligible_repository_count"] == 2
    assert rq2_median_js["contributing_repository_count"] == 2
    assert rq2_median_js["count"] == 2
    assert rq2_median_js["median"] == 4.0


def test_reporting_run_type_inference_for_final_and_custom_paths(tmp_path) -> None:
    final = tmp_path / "data" / "processed" / "repo_metrics" / "final_sample" / "repository_metrics.csv"
    custom = tmp_path / "metrics.csv"

    assert build_reporting_run_provenance(final)["reporting_run_type"] == "final_study"
    assert infer_reporting_run_type(custom) == "custom"


def test_reporting_defaults_use_custom_paths_for_custom_metrics(tmp_path) -> None:
    metrics = tmp_path / "data" / "processed" / "repo_metrics" / "repository_metrics.csv"

    assert default_reporting_tables_dir(metrics, tmp_path).as_posix().endswith("results/tables")
    assert default_reporting_figures_dir(metrics, tmp_path).as_posix().endswith("results/figures")
    assert default_reporting_final_dir(metrics, tmp_path).as_posix().endswith("results/final")


def test_reporting_defaults_route_final_study_paths(tmp_path) -> None:
    metrics = tmp_path / "data" / "processed" / "repo_metrics" / "final_sample" / "repository_metrics.csv"

    assert default_reporting_tables_dir(metrics, tmp_path).as_posix().endswith("results/final_sample/tables")
    assert default_reporting_figures_dir(metrics, tmp_path).as_posix().endswith("results/final_sample/figures")
    assert default_reporting_final_dir(metrics, tmp_path).as_posix().endswith("results/final_sample")


def test_render_markdown_summary_contains_sections(tmp_path) -> None:
    metrics_path = tmp_path / "repository_metrics.csv"
    _write_repo_metrics_csv(metrics_path)
    repository_metrics = load_repository_metrics(metrics_path)
    summary = build_descriptive_summary_table(repository_metrics)

    markdown = render_markdown_summary(summary)

    assert "## RQ1" in markdown
    assert "## RQ2" in markdown
    assert "Bug-fix commit ratio" in markdown
    assert "Median bug issue resolution time (days)" in markdown


def test_plot_metric_by_language_writes_png(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    metrics_path = tmp_path / "repository_metrics.csv"
    _write_repo_metrics_csv(metrics_path)
    repository_metrics = load_repository_metrics(metrics_path)
    output_path = tmp_path / "figures" / "bug_fix_commit_ratio_by_language.png"

    plot_metric_by_language(
        repository_metrics,
        metric_field="bug_fix_commit_ratio",
        metric_label="Bug-fix commit ratio",
        output_path=output_path,
        y_label="Bug-fix commit ratio",
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_plot_metric_by_language_supports_clipped_points(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    metrics_path = tmp_path / "repository_metrics.csv"
    _write_repo_metrics_csv(metrics_path)
    repository_metrics = load_repository_metrics(metrics_path)
    output_path = tmp_path / "figures" / "median_bug_issue_resolution_time_days_by_language.png"

    plot_metric_by_language(
        repository_metrics,
        metric_field="median_bug_issue_resolution_time_days",
        metric_label="Median bug issue resolution time (days)",
        output_path=output_path,
        y_label="Median bug issue resolution time (days)",
        y_clip_max=4.0,
        clipped_label="Repositories >4 days (clipped)",
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_build_reporting_summary_records_counts_and_paths(tmp_path) -> None:
    metrics_path = tmp_path / "repository_metrics.csv"
    _write_repo_metrics_csv(metrics_path)
    repository_metrics = load_repository_metrics(metrics_path)
    summary = build_descriptive_summary_table(repository_metrics)
    reporting_summary = build_reporting_summary(
        repository_metrics,
        summary,
        input_file=metrics_path,
        output_files={"tables_csv": "tables.csv"},
    )

    assert reporting_summary["repository_row_count_loaded"] == 4
    assert reporting_summary["rq1_contributing_repository_rows"] == 2
    assert reporting_summary["rq2_contributing_repository_rows"] == 3
    assert reporting_summary["input_file"] == str(metrics_path)
    assert reporting_summary["output_files"]["tables_csv"] == "tables.csv"
    assert len(reporting_summary["summary_table_records"]) == 12
    assert isinstance(reporting_summary["summary_table_records"], list)
