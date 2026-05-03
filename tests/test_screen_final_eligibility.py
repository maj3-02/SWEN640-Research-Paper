from __future__ import annotations

import csv
import json

from scripts.filter.screen_final_eligibility import main, screen_enriched_candidate_rows
from scripts.utils.pre_sampling_eligibility import REASON_COMMIT_THRESHOLD_FAILED, REASON_LANGUAGE_THRESHOLD_FAILED


def write_csv(path, rows, fieldnames) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def make_enriched_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "repository_full_name": "owner/eligible",
        "full_name": "owner/eligible",
        "language_group": "JavaScript",
        "target_language_share": 0.8,
        "default_branch_commit_count_in_window": 60,
        "closed_issue_count_in_window": 7,
        "quality_screen_pass": True,
        "enrichment_status": "enriched",
        "enrichment_input_file": "data/interim/quality_screened_candidates/javascript_candidates_filtered.csv",
        "enrichment_input_record_index": 1,
    }
    row.update(overrides)
    return row


def test_screen_enriched_candidate_rows_uses_pre_sampling_helper_logic() -> None:
    rows = [
        make_enriched_row(),
        make_enriched_row(
            repository_full_name="owner/low-commits",
            full_name="owner/low-commits",
            default_branch_commit_count_in_window=12,
        ),
    ]

    eligibility_rows, eligible_pool_rows, exclusion_rows, summary = screen_enriched_candidate_rows(
        rows,
        config={
            "language_threshold": 0.70,
            "min_commits_in_window": 50,
            "min_closed_issues_in_window": 5,
        },
    )

    assert len(eligibility_rows) == 2
    assert [row["repository_full_name"] for row in eligible_pool_rows] == ["owner/eligible"]
    assert exclusion_rows == [
        {
            "repository_full_name": "owner/low-commits",
            "language_group": "JavaScript",
            "exclusion_reason": REASON_COMMIT_THRESHOLD_FAILED,
            "pre_sampling_exclusion_reasons": REASON_COMMIT_THRESHOLD_FAILED,
            "source_file": "data/interim/quality_screened_candidates/javascript_candidates_filtered.csv",
            "source_record_index": 1,
        }
    ]
    assert summary["rows_seen"] == 2
    assert summary["pre_sampling_eligible_count"] == 1


def test_main_writes_screen_outputs_from_synthetic_enriched_rows(tmp_path, monkeypatch) -> None:
    input_dir = tmp_path / "data" / "interim" / "enriched_candidates"
    output_dir = tmp_path / "data" / "interim" / "final_candidate_screen"
    config_path = tmp_path / "study_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "language_threshold: 0.70",
                "min_commits_in_window: 50",
                "min_closed_issues_in_window: 5",
                "languages:",
                "  - JavaScript",
                "  - TypeScript",
                "final_candidate_screen:",
                f"  input_dir: \"{input_dir.as_posix()}\"",
                f"  output_dir: \"{output_dir.as_posix()}\"",
            ]
        ),
        encoding="utf-8",
    )
    rows = [
        make_enriched_row(),
        make_enriched_row(
            repository_full_name="owner/lang-fail",
            full_name="owner/lang-fail",
            language_group="TypeScript",
            target_language_share=0.5,
            default_branch_commit_count_in_window=80,
            closed_issue_count_in_window=9,
            quality_screen_pass=True,
            enrichment_input_record_index=2,
        ),
        make_enriched_row(
            repository_full_name="owner/multi-fail",
            full_name="owner/multi-fail",
            language_group="TypeScript",
            target_language_share=0.9,
            default_branch_commit_count_in_window=20,
            closed_issue_count_in_window=2,
            quality_screen_pass=False,
            enrichment_input_record_index=3,
        ),
    ]
    fieldnames = list(rows[0].keys())
    write_csv(input_dir / "candidate_enrichment_results.csv", rows, fieldnames)

    monkeypatch.setattr(
        "sys.argv",
        [
            "screen_final_eligibility.py",
            "--config",
            str(config_path),
        ],
    )

    main()

    eligibility_rows = read_csv(output_dir / "candidate_pre_sampling_eligibility.csv")
    eligible_pool_rows = read_csv(output_dir / "final_eligible_candidate_pool.csv")
    exclusion_rows = read_csv(output_dir / "candidate_pre_sampling_exclusion_log.csv")
    summary = json.loads(
        (output_dir / "candidate_pre_sampling_eligibility_summary.json").read_text(encoding="utf-8")
    )

    assert len(eligibility_rows) == 3
    assert [row["repository_full_name"] for row in eligible_pool_rows] == ["owner/eligible"]
    assert {
        (row["repository_full_name"], row["exclusion_reason"])
        for row in exclusion_rows
    } == {
        ("owner/lang-fail", REASON_LANGUAGE_THRESHOLD_FAILED),
        ("owner/multi-fail", REASON_COMMIT_THRESHOLD_FAILED),
        ("owner/multi-fail", "closed_issue_threshold_failed"),
        ("owner/multi-fail", "quality_screen_failed"),
    }
    assert summary["rows_seen"] == 3
    assert summary["language_threshold_pass_count"] == 2
    assert summary["commit_threshold_pass_count"] == 2
    assert summary["closed_issue_threshold_pass_count"] == 2
    assert summary["quality_screen_pass_count"] == 2
    assert summary["pre_sampling_eligible_count"] == 1
    assert summary["pre_sampling_eligible_by_language"] == {"JavaScript": 1}
    assert summary["input_files"] == [str(input_dir / "candidate_enrichment_results.csv")]
    assert summary["output_files"]["eligible_pool_csv"] == str(output_dir / "final_eligible_candidate_pool.csv")
