"""The object exposed to JavaScript as `window.pywebview.api`.

pywebview publishes every public method (and walks public attributes), so all
internals live in underscore attributes. Each call runs on a pywebview worker
thread; device work is forwarded to the BLE loop and awaited with a timeout.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
from collections.abc import Coroutine
from typing import Any

from . import updater
from .controller import MESSAGES, CommandError, DeviceController
from .runner import LoopThread
from .storage import Storage
from .transport import TransportError

log = logging.getLogger(__name__)

CALL_TIMEOUT_S = 25.0


class StatePusher:
    """Coalesces controller snapshots and pushes the newest one to the page."""

    def __init__(self) -> None:
        self._window = None
        self._latest: dict | None = None
        self._lock = threading.Lock()
        self._dirty = threading.Event()
        self._ready = threading.Event()
        threading.Thread(target=self._run, name="ui-push", daemon=True).start()

    def attach(self, window) -> None:
        self._window = window

    def mark_ready(self) -> None:
        self._ready.set()
        self._dirty.set()

    def push_state(self, state: dict) -> None:
        with self._lock:
            self._latest = state
        self._dirty.set()

    def run_js(self, script: str) -> None:
        if self._window is not None and self._ready.is_set():
            try:
                self._window.run_js(script)
            except Exception:  # noqa: BLE001 — window may be closing
                log.debug("run_js failed", exc_info=True)

    def _run(self) -> None:
        while True:
            self._dirty.wait()
            self._ready.wait()
            self._dirty.clear()
            threading.Event().wait(0.03)  # let bursts of updates coalesce
            with self._lock:
                state = self._latest
            if state is not None:
                self.run_js(f"window.WL&&window.WL.onState({json.dumps(state)})")


class Bridge:
    def __init__(self, loop: LoopThread, controller: DeviceController, storage: Storage,
                 pusher: StatePusher, version: str):
        self._loop = loop
        self._ctrl = controller
        self._storage = storage
        self._pusher = pusher
        self._version = version
        self._window = None
        self._update: updater.UpdateInfo | None = None
        self._updating = threading.Lock()

    def _attach_window(self, window) -> None:
        self._window = window

    # ------------------------------------------------------------ helpers

    def _run(self, coro: Coroutine[Any, Any, Any], timeout: float = CALL_TIMEOUT_S) -> dict:
        try:
            self._loop.call(coro, timeout)
            return {"ok": True}
        except CommandError as exc:
            return {"ok": False, "error": str(exc)}
        except TransportError as exc:
            return {"ok": False, "error": MESSAGES.get(exc.code, MESSAGES["write_failed"])}
        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": "이어버드가 응답하지 않아요."}
        except Exception:  # noqa: BLE001 — surface a message, keep the app alive
            log.exception("bridge call failed")
            return {"ok": False, "error": "알 수 없는 오류가 발생했어요."}

    async def _snapshot(self) -> dict:
        return self._ctrl.snapshot()

    # ------------------------------------------------------------- reads

    def get_app_info(self) -> dict:
        return {
            "ok": True,
            "version": self._version,
            "checkUpdatesOnStart": bool(self._storage.get("checkUpdatesOnStart")),
        }

    def get_state(self) -> dict:
        try:
            return self._loop.call(self._snapshot(), 5)
        except Exception:  # noqa: BLE001
            log.exception("get_state failed")
            return {"ok": False}

    def refresh(self) -> dict:
        return self._run(self._ctrl.refresh(light=True), 10)

    # ---------------------------------------------------------- commands

    def set_anc(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {"ok": False, "error": "잘못된 요청이에요."}
        return self._run(self._ctrl.set_anc(payload))

    def set_eq_preset(self, key: str) -> dict:
        return self._run(self._ctrl.set_eq_preset(str(key)))

    def set_eq_custom(self, gains: list) -> dict:
        if not isinstance(gains, list):
            return {"ok": False, "error": "잘못된 요청이에요."}
        return self._run(self._ctrl.set_eq_custom(gains))

    def set_balance(self, value: int) -> dict:
        return self._run(self._ctrl.set_balance(value))

    def set_toggle(self, name: str, on: bool) -> dict:
        return self._run(self._ctrl.set_toggle(str(name), bool(on)))

    def set_wear(self, enabled: bool, anc_on_wear: bool) -> dict:
        return self._run(self._ctrl.set_wear(bool(enabled), bool(anc_on_wear)))

    def set_tone_volume(self, level: int) -> dict:
        return self._run(self._ctrl.set_tone_volume(level))

    def set_auto_off(self, minutes: int | None) -> dict:
        return self._run(self._ctrl.set_auto_off(minutes))

    def set_disconnect_off(self, minutes: int | None) -> dict:
        return self._run(self._ctrl.set_disconnect_off(minutes))

    def set_touch(self, slot: int, function: str) -> dict:
        return self._run(self._ctrl.set_touch(slot, function))

    def rename(self, name: str) -> dict:
        return self._run(self._ctrl.rename(str(name)[:64]))

    def find(self, on: bool) -> dict:
        return self._run(self._ctrl.find(bool(on)))

    def reconnect(self) -> dict:
        return self._run(self._ctrl.reconnect(), 10)

    def reset_default(self) -> dict:
        return self._run(self._ctrl.reset_default(), 40)

    def factory_reset(self) -> dict:
        return self._run(self._ctrl.factory_reset())

    # ----------------------------------------------------------- updates

    def set_auto_update_check(self, enabled: bool) -> dict:
        self._storage.set("checkUpdatesOnStart", bool(enabled))
        return {"ok": True}

    def check_update(self) -> dict:
        try:
            info, newer = updater.check()
        except updater.UpdateError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:  # noqa: BLE001
            log.exception("update check failed")
            return {"ok": False, "error": "업데이트를 확인하지 못했어요."}
        self._update = info if newer else None
        return {
            "ok": True,
            "available": newer,
            "version": info.version,
            "changelog": info.changelog,
            "canApply": newer and updater.can_self_update() and bool(info.zip_url and info.sha_url),
        }

    def apply_update(self) -> dict:
        if self._update is None:
            return {"ok": False, "error": "먼저 업데이트를 확인해 주세요."}
        if not self._updating.acquire(blocking=False):
            return {"ok": False, "error": "이미 업데이트 중이에요."}
        try:
            def progress(p: float) -> None:
                self._pusher.run_js(f"window.WL&&window.WL.onUpdateProgress({max(0.0, min(1.0, p)):.3f})")

            updater.apply(self._update, progress)
        except updater.UpdateError as exc:
            self._updating.release()
            return {"ok": False, "error": str(exc)}
        except Exception:  # noqa: BLE001
            self._updating.release()
            log.exception("update failed")
            return {"ok": False, "error": "업데이트에 실패했어요. 지금 버전은 그대로 쓸 수 있어요."}
        # Close the window; app.main() then disconnects the earbuds and exits,
        # which lets the helper script swap the files and relaunch.
        if self._window is not None:
            threading.Timer(0.6, self._window.destroy).start()
        return {"ok": True}
