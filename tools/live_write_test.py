"""Live write verification against real earbuds, restoring every value after.

Covers noise control, EQ (preset + custom), balance, game/sleep mode, wear
detection, prompt volume, both power-off timers and one touch slot. Skips
LDAC / multipoint (may reboot the buds), rename, find and resets on purpose.

    .venv\\Scripts\\python.exe tools\\live_write_test.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wireless_limitless.controller import DeviceController  # noqa: E402
from wireless_limitless.storage import Storage  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


async def wait_for(ctrl: DeviceController, predicate, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    snap = ctrl.snapshot()
    while time.monotonic() < deadline:
        snap = ctrl.snapshot()
        if predicate(snap):
            return snap
        await asyncio.sleep(0.2)
    return snap


async def anc_step(ctrl: DeviceController, payload: dict) -> None:
    await ctrl.set_anc(payload)
    snap = await wait_for(ctrl, lambda s: not s["ancPending"], 12)
    await ctrl.refresh(light=True)
    snap = ctrl.snapshot()
    want = {k: payload.get(k) for k in ("mode", "scene", "level")}
    got = {k: snap["anc"].get(k) for k in ("mode", "scene", "level")}
    if payload["mode"] == "transparency":
        want["vocal"], got["vocal"] = bool(payload.get("vocal")), snap["anc"]["vocal"]
    check(f"ANC {payload}", want == got, f"device={snap['anc']}")


async def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    with tempfile.TemporaryDirectory() as tmp:
        ctrl = DeviceController(Storage(Path(tmp) / "s.json"), lambda s: None)
        await ctrl.start()
        snap = await wait_for(ctrl, lambda s: s["status"] == "connected", 60)
        if snap["status"] != "connected":
            print("could not connect:", snap["status"], snap["message"])
            await ctrl.stop()
            return 2
        orig = ctrl.snapshot()
        print("original:", {k: orig[k] for k in ("anc", "balance", "toggles", "wear", "toneVolume",
                                                 "autoOff", "disconnectOff")}, "eq:", orig["eq"]["preset"])
        try:
            print("[noise control]")
            await anc_step(ctrl, {"mode": "transparency", "vocal": True})
            await anc_step(ctrl, {"mode": "transparency", "vocal": False, "level": 3})
            await anc_step(ctrl, {"mode": "anc", "scene": "indoor", "level": 2})
            await anc_step(ctrl, {"mode": "anc", "scene": "wind"})
            await anc_step(ctrl, {"mode": "anc", "scene": "adaptive"})

            print("[equalizer]")
            await ctrl.set_eq_preset("bass")
            await ctrl.set_eq_preset("rock")
            await ctrl.set_eq_preset("pop")  # rapid clicks: only the last should be sent
            await ctrl.flush()
            snap = ctrl.snapshot()
            check("EQ preset pop", snap["eq"]["preset"] == "pop", f"device={snap['eq']['preset']}")
            gains = [2, 1, 0, 0, -1, -1, 0, 1, 2, 0]
            await ctrl.set_eq_custom(gains)
            await ctrl.flush()
            snap = ctrl.snapshot()
            check("EQ custom gains", snap["eq"]["preset"] == "custom" and snap["eq"]["gains"] == gains,
                  f"device={snap['eq']['gains']}")

            print("[balance / toggles / wear]")
            await ctrl.set_balance(45)
            await ctrl.flush()
            check("balance 45", ctrl.snapshot()["balance"] == 45, f"device={ctrl.snapshot()['balance']}")
            for name in ("game", "sleep"):
                want = not orig["toggles"][name]
                await ctrl.set_toggle(name, want)
                got = ctrl.snapshot()["toggles"][name]
                check(f"toggle {name} -> {want}", got == want, f"device={got}")
            w = orig["wear"]
            await ctrl.set_wear(w["enabled"], not w["ancOnWear"])
            got = ctrl.snapshot()["wear"]
            check("wear ancOnWear flip", got == {"enabled": w["enabled"], "ancOnWear": not w["ancOnWear"]}, f"device={got}")

            print("[prompt volume / timers / touch]")
            level = 6 if orig["toneVolume"] != 6 else 4
            await ctrl.set_tone_volume(level)
            check(f"prompt volume {level}", ctrl.snapshot()["toneVolume"] == level, f"device={ctrl.snapshot()['toneVolume']}")
            await ctrl.set_auto_off(90)
            check("auto-off 90", ctrl.snapshot()["autoOff"] == {"minutes": 90}, f"device={ctrl.snapshot()['autoOff']}")
            await ctrl.set_disconnect_off(10)
            check("disconnect-off 10", ctrl.snapshot()["disconnectOff"] == {"minutes": 10},
                  f"device={ctrl.snapshot()['disconnectOff']}")
            slot_before = orig["touch"]["1"]
            probe_fn = "volume_down" if slot_before != "volume_down" else "volume_up"
            await ctrl.set_touch(1, probe_fn)
            check(f"touch L1 -> {probe_fn}", ctrl.snapshot()["touch"]["1"] == probe_fn, f"device={ctrl.snapshot()['touch']['1']}")
        finally:
            print("[restore]")
            try:
                await ctrl.set_touch(1, orig["touch"]["1"])
                await ctrl.set_disconnect_off(orig["disconnectOff"]["minutes"])
                await ctrl.set_auto_off(orig["autoOff"]["minutes"])
                await ctrl.set_tone_volume(orig["toneVolume"])
                await ctrl.set_wear(orig["wear"]["enabled"], orig["wear"]["ancOnWear"])
                for name in ("game", "sleep"):
                    await ctrl.set_toggle(name, orig["toggles"][name])
                await ctrl.set_balance(orig["balance"])
                if orig["eq"]["preset"] == "custom":
                    await ctrl.set_eq_custom(orig["eq"]["gains"])
                else:
                    await ctrl.set_eq_preset(orig["eq"]["preset"])
                await ctrl.flush()
                a = orig["anc"]
                await ctrl.set_anc({"mode": a["mode"], "scene": a["scene"], "level": a["level"], "vocal": a["vocal"]})
                await wait_for(ctrl, lambda s: not s["ancPending"], 12)
                await ctrl.refresh(light=False)
            except Exception as exc:  # noqa: BLE001
                print("RESTORE ERROR:", repr(exc))
            final = ctrl.snapshot()
            keys = ("anc", "balance", "toggles", "wear", "toneVolume", "autoOff", "disconnectOff", "touch")
            same = {k: final[k] == orig[k] for k in keys}
            same["eq"] = final["eq"]["preset"] == orig["eq"]["preset"]
            check("everything restored", all(same.values()), str({k: v for k, v in same.items() if not v}))
            await ctrl.stop()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
