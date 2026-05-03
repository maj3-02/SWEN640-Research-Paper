from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTIVITY_STRATA = ("high", "medium", "low")


def read_csv_rows(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_iso_datetime(value: str) -> datetime:
    if not value:
        raise ValueError("Activity field is empty; cannot stratify without a proxy value.")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Unable to parse ISO timestamp value: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_numeric_activity_value(value: Any) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError(f"Activity value must be a non-negative integer, got {value!r}.")
    text = str(value).strip()
    if not text:
        raise ValueError("Activity value is empty; cannot stratify without a numeric value.")
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"Unable to parse numeric activity value: {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"Activity value must be non-negative, got {value!r}.")
    return parsed


def bucket_sizes(total: int, bucket_count: int) -> list[int]:
    base, remainder = divmod(total, bucket_count)
    return [base + (1 if index < remainder else 0) for index in range(bucket_count)]


def sort_rows_by_activity(rows: list[dict[str, Any]], activity_field: str) -> list[dict[str, Any]]:
    for row in rows:
        if activity_field not in row or not str(row[activity_field]).strip():
            raise ValueError(
                f"Missing required activity field {activity_field!r} in candidate row {row.get('full_name')!r}."
            )
    return sorted(
        rows,
        key=lambda row: (
            parse_iso_datetime(str(row[activity_field])),
            str(row.get("full_name") or row.get("name") or ""),
        ),
        reverse=True,
    )


def sort_rows_by_numeric_activity(rows: list[dict[str, Any]], activity_field: str) -> list[dict[str, Any]]:
    for row in rows:
        if activity_field not in row:
            raise ValueError(
                f"Missing required activity field {activity_field!r} in candidate row {row.get('repository_full_name') or row.get('full_name')!r}."
            )
        parse_numeric_activity_value(row[activity_field])
    return sorted(
        rows,
        key=lambda row: (
            -parse_numeric_activity_value(row[activity_field]),
            str(row.get("repository_full_name") or row.get("full_name") or row.get("name") or ""),
        ),
    )


def assign_activity_strata(
    rows: list[dict[str, Any]],
    *,
    activity_field: str,
    activity_field_is_proxy: bool,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        language_group = str(row.get("language_group") or "").strip()
        if not language_group:
            raise ValueError("Missing language_group in filtered candidate row.")
        grouped[language_group].append(dict(row))

    stratified_rows: list[dict[str, Any]] = []
    for language_group in grouped:
        sorted_rows = sort_rows_by_activity(grouped[language_group], activity_field)
        sizes = bucket_sizes(len(sorted_rows), len(ACTIVITY_STRATA))
        start = 0
        for stratum_rank, (stratum_name, size) in enumerate(zip(ACTIVITY_STRATA, sizes), start=1):
            for within_stratum_rank, row in enumerate(sorted_rows[start : start + size], start=1):
                enriched = dict(row)
                enriched["activity_field_used"] = activity_field
                enriched["activity_field_is_proxy"] = activity_field_is_proxy
                enriched["activity_value"] = row[activity_field]
                enriched["activity_stratum"] = stratum_name
                enriched["activity_stratum_rank"] = stratum_rank
                enriched["activity_rank_within_stratum"] = within_stratum_rank
                stratified_rows.append(enriched)
            start += size

    stratified_rows.sort(
        key=lambda row: (
            str(row.get("language_group") or ""),
            row.get("activity_stratum_rank") or 0,
            parse_iso_datetime(str(row.get("activity_value") or "")),
            str(row.get("full_name") or row.get("name") or ""),
        ),
        reverse=False,
    )
    return stratified_rows


def assign_numeric_activity_strata(
    rows: list[dict[str, Any]],
    *,
    activity_field: str,
    activity_field_is_proxy: bool,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        language_group = str(row.get("language_group") or "").strip()
        if not language_group:
            raise ValueError("Missing language_group in enriched candidate row.")
        grouped[language_group].append(dict(row))

    stratified_rows: list[dict[str, Any]] = []
    for language_group in grouped:
        sorted_rows = sort_rows_by_numeric_activity(grouped[language_group], activity_field)
        sizes = bucket_sizes(len(sorted_rows), len(ACTIVITY_STRATA))
        start = 0
        for stratum_rank, (stratum_name, size) in enumerate(zip(ACTIVITY_STRATA, sizes), start=1):
            for within_stratum_rank, row in enumerate(sorted_rows[start : start + size], start=1):
                enriched = dict(row)
                activity_value = parse_numeric_activity_value(row[activity_field])
                enriched["activity_field_used"] = activity_field
                enriched["activity_field_is_proxy"] = activity_field_is_proxy
                enriched["activity_value"] = activity_value
                enriched["activity_stratum"] = stratum_name
                enriched["activity_stratum_rank"] = stratum_rank
                enriched["activity_rank_within_stratum"] = within_stratum_rank
                stratified_rows.append(enriched)
            start += size

    return sort_rows_for_numeric_activity_output(stratified_rows)


def sort_rows_for_numeric_activity_output(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("language_group") or ""),
            int(row.get("activity_stratum_rank") or 0),
            -parse_numeric_activity_value(row.get("activity_value")),
            str(row.get("repository_full_name") or row.get("full_name") or row.get("name") or ""),
        ),
    )


def counts_by_language_and_stratum(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        counts[str(row.get("language_group") or "")][str(row.get("activity_stratum") or "")] += 1
    return {language: dict(counter) for language, counter in counts.items()}


def allocate_targets(
    available_counts: dict[str, int],
    total_target: int,
    strata_order: tuple[str, ...] = ACTIVITY_STRATA,
) -> dict[str, int]:
    if total_target > sum(available_counts.values()):
        raise ValueError(
            f"Cannot draw {total_target} rows from only {sum(available_counts.values())} available candidates."
        )

    targets = {stratum: min(total_target // len(strata_order), available_counts.get(stratum, 0)) for stratum in strata_order}
    remaining = total_target - sum(targets.values())

    order_index = {stratum: index for index, stratum in enumerate(strata_order)}
    while remaining > 0:
        candidates = [stratum for stratum in strata_order if targets[stratum] < available_counts.get(stratum, 0)]
        if not candidates:
            raise ValueError("Unable to allocate sample targets across strata because one or more strata are empty.")
        candidates.sort(
            key=lambda stratum: (
                available_counts.get(stratum, 0) - targets[stratum],
                available_counts.get(stratum, 0),
                -order_index[stratum],
            ),
            reverse=True,
        )
        chosen = candidates[0]
        targets[chosen] += 1
        remaining -= 1

    return targets


def draw_stratified_sample(
    rows: list[dict[str, Any]],
    *,
    sample_per_language: int,
    random_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("language_group") or "")].append(dict(row))

    language_order = sorted(grouped.keys())
    selected_rows: list[dict[str, Any]] = []
    selected_counts_by_language: dict[str, int] = {}
    selected_counts_by_stratum: Counter[str] = Counter()
    selected_counts_by_language_and_stratum: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in ACTIVITY_STRATA})
    targets_by_language: dict[str, dict[str, int]] = {}
    rng_by_language = {
        language: random.Random(random_seed + index)
        for index, language in enumerate(language_order)
    }

    for language in language_order:
        language_rows = grouped[language]
        if len(language_rows) < sample_per_language:
            raise ValueError(
                f"Not enough candidates for {language} to draw {sample_per_language} repos; only {len(language_rows)} available."
            )

        by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in language_rows:
            stratum = str(row.get("activity_stratum") or "")
            if stratum not in ACTIVITY_STRATA:
                raise ValueError(f"Unexpected activity stratum {stratum!r} for {language}.")
            by_stratum[stratum].append(row)

        available_counts = {stratum: len(by_stratum.get(stratum, [])) for stratum in ACTIVITY_STRATA}
        targets = allocate_targets(available_counts, sample_per_language)
        targets_by_language[language] = targets

        for stratum in ACTIVITY_STRATA:
            stratum_rows = sorted(
                by_stratum.get(stratum, []),
                key=lambda row: (
                    parse_iso_datetime(str(row.get("activity_value") or "")),
                    str(row.get("full_name") or row.get("name") or ""),
                ),
                reverse=True,
            )
            selected = rng_by_language[language].sample(stratum_rows, targets[stratum]) if targets[stratum] else []
            selected_rows.extend(selected)
            selected_counts_by_stratum[stratum] += len(selected)
            selected_counts_by_language_and_stratum[language][stratum] += len(selected)

        selected_counts_by_language[language] = sum(targets.values())

    selected_rows.sort(
        key=lambda row: (
            str(row.get("language_group") or ""),
            row.get("activity_stratum_rank") or 0,
            parse_iso_datetime(str(row.get("activity_value") or "")),
            str(row.get("full_name") or row.get("name") or ""),
        )
    )

    metadata = {
        "random_seed": random_seed,
        "selected_counts_by_language": selected_counts_by_language,
        "selected_counts_by_stratum": dict(selected_counts_by_stratum),
        "selected_counts_by_language_and_stratum": {
            language: counts for language, counts in selected_counts_by_language_and_stratum.items()
        },
        "targets_by_language": targets_by_language,
    }
    return selected_rows, metadata


def _repository_key(row: dict[str, Any]) -> str:
    return str(row.get("repository_full_name") or row.get("full_name") or "").strip()


def draw_stratified_sample_numeric_activity(
    rows: list[dict[str, Any]],
    *,
    sample_per_language: int,
    random_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("language_group") or "")].append(dict(row))

    language_order = sorted(grouped.keys())
    selected_rows: list[dict[str, Any]] = []
    selected_counts_by_language: dict[str, int] = {}
    selected_counts_by_stratum: Counter[str] = Counter()
    selected_counts_by_language_and_stratum: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in ACTIVITY_STRATA})
    targets_by_language: dict[str, dict[str, int]] = {}
    rng_by_language = {
        language: random.Random(random_seed + index)
        for index, language in enumerate(language_order)
    }

    for language in language_order:
        language_rows = grouped[language]
        if len(language_rows) < sample_per_language:
            raise ValueError(
                f"Not enough candidates for {language} to draw {sample_per_language} repos; only {len(language_rows)} available."
            )

        by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in language_rows:
            stratum = str(row.get("activity_stratum") or "")
            if stratum not in ACTIVITY_STRATA:
                raise ValueError(f"Unexpected activity stratum {stratum!r} for {language}.")
            by_stratum[stratum].append(row)

        available_counts = {stratum: len(by_stratum.get(stratum, [])) for stratum in ACTIVITY_STRATA}
        targets = allocate_targets(available_counts, sample_per_language)
        targets_by_language[language] = targets

        for stratum in ACTIVITY_STRATA:
            stratum_rows = sort_rows_for_numeric_activity_output(by_stratum.get(stratum, []))
            selected = rng_by_language[language].sample(stratum_rows, targets[stratum]) if targets[stratum] else []
            selected_rows.extend(selected)
            selected_counts_by_stratum[stratum] += len(selected)
            selected_counts_by_language_and_stratum[language][stratum] += len(selected)

        selected_counts_by_language[language] = sum(targets.values())

    selected_rows = sort_rows_for_numeric_activity_output(selected_rows)
    metadata = {
        "random_seed": random_seed,
        "selected_counts_by_language": selected_counts_by_language,
        "selected_counts_by_stratum": dict(selected_counts_by_stratum),
        "selected_counts_by_language_and_stratum": {
            language: counts for language, counts in selected_counts_by_language_and_stratum.items()
        },
        "targets_by_language": targets_by_language,
    }
    return selected_rows, metadata


