from __future__ import annotations

import logging.config
from pathlib import Path

from scripts.utils.config import load_yaml_file, repo_root


def configure_logging(path: str | Path | None = None) -> None:
    logging_path = Path(path) if path is not None else repo_root() / "config" / "logging.yaml"
    config = load_yaml_file(logging_path)
    logging.config.dictConfig(config)
