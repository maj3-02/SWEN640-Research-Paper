# Bug-Related Outcomes in JavaScript and TypeScript GitHub Repositories

**Read the full research paper:** [`results/Final-Draft.pdf`](results/Final-Draft.pdf)

This repository contains the public code and curated artifacts for a repository-mining study comparing bug-related maintenance outcomes in JavaScript and TypeScript GitHub repositories.

## Repository Contents

- `config/` - study configuration and keyword rules
- `scripts/` - final-study pipeline stages and shared helpers
- `tests/` - focused unit and routing tests for the pipeline
- `data/` - final-study data artifacts, including raw final-sample collection outputs and processed metrics
- `results/final_sample/` - final tables, figures, and reporting summaries
- `docs/` - runbook, reproducibility notes, data dictionary, and AI-assistance disclosure

The repository includes the final-study data artifacts used to support the paper results, including raw final-sample commit and issue payloads, row-level classified commit and issue outputs, final sample manifest, repository metrics, descriptive summaries, and generated figures.

## Key Final-Study Artifacts

- Final sample manifest: `data/interim/final_sample/final_sample.csv`
- Final eligible candidate pool: `data/interim/final_candidate_screen/final_eligible_candidate_pool.csv`
- Collection completeness audit: `data/interim/final_sample/collection_completeness_audit.json`
- Raw final-sample commits: `data/interim/final_sample/raw_commits/`
- Raw final-sample issues: `data/interim/final_sample/raw_issues/`
- Row-level classified commits: `data/interim/final_sample/classified_commits/classified_commits.csv`
- Row-level classified issues: `data/interim/final_sample/classified_issues/classified_issues.csv`
- Repository metrics: `data/processed/repo_metrics/final_sample/repository_metrics.csv`
- Descriptive summary table: `results/final_sample/tables/descriptive_summary_by_language.csv`
- Reporting summary: `results/final_sample/reporting_summary.json`
- Figures: `results/final_sample/figures/`

## Setup

Create a Python environment and install the dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set a GitHub token before running GitHub-facing stages:

```powershell
$env:GITHUB_TOKEN = "your-token-here"
```

## Final-Study Pipeline

The active final-study workflow is:

```powershell
python scripts/collect/discover_candidates.py
python scripts/filter/filter_candidates.py
python scripts/filter/screen_final_candidates.py
python scripts/collect/enrich_final_candidates.py --resume
python scripts/filter/screen_final_eligibility.py
python scripts/sample/draw_final_sample.py
python scripts/collect/fetch_commits.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/collect/fetch_issues.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/collect/audit_final_collection.py
python scripts/classify/classify_commits.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/classify/classify_issues.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/aggregate/compute_repo_metrics.py --sample-file data/interim/final_sample/final_sample.csv
python scripts/analyze/generate_descriptive_outputs.py --repo-metrics data/processed/repo_metrics/final_sample/repository_metrics.csv
```

The downstream final-study stages use `data/interim/final_sample/final_sample.csv` as the locked sample manifest.

## Tests

Run the focused test suite with:

```powershell
python -m pytest
```

Some end-to-end stages require live GitHub API access and can be affected by rate limits. The generated final-study artifacts included in this repository allow the main paper numbers to be inspected without rerunning the full collection workflow.

## Notes on AI Assistance

AI assistance was used during pipeline development and planning. The author reviewed, tested, curated, and is responsible for the code, data artifacts, and paper claims. See `docs/ai-assistance-disclosure.md` for details.
