from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.classification import (
    build_classification_run_provenance,
    build_commit_validation_sample_rows,
    classify_commit_record,
    load_json,
    load_sample_manifest_rows,
    parse_bool,
    row_lookup,
    sample_manifest_row_trace,
    write_csv,
    write_json,
)
from scripts.utils.config import load_study_config, load_yaml_file
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import (
    classified_commits_dir,
    final_sample_dir,
    processed_validation_dir,
    raw_commits_dir,
    resolve_repo_path,
)
from scripts.utils.collection import repository_artifact_path

LOGGER = logging.getLogger(__name__)
CLASSIFIED_COMMITS_FILENAME = "classified_commits.csv"
CLASSIFIED_COMMITS_SUMMARY_FILENAME = "classified_commits_summary.json"
COMMIT_VALIDATION_SAMPLE_FILENAME = "commit_validation_sample.csv"


def default_raw_commits_dir(manifest_file: Path) -> Path:
    provenance = build_classification_run_provenance(manifest_file)
    if provenance["classification_run_type"] == "final_study":
        return final_sample_dir() / "raw_commits"
    return raw_commits_dir()


def default_classified_commits_dir(manifest_file: Path) -> Path:
    provenance = build_classification_run_provenance(manifest_file)
    if provenance["classification_run_type"] == "final_study":
        return final_sample_dir() / "classified_commits"
    return classified_commits_dir()


def default_commit_validation_dir(manifest_file: Path) -> Path:
    provenance = build_classification_run_provenance(manifest_file)
    if provenance["classification_run_type"] == "final_study":
        return processed_validation_dir() / "final_sample"
    return processed_validation_dir()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify raw commits as bug-fix or not.")
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
        "--sample-file",
        default=None,
        help="Path to the final sample manifest CSV. Defaults to data/interim/final_sample/final_sample.csv.",
    )
    parser.add_argument(
        "--raw-commits-dir",
        default=None,
        help="Directory containing raw commit JSON files. Defaults to data/raw/commits.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for classified commit outputs. Defaults to data/interim/classified_commits.",
    )
    parser.add_argument(
        "--validation-dir",
        default=None,
        help="Directory for commit validation samples. Defaults to data/processed/validation.",
    )
    return parser.parse_args()


def _repo_path(raw_dir: Path, repository_full_name: str) -> Path:
    return repository_artifact_path(raw_dir, repository_full_name, "commits_raw.json")


def default_sample_manifest_file() -> Path:
    return final_sample_dir() / "final_sample.csv"


def _repository_full_name(row: dict[str, Any]) -> str:
    return str(row.get("repository_full_name") or row.get("full_name") or "").strip()


def _load_active_commit_manifest(
    *,
    sample_file: Path,
) -> tuple[list[dict[str, Any]], str]:
    rows = load_sample_manifest_rows(sample_file)
    missing_fields = [
        field
        for field in ["repository_full_name", "language_group", "pre_sampling_eligible"]
        if rows and field not in rows[0]
    ]
    if missing_fields:
        raise ValueError(
            f"Sample manifest {sample_file} is missing required fields: {', '.join(missing_fields)}"
        )
    non_eligible = [
        _repository_full_name(row)
        for row in rows
        if row.get("pre_sampling_eligible") is not None and not parse_bool(row.get("pre_sampling_eligible"))
    ]
    if non_eligible:
        raise ValueError(
            f"Sample manifest {sample_file} contains non-eligible rows: {', '.join(non_eligible)}"
        )
    return [row for row in rows if _repository_full_name(row)], "sample_manifest"


def _load_keywords(keywords_path: str | Path) -> dict[str, Any]:
    payload = load_yaml_file(keywords_path)
    bug_fix_commit = payload.get("bug_fix_commit") or {}
    if not isinstance(bug_fix_commit, dict):
        raise ValueError("keywords.yaml bug_fix_commit section must be a mapping")
    required = list(bug_fix_commit.get("required") or [])
    additional = list(bug_fix_commit.get("additional_any_of") or [])
    return {
        "required": [str(term) for term in required if str(term).strip()],
        "additional": [str(term) for term in additional if str(term).strip()],
    }


