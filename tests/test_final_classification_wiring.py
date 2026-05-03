from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.classify.classify_commits import (
    default_classified_commits_dir,
    default_commit_validation_dir,
    default_raw_commits_dir,
    _load_active_commit_manifest,
)
from scripts.classify.classify_issues import (
    default_classified_issues_dir,
    default_issue_validation_dir,
    default_raw_issues_dir,
    _load_active_issue_manifest,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_commit_classification_routes_final_study_paths() -> None:
    sample_file = "data/interim/final_sample/final_sample.csv"

    assert default_raw_commits_dir(sample_file).as_posix().endswith("data/interim/final_sample/raw_commits")
    assert default_classified_commits_dir(sample_file).as_posix().endswith(
        "data/interim/final_sample/classified_commits"
    )
    assert default_commit_validation_dir(sample_file).as_posix().endswith(
        "data/processed/validation/final_sample"
    )


def test_issue_classification_routes_final_study_paths() -> None:
    sample_file = "data/interim/final_sample/final_sample.csv"

    assert default_raw_issues_dir(sample_file).as_posix().endswith("data/interim/final_sample/raw_issues")
    assert default_classified_issues_dir(sample_file).as_posix().endswith(
        "data/interim/final_sample/classified_issues"
    )
    assert default_issue_validation_dir(sample_file).as_posix().endswith(
        "data/processed/validation/final_sample"
    )


def test_commit_classification_uses_sample_manifest_rows_without_rq1_gate(tmp_path) -> None:
    sample_file = tmp_path / "final_sample.csv"
    _write_csv(
        sample_file,
        [
            {
                "repository_full_name": "example/sampled",
                "language_group": "JavaScript",
                "pre_sampling_eligible": "True",
            }
        ],
    )

    rows, manifest_kind = _load_active_commit_manifest(
        sample_file=sample_file,
    )

    assert manifest_kind == "sample_manifest"
    assert [row["repository_full_name"] for row in rows] == ["example/sampled"]


def test_issue_classification_rejects_noneligible_sample_manifest_rows(tmp_path) -> None:
    sample_file = tmp_path / "final_sample.csv"
    _write_csv(
        sample_file,
        [
            {
                "repository_full_name": "example/not-eligible",
                "language_group": "TypeScript",
                "pre_sampling_eligible": "False",
            }
        ],
    )

    with pytest.raises(ValueError, match="contains non-eligible rows"):
        _load_active_issue_manifest(
            sample_file=sample_file,
        )
