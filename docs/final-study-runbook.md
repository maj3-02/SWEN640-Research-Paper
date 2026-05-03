# Final-Study Runbook

This runbook documents the active final-study workflow used for the public repository-mining study. Commands are intended to be run from the repository root.

## 1. Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GITHUB_TOKEN = "your-token-here"
```

A GitHub token is required for discovery, enrichment, and raw commit/issue collection. GitHub API rate limits may require rerunning long stages after quota reset. The enrichment stage supports `--resume` so completed rows are not duplicated.

## 2. Candidate Discovery

```powershell
python scripts/collect/discover_candidates.py
```

Primary outputs:

- `data/raw/candidate_repos/javascript_candidates_raw.csv`
- `data/raw/candidate_repos/typescript_candidates_raw.csv`

## 3. Basic Filtering

```powershell
python scripts/filter/filter_candidates.py
```

Primary outputs:

- `data/interim/filtered_candidates/javascript_candidates_filtered.csv`
- `data/interim/filtered_candidates/typescript_candidates_filtered.csv`
- `data/interim/filtered_candidates/candidate_exclusion_log.csv`

## 4. Quality and Maturity Screen

```powershell
python scripts/filter/screen_final_candidates.py
```

Primary outputs:

- `data/interim/quality_screened_candidates/candidate_quality_screen_results.csv`
- `data/interim/quality_screened_candidates/candidate_quality_screen_summary.json`

## 5. Candidate Enrichment

```powershell
python scripts/collect/enrich_final_candidates.py --resume
```

Primary outputs:

- `data/interim/enriched_candidates/candidate_enrichment_results.csv`
- `data/interim/enriched_candidates/candidate_enrichment_summary.json`

This stage collects language share, default-branch commit count in the study window, and exact closed issue count in the study window.

## 6. Pre-Sampling Eligibility

```powershell
python scripts/filter/screen_final_eligibility.py
```

Primary outputs:

- `data/interim/final_candidate_screen/candidate_pre_sampling_eligibility.csv`
- `data/interim/final_candidate_screen/candidate_pre_sampling_exclusion_log.csv`
- `data/interim/final_candidate_screen/final_eligible_candidate_pool.csv`
- `data/interim/final_candidate_screen/candidate_pre_sampling_eligibility_summary.json`

## 7. Final Sample Drawing

```powershell
python scripts/sample/draw_final_sample.py
```

Primary outputs:

- `data/interim/final_sample/final_sample.csv`
- `data/interim/final_sample/final_reserves.csv`
- `data/interim/final_sample/final_sample_metadata.json`
- `data/interim/final_sample/pool_sufficiency_report.json`

## 8. Raw Collection

```powershell
python scripts/collect/fetch_commits.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/collect/fetch_issues.py --sample-file data/interim/final_sample/final_sample.csv
```

Primary outputs include raw commit and issue files plus collection summaries under `data/interim/final_sample/raw_commits/` and `data/interim/final_sample/raw_issues/`.

Large raw payloads are excluded from the public repository. The collection summary and failure files are retained.

## 9. Collection Completeness Audit

```powershell
python scripts/collect/audit_final_collection.py
```

Primary outputs:

- `data/interim/final_sample/collection_completeness_audit.csv`
- `data/interim/final_sample/collection_completeness_audit.json`

This audit is operational only. It does not act as an eligibility gate.

## 10. Classification

```powershell
python scripts/classify/classify_commits.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/classify/classify_issues.py --sample-file data/interim/final_sample/final_sample.csv
```

Primary summary outputs:

- `data/interim/final_sample/classified_commits/classified_commits_summary.json`
- `data/interim/final_sample/classified_issues/classified_issues_summary.json`

Large classified row-level CSVs are excluded from the public repository. They can be regenerated from raw collection outputs.

## 11. Aggregation

```powershell
python scripts/aggregate/compute_repo_metrics.py --sample-file data/interim/final_sample/final_sample.csv
```

Primary outputs:

- `data/processed/repo_metrics/final_sample/repository_metrics.csv`
- `data/processed/repo_metrics/final_sample/repository_metrics_summary.json`

## 12. Descriptive Reporting

```powershell
python scripts/analyze/generate_descriptive_outputs.py --repo-metrics data/processed/repo_metrics/final_sample/repository_metrics.csv
```

Primary outputs:

- `results/final_sample/tables/descriptive_summary_by_language.csv`
- `results/final_sample/tables/descriptive_summary_by_language.md`
- `results/final_sample/figures/bug_fix_commit_ratio_by_language.png`
- `results/final_sample/figures/median_bug_issue_resolution_time_days_by_language.png`
- `results/final_sample/reporting_summary.json`
