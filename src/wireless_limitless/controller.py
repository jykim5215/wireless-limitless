"""DeviceController: connection lifecycle, commands and state sync.

Runs entirely on one asyncio loop (the BLE thread). The UI receives JSON
snapshots through `on_state`; commands come in as coroutines scheduled from
the pywebview bridge.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from . import catalog
from . import protocol as p
from .protocol import Op
from .storage import Storage
from .transport import FoundDevice, QcyTransport, TransportError, mask_address, scan

log = logging.getLogger(__name__)

SCAN_TIMEOUT_S = 12.0
QUERY_TIMEOUT_S = 1.5
ANC_ECHO_TIMEOUT_S = 2.5
ANC_RESULT_TIMEOUT_S = 10.0
FIND_AUTO_STOP_S = 60.0
POLL_INTERVAL_S = 30.0
RETRY_DELAYS_S = (3, 5, 8, 12)
EQ_WRITE_GAP_S = 0.6  # 147-byte EQ frames: keep the earbuds' radio from being flooded

TOGGLES = {"game": Op.GAME_MODE, "sleep": Op.SLEEP_MODE, "ldac": Op.LDAC, "multipoint": Op.MULTIPOINT}
TOGGLE_NAMES = {op: name for name, op in TOGGLES.items()}

MESSAGES = {
    "bluetooth_unavailable": "Windows 설정에서 블루투스를 켜 주세요.",
    "scan_failed": "블루투스 검색을 시작하지 못했어요. 잠시 후 다시 시도할게요.",
    "not_found": "이어버드를 꺼내 전원을 켜 주세요. 휴대폰의 QCY 앱은 닫아 주세요.",
    "connect_failed": "연결하지 못했어요. 자동으로 다시 시도할게요.",
    "service_missing": "이 기기는 QCY 제어 서비스를 제공하지 않아요.",
    "link_lost": "다시 연결하는 중…",
    "write_failed": "명령을 보내지 못했어요. 연결 상태를 확인해 주세요.",
    "read_failed": "기기에서 설정을 읽지 못했어요.",
    "not_connected": "이어버드가 연결되어 있지 않아요.",
    "unsupported": "지원 목록에 없는 QCY 모델이에요.",
}


class CommandError(Exception):
    pass


def _reraise_if_task_cancelled() -> None:
    """Distinguish our own task being cancelled from a waiter future being dropped."""
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


def _blank_state() -> dict[str, Any]:
    return {
        "status": "idle",  # idle|searching|connecting|syncing|connected|offline|unsupported|bt_off
        "message": None,
        "device": None,
        "caps": None,
        "battery": None,
        "anc": None,
        "ancPending": False,
        "eq": None,
        "balance": None,
        "toggles": {name: None for name in TOGGLES},
        "wear": None,
        "toneVolume": None,
        "autoOff": None,  # {"minutes": int|None}; None minutes = off
        "disconnectOff": None,
        "name": None,
        "touch": None,  # {"1": "play_pause", ...}
        "finding": False,
    }


class DeviceController:
    def __init__(self, storage: Storage, on_state: Callable[[dict], None]):
        self._storage = storage
        self._emit = on_state
        self._transport = QcyTransport(self._on_frame_threadsafe, self._on_battery_threadsafe,
                                       self._on_link_lost_threadsafe)
        self._state = _blank_state()
        self._lock = asyncio.Lock()
        self._waiters: dict[int, list[asyncio.Future]] = {}
        self._wake = asyncio.Event()
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task] = set()
        self._model: catalog.Model | None = None
        self._device: FoundDevice | None = None
        self._latest: dict[str, Any] = {}
        self._coalescers: dict[str, asyncio.Task] = {}
        self._anc_timeout: asyncio.TimerHandle | None = None
        self._find_timeout: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------------ state

    def snapshot(self) -> dict:
        return copy.deepcopy(self._state)

    def _set(self, **changes: Any) -> None:
        self._state.update(changes)
        self._emit(self.snapshot())

    def _set_nested(self, key: str, sub: str, value: Any) -> None:
        self._state[key] = {**(self._state.get(key) or {}), sub: value}
        self._emit(self.snapshot())

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._running = True
        self._spawn(self._manager())
        self._spawn(self._poller())

    async def flush(self, timeout: float = 3.0) -> None:
        """Wait for queued slider/EQ writes (and their read-back) to finish."""
        pending = [t for t in self._coalescers.values() if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=timeout)

    async def stop(self) -> None:
        await self.flush()
        self._running = False
        self._wake.set()
        if self._state.get("finding") and self._transport.connected:
            try:
                await self._transport.write_command(p.build_find(False))
            except TransportError:
                pass
        for task in list(self._tasks):
            task.cancel()
        await self._transport.disconnect()

    def _spawn(self, coro: Awaitable) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _manager(self) -> None:
        failures = 0
        while self._running:
            if self._transport.connected:
                await self._wake.wait()
                self._wake.clear()
                continue
            try:
                await self._connect_once()
                failures = 0
                continue
            except TransportError as exc:
                failures += 1
                self._report_connect_failure(exc)
            except Exception:  # noqa: BLE001 — never let the manager die
                failures += 1
                log.exception("unexpected connection error")
                self._set(status="offline", message=MESSAGES["connect_failed"])
            delay = RETRY_DELAYS_S[min(failures - 1, len(RETRY_DELAYS_S) - 1)]
            try:
                await asyncio.wait_for(self._wake.wait(), delay)
            except TimeoutError:
                pass
            self._wake.clear()

    def _report_connect_failure(self, exc: TransportError) -> None:
        if exc.code == "bluetooth_unavailable":
            self._set(status="bt_off", message=MESSAGES["bluetooth_unavailable"])
        elif exc.code == "unsupported":
            self._set(status="unsupported", message=str(exc).split(": ", 1)[-1])
        else:
            self._set(status="offline", message=MESSAGES.get(exc.code, MESSAGES["connect_failed"]))

    async def _connect_once(self) -> None:
        last = self._storage.get("lastDevice") or {}
        prefer = last.get("address") if isinstance(last, dict) else None
        self._set(status="searching", message=None)
        devices = await scan(SCAN_TIMEOUT_S, prefer, supported=lambda vid: catalog.model_for(vid) is not None)
        if not devices:
            raise TransportError("not_found")
        supported = [d for d in devices if catalog.model_for(d.vendor_id)]
        preferred = [d for d in supported if prefer and d.address.upper() == prefer.upper()]
        target = (preferred or supported or [None])[0]
        if target is None:
            vid = devices[0].vendor_id
            raise TransportError(
                "unsupported",
                f"{MESSAGES['unsupported']} (제품 ID {vid}) 현재 HT08 MeloBuds Pro / Pro Plus를 지원해요.")

        self._model = catalog.model_for(target.vendor_id)
        self._device = target
        self._set(status="connecting", message=None,
                  device={"model": self._model.name, "vendorId": target.vendor_id,
                          "address": mask_address(target.address), "firmware": None},
                  caps=self._model.capabilities(),
                  battery=target.advert.battery.to_dict())
        await self._transport.connect(target)
        self._storage.set("lastDevice", {"address": target.address, "vendorId": target.vendor_id})
        self._set(status="syncing")
        await self._sync_all()
        self._set(status="connected", message=None)

    def _on_link_lost(self) -> None:
        self._cancel_timer("_anc_timeout")
        self._cancel_timer("_find_timeout")
        for futures in self._waiters.values():
            for fut in futures:
                if not fut.done():
                    fut.cancel()
        self._waiters.clear()
        if self._running:
            self._set(status="offline", message=MESSAGES["link_lost"], ancPending=False, finding=False)
            self._wake.set()

    async def reconnect(self) -> None:
        await self._transport.disconnect()
        self._set(status="searching", message=None)
        self._wake.set()

    async def _poller(self) -> None:
        while self._running:
            await asyncio.sleep(POLL_INTERVAL_S)
            if self._transport.connected and self._state["status"] == "connected":
                try:
                    await self.refresh(light=True)
                except (TransportError, CommandError) as exc:
                    log.info("poll failed: %s", exc)

    # ---------------------------------------------------------- notifications

    def _on_frame_threadsafe(self, data: bytes) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._on_frame, data)

    def _on_battery_threadsafe(self, data: bytes) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._apply_battery, data)

    def _on_link_lost_threadsafe(self) -> None:
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._on_link_lost)

    def _on_frame(self, data: bytes) -> None:
        try:
            blocks = p.parse_frame(data)
        except p.ProtocolError:
            blocks = p.parse_state_blob(data)
            if not blocks:
                log.debug("ignored malformed notification (%d bytes)", len(data))
                return
        for block in blocks:
            self._apply_block(block)
            for fut in self._waiters.pop(block.op, []):
                if not fut.done():
                    fut.set_result(block.params)

    def _apply_battery(self, data: bytes) -> None:
        battery = p.parse_battery(data)
        if battery is not None:
            self._set(battery=battery.to_dict())

    def _apply_block(self, block: p.Block) -> None:
        op, prm = block.op, block.params
        if op == Op.ANC:
            setting = p.parse_anc(prm)
            if setting is not None:
                self._set(anc=setting.to_dict())
        elif op == Op.ANC_RESULT:
            self._cancel_timer("_anc_timeout")
            self._set(ancPending=False)
        elif op == Op.BALANCE:
            value = p.parse_balance(prm)
            if value is not None:
                self._set(balance=value)
        elif op == Op.EQ:
            reading = p.parse_eq(prm)
            if reading is not None:
                self._set(eq=self._eq_state(reading))
        elif op in TOGGLE_NAMES:
            value = p.parse_toggle(prm)
            if value is not None:
                self._set_nested("toggles", TOGGLE_NAMES[op], value)
        elif op == Op.WEAR:
            wear = p.parse_wear(prm)
            if wear is not None:
                self._set(wear={"enabled": wear[0], "ancOnWear": wear[1]})
        elif op == Op.TONE_VOLUME:
            level = p.parse_tone_volume(prm)
            if level is not None:
                self._set(toneVolume=level)
        elif op == Op.AUTO_OFF:
            if len(prm) >= 2:
                self._set(autoOff={"minutes": p.parse_timer(prm)})
        elif op == Op.DISCONNECT_OFF:
            if len(prm) >= 2:
                self._set(disconnectOff={"minutes": p.parse_timer(prm)})
        elif op == Op.NAME:
            self._set(name=p.parse_name(prm))
        elif op == Op.KEY_FUNCTION:
            self._apply_touch(prm)

    def _apply_touch(self, data: bytes) -> None:
        mapping = p.parse_touch_map(data)
        self._set(touch={str(slot): p.TOUCH_FUNCTIONS.get(func, f"unknown_{func:02x}")
                         for slot, func in mapping.items() if slot in p.TOUCH_SLOTS})

    def _eq_state(self, reading: p.EqReading) -> dict:
        bands = [[b.freq, b.gain_db, b.q, b.kind] for b in reading.bands]
        if reading.is_custom:
            return {"preset": "custom", "gains": reading.custom_gains(), "bands": bands}
        preset = self._model.preset_by_id(reading.preset_id) if self._model else None
        return {"preset": preset.key if preset else None, "gains": None, "bands": bands}

    # ---------------------------------------------------------------- syncing

    async def _query(self, op: int, timeout: float = QUERY_TIMEOUT_S) -> bytes | None:
        return await self._send_and_wait(p.build_query(op), op, timeout)

    async def _send_and_wait(self, frame: bytes, op: int, timeout: float) -> bytes | None:
        assert self._loop is not None
        fut = self._loop.create_future()
        self._waiters.setdefault(op, []).append(fut)
        try:
            await self._transport.write_command(frame)
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return None
        except asyncio.CancelledError:
            _reraise_if_task_cancelled()
            raise TransportError("not_connected") from None  # waiter dropped by link loss
        finally:
            waiters = self._waiters.get(op)
            if waiters and fut in waiters:
                waiters.remove(fut)

    async def _sync_all(self) -> None:
        async with self._lock:
            seen: set[int] = set()
            blob = await self._transport.read(p.CHAR_NOTIFY)
            for block in p.parse_state_blob(blob or b""):
                self._apply_block(block)
                seen.add(block.op)
            battery = await self._transport.read(p.CHAR_BATTERY)
            if battery:
                self._apply_battery(battery)
            version = await self._transport.read(p.CHAR_VERSION)
            parsed = p.parse_version(version or b"")
            if parsed:
                left, right = parsed
                firmware = left if right in (None, left) else f"L {left} · R {right}"
                self._set_nested("device", "firmware", firmware)
            touch = await self._transport.read(p.CHAR_TOUCH)
            if touch:
                self._apply_touch(touch)
            wanted = [Op.EQ, Op.AUTO_OFF, Op.NAME]
            wanted += [op for op in (Op.ANC, Op.BALANCE, Op.GAME_MODE, Op.SLEEP_MODE, Op.LDAC,
                                     Op.MULTIPOINT, Op.WEAR, Op.TONE_VOLUME, Op.DISCONNECT_OFF)
                       if op not in seen]
            for op in wanted:
                await self._query(op)

    async def refresh(self, light: bool = False) -> None:
        self._require_connected()
        if not light:
            await self._sync_all()
            return
        async with self._lock:
            battery = await self._transport.read(p.CHAR_BATTERY)
            if battery:
                self._apply_battery(battery)
            if not self._state["ancPending"]:
                await self._query(Op.ANC)

    # --------------------------------------------------------------- commands

    def _require_connected(self) -> None:
        if not self._transport.connected or self._model is None:
            raise CommandError(MESSAGES["not_connected"])

    async def _write(self, frame: bytes) -> None:
        log.info("send op=0x%02X len=%d", frame[2] if len(frame) > 2 else -1, len(frame))
        try:
            await self._transport.write_command(frame)
        except TransportError as exc:
            raise CommandError(MESSAGES.get(exc.code, MESSAGES["write_failed"])) from exc

    async def _write_then_confirm(self, frame: bytes, op: int, settle: float = 0.25) -> None:
        async with self._lock:
            await self._write(frame)
            await asyncio.sleep(settle)
            await self._query(op)

    def _cancel_timer(self, attr: str) -> None:
        handle = getattr(self, attr)
        if handle is not None:
            handle.cancel()
            setattr(self, attr, None)

    async def set_anc(self, payload: dict) -> None:
        self._require_connected()
        setting = p.AncSetting(
            mode=str(payload.get("mode")),
            scene=payload.get("scene"),
            level=int(payload["level"]) if payload.get("level") is not None else None,
            vocal=bool(payload.get("vocal")),
        )
        try:
            frame = p.build_anc(setting)
        except p.ProtocolError as exc:
            raise CommandError(str(exc)) from exc
        self._set(anc=setting.to_dict(), ancPending=True)
        async with self._lock:
            await self._write(frame)
            echo = await self._wait_for(Op.ANC, ANC_ECHO_TIMEOUT_S)
            if echo is None:
                await self._query(Op.ANC)
                self._set(ancPending=False)
                raise CommandError("이어버드가 노이즈 제어 변경을 확인하지 않았어요. 다시 시도해 주세요.")
        self._cancel_timer("_anc_timeout")
        assert self._loop is not None
        self._anc_timeout = self._loop.call_later(ANC_RESULT_TIMEOUT_S, lambda: self._set(ancPending=False))

    async def _wait_for(self, op: int, timeout: float) -> bytes | None:
        assert self._loop is not None
        fut = self._loop.create_future()
        self._waiters.setdefault(op, []).append(fut)
        try:
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return None
        except asyncio.CancelledError:
            _reraise_if_task_cancelled()
            raise TransportError("not_connected") from None
        finally:
            waiters = self._waiters.get(op)
            if waiters and fut in waiters:
                waiters.remove(fut)

    async def set_eq_preset(self, key: str) -> None:
        self._require_connected()
        assert self._model is not None
        preset = self._model.preset_by_key(key)
        if preset is None:
            raise CommandError("알 수 없는 이퀄라이저 프리셋이에요.")
        self._set(eq={"preset": preset.key, "gains": None,
                      "bands": [[b.freq, b.gain_db, b.q, b.kind] for b in preset.bands]})
        # Preset clicks share the custom-EQ queue: rapid clicks send only the last one.
        self._coalesce("eq", p.build_eq_raw(preset.id, preset.table()), Op.EQ, gap=EQ_WRITE_GAP_S)

    async def set_eq_custom(self, gains: list) -> None:
        self._require_connected()
        try:
            clean = [max(-p.EQ_GAIN_LIMIT_DB, min(p.EQ_GAIN_LIMIT_DB, round(float(g)))) for g in gains]
            frame = p.build_eq_custom(clean)
        except (TypeError, ValueError, p.ProtocolError) as exc:
            raise CommandError("사용자 지정 이퀄라이저 값이 올바르지 않아요.") from exc
        self._set(eq={"preset": "custom", "gains": clean,
                      "bands": [[f, g, 1.0, 0] for f, g in zip(p.EQ_FREQS, clean)]})
        self._coalesce("eq", frame, Op.EQ, gap=EQ_WRITE_GAP_S)

    async def set_balance(self, value: int) -> None:
        self._require_connected()
        try:
            frame = p.build_balance(int(value))
        except (TypeError, ValueError, p.ProtocolError) as exc:
            raise CommandError("밸런스 값이 올바르지 않아요.") from exc
        self._set(balance=int(value))
        self._coalesce("balance", frame, Op.BALANCE)

    def _coalesce(self, key: str, frame: bytes, confirm_op: int, gap: float = 0.15) -> None:
        """Slider/rapid input: send only the newest value (at most one write per
        `gap` seconds), then read it back once."""
        self._latest[key] = frame
        task = self._coalescers.get(key)
        if task is not None and not task.done():
            return

        async def run() -> None:
            try:
                while key in self._latest:
                    newest = self._latest.pop(key)
                    async with self._lock:
                        await self._write(newest)
                    await asyncio.sleep(gap)
                await asyncio.sleep(0.2)
                async with self._lock:
                    await self._query(confirm_op)
            except (CommandError, TransportError) as exc:
                self._set(message=str(exc) if isinstance(exc, CommandError) else MESSAGES["write_failed"])

        self._coalescers[key] = self._spawn(run())

    async def set_toggle(self, name: str, on: bool) -> None:
        self._require_connected()
        op = TOGGLES.get(name)
        if op is None:
            raise CommandError("알 수 없는 설정이에요.")
        self._set_nested("toggles", name, bool(on))
        await self._write_then_confirm(p.build_toggle(op, bool(on)), op, settle=0.3)

    async def set_wear(self, enabled: bool, anc_on_wear: bool) -> None:
        self._require_connected()
        self._set(wear={"enabled": bool(enabled), "ancOnWear": bool(anc_on_wear)})
        await self._write_then_confirm(p.build_wear(bool(enabled), bool(anc_on_wear)), Op.WEAR)

    async def set_tone_volume(self, level: int) -> None:
        self._require_connected()
        try:
            frame = p.build_tone_volume(int(level))
        except (TypeError, ValueError, p.ProtocolError) as exc:
            raise CommandError("알림음 볼륨 값이 올바르지 않아요.") from exc
        self._set(toneVolume=int(level))
        await self._write_then_confirm(frame, Op.TONE_VOLUME)

    async def set_auto_off(self, minutes: int | None) -> None:
        self._require_connected()
        try:
            frame = p.build_auto_off(None if minutes is None else int(minutes))
        except (TypeError, ValueError, p.ProtocolError) as exc:
            raise CommandError("자동 전원 끄기 시간은 1~1440분 사이로 설정해 주세요.") from exc
        self._set(autoOff={"minutes": minutes})
        await self._write_then_confirm(frame, Op.AUTO_OFF)

    async def set_disconnect_off(self, minutes: int | None) -> None:
        self._require_connected()
        try:
            frame = p.build_disconnect_off(None if minutes is None else int(minutes))
        except (TypeError, ValueError, p.ProtocolError) as exc:
            raise CommandError("연결 끊김 후 전원 끄기 값이 올바르지 않아요.") from exc
        self._set(disconnectOff={"minutes": minutes})
        await self._write_then_confirm(frame, Op.DISCONNECT_OFF)

    async def set_touch(self, slot: int, function: str) -> None:
        self._require_connected()
        try:
            data = p.build_touch_write(int(slot), str(function))
        except (TypeError, ValueError, p.ProtocolError) as exc:
            raise CommandError("터치 조작 설정이 올바르지 않아요.") from exc
        self._set(touch={**(self._state.get("touch") or {}), str(int(slot)): str(function)})
        async with self._lock:
            try:
                log.info("send touch slot=%d func=0x%02X", data[0], data[1])
                await self._transport.write_touch(data)
                await asyncio.sleep(0.25)
                table = await self._transport.read(p.CHAR_TOUCH)
            except TransportError as exc:
                raise CommandError(MESSAGES.get(exc.code, MESSAGES["write_failed"])) from exc
            if table:
                self._apply_touch(table)

    async def rename(self, name: str) -> None:
        self._require_connected()
        try:
            frame = p.build_rename(str(name))
        except p.ProtocolError as exc:
            raise CommandError("이름은 1~31바이트(한글 약 10자)로 입력해 주세요.") from exc
        await self._write_then_confirm(frame, Op.NAME, settle=0.4)

    async def find(self, on: bool) -> None:
        self._require_connected()
        self._cancel_timer("_find_timeout")
        async with self._lock:
            await self._write(p.build_find(bool(on)))
        self._set(finding=bool(on))
        if on:
            assert self._loop is not None
            self._find_timeout = self._loop.call_later(
                FIND_AUTO_STOP_S, lambda: self._spawn(self._auto_stop_find()))

    async def _auto_stop_find(self) -> None:
        if self._state.get("finding") and self._transport.connected:
            try:
                await self.find(False)
            except CommandError:
                self._set(finding=False)

    async def reset_default(self) -> None:
        self._require_connected()
        async with self._lock:
            await self._write(p.build_reset_default())
        await asyncio.sleep(1.5)
        try:
            if self._transport.connected:
                await self._sync_all()
        except TransportError:
            pass  # the earbuds may reboot; the manager resyncs after reconnecting

    async def factory_reset(self) -> None:
        self._require_connected()
        async with self._lock:
            await self._write(p.build_factory_reset())
        self._storage.set("lastDevice", None)
        self._set(message="공장 초기화를 보냈어요. 이어버드가 모든 페어링 기록을 지우므로 "
                          "Windows 블루투스 설정에서 다시 페어링해 주세요.")
