from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # noqa: E402


DEFAULT_LANGUAGE_ORDER = ["JavaScript", "TypeScript"]

RQ_METRIC_DEFINITIONS: dict[str, list[dict[str, str]]] = {
    "RQ1": [
        {
            "metric_name": "bug_fix_commit_ratio",
            "metric_label": "Bug-fix commit ratio",
            "metric_field": "bug_fix_commit_ratio",
        },
        {
            "metric_name": "bug_fix_commit_count",
            "metric_label": "Bug-fix commit count",
            "metric_field": "bug_fix_commit_count",
        },
        {
            "metric_name": "total_commits_in_window",
            "metric_label": "Total commits in window",
            "metric_field": "total_commits_in_window",
        },
    ],
    "RQ2": [
        {
            "metric_name": "median_bug_issue_resolution_time_days",
            "metric_label": "Median bug issue resolution time (days)",
            "metric_field": "median_bug_issue_resolution_time_days",
        },
        {
            "metric_name": "bug_related_issue_count",
            "metric_label": "Bug-related issue count",
            "metric_field": "bug_related_issue_count",
        },
        {
            "metric_name": "total_closed_issues_in_window_considered",
            "metric_label": "Total closed issues in window considered",
            "metric_field": "total_closed_issues_in_window_considered",
        },
    ],
}

REQUIRED_COLUMNS = {
    "repository_full_name",
    "language_group",
    "eligible_for_rq1",
    "eligible_for_rq2",
    "bug_fix_commit_ratio",
    "bug_fix_commit_count",
    "total_commits_in_window",
    "median_bug_issue_resolution_time_days",
    "bug_related_issue_count",
    "total_closed_issues_in_window_considered",
}


def infer_reporting_run_type(repo_metrics_file: str | Path) -> str:
    path = Path(repo_metrics_file)
    normalized_parts = {part.lower() for part in path.parts}
    filename = path.name.lower()
    if filename == "repository_metrics.csv" and "final_sample" in normalized_parts:
        return "final_study"
    return "custom"


def build_reporting_run_provenance(repo_metrics_file: str | Path) -> dict[str, Any]:
    return {
        "repo_metrics_file": str(repo_metrics_file),
        "reporting_run_type": infer_reporting_run_type(repo_metrics_file),
    }


def _parse_bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_repository_metrics(path: str | Path) -> pd.DataFrame:
    metrics_path = Path(path)
    frame = pd.read_csv(metrics_path)
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required repository metric columns in {metrics_path}: {sorted(missing)}")
    frame = frame.copy()
    frame["eligible_for_rq1"] = frame["eligible_for_rq1"].map(_parse_bool_value)
    frame["eligible_for_rq2"] = frame["eligible_for_rq2"].map(_parse_bool_value)
    numeric_columns = [
        "bug_fix_commit_ratio",
        "bug_fix_commit_count",
        "total_commits_in_window",
        "median_bug_issue_resolution_time_days",
        "bug_related_issue_count",
        "total_closed_issues_in_window_considered",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def summarize_numeric_series(values: pd.Series) -> dict[str, Any]:
    cleaned = pd.to_numeric(values, errors="coerce").dropna()
    if cleaned.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
            "stddev": None,
            "iqr": None,
        }

    count = int(cleaned.count())
    return {
        "count": count,
        "mean": float(cleaned.mean()),
        "median": float(cleaned.median()),
        "min": float(cleaned.min()),
        "max": float(cleaned.max()),
        "stddev": float(cleaned.std(ddof=1)) if count > 1 else None,
        "iqr": float(cleaned.quantile(0.75) - cleaned.quantile(0.25)) if count > 1 else None,
    }


def _ordered_languages(frame: pd.DataFrame, language_order: list[str] | None = None) -> list[str]:
    ordered = list(language_order or DEFAULT_LANGUAGE_ORDER)
    seen = set(ordered)
    for language in frame["language_group"].dropna().astype(str):
        if language not in seen:
            ordered.append(language)
            seen.add(language)
    return ordered


