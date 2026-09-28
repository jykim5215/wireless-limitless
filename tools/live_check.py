"""Read-only live check: connect with the real controller, print the synced
state, disconnect. Sends only 0xFE queries and characteristic reads.

    .venv\\Scripts\\python.exe tools\\live_check.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wireless_limitless.controller import DeviceController  # noqa: E402
from wireless_limitless.storage import Storage  # noqa: E402


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    statuses: list[str] = []
    latest: dict = {}

    def on_state(state: dict) -> None:
        latest.clear()
        latest.update(state)
        if not statuses or statuses[-1] != state["status"]:
            statuses.append(state["status"])
            print(f"[{time.strftime('%H:%M:%S')}] status -> {state['status']}  {state['message'] or ''}")

    with tempfile.TemporaryDirectory() as tmp:
        ctrl = DeviceController(Storage(Path(tmp) / "settings.json"), on_state)
        await ctrl.start()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and latest.get("status") != "connected":
            await asyncio.sleep(0.2)
        await asyncio.sleep(1.0)
        snapshot = ctrl.snapshot()
        await ctrl.stop()

    snapshot.pop("caps", None)
    print(json.dumps(snapshot, ensure_ascii=False, indent=1))
    return 0 if snapshot["status"] == "connected" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
