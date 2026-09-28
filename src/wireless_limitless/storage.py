"""Small JSON settings store in %APPDATA%\\WirelessLimitless\\settings.json."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "lastDevice": None,  # {"address": str, "vendorId": int}
    "checkUpdatesOnStart": True,
    "customEqPresets": [],  # [{"name": str, "gains": [10 x number]}]
}

MAX_CUSTOM_PRESETS = 20


class Storage:
    def __init__(self, path: Path | None = None):
        self._path = path or paths.data_dir() / "settings.json"
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            log.warning("settings unreadable, using defaults: %s", exc)
            return
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    self._data[key] = raw[key]

    def get(self, key: str) -> Any:
        with self._lock:
            value = self._data.get(key, DEFAULTS.get(key))
            return json.loads(json.dumps(value))  # detached copy

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        with self._lock:
            self._data[key] = value
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._path)
