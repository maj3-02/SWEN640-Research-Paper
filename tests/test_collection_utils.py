from __future__ import annotations

import csv

from scripts.utils.collection import (
    build_sample_provenance,
    build_collection_failure_record,
    commit_window_timestamp,
    extract_repository_full_name,
    infer_sample_run_type,
    issue_is_pull_request,
    load_sampled_repositories,
    repository_artifact_path,
    repository_slug,
    study_window_bounds,
    timestamp_inclusive_window,
)


def test_repository_slug_and_artifact_path() -> None:
    path = repository_artifact_path("data/raw/commits", "Example Org/Repo Name", "commits_raw.json")

    assert repository_slug("Example Org/Repo Name") == "example_org_repo_name"
    assert path.name == "example_org_repo_name_commits_raw.json"


def test_study_window_bounds_and_timestamp_window() -> None:
    start, end = study_window_bounds("2024-01-01", "2025-12-31")

    assert timestamp_inclusive_window("2024-01-01T00:00:00Z", start, end)
    assert timestamp_inclusive_window("2025-12-31T23:59:59Z", start, end)
    assert not timestamp_inclusive_window("2026-01-01T00:00:00Z", start, end)


def test_issue_is_pull_request_detection() -> None:
    assert issue_is_pull_request({"pull_request": {"url": "https://example.com"}})
    assert not issue_is_pull_request({"number": 1, "title": "Bug"})


def test_commit_window_timestamp_prefers_author_then_committer() -> None:
    commit = {
        "commit": {
            "author": {"date": "2024-02-01T10:00:00Z"},
            "committer": {"date": "2024-02-01T11:00:00Z"},
        }
    }
    fallback_commit = {
        "commit": {
            "author": {"date": None},
            "committer": {"date": "2024-02-01T11:00:00Z"},
        }
    }

    assert commit_window_timestamp(commit) == "2024-02-01T10:00:00Z"
    assert commit_window_timestamp(fallback_commit) == "2024-02-01T11:00:00Z"


def test_load_sampled_repositories_deduplicates_full_name(tmp_path) -> None:
    sample_file = tmp_path / "sample.csv"
    with sample_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["full_name", "language_group"])
        writer.writeheader()
        writer.writerow({"full_name": "example/repo", "language_group": "JavaScript"})
        writer.writerow({"full_name": "example/repo", "language_group": "JavaScript"})

    rows = load_sampled_repositories(sample_file)

    assert len(rows) == 1
    assert rows[0]["full_name"] == "example/repo"


def test_load_sampled_repositories_accepts_final_sample_repository_full_name(tmp_path) -> None:
    sample_file = tmp_path / "data" / "interim" / "final_sample" / "final_sample.csv"
    sample_file.parent.mkdir(parents=True)
    with sample_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["repository_full_name", "language_group", "final_sampling_role"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "repository_full_name": "example/final-repo",
                "language_group": "TypeScript",
                "final_sampling_role": "final_sample",
            }
        )

    rows = load_sampled_repositories(sample_file)

    assert len(rows) == 1
    assert extract_repository_full_name(rows[0]) == "example/final-repo"


def test_sample_run_type_inference_for_final_and_custom_paths(tmp_path) -> None:
    final = tmp_path / "data" / "interim" / "final_sample" / "final_sample.csv"
    custom = tmp_path / "sample.csv"

    assert build_sample_provenance(final)["sample_run_type"] == "final_study"
    assert infer_sample_run_type(custom) == "custom"


def test_build_collection_failure_record_includes_retry_metadata() -> None:
    class DummyError(Exception):
        def __init__(self) -> None:
            super().__init__("temporary failure")
            self.status_code = 429
            self.retryable = True
            self.attempts = 4
            self.retry_after_seconds = 2.5

    record = build_collection_failure_record(
        stage="commits",
        repository_full_name="example/repo",
        error=DummyError(),
        retries_attempted=3,
        language_group="JavaScript",
    )

    assert record["stage"] == "commits"
    assert record["repository_full_name"] == "example/repo"
    assert record["status_code"] == 429
    assert record["retryable"] is True
    assert record["retries_attempted"] == 3
    assert record["retry_after_seconds"] == 2.5