def draw_reserves_by_language_stratum(
    rows: list[dict[str, Any]],
    *,
    selected_rows: list[dict[str, Any]],
    reserve_per_language_stratum: int,
    random_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_keys = {_repository_key(row) for row in selected_rows}
    remaining_rows = [dict(row) for row in rows if _repository_key(row) not in selected_keys]

    languages = sorted({str(row.get("language_group") or "") for row in rows})
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in remaining_rows:
        language = str(row.get("language_group") or "")
        stratum = str(row.get("activity_stratum") or "")
        if stratum not in ACTIVITY_STRATA:
            raise ValueError(f"Unexpected activity stratum {stratum!r} for reserve candidate {row.get('repository_full_name')!r}.")
        grouped[(language, stratum)].append(row)

    reserve_rows: list[dict[str, Any]] = []
    reserve_counts_by_language_and_stratum: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in ACTIVITY_STRATA})
    reserve_shortfalls_by_language_and_stratum: dict[str, dict[str, int]] = defaultdict(lambda: {s: 0 for s in ACTIVITY_STRATA})

    cell_order = [(language, stratum) for language in languages for stratum in ACTIVITY_STRATA]
    for cell_index, (language, stratum) in enumerate(cell_order):
        candidates = sort_rows_for_numeric_activity_output(grouped[(language, stratum)])
        draw_count = min(reserve_per_language_stratum, len(candidates))
        rng = random.Random(random_seed + 10_000 + cell_index)
        selected = rng.sample(candidates, draw_count) if draw_count else []
        selected = sort_rows_for_numeric_activity_output(selected)
        for reserve_rank, row in enumerate(selected, start=1):
            reserve = dict(row)
            reserve["reserve_rank_within_language_stratum"] = reserve_rank
            reserve_rows.append(reserve)

        reserve_counts_by_language_and_stratum[language][stratum] = draw_count
        reserve_shortfalls_by_language_and_stratum[language][stratum] = max(0, reserve_per_language_stratum - draw_count)

    reserve_rows = sort_rows_for_numeric_activity_output(reserve_rows)
    metadata = {
        "reserve_per_language_stratum": reserve_per_language_stratum,
        "reserve_counts_by_language_and_stratum": {
            language: counts for language, counts in reserve_counts_by_language_and_stratum.items()
        },
        "reserve_shortfalls_by_language_and_stratum": {
            language: counts for language, counts in reserve_shortfalls_by_language_and_stratum.items()
        },
        "reserve_repository_count": len(reserve_rows),
    }
    return reserve_rows, metadata


