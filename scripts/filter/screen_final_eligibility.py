from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.config import load_study_config
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import (
    enriched_candidate_paths,
    enriched_candidates_dir,
    final_candidate_screen_dir,
    final_candidate_screen_paths,
    resolve_repo_path,
)
from scripts.utils.pre_sampling_eligibility import (
    FIELD_LANGUAGE_GROUP,
    FIELD_PRE_SAMPLING_ELIGIBLE,
    FIELD_PRE_SAMPLING_EXCLUSION_REASONS,
    FIELD_REPOSITORY_FULL_NAME,
    PRE_SAMPLING_ELIGIBILITY_FIELDS,
    build_pre_sampling_eligibility_row,
    build_pre_sampling_eligibility_summary,
    thresholds_from_config,
)

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the final-study pre-sampling eligibility screen and eligible candidate pool."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Override for enriched candidate input directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override for pre-sampling eligibility outputs.",
    )
    return parser.parse_args()


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path: str | Path, rows: list[Mapping[str, Any]], fieldnames: list[str]) -> None:
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def load_enriched_candidate_rows(input_dir: Path) -> tuple[list[dict[str, Any]], str]:
    input_file = enriched_candidate_paths(input_dir)["results_csv"]
    if not input_file.exists():
        raise FileNotFoundError(f"Missing enriched candidate results file: {input_file}")
    rows = read_csv_rows(input_file)
    for index, row in enumerate(rows, start=1):
        row["pre_sampling_screen_input_file"] = str(input_file)
        row["pre_sampling_screen_input_record_index"] = index
    return rows, str(input_file)


def screen_enriched_candidate_rows(
    rows: list[Mapping[str, Any]],
    *,
    config: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    thresholds = thresholds_from_config(config)
    eligibility_rows: list[dict[str, Any]] = []
    eligible_pool_rows: list[dict[str, Any]] = []
    exclusion_rows: list[dict[str, Any]] = []

    for row in rows:
        eligibility_row = build_pre_sampling_eligibility_row(row, thresholds=thresholds)
        combined_row = dict(row)
        combined_row.update(eligibility_row)
        eligibility_rows.append(combined_row)

        if eligibility_row[FIELD_PRE_SAMPLING_ELIGIBLE] is True:
            eligible_pool_rows.append(combined_row)
            continue

        reasons = str(eligibility_row[FIELD_PRE_SAMPLING_EXCLUSION_REASONS] or "")
        for reason in [value for value in reasons.split(";") if value]:
            exclusion_rows.append(
                {
                    "repository_full_name": eligibility_row[FIELD_REPOSITORY_FULL_NAME],
                    "language_group": eligibility_row[FIELD_LANGUAGE_GROUP],
                    "exclusion_reason": reason,
                    "pre_sampling_exclusion_reasons": reasons,
                    "source_file": row.get("pre_sampling_screen_input_file")
                    or row.get("enrichment_input_file")
                    or row.get("source_file")
                    or "",
                    "source_record_index": row.get("pre_sampling_screen_input_record_index")
                    or row.get("enrichment_input_record_index")
                    or row.get("source_record_index")
                    or "",
                }
            )

    summary = build_pre_sampling_eligibility_summary(rows, thresholds=thresholds)
    return eligibility_rows, eligible_pool_rows, exclusion_rows, summary


def _ordered_fieldnames(rows: list[Mapping[str, Any]], *, priority_fields: list[str]) -> list[str]:
    ordered = list(priority_fields)
    for row in rows:
        for field in row.keys():
            if field not in ordered:
                ordered.append(field)
    return ordered


def build_summary_payload(
    *,
    base_summary: Mapping[str, Any],
    input_file: str,
    output_files: Mapping[str, str],
) -> dict[str, Any]:
    summary = dict(base_summary)
    summary.update(
        {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "input_files": [input_file],
            "output_files": dict(output_files),
        }
    )
    return summary


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    screen_config = config.get("final_candidate_screen", {})
    input_dir = (
        resolve_repo_path(args.input_dir)
        if args.input_dir is not None
        else resolve_repo_path(screen_config.get("input_dir", enriched_candidates_dir()))
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else resolve_repo_path(screen_config.get("output_dir", final_candidate_screen_dir()))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Using enriched candidate input directory: %s", input_dir)
    LOGGER.info("Using final candidate screen output directory: %s", output_dir)

    enriched_rows, input_file = load_enriched_candidate_rows(input_dir)
    eligibility_rows, eligible_pool_rows, exclusion_rows, summary = screen_enriched_candidate_rows(
        enriched_rows,
        config=config,
    )

    paths = final_candidate_screen_paths(output_dir)
    output_files = {name: str(path) for name, path in paths.items()}
    summary_payload = build_summary_payload(
        base_summary=summary,
        input_file=input_file,
        output_files=output_files,
    )

    eligibility_fieldnames = _ordered_fieldnames(
        eligibility_rows,
        priority_fields=PRE_SAMPLING_ELIGIBILITY_FIELDS,
    )
    eligible_pool_fieldnames = _ordered_fieldnames(
        eligible_pool_rows or eligibility_rows,
        priority_fields=PRE_SAMPLING_ELIGIBILITY_FIELDS,
    )
    exclusion_fieldnames = [
        "repository_full_name",
        "language_group",
        "exclusion_reason",
        "pre_sampling_exclusion_reasons",
        "source_file",
        "source_record_index",
    ]

    write_csv_rows(paths["eligibility_csv"], eligibility_rows, eligibility_fieldnames)
    write_csv_rows(paths["eligible_pool_csv"], eligible_pool_rows, eligible_pool_fieldnames)
    write_csv_rows(paths["exclusion_log_csv"], exclusion_rows, exclusion_fieldnames)
    write_json(paths["summary_json"], summary_payload)

    LOGGER.info("Rows seen: %s", summary_payload["rows_seen"])
    LOGGER.info("Language threshold pass count: %s", summary_payload["language_threshold_pass_count"])
    LOGGER.info("Commit threshold pass count: %s", summary_payload["commit_threshold_pass_count"])
    LOGGER.info("Closed-issue threshold pass count: %s", summary_payload["closed_issue_threshold_pass_count"])
    LOGGER.info("Quality screen pass count: %s", summary_payload["quality_screen_pass_count"])
    LOGGER.info("Pre-sampling eligible count: %s", summary_payload["pre_sampling_eligible_count"])
    LOGGER.info("Pre-sampling eligible by language: %s", summary_payload["pre_sampling_eligible_by_language"])
    LOGGER.info("Saved pre-sampling eligibility rows to %s", paths["eligibility_csv"])
    LOGGER.info("Saved final eligible candidate pool to %s", paths["eligible_pool_csv"])
    LOGGER.info("Saved pre-sampling exclusion log to %s", paths["exclusion_log_csv"])
    LOGGER.info("Saved pre-sampling eligibility summary to %s", paths["summary_json"])


if __name__ == "__main__":
    main()
