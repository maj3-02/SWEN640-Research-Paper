from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.candidate_filtering import (
    build_exclusion_log_row,
    build_filtered_candidate_row,
    build_manual_review_row,
    can_validate_language_threshold,
    classify_repository_record,
    detect_manual_review_matches,
    deduplicate_records,
    extract_repository_records,
    load_json_payload,
)
from scripts.utils.config import load_study_config, load_yaml_file
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import filtered_candidate_dir, repo_root, resolve_repo_path

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter raw GitHub candidate repositories for the study.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--keywords",
        default=None,
        help="Path to the keyword configuration YAML file. Defaults to config/keywords.yaml.",
    )
    parser.add_argument(
        "--raw-dir",
        default=None,
        help="Override for the raw candidate repository directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override for the interim filtered candidate directory.",
    )
    return parser.parse_args()


def get_config_path(default_relative_path: str, override: str | None) -> Path:
    if override is not None:
        return Path(override)
    return repo_root() / default_relative_path


def get_output_dir(config: dict[str, Any], override: str | None) -> Path:
    if override is not None:
        return resolve_repo_path(override)
    filtering_config = config.get("candidate_filtering", {})
    configured_output = filtering_config.get("output_dir")
    if isinstance(configured_output, str) and configured_output.strip():
        return resolve_repo_path(configured_output)
    return filtered_candidate_dir()