def build_sampling_metadata(
    *,
    input_files: list[str],
    activity_field_used: str,
    activity_field_is_proxy: bool,
    activity_field_note: str,
    sample_per_language: int,
    random_seed: int,
    stratified_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    selection_metadata: dict[str, Any],
) -> dict[str, Any]:
    total_candidates_by_language = Counter(row["language_group"] for row in stratified_rows)
    candidates_by_language_and_stratum = counts_by_language_and_stratum(stratified_rows)

    return {
        "sampling_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "input_files": input_files,
        "activity_field_used": activity_field_used,
        "activity_field_is_proxy": activity_field_is_proxy,
        "activity_field_note": activity_field_note,
        "stratification_method": "terciles within each language group",
        "random_seed": random_seed,
        "sample_per_language": sample_per_language,
        "language_balance_rule": "exact",
        "strata_balance_rule": "as balanced as possible",
        "activity_strata_count": len(ACTIVITY_STRATA),
        "total_candidates_by_language": dict(total_candidates_by_language),
        "candidates_by_language_and_stratum": candidates_by_language_and_stratum,
        "selected_counts_by_language": selection_metadata["selected_counts_by_language"],
        "selected_counts_by_stratum": selection_metadata["selected_counts_by_stratum"],
        "selected_counts_by_language_and_stratum": selection_metadata["selected_counts_by_language_and_stratum"],
        "sampled_repository_count": len(selected_rows),
        "selected_full_names": [row.get("full_name") for row in selected_rows],
    }


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    csv_path = Path(path)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    json_path = Path(path)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
