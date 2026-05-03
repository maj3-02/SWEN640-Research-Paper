from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at top level in {config_path}")
    return data


def load_study_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else repo_root() / "config" / "study_config.yaml"
    return load_yaml_file(config_path)
