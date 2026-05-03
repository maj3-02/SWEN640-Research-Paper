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
    build_issue_validation_sample_rows,
    classify_issue_record,
    load_json,
    load_sample_manifest_rows,
    parse_bool,
    row_lookup,
    sample_manifest_row_trace,
    write_csv,
    write_json,
)
from scripts.utils.config import load_study_config, load_yaml_file
from scripts.utils.collection import repository_artifact_path
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import (
    classified_issues_dir,
    final_sample_dir,
    processed_validation_dir,
    raw_issues_dir,
    resolve_repo_path,
)

LOGGER = logging.getLogger(__name__)
CLASSIFIED_ISSUES_FILENAME = "classified_issues.csv"
CLASSIFIED_ISSUES_SUMMARY_FILENAME = "classified_issues_summary.json"
ISSUE_VALIDATION_SAMPLE_FILENAME = "issue_validation_sample.csv"


def default_raw_issues_dir(manifest_file: Path) -> Path:
    provenance = build_classification_run_provenance(manifest_file)
    if provenance["classification_run_type"] == "final_study":
        return final_sample_dir() / "raw_issues"
    return raw_issues_dir()


def default_classified_issues_dir(manifest_file: Path) -> Path:
    provenance = build_classification_run_provenance(manifest_file)
    if provenance["classification_run_type"] == "final_study":
        return final_sample_dir() / "classified_issues"
    return classified_issues_dir()


def default_issue_validation_dir(manifest_file: Path) -> Path:
    provenance = build_classification_run_provenance(manifest_file)
    if provenance["classification_run_type"] == "final_study":
        return processed_validation_dir() / "final_sample"
    return processed_validation_dir()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify raw issues as bug-related or not.")
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
        "--raw-issues-dir",
        default=None,
        help="Directory containing raw issue JSON files. Defaults to data/raw/issues.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for classified issue outputs. Defaults to data/interim/classified_issues.",
    )
    parser.add_argument(
        "--validation-dir",
        default=None,
        help="Directory for issue validation samples. Defaults to data/processed/validation.",
    )
    return parser.parse_args()


def _repo_path(raw_dir: Path, repository_full_name: str) -> Path:
    return repository_artifact_path(raw_dir, repository_full_name, "issues_raw.json")


def default_sample_manifest_file() -> Path:
    return final_sample_dir() / "final_sample.csv"


def _repository_full_name(row: dict[str, Any]) -> str:
    return str(row.get("repository_full_name") or row.get("full_name") or "").strip()


