from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import Counter
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
    final_candidate_screen_dir,
    final_candidate_screen_paths,
    final_sample_dir,
    final_sample_paths,
    resolve_repo_path,
)
from scripts.utils.sampling import (
    ACTIVITY_STRATA,
    allocate_targets,
    assign_numeric_activity_strata,
    counts_by_language_and_stratum,
    draw_reserves_by_language_stratum,
    draw_stratified_sample_numeric_activity,
    parse_numeric_activity_value,
    write_csv,
    write_json,
)

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assign numeric activity strata and draw the final-study sample plus reserve candidates."
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Override for final candidate screen input directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override for final-study sample output directory.",
    )
    return parser.parse_args()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _repository_key(row: Mapping[str, Any]) -> str:
    return str(row.get("repository_full_name") or row.get("full_name") or "").strip()


REQUIRED_ELIGIBLE_POOL_FIELDS = [
    "repository_full_name",
    "language_group",
    "pre_sampling_eligible",
    "default_branch_commit_count_in_window",
]


def read_csv_rows_with_fieldnames(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def validate_eligible_pool_fieldnames(fieldnames: list[str], *, input_file: Path) -> None:
    missing = [field for field in REQUIRED_ELIGIBLE_POOL_FIELDS if field not in fieldnames]
    if missing:
        raise ValueError(
            f"Final eligible candidate pool {input_file} is missing required fields: {', '.join(missing)}"
        )


def load_eligible_candidate_pool_rows(
    input_dir: Path,
    languages: list[str],
    *,
    activity_field: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    path = final_candidate_screen_paths(input_dir)["eligible_pool_csv"]
    if not path.exists():
        raise FileNotFoundError(f"Missing final eligible candidate pool file: {path}")

    LOGGER.info("Loading final eligible candidate pool from %s", path)
    candidate_rows, fieldnames = read_csv_rows_with_fieldnames(path)
    validate_eligible_pool_fieldnames(fieldnames, input_file=path)
    language_set = set(languages)

    for index, row in enumerate(candidate_rows, start=1):
        row["final_sampling_input_file"] = str(path)
        row["final_sampling_input_record_index"] = index

        if not _repository_key(row):
            invalid_rows.append(_invalid_row(row, "missing_repository_full_name"))
            continue
        language_group = str(row.get("language_group") or "").strip()
        if language_group not in language_set:
            invalid_rows.append(_invalid_row(row, f"unexpected_language_group:{language_group or '<missing>'}"))
            continue
        if not parse_bool(row.get("pre_sampling_eligible")):
            raise ValueError(
                f"Final eligible candidate pool contains a non-eligible row for {_repository_key(row) or '<missing repository>'}."
            )
        try:
            row[activity_field] = parse_numeric_activity_value(row.get(activity_field))
        except ValueError as exc:
            invalid_rows.append(_invalid_row(row, f"invalid_activity_value: {exc}"))
            continue

        rows.append(row)

    LOGGER.info("Loaded %s candidate-pool rows from %s", len(candidate_rows), path)
    return rows, invalid_rows, [str(path)]


def _invalid_row(row: Mapping[str, Any], reason: str) -> dict[str, Any]:
    return {
        "repository_full_name": _repository_key(row),
        "language_group": row.get("language_group"),
        "reason": reason,
        "final_sampling_input_file": row.get("final_sampling_input_file"),
        "final_sampling_input_record_index": row.get("final_sampling_input_record_index"),
    }


def output_fieldnames(rows: list[Mapping[str, Any]]) -> list[str]:
    base_fields: list[str] = []
    for row in rows:
        for field in row.keys():
            if field not in base_fields:
                base_fields.append(field)

    final_fields = [
        "final_sampling_stage",
        "final_sampling_role",
        "reserve_rank_within_language_stratum",
    ]
    return base_fields + [field for field in final_fields if field not in base_fields]


def _counts_by_language(rows: list[Mapping[str, Any]], languages: list[str]) -> dict[str, int]:
    counts = Counter(str(row.get("language_group") or "") for row in rows)
    return {language: counts.get(language, 0) for language in languages}


def _complete_language_stratum_counts(rows: list[dict[str, Any]], languages: list[str]) -> dict[str, dict[str, int]]:
    counts = counts_by_language_and_stratum(rows)
    return {
        language: {stratum: int(counts.get(language, {}).get(stratum, 0)) for stratum in ACTIVITY_STRATA}
        for language in languages
    }


def _scenario_support(
    *,
    counts_by_language_stratum: Mapping[str, Mapping[str, int]],
    sample_per_language: int,
    reserve_per_language_stratum: int,
    languages: list[str],
) -> dict[str, Any]:
    by_language: dict[str, Any] = {}
    sample_possible_all = True
    reserves_possible_all = True

    for language in languages:
        stratum_counts = {stratum: int(counts_by_language_stratum.get(language, {}).get(stratum, 0)) for stratum in ACTIVITY_STRATA}
        language_total = sum(stratum_counts.values())
        sample_possible = language_total >= sample_per_language
        sample_allocation: dict[str, int] = {stratum: 0 for stratum in ACTIVITY_STRATA}
        allocation_error = ""

        if sample_possible:
            try:
                sample_allocation = allocate_targets(stratum_counts, sample_per_language)
            except ValueError as exc:
                sample_possible = False
                allocation_error = str(exc)

        reserve_capacity_after_sample = {
            stratum: max(0, stratum_counts[stratum] - sample_allocation.get(stratum, 0))
            for stratum in ACTIVITY_STRATA
        }
        reserve_shortfalls = {
            stratum: max(0, reserve_per_language_stratum - reserve_capacity_after_sample[stratum])
            for stratum in ACTIVITY_STRATA
        }
        reserves_possible = sample_possible and all(shortfall == 0 for shortfall in reserve_shortfalls.values())

        sample_possible_all = sample_possible_all and sample_possible
        reserves_possible_all = reserves_possible_all and reserves_possible
        by_language[language] = {
            "candidate_count": language_total,
            "stratum_counts": stratum_counts,
            "sample_per_language": sample_per_language,
            "sample_possible": sample_possible,
            "sample_allocation_by_stratum": sample_allocation,
            "reserve_per_language_stratum": reserve_per_language_stratum,
            "reserve_capacity_after_sample_by_stratum": reserve_capacity_after_sample,
            "reserve_shortfalls_by_stratum": reserve_shortfalls,
            "sample_plus_reserves_possible": reserves_possible,
            "allocation_error": allocation_error,
        }

    return {
        "sample_per_language": sample_per_language,
        "sample_possible": sample_possible_all,
        "sample_plus_reserves_possible": sample_possible_all and reserves_possible_all,
        "by_language": by_language,
    }


def build_pool_sufficiency_report(
    *,
    stratified_rows: list[dict[str, Any]],
    invalid_rows: list[dict[str, Any]],
    languages: list[str],
    target_sample_per_language: int,
    fallback_sample_per_language: int,
    reserve_per_language_stratum: int,
    activity_field: str,
    input_files: list[str],
) -> dict[str, Any]:
    language_counts = _counts_by_language(stratified_rows, languages)
    language_stratum_counts = _complete_language_stratum_counts(stratified_rows, languages)
    target_support = _scenario_support(
        counts_by_language_stratum=language_stratum_counts,
        sample_per_language=target_sample_per_language,
        reserve_per_language_stratum=reserve_per_language_stratum,
        languages=languages,
    )
    fallback_support = _scenario_support(
        counts_by_language_stratum=language_stratum_counts,
        sample_per_language=fallback_sample_per_language,
        reserve_per_language_stratum=reserve_per_language_stratum,
        languages=languages,
    )

    return {
        "checkpoint_type": "final_sample_pool_sufficiency",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "final_sample_only",
        "input_files": input_files,
        "activity_field": activity_field,
        "activity_strata": list(ACTIVITY_STRATA),
        "threshold_passing_candidates_by_language": language_counts,
        "threshold_passing_candidates_by_language_and_stratum": language_stratum_counts,
        "invalid_activity_candidate_count": len(invalid_rows),
        "invalid_activity_candidates": invalid_rows,
        "target": target_support,
        "fallback": fallback_support,
        "selected_plan": (
            "target"
            if target_support["sample_plus_reserves_possible"]
            else "fallback"
            if fallback_support["sample_plus_reserves_possible"] or fallback_support["sample_possible"]
            else "none"
        ),
    }


def select_sample_size_from_sufficiency(
    report: Mapping[str, Any],
    *,
    target_sample_per_language: int,
    fallback_sample_per_language: int,
) -> tuple[int, bool]:
    target = report.get("target") or {}
    fallback = report.get("fallback") or {}
    if target.get("sample_plus_reserves_possible") is True:
        return target_sample_per_language, False
    if fallback.get("sample_plus_reserves_possible") is True or fallback.get("sample_possible") is True:
        return fallback_sample_per_language, True
    raise ValueError("Final candidate pool cannot support even the fallback sample size for every language.")


def build_final_sample_metadata(
    *,
    input_files: list[str],
    output_files: Mapping[str, str],
    activity_field: str,
    target_sample_per_language: int,
    fallback_sample_per_language: int,
    selected_sample_per_language: int,
    fallback_used: bool,
    reserve_per_language_stratum: int,
    random_seed: int,
    stratified_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    reserve_rows: list[dict[str, Any]],
    selection_metadata: Mapping[str, Any],
    reserve_metadata: Mapping[str, Any],
    sufficiency_report: Mapping[str, Any],
) -> dict[str, Any]:
    sample_counts_by_language = Counter(row["language_group"] for row in selected_rows)
    sample_counts_by_stratum = Counter(row["activity_stratum"] for row in selected_rows)
    reserve_counts_by_language = Counter(row["language_group"] for row in reserve_rows)
    reserve_counts_by_stratum = Counter(row["activity_stratum"] for row in reserve_rows)

    return {
        "sampling_type": "final_study_sample",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "final_sample_only",
        "input_files": input_files,
        "input_source": "pre_sampling_eligible_candidate_pool",
        "output_files": dict(output_files),
        "activity_field_used": activity_field,
        "activity_field_is_proxy": False,
        "stratification_method": "numeric terciles within each language group",
        "language_balance_rule": "exact where possible",
        "strata_balance_rule": "as balanced as possible",
        "random_seed": random_seed,
        "target_final_sample_per_language": target_sample_per_language,
        "fallback_final_sample_per_language": fallback_sample_per_language,
        "selected_sample_per_language": selected_sample_per_language,
        "fallback_used": fallback_used,
        "reserve_per_language_stratum": reserve_per_language_stratum,
        "candidate_pool_count": len(stratified_rows),
        "actual_sample_size": len(selected_rows),
        "actual_reserve_size": len(reserve_rows),
        "sample_counts_by_language": dict(sample_counts_by_language),
        "sample_counts_by_stratum": dict(sample_counts_by_stratum),
        "sample_counts_by_language_and_stratum": selection_metadata["selected_counts_by_language_and_stratum"],
        "reserve_counts_by_language": dict(reserve_counts_by_language),
        "reserve_counts_by_stratum": dict(reserve_counts_by_stratum),
        "reserve_counts_by_language_and_stratum": reserve_metadata["reserve_counts_by_language_and_stratum"],
        "reserve_shortfalls_by_language_and_stratum": reserve_metadata["reserve_shortfalls_by_language_and_stratum"],
        "selected_full_names": [_repository_key(row) for row in selected_rows],
        "reserve_full_names": [_repository_key(row) for row in reserve_rows],
        "pool_sufficiency_selected_plan": sufficiency_report.get("selected_plan"),
    }


def _with_sampling_role(rows: list[dict[str, Any]], *, role: str) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched["final_sampling_stage"] = "final_study_sampling"
        enriched["final_sampling_role"] = role
        prepared.append(enriched)
    return prepared


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    final_sampling_config = config.get("final_sampling", {})

    input_dir = (
        resolve_repo_path(args.input_dir)
        if args.input_dir is not None
        else resolve_repo_path(final_sampling_config.get("input_dir", final_candidate_screen_dir()))
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else resolve_repo_path(final_sampling_config.get("output_dir", final_sample_dir()))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    languages = [str(language) for language in config.get("languages", ["JavaScript", "TypeScript"])]
    activity_field = str(final_sampling_config.get("activity_field", "default_branch_commit_count_in_window"))
    target_sample_per_language = int(final_sampling_config.get("final_sample_per_language", 30))
    fallback_sample_per_language = int(final_sampling_config.get("fallback_final_sample_per_language", 20))
    reserve_per_language_stratum = int(final_sampling_config.get("reserve_per_language_stratum", 3))
    random_seed = int(config.get("random_seed", 640))

    LOGGER.info("Using final eligible candidate pool input directory: %s", input_dir)
    LOGGER.info("Using final sample output directory: %s", output_dir)
    LOGGER.info("Using numeric activity field: %s", activity_field)

    eligible_rows, invalid_rows, input_files = load_eligible_candidate_pool_rows(
        input_dir,
        languages,
        activity_field=activity_field,
    )
    stratified_rows = assign_numeric_activity_strata(
        eligible_rows,
        activity_field=activity_field,
        activity_field_is_proxy=False,
    )

    paths = final_sample_paths(output_dir)
    sufficiency_report = build_pool_sufficiency_report(
        stratified_rows=stratified_rows,
        invalid_rows=invalid_rows,
        languages=languages,
        target_sample_per_language=target_sample_per_language,
        fallback_sample_per_language=fallback_sample_per_language,
        reserve_per_language_stratum=reserve_per_language_stratum,
        activity_field=activity_field,
        input_files=input_files,
    )
    write_json(paths["pool_sufficiency_report_json"], sufficiency_report)
    LOGGER.info("Saved pool sufficiency report to %s", paths["pool_sufficiency_report_json"])

    selected_sample_per_language, fallback_used = select_sample_size_from_sufficiency(
        sufficiency_report,
        target_sample_per_language=target_sample_per_language,
        fallback_sample_per_language=fallback_sample_per_language,
    )
    LOGGER.info("Selected sample per language: %s (fallback used: %s)", selected_sample_per_language, fallback_used)

    sample_rows, selection_metadata = draw_stratified_sample_numeric_activity(
        stratified_rows,
        sample_per_language=selected_sample_per_language,
        random_seed=random_seed,
    )
    reserve_rows, reserve_metadata = draw_reserves_by_language_stratum(
        stratified_rows,
        selected_rows=sample_rows,
        reserve_per_language_stratum=reserve_per_language_stratum,
        random_seed=random_seed,
    )

    pool_rows = _with_sampling_role(stratified_rows, role="candidate_pool")
    sample_rows = _with_sampling_role(sample_rows, role="final_sample")
    reserve_rows = _with_sampling_role(reserve_rows, role="reserve")

    fieldnames = output_fieldnames(pool_rows + sample_rows + reserve_rows)
    write_csv(paths["candidate_pool_with_strata_csv"], pool_rows, fieldnames)
    write_csv(paths["final_sample_csv"], sample_rows, fieldnames)
    write_csv(paths["final_reserves_csv"], reserve_rows, fieldnames)

    output_files = {name: str(path) for name, path in paths.items()}
    metadata = build_final_sample_metadata(
        input_files=input_files,
        output_files=output_files,
        activity_field=activity_field,
        target_sample_per_language=target_sample_per_language,
        fallback_sample_per_language=fallback_sample_per_language,
        selected_sample_per_language=selected_sample_per_language,
        fallback_used=fallback_used,
        reserve_per_language_stratum=reserve_per_language_stratum,
        random_seed=random_seed,
        stratified_rows=stratified_rows,
        selected_rows=sample_rows,
        reserve_rows=reserve_rows,
        selection_metadata=selection_metadata,
        reserve_metadata=reserve_metadata,
        sufficiency_report=sufficiency_report,
    )
    write_json(paths["metadata_json"], metadata)

    LOGGER.info("Saved final candidate pool with strata to %s", paths["candidate_pool_with_strata_csv"])
    LOGGER.info("Saved final sample to %s", paths["final_sample_csv"])
    LOGGER.info("Saved final reserves to %s", paths["final_reserves_csv"])
    LOGGER.info("Saved final sample metadata to %s", paths["metadata_json"])


if __name__ == "__main__":
    main()