def _classify_repository_commits(
    *,
    repository_full_name: str,
    language_group: str | None,
    source_file: str,
    commits: list[dict[str, Any]],
    required_terms: list[str],
    additional_terms: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    classified_rows: list[dict[str, Any]] = []
    bug_fix_count = 0
    provisional_issue_term_count = 0

    for index, commit in enumerate(commits):
        row = classify_commit_record(
            commit,
            repository_full_name=repository_full_name,
            language_group=language_group,
            source_file=source_file,
            record_index=index,
            required_terms=required_terms,
            additional_terms=additional_terms,
        )
        classified_rows.append(row)
        if row["is_bug_fix"]:
            bug_fix_count += 1
        if row["is_bug_fix"] and row["provisional_issue_term_used"]:
            provisional_issue_term_count += 1

    repo_summary = {
        "repository_full_name": repository_full_name,
        "language_group": language_group,
        "source_file": source_file,
        "raw_commit_count": len(commits),
        "classified_commit_count": len(classified_rows),
        "bug_fix_commit_count": bug_fix_count,
        "provisional_issue_term_commit_count": provisional_issue_term_count,
    }
    return classified_rows, repo_summary


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    keywords_path = (
        resolve_repo_path(args.keywords)
        if args.keywords is not None
        else resolve_repo_path(Path("config") / "keywords.yaml")
    )
    sample_file = resolve_repo_path(args.sample_file) if args.sample_file is not None else default_sample_manifest_file()
    active_manifest_file = sample_file
    raw_dir = (
        resolve_repo_path(args.raw_commits_dir)
        if args.raw_commits_dir is not None
        else default_raw_commits_dir(active_manifest_file)
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else default_classified_commits_dir(active_manifest_file)
    )
    validation_dir = (
        resolve_repo_path(args.validation_dir)
        if args.validation_dir is not None
        else default_commit_validation_dir(active_manifest_file)
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    keywords = _load_keywords(keywords_path)
    run_provenance = build_classification_run_provenance(active_manifest_file)
    manifest_rows, manifest_kind = _load_active_commit_manifest(
        sample_file=sample_file,
    )
    manifest_lookup = row_lookup(manifest_rows, key_field="repository_full_name")

    LOGGER.info("Using active commit classification manifest: %s", active_manifest_file)
    LOGGER.info("Classification input kind: %s", manifest_kind)
    LOGGER.info("Classification run type: %s", run_provenance["classification_run_type"])
    LOGGER.info("Using raw commit directory: %s", raw_dir)
    LOGGER.info("Using classified commit output directory: %s", output_dir)
    LOGGER.info("Using commit validation output directory: %s", validation_dir)
    LOGGER.info("Repositories requested for commit classification: %s", len(manifest_rows))

    classified_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    total_records = 0
    total_positive = 0
    total_provisional = 0

    for repository_full_name, repo_row in manifest_lookup.items():
        language_group = repo_row.get("language_group")
        trace = sample_manifest_row_trace(repo_row)
        raw_path = _repo_path(raw_dir, repository_full_name)
        if not raw_path.exists():
            LOGGER.warning("Missing raw commit file for %s: %s", repository_full_name, raw_path)
            failures.append(
                {
                    "repository_full_name": repository_full_name,
                    "language_group": language_group,
                    "stage": "commits",
                    "error_type": "FileNotFoundError",
                    "message": f"Missing raw commit file: {raw_path}",
                    "source_file": str(raw_path),
                    "classification_run_type": run_provenance["classification_run_type"],
                    "sample_trace": trace,
                }
            )
            continue

        payload = load_json(raw_path)
        commits = payload.get("commits") or []
        sample_row = payload.get("sample_row") or {}
        payload_language = sample_row.get("language_group") or language_group
        repo_rows, repo_summary = _classify_repository_commits(
            repository_full_name=repository_full_name,
            language_group=payload_language,
            source_file=str(raw_path),
            commits=commits,
            required_terms=keywords["required"],
            additional_terms=keywords["additional"],
        )
        for classified_row in repo_rows:
            classified_row["classification_run_type"] = run_provenance["classification_run_type"]
            classified_row["sample_manifest_file"] = str(active_manifest_file)
            classified_row["sample_source_file"] = trace.get("sample_source_file", "")
            classified_row["sample_source_record_index"] = trace.get("sample_source_record_index", "")
            classified_row["sample_role"] = trace.get("sample_role", "")
            classified_row["sample_activity_stratum"] = trace.get(
                "sample_activity_stratum",
                trace.get("activity_stratum", ""),
            )
            classified_row["sample_activity_value"] = trace.get(
                "sample_activity_value",
                trace.get("activity_value", ""),
            )
        classified_rows.extend(repo_rows)
        total_records += len(repo_rows)
        total_positive += int(repo_summary["bug_fix_commit_count"])
        total_provisional += int(repo_summary["provisional_issue_term_commit_count"])

        repo_summary["output_file"] = str(output_dir / CLASSIFIED_COMMITS_FILENAME)
        repo_summary["classification_run_type"] = run_provenance["classification_run_type"]
        repo_summary["sample_trace"] = trace
        results.append(repo_summary)
        LOGGER.info(
            "Classified %s commits for %s (%s bug-fix, %s provisional-issue-term matches)",
            repo_summary["classified_commit_count"],
            repository_full_name,
            repo_summary["bug_fix_commit_count"],
            repo_summary["provisional_issue_term_commit_count"],
        )

    output_file = output_dir / CLASSIFIED_COMMITS_FILENAME
    summary_file = output_dir / CLASSIFIED_COMMITS_SUMMARY_FILENAME
    fieldnames = [
        "repository_full_name",
        "language_group",
        "commit_sha",
        "commit_message",
        "commit_date",
        "commit_author_login",
        "commit_author_name",
        "commit_author_email",
        "commit_committer_name",
        "commit_committer_email",
        "is_bug_fix",
        "matched_required_term",
        "matched_additional_terms",
        "provisional_issue_term_used",
        "provisional_issue_term_matched",
        "classification_reason",
        "source_file",
        "raw_record_index",
        "classification_run_type",
        "sample_manifest_file",
        "sample_source_file",
        "sample_source_record_index",
        "sample_role",
        "sample_activity_stratum",
        "sample_activity_value",
    ]
    write_csv(output_file, classified_rows, fieldnames=fieldnames)

    validation_rows = build_commit_validation_sample_rows(classified_rows, sample_size=20, positive_target=10, seed=int(config.get("random_seed", 640)))
    validation_output_file = validation_dir / COMMIT_VALIDATION_SAMPLE_FILENAME
    validation_fieldnames = fieldnames + ["validation_sample_category", "validation_sample_reason"]
    write_csv(validation_output_file, validation_rows, fieldnames=validation_fieldnames)

    summary = {
        "classification_type": "commits",
        "classification_run_type": run_provenance["classification_run_type"],
        "classification_input_kind": manifest_kind,
        "sample_manifest_file": str(active_manifest_file),
        "raw_commits_dir": str(raw_dir),
        "output_dir": str(output_dir),
        "validation_output_dir": str(validation_dir),
        "validation_output_file": str(validation_output_file),
        "keywords_file": str(keywords_path),
        "random_seed": int(config.get("random_seed", 640)),
        "required_terms": keywords["required"],
        "additional_terms": keywords["additional"],
        "repositories_requested": len(manifest_rows),
        "repositories_classified": len(results),
        "repositories_failed": len(failures),
        "records_classified": total_records,
        "positive_classifications": total_positive,
        "provisional_issue_term_matches": total_provisional,
        "validation_sample_size_requested": 20,
        "validation_sample_size_written": len(validation_rows),
        "results": results,
        "failures": failures,
    }
    write_json(summary_file, summary)

    LOGGER.info("Total commit records classified: %s", total_records)
    LOGGER.info("Positive bug-fix commit classifications: %s", total_positive)
    LOGGER.info("Provisional issue-term matches among positive commits: %s", total_provisional)
    LOGGER.info("Saved classified commits to %s", output_file)
    LOGGER.info("Saved commit classification summary to %s", summary_file)
    LOGGER.info("Saved commit validation sample to %s", validation_output_file)


if __name__ == "__main__":
    main()