def get_raw_input_dir(config: dict[str, Any], override: str | None) -> Path:
    if override is not None:
        return resolve_repo_path(override)
    filtering_config = config.get("candidate_filtering", {})
    configured_input = filtering_config.get("raw_input_dir")
    if isinstance(configured_input, str) and configured_input.strip():
        return resolve_repo_path(configured_input)
    return repo_root() / "data" / "raw" / "candidate_repos"


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def process_language_group(
    *,
    language_group: str,
    raw_path: Path,
    manual_cues: list[str],
    defer_language_threshold_validation: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    LOGGER.info("Loading %s raw candidates from %s", language_group, raw_path)
    payload = load_json_payload(raw_path)
    records = extract_repository_records(payload)
    LOGGER.info("Loaded %s raw repository records for %s", len(records), language_group)

    if defer_language_threshold_validation:
        if can_validate_language_threshold(payload):
            LOGGER.info(
                "%s payload appears to contain language-stats metadata, but full threshold validation is still deferred",
                language_group,
            )
        else:
            LOGGER.info(
                "Language-threshold validation is deferred for %s because the raw discovery payload does not include language-stats breakdowns",
                language_group,
            )

    deduped_records, duplicate_records = deduplicate_records(records)
    exclusion_rows: list[dict[str, Any]] = []
    manual_review_rows: list[dict[str, Any]] = []
    filtered_rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()

    timestamp = payload.get("fetched_at") if isinstance(payload.get("fetched_at"), str) else None
    source_file = str(raw_path)

    for source_index, record in duplicate_records:
        exclusion_rows.append(
            build_exclusion_log_row(
                record,
                language_group=language_group,
                exclusion_reason_code="duplicate_candidate",
                exclusion_reason_detail="duplicate repository key encountered in the raw discovery payload",
                source_file=source_file,
                source_record_index=source_index,
                timestamp=timestamp,
            )
        )
        reason_counts["duplicate_candidate"] += 1

    for source_index, record in deduped_records:
        reason_code, reason_detail = classify_repository_record(record, expected_language=language_group)
        if reason_code is not None:
            exclusion_rows.append(
                build_exclusion_log_row(
                    record,
                    language_group=language_group,
                    exclusion_reason_code=reason_code,
                    exclusion_reason_detail=reason_detail or "",
                    source_file=source_file,
                    source_record_index=source_index,
                    timestamp=timestamp,
                )
            )
            reason_counts[reason_code] += 1
            continue

        manual_review_matches = detect_manual_review_matches(record, manual_cues)
        filtered_rows.append(
            build_filtered_candidate_row(
                record,
                language_group=language_group,
                manual_review_matches=manual_review_matches,
                source_file=source_file,
                source_record_index=source_index,
            )
        )
        if manual_review_matches:
            manual_review_rows.append(
                build_manual_review_row(
                    record,
                    language_group=language_group,
                    manual_review_matches=manual_review_matches,
                    source_file=source_file,
                    source_record_index=source_index,
                    timestamp=timestamp,
                )
            )

    reason_counts["retained"] = len(filtered_rows)
    reason_counts["manual_review_flagged"] = len(manual_review_rows)
    return filtered_rows, exclusion_rows, manual_review_rows, reason_counts


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    keywords_path = get_config_path("config/keywords.yaml", args.keywords)
    keywords = load_yaml_file(keywords_path)
    manual_cues = [str(cue) for cue in keywords.get("manual_exclusion_cues", []) if str(cue).strip()]

    filtering_config = config.get("candidate_filtering", {})
    defer_language_threshold_validation = bool(filtering_config.get("defer_language_threshold_validation", True))

    raw_input_dir = get_raw_input_dir(config, args.raw_dir)
    output_dir = get_output_dir(config, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Using raw candidate input directory: %s", raw_input_dir)
    LOGGER.info("Using filtered candidate output directory: %s", output_dir)

    language_groups = config.get("languages", ["JavaScript", "TypeScript"])
    all_exclusion_rows: list[dict[str, Any]] = []
    all_manual_review_rows: list[dict[str, Any]] = []

    filtered_fieldnames = [
        "language_group",
        "manual_review_flag",
        "manual_review_cues",
        "manual_review_fields",
        "id",
        "node_id",
        "name",
        "full_name",
        "html_url",
        "description",
        "language",
        "stargazers_count",
        "watchers_count",
        "forks_count",
        "open_issues_count",
        "archived",
        "fork",
        "has_issues",
        "private",
        "created_at",
        "updated_at",
        "pushed_at",
        "default_branch",
        "owner_login",
        "owner_type",
        "license_spdx_id",
        "source_file",
        "source_record_index",
    ]
    exclusion_fieldnames = [
        "timestamp",
        "language_group",
        "repository_id",
        "repository_full_name",
        "exclusion_reason_code",
        "exclusion_reason_detail",
        "source_file",
        "source_record_index",
    ]
    manual_review_fieldnames = [
        "timestamp",
        "language_group",
        "repository_id",
        "repository_full_name",
        "matched_cues",
        "matched_fields",
        "current_inclusion_status",
        "review_note",
        "source_file",
        "source_record_index",
    ]

    for language_group in language_groups:
        slug = str(language_group).strip().lower().replace(" ", "_")
        raw_path = raw_input_dir / f"{slug}_candidates_raw.json"
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing raw candidate discovery file for {language_group}: {raw_path}")

        filtered_rows, exclusion_rows, manual_review_rows, reason_counts = process_language_group(
            language_group=language_group,
            raw_path=raw_path,
            manual_cues=manual_cues,
            defer_language_threshold_validation=defer_language_threshold_validation,
        )

        filtered_path = output_dir / f"{slug}_candidates_filtered.csv"
        write_csv(filtered_path, filtered_rows, filtered_fieldnames)
        LOGGER.info("Saved %s filtered candidates to %s", language_group, filtered_path)

        all_exclusion_rows.extend(exclusion_rows)
        all_manual_review_rows.extend(manual_review_rows)

        LOGGER.info(
            "%s filtering summary: retained=%s, excluded=%s, manual_review_flags=%s",
            language_group,
            reason_counts["retained"],
            sum(count for key, count in reason_counts.items() if key not in {"retained", "manual_review_flagged"}),
            reason_counts["manual_review_flagged"],
        )
        for reason_code, count in sorted(reason_counts.items()):
            if reason_code in {"retained", "manual_review_flagged"}:
                continue
            LOGGER.info("%s exclusion count for %s: %s", language_group, reason_code, count)

    exclusion_path = output_dir / "candidate_exclusion_log.csv"
    manual_review_path = output_dir / "candidate_manual_review_flags.csv"
    write_csv(exclusion_path, all_exclusion_rows, exclusion_fieldnames)
    write_csv(manual_review_path, all_manual_review_rows, manual_review_fieldnames)

    LOGGER.info("Saved exclusion log to %s", exclusion_path)
    LOGGER.info("Saved manual-review flags to %s", manual_review_path)
    LOGGER.info("Total excluded repositories: %s", len(all_exclusion_rows))
    LOGGER.info("Total manual-review flags: %s", len(all_manual_review_rows))
    if defer_language_threshold_validation:
        LOGGER.info("Language-threshold validation remains deferred until a later metadata/language-stats step.")


if __name__ == "__main__":
    main()
