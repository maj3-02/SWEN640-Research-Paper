from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from scripts.utils.config import load_study_config
from scripts.utils.github_api import GitHubAPIError, create_github_session, fetch_repository_search_page
from scripts.utils.logging_utils import configure_logging
from scripts.utils.paths import candidate_raw_dir
from scripts.utils.query_builder import build_candidate_search_query

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover candidate GitHub repositories for the study.")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to the study configuration YAML file. Defaults to config/study_config.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional override for the raw candidate output directory.",
    )
    return parser.parse_args()


def ensure_output_dir(path: str | Path | None = None) -> Path:
    output_dir = Path(path) if path is not None else candidate_raw_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def deduplicate_repositories(repositories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: OrderedDict[int | str, dict[str, Any]] = OrderedDict()
    for repository in repositories:
        key = repository.get("id") or repository.get("full_name")
        if key is None:
            continue
        if key not in ordered:
            ordered[key] = repository
    return list(ordered.values())


def flatten_repository(repository: dict[str, Any]) -> dict[str, Any]:
    owner = repository.get("owner") or {}
    license_info = repository.get("license") or {}
    return {
        "id": repository.get("id"),
        "node_id": repository.get("node_id"),
        "name": repository.get("name"),
        "full_name": repository.get("full_name"),
        "html_url": repository.get("html_url"),
        "description": repository.get("description"),
        "language": repository.get("language"),
        "stargazers_count": repository.get("stargazers_count"),
        "watchers_count": repository.get("watchers_count"),
        "forks_count": repository.get("forks_count"),
        "open_issues_count": repository.get("open_issues_count"),
        "archived": repository.get("archived"),
        "fork": repository.get("fork"),
        "created_at": repository.get("created_at"),
        "updated_at": repository.get("updated_at"),
        "pushed_at": repository.get("pushed_at"),
        "default_branch": repository.get("default_branch"),
        "owner_login": owner.get("login"),
        "owner_type": owner.get("type"),
        "license_spdx_id": license_info.get("spdx_id"),
    }


def write_json_output(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_csv_output(path: Path, repositories: list[dict[str, Any]]) -> None:
    rows = [flatten_repository(repository) for repository in repositories]
    fieldnames = list(rows[0].keys()) if rows else list(flatten_repository({}).keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def discover_language_candidates(
    *,
    language: str,
    session,
    per_page: int,
    target_pages: int,
    sort: str,
    order: str,
) -> dict[str, Any]:
    query = build_candidate_search_query(language)
    LOGGER.info('Discovering %s candidates with query "%s"', language, query)

    pages: list[dict[str, Any]] = []
    all_repositories: list[dict[str, Any]] = []

    for page in range(1, target_pages + 1):
        LOGGER.info("Requesting %s candidate page %s", language, page)
        payload = fetch_repository_search_page(
            session,
            query=query,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
        )

        items = payload.get("items") or []
        if not isinstance(items, list):
            raise GitHubAPIError(f"GitHub repository search returned unexpected items payload for {language} page {page}")

        LOGGER.info("Retrieved %s repositories for %s page %s", len(items), language, page)
        pages.append(
            {
                "page": page,
                "total_count": payload.get("total_count"),
                "incomplete_results": payload.get("incomplete_results"),
                "items": items,
            }
        )
        all_repositories.extend(items)

        if not items:
            LOGGER.warning("Stopping %s discovery early because page %s returned no repositories", language, page)
            break

    repositories = deduplicate_repositories(all_repositories)
    return {
        "language": language,
        "query": query,
        "sort": sort,
        "order": order,
        "per_page": per_page,
        "target_pages": target_pages,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
        "repositories": repositories,
    }


def save_language_outputs(language: str, discovery_result: dict[str, Any], output_dir: Path) -> None:
    slug = language.strip().lower().replace(" ", "_")
    json_path = output_dir / f"{slug}_candidates_raw.json"
    csv_path = output_dir / f"{slug}_candidates_raw.csv"
    json_payload = {
        "language": discovery_result["language"],
        "query": discovery_result["query"],
        "sort": discovery_result["sort"],
        "order": discovery_result["order"],
        "per_page": discovery_result["per_page"],
        "target_pages": discovery_result["target_pages"],
        "fetched_at": discovery_result["fetched_at"],
        "pages": discovery_result["pages"],
        "repositories": discovery_result["repositories"],
    }
    write_json_output(json_path, json_payload)
    write_csv_output(csv_path, discovery_result["repositories"])
    LOGGER.info("Saved %s JSON output to %s", language, json_path)
    LOGGER.info("Saved %s CSV output to %s", language, csv_path)


def main() -> None:
    args = parse_args()
    configure_logging()

    config = load_study_config(args.config)
    discovery_config = config.get("candidate_discovery", {})
    per_page = int(discovery_config.get("per_page", 100))
    target_pages = int(discovery_config.get("per_language_target_pages", 5))
    sort = str(discovery_config.get("sort", "stars"))
    order = str(discovery_config.get("order", "desc"))

    output_dir = ensure_output_dir(args.output_dir)
    LOGGER.info("Using raw candidate output directory: %s", output_dir)

    session = create_github_session()
    if "Authorization" not in session.headers:
        LOGGER.warning("GITHUB_TOKEN is not set; proceeding with unauthenticated GitHub API requests.")

    for language in config.get("languages", ["JavaScript", "TypeScript"]):
        discovery_result = discover_language_candidates(
            language=language,
            session=session,
            per_page=per_page,
            target_pages=target_pages,
            sort=sort,
            order=order,
        )
        save_language_outputs(language, discovery_result, output_dir)


if __name__ == "__main__":
    try:
        main()
    except GitHubAPIError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc
