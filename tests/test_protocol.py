"""Protocol tests pinned to bytes captured from a real HT08 MeloBuds Pro Plus
(firmware 2.0.7). Device identifiers (MAC addresses) are replaced with fakes."""

import pytest

from wireless_limitless import catalog, protocol as p
from wireless_limitless.protocol import AncSetting, Op, ProtocolError

H = bytes.fromhex

# Settings blob read from the notify characteristic. Note "2c 03" followed by
# FOUR parameter bytes: a firmware quirk the tolerant parser must absorb.
STATE_BLOB = H(
    "ff 30 2c 03 01 01 01 01 08 03 11 11 0f 09 01 02 17 03 01 05 00 10 01 00"
    " 16 01 32 04 01 02 23 01 01 24 01 00 1f 02 05 00 1d 02 08 0f 19 04 57 51 30 30"
)

# 0xFE 0x22 reply while the "Default" preset (0x01) was active: preset id,
# master gain, six active slots, then zero padding up to 142 table bytes.
EQ_DEFAULT_READBACK = H(
    "01 00 00"
    " 1e 00 00 00 46 00 00  dc 00 e0 fc 64 00 00  84 03 38 ff 96 00 00"
    " f0 0a 90 01 64 00 00  e0 2e 2c 01 50 00 00  b4 14 d4 fe c8 00 00"
) + bytes(98)

# Tables the official app sends for two presets (from qcyx wire captures).
UNUSED_SLOT = H("00 00 00 00 00 00 ff")
QCYX_DEFAULT_TABLE = H(
    "00 00"
    " 1e 00 00 00 46 00 04  dc 00 e0 fc 64 00 00  84 03 38 ff 96 00 00"
    " f0 0a 90 01 64 00 00  e0 2e 2c 01 50 00 00  b4 14 d4 fe c8 00 00"
) + UNUSED_SLOT * 14
QCYX_BASS_TABLE = H(
    "00 00"
    " 1e 00 00 00 46 00 04  dc 00 e0 fc 64 00 00  f0 0a 64 00 64 00 00"
    " e0 2e 20 03 50 00 00  b4 14 0c fe c8 00 00  3c 00 f4 01 3c 00 00"
) + UNUSED_SLOT * 14


# --- framing -----------------------------------------------------------------

def test_command_framing():
    assert p.command(Op.ANC, [2, 0, 0]) == H("ff 05 17 03 02 00 00")
    assert p.build_query(Op.EQ) == H("ff03fe0122")
    assert p.build_reset_default() == H("ff020100")
    assert p.build_factory_reset() == H("ff020300")


def test_parse_frame_multi_block():
    blocks = p.parse_frame(H("ff 08 17 03 01 05 00 16 01 32"))
    assert blocks == [p.Block(0x17, H("010500")), p.Block(0x16, H("32"))]


@pytest.mark.parametrize("bad", [b"", H("ff"), H("fe03fe0122"), H("ff04fe0122"), H("ff03fe05")])
def test_parse_frame_rejects_malformed(bad):
    with pytest.raises(ProtocolError):
        p.parse_frame(bad)


def test_state_blob_quirk_is_absorbed():
    blocks = {b.op: b.params for b in p.parse_state_blob(STATE_BLOB)}
    assert blocks[Op.WEAR] == H("01010101")
    assert p.parse_anc(blocks[Op.ANC]) == AncSetting("anc", scene="adaptive")
    assert p.parse_balance(blocks[Op.BALANCE]) == 50
    assert p.parse_toggle(blocks[Op.GAME_MODE]) is False
    assert p.parse_toggle(blocks[Op.LDAC]) is True
    assert p.parse_toggle(blocks[Op.MULTIPOINT]) is False
    assert p.parse_toggle(blocks[Op.SLEEP_MODE]) is False
    assert p.parse_timer(blocks[Op.DISCONNECT_OFF]) == 5
    assert p.parse_tone_volume(blocks[Op.TONE_VOLUME]) == 8


# Same blob while ANC was "normal": here the misaligned 3-byte reading of 0x2C
# also walks cleanly through opcodes 0x01/0x03, so preference order matters.
STATE_BLOB_NORMAL = H(
    "ff 30 2c 03 01 01 01 01 08 03 11 11 0f 09 01 01 17 03 02 00 00 10 01 00"
    " 16 01 32 04 01 02 23 01 01 24 01 00 1f 02 05 00 1d 02 08 0f 19 04 57 51 30 30"
)


def test_state_blob_prefers_quirk_alignment():
    blocks = p.parse_state_blob(STATE_BLOB_NORMAL)
    ops = [b.op for b in blocks]
    assert Op.RESET_DEFAULT not in ops and Op.FACTORY_RESET not in ops
    by_op = {b.op: b.params for b in blocks}
    assert p.parse_anc(by_op[Op.ANC]) == AncSetting("normal")
    assert p.parse_toggle(by_op[Op.GAME_MODE]) is True
    assert p.parse_wear(by_op[Op.WEAR]) == (True, True)


def test_state_blob_accepts_correct_length_firmware():
    fixed = H("ff 0e 2c 04 00 01 01 01 09 01 02 17 03 03 02 00")
    by_op = {b.op: b.params for b in p.parse_state_blob(fixed)}
    assert p.parse_wear(by_op[Op.WEAR]) == (False, True)
    assert p.parse_anc(by_op[Op.ANC]) == AncSetting("transparency", vocal=True)


def test_state_blob_garbage_returns_empty():
    assert p.parse_state_blob(H("ff0499990000")) == []
    assert p.parse_state_blob(b"\x00\x01") == []


# --- noise control -----------------------------------------------------------

@pytest.mark.parametrize(
    "setting,triplet",
    [
        (AncSetting("normal"), (2, 0, 0)),
        (AncSetting("transparency", vocal=True), (3, 2, 0)),
        (AncSetting("transparency", level=4), (3, 1, 4)),
        (AncSetting("anc", scene="adaptive"), (1, 5, 0)),
        (AncSetting("anc", scene="indoor", level=1), (1, 1, 0)),
        (AncSetting("anc", scene="commute", level=2), (1, 2, 1)),
        (AncSetting("anc", scene="noisy", level=3), (1, 3, 2)),
        (AncSetting("anc", scene="wind"), (1, 4, 0)),
    ],
)
def test_anc_round_trip(setting, triplet):
    assert setting.triplet() == triplet
    assert p.anc_from_triplet(*triplet) == setting
    assert p.build_anc(setting) == p.command(Op.ANC, list(triplet))


def test_anc_official_app_remap_of_ambient_zero():
    assert p.anc_from_triplet(3, 1, 0) == AncSetting("transparency", vocal=True)


@pytest.mark.parametrize(
    "bad",
    [
        AncSetting("anc", scene="indoor"),
        AncSetting("anc", scene="indoor", level=4),
        AncSetting("anc", scene="space"),
        AncSetting("transparency", level=7),
        AncSetting("off"),
    ],
)
def test_anc_rejects_invalid(bad):
    with pytest.raises(ProtocolError):
        bad.triplet()


def test_anc_unknown_triplet_is_none():
    assert p.anc_from_triplet(1, 1, 9) is None
    assert p.anc_from_triplet(7, 0, 0) is None


# --- equalizer ---------------------------------------------------------------

def test_presets_reproduce_official_app_tables():
    model = catalog.model_for(19790)
    assert model.preset_by_key("default").table() == QCYX_DEFAULT_TABLE
    assert model.preset_by_key("bass").table() == QCYX_BASS_TABLE
    for preset in model.eq_presets:
        frame = p.build_eq_raw(preset.id, preset.table())
        assert len(frame) == 147 and frame[:4] == H("ff91228f")


def test_parse_device_eq_readback():
    reading = p.parse_eq(EQ_DEFAULT_READBACK)
    assert reading.preset_id == 0x01 and not reading.is_custom
    assert [(b.freq, b.gain_db, b.q) for b in reading.bands] == [
        (30, 0, 0.7), (220, -8, 1.0), (900, -2, 1.5), (2800, 4, 1.0), (12000, 3, 0.8), (5300, -3, 2.0)
    ]


def test_custom_eq_round_trip():
    gains = [3, 2, 0, 0, -2, -2, 0, 1, 2, -8]
    frame = p.build_eq_custom(gains)
    assert len(frame) == 147
    reading = p.parse_eq(p.parse_frame(frame)[0].params)
    assert reading.is_custom
    assert reading.custom_gains() == gains
    assert all(b.q == 1.0 and b.kind == 0 for b in reading.bands)


@pytest.mark.parametrize("gains", [[0] * 9, [9] + [0] * 9, [0] * 9 + [-8.5]])
def test_custom_eq_validation(gains):
    with pytest.raises(ProtocolError):
        p.build_eq_custom(gains)


# --- touch, wear, timers, name ----------------------------------------------

def test_touch_map_parse_and_write():
    mapping = p.parse_touch_map(H("0100020003010401050406030700080000000000"))
    assert mapping == {1: 0, 2: 0, 3: 1, 4: 1, 5: 4, 6: 3, 7: 0, 8: 0}
    assert p.build_touch_write(6, "anc") == H("060b")
    assert p.build_touch_write(1, "game_mode") == H("0107")
    with pytest.raises(ProtocolError):
        p.build_touch_write(7, "anc")
    with pytest.raises(ProtocolError):
        p.build_touch_write(1, "self_destruct")


def test_wear_detection():
    assert p.build_wear(True, False) == H("ff052c03010100")
    assert p.parse_wear(H("010101ee")) == (True, True)
    assert p.parse_wear(H("000100")) == (False, False)


def test_toggles():
    assert p.build_toggle(Op.GAME_MODE, True) == H("ff03090101")
    assert p.build_toggle(Op.LDAC, False) == H("ff03230102")
    assert p.parse_toggle(H("02")) is False and p.parse_toggle(H("01")) is True
    with pytest.raises(ProtocolError):
        p.build_toggle(Op.ANC, True)


def test_timers():
    assert p.build_auto_off(None) == H("ff061404ffff0000")
    assert p.build_auto_off(183) == H("ff061404b7000000")
    assert p.build_disconnect_off(None) == H("ff041f02ffff")
    assert p.build_disconnect_off(10) == H("ff041f020a00")
    assert p.parse_timer(H("ffff0000")) is None and p.parse_timer(H("0500")) == 5
    for bad in (0, 1441):
        with pytest.raises(ProtocolError):
            p.build_auto_off(bad)
    with pytest.raises(ProtocolError):
        p.build_disconnect_off(15)


def test_tone_volume_and_balance():
    assert p.build_tone_volume(8) == H("ff041d020800")
    assert p.build_balance(50) == H("ff03160132")
    with pytest.raises(ProtocolError):
        p.build_tone_volume(7)
    with pytest.raises(ProtocolError):
        p.build_balance(101)


def test_rename():
    assert p.build_rename("  My Buds\n") == p.command(Op.NAME, b"My Buds")
    assert p.parse_name(bytes(32)) == ""
    assert p.parse_name(b"QCY MeloBuds Pro" + bytes(16)) == "QCY MeloBuds Pro"
    with pytest.raises(ProtocolError):
        p.build_rename("   ")
    with pytest.raises(ProtocolError):
        p.build_rename("가" * 11)  # 33 UTF-8 bytes


# --- plain characteristics ----------------------------------------------------

def test_battery_version_advert():
    bat = p.parse_battery(H("5fdf00"))
    assert (bat.left, bat.right, bat.case) == (95, 95, None)
    assert bat.right_charging and not bat.left_charging
    assert p.parse_version(H("020007020007")) == ("2.0.7", "2.0.7")
    # Fake addresses: classic 11:22:33:44:55:66 in the scrambled byte order.
    advert = p.parse_advert(H("4d4e38006e5f5f00000000" "22113366554401") + bytes(7))
    assert advert.vendor_id == 19790
    assert advert.battery.left == 95 and advert.battery.case is None
    assert advert.classic_address == "11:22:33:44:55:66"
    assert catalog.model_for(advert.vendor_id).name == "QCY HT08 MeloBuds Pro Plus"
