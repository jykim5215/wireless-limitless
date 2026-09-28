"""Filesystem locations for both source checkouts and PyInstaller builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "WirelessLimitless"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """Folder that holds the bundled `ui/` directory and `version.json`."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def install_dir() -> Path | None:
    """Folder containing WirelessLimitless.exe (None when running from source)."""
    return Path(sys.executable).resolve().parent if is_frozen() else None


def ui_index() -> Path:
    return resource_root() / "ui" / "index.html"


def version_file() -> Path:
    if is_frozen():
        return resource_root() / "version.json"
    return Path(__file__).resolve().parents[2] / "version.json"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