def build_descriptive_summary_table(
    repository_metrics: pd.DataFrame,
    *,
    language_order: list[str] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ordered_languages = _ordered_languages(repository_metrics, language_order)

    for rq_section, metric_definitions in RQ_METRIC_DEFINITIONS.items():
        eligible_flag = "eligible_for_rq1" if rq_section == "RQ1" else "eligible_for_rq2"
        for language_group in ordered_languages:
            language_mask = repository_metrics["language_group"].astype(str) == language_group
            eligible_mask = repository_metrics[eligible_flag].astype(bool)
            eligible_subset = repository_metrics[language_mask & eligible_mask].copy()
            eligible_repository_count = int(eligible_subset["repository_full_name"].nunique())

            for metric in metric_definitions:
                metric_field = metric["metric_field"]
                metric_values = eligible_subset[metric_field].dropna()
                stats = summarize_numeric_series(metric_values)
                rows.append(
                    {
                        "rq_section": rq_section,
                        "language_group": language_group,
                        "metric_name": metric["metric_name"],
                        "metric_label": metric["metric_label"],
                        "metric_field": metric_field,
                        "eligible_repository_count": eligible_repository_count,
                        "contributing_repository_count": int(metric_values.count()),
                        "count": stats["count"],
                        "mean": stats["mean"],
                        "median": stats["median"],
                        "min": stats["min"],
                        "max": stats["max"],
                        "stddev": stats["stddev"],
                        "iqr": stats["iqr"],
                    }
                )

    summary = pd.DataFrame(rows)
    column_order = [
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
    return summary[column_order]


def _format_markdown_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if pd.isna(value):  # type: ignore[arg-type]
        return ""
    return str(value)


def render_markdown_summary(summary_table: pd.DataFrame) -> str:
    lines: list[str] = [
        "# Descriptive Summary by Language",
        "",
        "The tables below report descriptive statistics only.",
        "",
    ]
    display_columns = [
        "language_group",
        "metric_label",
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

    for rq_section in ["RQ1", "RQ2"]:
        section = summary_table[summary_table["rq_section"] == rq_section].copy()
        lines.extend([f"## {rq_section}", ""])
        if section.empty:
            lines.extend(["No rows available.", ""])
            continue
        section = section[display_columns]
        header = "| " + " | ".join(display_columns) + " |"
        separator = "| " + " | ".join(["---"] * len(display_columns)) + " |"
        lines.extend([header, separator])
        for _, row in section.iterrows():
            rendered = [ _format_markdown_value(row[column]) for column in display_columns ]
            lines.append("| " + " | ".join(rendered) + " |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def dataframe_records_for_json(summary_table: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in summary_table.to_dict(orient="records"):
        safe_row: dict[str, Any] = {}
        for key, value in row.items():
            if pd.isna(value):
                safe_row[key] = None
            elif hasattr(value, "item") and not isinstance(value, (str, bytes, bool)):
                safe_row[key] = value.item()
            elif isinstance(value, (int, float, str, bool)):
                safe_row[key] = value
            else:
                safe_row[key] = str(value)
        records.append(safe_row)
    return records


def _language_series_for_metric(repository_metrics: pd.DataFrame, metric_field: str) -> tuple[list[str], list[list[float]]]:
    languages = _ordered_languages(repository_metrics)
    data: list[list[float]] = []
    for language in languages:
        subset = repository_metrics[
            repository_metrics["language_group"].astype(str).eq(language)
            & pd.notna(repository_metrics[metric_field])
        ][metric_field]
        values = pd.to_numeric(subset, errors="coerce").dropna().astype(float).tolist()
        data.append(values)
    return languages, data


def _load_matplotlib_pyplot() -> Any:
    try:
        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg")
        return importlib.import_module("matplotlib.pyplot")
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only in environments without matplotlib
        raise ModuleNotFoundError(
            "matplotlib is required to generate reporting figures. "
            "Install the project requirements before running the descriptive report."
        ) from exc


def plot_metric_by_language(
    repository_metrics: pd.DataFrame,
    *,
    metric_field: str,
    metric_label: str,
    output_path: str | Path,
    y_label: str,
    y_scale: str | None = None,
    y_clip_max: float | None = None,
    clipped_label: str | None = None,
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    plt = _load_matplotlib_pyplot()
    languages, data = _language_series_for_metric(repository_metrics, metric_field)
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    box = ax.boxplot(
        data,
        tick_labels=languages,
        patch_artist=True,
        showmeans=True,
        showfliers=False,
        boxprops={"linewidth": 1.8, "edgecolor": "#222222"},
        whiskerprops={"linewidth": 1.7, "color": "#222222"},
        capprops={"linewidth": 1.7, "color": "#222222"},
        medianprops={"linewidth": 2.2, "color": "#111111"},
        meanprops={
            "marker": "^",
            "markerfacecolor": "#2CA02C",
            "markeredgecolor": "#FFFFFF",
            "markeredgewidth": 0.9,
            "markersize": 8.5,
        },
    )
    colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756"]
    for patch, color in zip(box["boxes"], colors, strict=False):
        patch.set_facecolor(color)
        patch.set_alpha(0.24)
        patch.set_zorder(3)
    for artist_group in ("whiskers", "caps", "medians", "means"):
        for artist in box[artist_group]:
            artist.set_zorder(4)
    clipped_points_present = False
    for index, values in enumerate(data, start=1):
        if not values:
            continue
        jitter = [
            index + (offset - 0.5) * 0.5
            for offset in [i / max(len(values) - 1, 1) for i in range(len(values))]
        ]
        normal_x: list[float] = []
        normal_y: list[float] = []
        clipped_x: list[float] = []
        clipped_y: list[float] = []
        for x_value, y_value in zip(jitter, values, strict=True):
            if y_clip_max is not None and y_value > y_clip_max:
                clipped_points_present = True
                clipped_x.append(x_value)
                clipped_y.append(y_clip_max)
            else:
                normal_x.append(x_value)
                normal_y.append(y_value)
        ax.scatter(normal_x, normal_y, color="#333333", alpha=0.52, s=18, zorder=2)
        if clipped_x:
            ax.scatter(
                clipped_x,
                clipped_y,
                color="#B23A48",
                edgecolor="#FFFFFF",
                linewidth=0.8,
                alpha=0.9,
                marker="^",
                s=42,
                zorder=5,
                label=clipped_label if not ax.get_legend_handles_labels()[1] else None,
            )

    ax.set_title(f"{metric_label} by language")
    ax.set_xlabel("Language group")
    ax.set_ylabel(y_label)
    if y_scale is not None:
        ax.set_yscale(y_scale)
    if y_clip_max is not None:
        ax.set_ylim(top=y_clip_max * 1.08)
    if clipped_points_present:
        ax.legend(frameon=False, loc="upper right")
    grid_marks = "major" if y_scale == "log" else "both"
    ax.grid(axis="y", which=grid_marks, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def build_reporting_summary(
    repository_metrics: pd.DataFrame,
    summary_table: pd.DataFrame,
    *,
    input_file: str | Path,
    output_files: dict[str, str],
) -> dict[str, Any]:
    rq1_contributing = int(
        repository_metrics.loc[
            repository_metrics["eligible_for_rq1"].astype(bool)
            & pd.notna(repository_metrics["bug_fix_commit_ratio"])
        ].shape[0]
    )
    rq2_contributing = int(
        repository_metrics.loc[
            repository_metrics["eligible_for_rq2"].astype(bool)
            & pd.notna(repository_metrics["median_bug_issue_resolution_time_days"])
        ].shape[0]
    )

    return {
        "report_type": "descriptive_outputs",
        "reporting_run_type": infer_reporting_run_type(input_file),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_file),
        "repository_row_count_loaded": int(repository_metrics.shape[0]),
        "rq1_contributing_repository_rows": rq1_contributing,
        "rq2_contributing_repository_rows": rq2_contributing,
        "language_groups": _ordered_languages(repository_metrics),
        "summary_table_records": dataframe_records_for_json(summary_table),
        "output_files": output_files,
    }
