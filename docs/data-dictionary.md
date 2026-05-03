# Data Dictionary

This document summarizes the main public artifacts used to verify the final-study results.

## Final Sample

`data/interim/final_sample/final_sample.csv`

Important fields:

- `repository_full_name`: GitHub owner/repository name.
- `language_group`: JavaScript or TypeScript.
- `target_language_share`: target-language byte share from GitHub language statistics.
- `default_branch_commit_count_in_window`: default-branch commit count during the study window.
- `closed_issue_count_in_window`: closed issue count during the study window.
- `pre_sampling_eligible`: whether the repository passed the pre-sampling eligibility screen.
- `activity_stratum`: high, medium, or low activity stratum used for balanced sampling.
- `final_sampling_role`: final sample or reserve role.

## Repository Metrics

`data/processed/repo_metrics/final_sample/repository_metrics.csv`

Important fields:

- `repository_full_name`: GitHub owner/repository name.
- `language_group`: JavaScript or TypeScript.
- `eligible_for_rq1`: whether the repository contributes to RQ1.
- `eligible_for_rq2`: whether the repository contributes to RQ2.
- `total_commits_in_window`: total collected commits in the study window.
- `bug_fix_commit_count`: commits classified as bug-fix commits.
- `bug_fix_commit_ratio`: `bug_fix_commit_count / total_commits_in_window`.
- `total_closed_issues_in_window_considered`: total closed issues considered for RQ2.
- `bug_related_issue_count`: issues classified as bug-related.
- `bug_related_issue_duration_count`: bug-related issues with valid resolution durations.
- `median_bug_issue_resolution_time_days`: repository-level median bug-related issue resolution time.

## Descriptive Summary

`results/final_sample/tables/descriptive_summary_by_language.csv`

Important fields:

- `rq_section`: RQ1 or RQ2.
- `language_group`: JavaScript or TypeScript.
- `metric_name`: summarized metric.
- `count`: number of contributing repositories.
- `mean`, `median`, `min`, `max`, `stddev`, `iqr`: descriptive statistics for the metric.

## Summary JSON Files

Summary JSON files record input paths, counts, outputs, and provenance for major stages. These files are useful for tracing the final numbers back through sampling, collection, classification, aggregation, and reporting.
