"""Filesystem locations. `WORKAGENT_HOME` overrides the data dir (used by dev mode and tests)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "PersonalWorkAgent"


def data_dir() -> Path:
    override = os.environ.get("WORKAGENT_HOME")
    if override:
        base = Path(override)
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def vault_path() -> Path:
    return data_dir() / "vault.db"


def config_path() -> Path:
    return data_dir() / "config.json"


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(exist_ok=True)
    return path
