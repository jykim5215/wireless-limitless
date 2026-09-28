"""Application bootstrap: logging, single instance, BLE thread, window."""

from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys

import webview

from . import config, paths, updater
from .bridge import Bridge, StatePusher
from .controller import DeviceController
from .runner import LoopThread
from .storage import Storage

log = logging.getLogger("wireless_limitless")

_MUTEX_NAME = f"Local\\{config.APP_ID}.SingleInstance"
_ERROR_ALREADY_EXISTS = 183
_mutex_handle = None


def _setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(
        paths.log_dir() / "app.log", maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not paths.is_frozen():
        root.addHandler(logging.StreamHandler())
    # Third-party debug output can include full device addresses.
    for noisy in ("bleak", "pywebview", "webview"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if kernel32.GetLastError() != _ERROR_ALREADY_EXISTS:
        return True
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, config.APP_NAME)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return False


def main() -> int:
    _setup_logging()
    if not _acquire_single_instance():
        return 0
    version = updater.current_version()
    log.info("%s %s starting (frozen=%s)", config.APP_NAME, version, paths.is_frozen())

    storage = Storage()
    ble = LoopThread()
    ble.start()
    pusher = StatePusher()
    controller = DeviceController(storage, pusher.push_state)
    ble.call(controller.start(), 5)
    bridge = Bridge(ble, controller, storage, pusher, version)

    window = webview.create_window(
        config.APP_NAME,
        url=paths.ui_index().as_uri(),  # file:// URL -> pywebview starts no HTTP server
        js_api=bridge,
        width=config.WINDOW_SIZE[0],
        height=config.WINDOW_SIZE[1],
        min_size=config.WINDOW_MIN_SIZE,
        background_color=config.WINDOW_BACKGROUND,
    )
    pusher.attach(window)
    bridge._attach_window(window)
    window.events.loaded += pusher.mark_ready

    try:
        webview.start(gui="edgechromium", debug=os.environ.get("WL_DEBUG") == "1", private_mode=True)
    finally:
        try:
            ble.call(controller.stop(), 8)
        except Exception:  # noqa: BLE001
            log.warning("controller did not stop cleanly", exc_info=True)
        ble.stop()
        log.info("exited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
