"""QCY earbuds BLE protocol: framing, command builders and parsers.

Pure functions only (no I/O), so everything here is unit-testable without
hardware. Byte layouts were verified against a QCY HT08 MeloBuds Pro Plus
running firmware 2.0.7; see HANDOFF.md section 3-3 for the full table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

COMPANY_ID = 0x521C

SERVICE_UUID = "0000a001-0000-1000-8000-00805f9b34fb"
CHAR_COMMAND = "00001001-0000-1000-8000-00805f9b34fb"
CHAR_NOTIFY = "00001002-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY = "00000008-0000-1000-8000-00805f9b34fb"
CHAR_VERSION = "00000007-0000-1000-8000-00805f9b34fb"
CHAR_TOUCH = "0000000d-0000-1000-8000-00805f9b34fb"

SOF = 0xFF


class Op(IntEnum):
    RESET_DEFAULT = 0x01
    FACTORY_RESET = 0x03
    MUSIC = 0x04
    FIND = 0x05
    VOLUME = 0x08
    GAME_MODE = 0x09
    SLEEP_MODE = 0x10
    AUTO_OFF = 0x14
    BALANCE = 0x16
    ANC = 0x17
    NAME = 0x18
    LANGUAGE = 0x19
    TONE_VOLUME = 0x1D
    DISCONNECT_OFF = 0x1F
    EQ = 0x22
    LDAC = 0x23
    MULTIPOINT = 0x24
    ANC_RESULT = 0x28
    KEY_FUNCTION = 0x2B
    WEAR = 0x2C
    QUERY = 0xFE


# Every opcode documented for the QCY command channel. Used to sanity-check
# the tolerant state-blob parser, not to gate what we accept on notify.
KNOWN_OPS = frozenset(
    {
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0C, 0x0D,
        0x10, 0x11, 0x12, 0x14, 0x16, 0x17, 0x18, 0x19, 0x1D, 0x1E, 0x1F, 0x20,
        0x22, 0x23, 0x24, 0x27, 0x28, 0x29, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30,
        0x32, 0x34, 0x35, 0x36, 0x37, 0x39, 0x3A, 0x3B, 0x3D, 0x3E, 0x3F, 0x43,
        0x44, 0x45, 0x46, 0x47, 0x48, 0x4A, 0xFE,
    }
)

# Opcodes that can legitimately appear in the settings blob. Action opcodes
# (reset, factory reset, find, query, ...) are excluded so that a misaligned
# walk through the blob can never "validate" by landing on them.
BLOB_OPS = frozenset(
    {
        0x04, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0C, 0x10, 0x12, 0x14, 0x16, 0x17,
        0x18, 0x19, 0x1D, 0x1F, 0x20, 0x22, 0x23, 0x24, 0x27, 0x29, 0x2B, 0x2C,
        0x2D, 0x2E, 0x2F, 0x30, 0x32, 0x34, 0x35, 0x37, 0x39, 0x44, 0x48, 0x4A,
    }
)

# Toggles use 0x01 = on / 0x02 = off on write. Reads come back as 0x01 / 0x02
# (game mode) or 0x00 / 0x01 (sleep, LDAC, multipoint), so "on" is == 0x01.
TOGGLE_OPS = frozenset({Op.GAME_MODE, Op.SLEEP_MODE, Op.LDAC, Op.MULTIPOINT})


class ProtocolError(ValueError):
    """Raised for malformed frames or out-of-range command arguments."""


@dataclass(frozen=True)
class Block:
    op: int
    params: bytes


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------


def build_frame(*blocks: tuple[int, bytes | bytearray | list[int]]) -> bytes:
    body = bytearray()
    for op, params in blocks:
        params = bytes(params)
        if not 0 <= op <= 0xFF:
            raise ProtocolError(f"opcode out of range: {op}")
        if len(params) > 0xFF:
            raise ProtocolError("parameter block too long")
        body += bytes([op, len(params)]) + params
    if not body or len(body) > 0xFF:
        raise ProtocolError("frame body must be 1..255 bytes")
    return bytes([SOF, len(body)]) + bytes(body)


def command(op: int, params: bytes | bytearray | list[int] = b"") -> bytes:
    return build_frame((op, params))


def parse_frame(data: bytes | bytearray) -> list[Block]:
    """Strict parser for one 0xFF-framed packet (notifications, query replies)."""
    data = bytes(data)
    if len(data) < 4 or data[0] != SOF:
        raise ProtocolError("not a QCY frame")
    if data[1] + 2 != len(data):
        raise ProtocolError("length byte does not match packet size")
    blocks: list[Block] = []
    i = 2
    while i < len(data):
        if i + 2 > len(data):
            raise ProtocolError("truncated block header")
        op, n = data[i], data[i + 1]
        i += 2
        if i + n > len(data):
            raise ProtocolError("truncated block parameters")
        blocks.append(Block(op, data[i : i + n]))
        i += n
    return blocks


def parse_state_blob(data: bytes | bytearray) -> list[Block]:
    """Tolerant parser for the settings blob read from the notify characteristic.

    Firmware 2.0.7 declares the 0x2C (wear detection) block as 3 bytes long but
    actually emits 4, which shifts every following block. For a 3-byte 0x2C we
    try 4 first, then 3, and accept the first interpretation that consumes the
    frame exactly using only settings opcodes (BLOB_OPS). Trying 3 first is not
    safe: with some values the shifted walk happens to parse cleanly.
    Returns [] instead of raising: the caller falls back to per-setting queries.
    """
    data = bytes(data)
    if len(data) < 4 or data[0] != SOF or data[1] + 2 != len(data):
        return []

    def walk(i: int) -> list[Block] | None:
        if i == len(data):
            return []
        if i + 2 > len(data):
            return None
        op, n = data[i], data[i + 1]
        if op not in BLOB_OPS:
            return None
        candidates = [4, 3] if op == Op.WEAR and n == 3 else [n]
        for length in candidates:
            end = i + 2 + length
            if end > len(data):
                continue
            rest = walk(end)
            if rest is not None:
                return [Block(op, data[i + 2 : end]), *rest]
        return None

    return walk(2) or []


# --------------------------------------------------------------------------
# Generic commands
# --------------------------------------------------------------------------


def build_query(op: int) -> bytes:
    return command(Op.QUERY, [op])


def build_toggle(op: int, on: bool) -> bytes:
    if op not in TOGGLE_OPS:
        raise ProtocolError(f"0x{op:02X} is not a toggle opcode")
    return command(op, [0x01 if on else 0x02])


def parse_toggle(params: bytes) -> bool | None:
    return params[0] == 0x01 if params else None


def build_balance(value: int) -> bytes:
    if not 0 <= value <= 100:
        raise ProtocolError("balance must be 0..100")
    return command(Op.BALANCE, [value])


def parse_balance(params: bytes) -> int | None:
    return params[0] if params and params[0] <= 100 else None


def build_find(on: bool) -> bytes:
    return command(Op.FIND, [0x01 if on else 0x00])


def build_reset_default() -> bytes:
    return command(Op.RESET_DEFAULT)


def build_factory_reset() -> bytes:
    return command(Op.FACTORY_RESET)


# --------------------------------------------------------------------------
# Noise control (opcode 0x17, confirmed asynchronously by 0x28)
# --------------------------------------------------------------------------

ANC_MODES = ("anc", "transparency", "normal")
ANC_SCENES = {"indoor": 0x01, "commute": 0x02, "noisy": 0x03, "wind": 0x04, "adaptive": 0x05}
LEVELED_SCENES = frozenset({"indoor", "commute", "noisy"})
NC_LEVELS = (1, 2, 3)
AMBIENT_LEVELS = (1, 2, 3, 4, 5, 6)


@dataclass(frozen=True)
class AncSetting:
    mode: str  # "anc" | "transparency" | "normal"
    scene: str | None = None  # anc only: indoor/commute/noisy/wind/adaptive
    level: int | None = None  # anc leveled scenes: 1..3, transparency ambient: 1..6
    vocal: bool = False  # transparency only: vocal enhancement

    def triplet(self) -> tuple[int, int, int]:
        if self.mode == "normal":
            return (0x02, 0x00, 0x00)
        if self.mode == "transparency":
            if self.vocal:
                return (0x03, 0x02, 0x00)
            if self.level not in AMBIENT_LEVELS:
                raise ProtocolError("ambient level must be 1..6")
            return (0x03, 0x01, self.level)
        if self.mode == "anc":
            if self.scene not in ANC_SCENES:
                raise ProtocolError(f"unknown ANC scene: {self.scene!r}")
            if self.scene in LEVELED_SCENES:
                if self.level not in NC_LEVELS:
                    raise ProtocolError("noise cancelling level must be 1..3")
                return (0x01, ANC_SCENES[self.scene], self.level - 1)
            return (0x01, ANC_SCENES[self.scene], 0x00)
        raise ProtocolError(f"unknown ANC mode: {self.mode!r}")

    def to_dict(self) -> dict:
        return {"mode": self.mode, "scene": self.scene, "level": self.level, "vocal": self.vocal}


def anc_from_triplet(mode: int, sub: int, value: int) -> AncSetting | None:
    if (mode, sub, value) == (0x02, 0x00, 0x00):
        return AncSetting("normal")
    if mode == 0x03:
        if sub == 0x02:
            return AncSetting("transparency", vocal=True)
        if sub == 0x01:
            if value == 0:  # the official app remaps (3,1,0) to vocal enhancement
                return AncSetting("transparency", vocal=True)
            if value in AMBIENT_LEVELS:
                return AncSetting("transparency", level=value)
        return None
    if mode == 0x01:
        for name, code in ANC_SCENES.items():
            if code != sub:
                continue
            if name in LEVELED_SCENES:
                return AncSetting("anc", scene=name, level=value + 1) if value <= 2 else None
            return AncSetting("anc", scene=name)
    return None


def build_anc(setting: AncSetting) -> bytes:
    return command(Op.ANC, list(setting.triplet()))


def parse_anc(params: bytes) -> AncSetting | None:
    return anc_from_triplet(params[0], params[1], params[2]) if len(params) >= 3 else None


# --------------------------------------------------------------------------
# Equalizer (opcode 0x22: 1-byte preset id + 142-byte table)
# --------------------------------------------------------------------------

EQ_TABLE_LEN = 142
EQ_SLOTS = 20
EQ_FREQS = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
EQ_GAIN_LIMIT_DB = 8
CUSTOM_EQ_ID = 0x80
_UNUSED_SLOT = bytes([0, 0, 0, 0, 0, 0, 0xFF])


@dataclass(frozen=True)
class EqBand:
    freq: int
    gain_db: float
    q: float
    kind: int = 0


@dataclass(frozen=True)
class EqReading:
    preset_id: int
    master_gain_db: float
    bands: tuple[EqBand, ...] = field(default_factory=tuple)

    @property
    def is_custom(self) -> bool:
        return self.preset_id == CUSTOM_EQ_ID

    def custom_gains(self) -> list[float] | None:
        """Per-band gains for EQ_FREQS if this is a custom curve, else None."""
        if not self.is_custom:
            return None
        by_freq = {b.freq: b.gain_db for b in self.bands}
        return [by_freq.get(f, 0.0) for f in EQ_FREQS]


def _i16(v: int) -> bytes:
    return int(v).to_bytes(2, "little", signed=True)


def _u16(v: int) -> bytes:
    return int(v).to_bytes(2, "little", signed=False)


def build_eq_table(bands: list[EqBand], master_gain_db: float = 0.0) -> bytes:
    if len(bands) > EQ_SLOTS:
        raise ProtocolError("too many EQ bands")
    out = bytearray(_i16(round(master_gain_db * 100)))
    for b in bands:
        if not 20 <= b.freq <= 20000:
            raise ProtocolError("EQ band frequency out of range")
        out += _u16(b.freq) + _i16(round(b.gain_db * 100)) + _u16(round(b.q * 100)) + bytes([b.kind])
    out += _UNUSED_SLOT * (EQ_SLOTS - len(bands))
    return bytes(out)


def parse_eq_table(table: bytes) -> tuple[float, tuple[EqBand, ...]]:
    if len(table) < 2:
        raise ProtocolError("EQ table too short")
    master = int.from_bytes(table[0:2], "little", signed=True) / 100
    bands = []
    for i in range(2, len(table) - 6, 7):
        freq = int.from_bytes(table[i : i + 2], "little")
        gain = int.from_bytes(table[i + 2 : i + 4], "little", signed=True) / 100
        q = int.from_bytes(table[i + 4 : i + 6], "little") / 100
        if freq == 0:
            continue
        bands.append(EqBand(freq, gain, q, table[i + 6]))
    return master, tuple(bands)


def build_eq_raw(preset_id: int, table: bytes) -> bytes:
    if len(table) != EQ_TABLE_LEN:
        raise ProtocolError("EQ table must be 142 bytes")
    return command(Op.EQ, bytes([preset_id]) + table)


def build_eq_custom(gains_db: list[float]) -> bytes:
    if len(gains_db) != len(EQ_FREQS):
        raise ProtocolError("custom EQ needs 10 band gains")
    bands = []
    for freq, gain in zip(EQ_FREQS, gains_db):
        if not -EQ_GAIN_LIMIT_DB <= gain <= EQ_GAIN_LIMIT_DB:
            raise ProtocolError("custom EQ gain must be within ±8 dB")
        bands.append(EqBand(freq, float(gain), 1.0, 0))
    return build_eq_raw(CUSTOM_EQ_ID, build_eq_table(bands))


def parse_eq(params: bytes) -> EqReading | None:
    if len(params) < 3:
        return None
    master, bands = parse_eq_table(params[1:])
    return EqReading(params[0], master, bands)


# --------------------------------------------------------------------------
# Touch controls (raw characteristic 000d, 2-byte [slot, function] writes)
# --------------------------------------------------------------------------

# slot -> (side, tap count)
TOUCH_SLOTS = {1: ("left", 1), 2: ("right", 1), 3: ("left", 2), 4: ("right", 2), 5: ("left", 3), 6: ("right", 3)}
TOUCH_FUNCTIONS = {
    0x00: "none",
    0x01: "play_pause",
    0x02: "previous",
    0x03: "next",
    0x04: "voice_assistant",
    0x05: "volume_up",
    0x06: "volume_down",
    0x07: "game_mode",
    0x0B: "anc",
}
TOUCH_FUNCTION_IDS = {name: code for code, name in TOUCH_FUNCTIONS.items()}


def parse_touch_map(data: bytes) -> dict[int, int]:
    """Returns {slot: function_code} for every non-padding pair."""
    mapping: dict[int, int] = {}
    for i in range(0, len(data) - 1, 2):
        slot, func = data[i], data[i + 1]
        if slot:
            mapping[slot] = func
    return mapping


def build_touch_write(slot: int, function: str) -> bytes:
    if slot not in TOUCH_SLOTS:
        raise ProtocolError(f"unknown touch slot: {slot}")
    if function not in TOUCH_FUNCTION_IDS:
        raise ProtocolError(f"unknown touch function: {function!r}")
    return bytes([slot, TOUCH_FUNCTION_IDS[function]])


# --------------------------------------------------------------------------
# Wear detection, prompt volume, power timers, name
# --------------------------------------------------------------------------


def build_wear(enabled: bool, anc_on_wear: bool) -> bytes:
    return command(Op.WEAR, [int(enabled), 0x01, int(anc_on_wear)])


def parse_wear(params: bytes) -> tuple[bool, bool] | None:
    return (params[0] != 0, params[2] != 0) if len(params) >= 3 else None


TONE_LEVELS = (4, 6, 8, 10)  # low / medium / high / max


def build_tone_volume(level: int) -> bytes:
    if level not in TONE_LEVELS:
        raise ProtocolError("prompt volume level must be one of 4/6/8/10")
    return command(Op.TONE_VOLUME, [level, 0x00])


def parse_tone_volume(params: bytes) -> int | None:
    return params[0] if params else None


TIMER_OFF = 0xFFFF
AUTO_OFF_MAX_MIN = 1440
DISCONNECT_OFF_PRESETS = (5, 10, 30, 60)


def build_auto_off(minutes: int | None) -> bytes:
    """Scheduled power-off; None disables it."""
    if minutes is None:
        value = TIMER_OFF
    elif 1 <= minutes <= AUTO_OFF_MAX_MIN:
        value = minutes
    else:
        raise ProtocolError(f"auto power-off must be 1..{AUTO_OFF_MAX_MIN} minutes")
    return command(Op.AUTO_OFF, _u16(value) + b"\x00\x00")


def build_disconnect_off(minutes: int | None) -> bytes:
    """Power-off after the link is lost; None means never."""
    if minutes is None:
        value = TIMER_OFF
    elif minutes in DISCONNECT_OFF_PRESETS:
        value = minutes
    else:
        raise ProtocolError("disconnect power-off must be 5/10/30/60 minutes or never")
    return command(Op.DISCONNECT_OFF, _u16(value))


def parse_timer(params: bytes) -> int | None:
    """Minutes, or None when disabled (0xFFFF)."""
    if len(params) < 2:
        return None
    value = int.from_bytes(params[0:2], "little")
    return None if value == TIMER_OFF else value


NAME_MAX_BYTES = 31


def build_rename(name: str) -> bytes:
    cleaned = "".join(ch for ch in name.strip() if ch.isprintable())
    encoded = cleaned.encode("utf-8")
    if not encoded:
        raise ProtocolError("device name must not be empty")
    if len(encoded) > NAME_MAX_BYTES:
        raise ProtocolError(f"device name must be at most {NAME_MAX_BYTES} UTF-8 bytes")
    return command(Op.NAME, encoded)


def parse_name(params: bytes) -> str:
    return params.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


# --------------------------------------------------------------------------
# Plain characteristics: battery, firmware version, advertisement
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Battery:
    left: int | None = None
    right: int | None = None
    case: int | None = None
    left_charging: bool = False
    right_charging: bool = False
    case_charging: bool = False

    def to_dict(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "case": self.case,
            "leftCharging": self.left_charging,
            "rightCharging": self.right_charging,
            "caseCharging": self.case_charging,
        }


def _battery_byte(b: int) -> tuple[int | None, bool]:
    level = b & 0x7F
    # 0 means "not reported" (the case always reads 0 on HT08; a bud that is
    # switched off or out of range also reports 0).
    return (min(level, 100) if level else None), bool(b & 0x80)


def parse_battery(data: bytes) -> Battery | None:
    if len(data) < 3:
        return None
    (left, lc), (right, rc), (case, cc) = (_battery_byte(b) for b in data[:3])
    return Battery(left, right, case, lc, rc, cc)


def parse_version(data: bytes) -> tuple[str, str | None] | None:
    if len(data) < 3:
        return None
    left = ".".join(str(b) for b in data[0:3])
    right = ".".join(str(b) for b in data[3:6]) if len(data) >= 6 else None
    return left, right


@dataclass(frozen=True)
class Advert:
    vendor_id: int
    battery: Battery
    classic_address: str | None


def parse_advert(payload: bytes) -> Advert | None:
    """Manufacturer data for company 0x521C (company id already stripped)."""
    if len(payload) < 8:
        return None
    vendor_id = (payload[0] << 8) | payload[1]
    battery = parse_battery(payload[5:8]) or Battery()
    classic = None
    if len(payload) >= 17:
        classic = ":".join(f"{payload[i]:02X}" for i in (12, 11, 13, 16, 15, 14))
    return Advert(vendor_id, battery, classic)