def _load_active_issue_manifest(
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
    bug_issue = payload.get("bug_issue") or {}
    if not isinstance(bug_issue, dict):
        raise ValueError("keywords.yaml bug_issue section must be a mapping")
    label_terms = list(bug_issue.get("label_terms") or [])
    text_terms = list(bug_issue.get("text_terms") or [])
    return {
        "label_terms": [str(term) for term in label_terms if str(term).strip()],
        "text_terms": [str(term) for term in text_terms if str(term).strip()],
    }


def _classify_repository_issues(
    *,
    repository_full_name: str,
    language_group: str | None,
    source_file: str,
    issues: list[dict[str, Any]],
    label_terms: list[str],
    text_terms: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    classified_rows: list[dict[str, Any]] = []
    bug_related_count = 0
    label_only_count = 0
    text_only_count = 0
    label_and_text_count = 0

    for index, issue in enumerate(issues):
        row = classify_issue_record(
            issue,
            repository_full_name=repository_full_name,
            language_group=language_group,
            source_file=source_file,
            record_index=index,
            label_terms=label_terms,
            text_terms=text_terms,
        )
        classified_rows.append(row)
        if row["is_bug_related"]:
            bug_related_count += 1
            if row["match_source"] == "label":
                label_only_count += 1
            elif row["match_source"] == "title" or row["match_source"] == "body" or row["match_source"] == "title;body":
                text_only_count += 1
            else:
                label_and_text_count += 1

    repo_summary = {
        "repository_full_name": repository_full_name,
        "language_group": language_group,
        "source_file": source_file,
        "raw_issue_count": len(issues),
        "classified_issue_count": len(classified_rows),
        "bug_related_issue_count": bug_related_count,
        "bug_related_label_only_count": label_only_count,
        "bug_related_text_only_count": text_only_count,
        "bug_related_label_and_text_count": label_and_text_count,
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
        resolve_repo_path(args.raw_issues_dir)
        if args.raw_issues_dir is not None
        else default_raw_issues_dir(active_manifest_file)
    )
    output_dir = (
        resolve_repo_path(args.output_dir)
        if args.output_dir is not None
        else default_classified_issues_dir(active_manifest_file)
    )
    validation_dir = (
        resolve_repo_path(args.validation_dir)
        if args.validation_dir is not None
        else default_issue_validation_dir(active_manifest_file)
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    validation_dir.mkdir(parents=True, exist_ok=True)

    keywords = _load_keywords(keywords_path)
    run_provenance = build_classification_run_provenance(active_manifest_file)
    manifest_rows, manifest_kind = _load_active_issue_manifest(
        sample_file=sample_file,
    )
    manifest_lookup = row_lookup(manifest_rows, key_field="repository_full_name")

    LOGGER.info("Using active issue classification manifest: %s", active_manifest_file)
    LOGGER.info("Classification input kind: %s", manifest_kind)
    LOGGER.info("Classification run type: %s", run_provenance["classification_run_type"])
    LOGGER.info("Using raw issue directory: %s", raw_dir)
    LOGGER.info("Using classified issue output directory: %s", output_dir)
    LOGGER.info("Using issue validation output directory: %s", validation_dir)
    LOGGER.info("Repositories requested for issue classification: %s", len(manifest_rows))

    classified_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    total_records = 0
    total_positive = 0
    total_label_only = 0
    total_text_only = 0
    total_label_and_text = 0

    for repository_full_name, repo_row in manifest_lookup.items():
        language_group = repo_row.get("language_group")
        trace = sample_manifest_row_trace(repo_row)
        raw_path = _repo_path(raw_dir, repository_full_name)
        if not raw_path.exists():
            LOGGER.warning("Missing raw issue file for %s: %s", repository_full_name, raw_path)
            failures.append(
                {
                    "repository_full_name": repository_full_name,
                    "language_group": language_group,
                    "stage": "issues",
                    "error_type": "FileNotFoundError",
                    "message": f"Missing raw issue file: {raw_path}",
                    "source_file": str(raw_path),
                    "classification_run_type": run_provenance["classification_run_type"],
                    "sample_trace": trace,
                }
            )
            continue

        payload = load_json(raw_path)
        issues = payload.get("issues") or []
        sample_row = payload.get("sample_row") or {}
        payload_language = sample_row.get("language_group") or language_group
        repo_rows, repo_summary = _classify_repository_issues(
            repository_full_name=repository_full_name,
            language_group=payload_language,
            source_file=str(raw_path),
            issues=issues,
            label_terms=keywords["label_terms"],
            text_terms=keywords["text_terms"],
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
        total_positive += int(repo_summary["bug_related_issue_count"])
        total_label_only += int(repo_summary["bug_related_label_only_count"])
        total_text_only += int(repo_summary["bug_related_text_only_count"])
        total_label_and_text += int(repo_summary["bug_related_label_and_text_count"])

        repo_summary["output_file"] = str(output_dir / CLASSIFIED_ISSUES_FILENAME)
        repo_summary["classification_run_type"] = run_provenance["classification_run_type"]
        repo_summary["sample_trace"] = trace
        results.append(repo_summary)
        LOGGER.info(
            "Classified %s issues for %s (%s bug-related, %s label-only, %s text-only, %s label+text)",
            repo_summary["classified_issue_count"],
            repository_full_name,
            repo_summary["bug_related_issue_count"],
            repo_summary["bug_related_label_only_count"],
            repo_summary["bug_related_text_only_count"],
            repo_summary["bug_related_label_and_text_count"],
        )

    output_file = output_dir / CLASSIFIED_ISSUES_FILENAME
    summary_file = output_dir / CLASSIFIED_ISSUES_SUMMARY_FILENAME
    fieldnames = [
        "repository_full_name",
        "language_group",
        "issue_id",
        "issue_number",
        "issue_url",
        "title",
        "body",
        "state",
        "closed_at",
        "issue_author_login",
        "label_names",
        "is_bug_related",
        "matched_label_terms",
        "matched_text_terms",
        "match_source",
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

    validation_rows = build_issue_validation_sample_rows(classified_rows, sample_size=20, positive_target=10, seed=int(config.get("random_seed", 640)))
    validation_output_file = validation_dir / ISSUE_VALIDATION_SAMPLE_FILENAME
    validation_fieldnames = fieldnames + ["validation_sample_category", "validation_sample_reason"]
    write_csv(validation_output_file, validation_rows, fieldnames=validation_fieldnames)

    summary = {
        "classification_type": "issues",
        "classification_run_type": run_provenance["classification_run_type"],
        "classification_input_kind": manifest_kind,
        "sample_manifest_file": str(active_manifest_file),
        "raw_issues_dir": str(raw_dir),
        "output_dir": str(output_dir),
        "validation_output_dir": str(validation_dir),
        "validation_output_file": str(validation_output_file),
        "keywords_file": str(keywords_path),
        "random_seed": int(config.get("random_seed", 640)),
        "label_terms": keywords["label_terms"],
        "text_terms": keywords["text_terms"],
        "repositories_requested": len(manifest_rows),
        "repositories_classified": len(results),
        "repositories_failed": len(failures),
        "records_classified": total_records,
        "positive_classifications": total_positive,
        "positive_label_only_count": total_label_only,
        "positive_text_only_count": total_text_only,
        "positive_label_and_text_count": total_label_and_text,
        "validation_sample_size_requested": 20,
        "validation_sample_size_written": len(validation_rows),
        "results": results,
        "failures": failures,
    }
    write_json(summary_file, summary)

    LOGGER.info("Total issue records classified: %s", total_records)
    LOGGER.info("Positive bug-related issue classifications: %s", total_positive)
    LOGGER.info("Saved classified issues to %s", output_file)
    LOGGER.info("Saved issue classification summary to %s", summary_file)
    LOGGER.info("Saved issue validation sample to %s", validation_output_file)


if __name__ == "__main__":
    main()
