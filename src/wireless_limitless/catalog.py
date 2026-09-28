"""Per-model capabilities and the built-in EQ preset curves.

The preset band lists reproduce, byte for byte, the 142-byte tables the
official QCY app sends for the HT08 family (captured by allansomensi/qcyx,
MIT licensed; see THIRD_PARTY_NOTICES.md). Band tuple: (Hz, dB, Q, kind),
kind 4 = the 30 Hz rumble filter every preset starts with, 0 = peaking.
"""

from __future__ import annotations

from dataclasses import dataclass

from .protocol import EQ_FREQS, EQ_GAIN_LIMIT_DB, EqBand, build_eq_table


@dataclass(frozen=True)
class EqPreset:
    id: int
    key: str
    label: str
    bands: tuple[EqBand, ...]

    def table(self) -> bytes:
        return build_eq_table(list(self.bands))


def _bands(*spec: tuple[int, float, float, int]) -> tuple[EqBand, ...]:
    return tuple(EqBand(f, g, q, k) for f, g, q, k in spec)


_DEFAULT_CURVE = _bands(
    (30, 0, 0.70, 4), (220, -8, 1.00, 0), (900, -2, 1.50, 0),
    (2800, 4, 1.00, 0), (12000, 3, 0.80, 0), (5300, -3, 2.00, 0),
)

HT08_EQ_PRESETS: tuple[EqPreset, ...] = (
    EqPreset(0x0A, "spatial", "공간 음향", _DEFAULT_CURVE),
    EqPreset(0x01, "default", "기본", _DEFAULT_CURVE),
    EqPreset(0x02, "pop", "팝", _bands(
        (30, 0, 0.40, 4), (220, -8, 1.00, 0), (2800, 3.5, 1.00, 0),
        (12000, 3, 0.80, 0), (5300, -3, 2.00, 0), (60, -3, 0.50, 0),
    )),
    EqPreset(0x03, "bass", "헤비 베이스", _bands(
        (30, 0, 0.70, 4), (220, -8, 1.00, 0), (2800, 1, 1.00, 0),
        (12000, 8, 0.80, 0), (5300, -5, 2.00, 0), (60, 5, 0.60, 0),
    )),
    EqPreset(0x04, "rock", "록", _bands(
        (30, 0, 0.70, 4), (220, -10, 1.00, 0), (2800, 2, 1.00, 0),
        (12000, 3, 0.80, 0), (5300, -1, 2.00, 0), (60, 3, 0.60, 0),
    )),
    EqPreset(0x05, "soft", "소프트", _bands(
        (30, 0, 0.40, 4), (220, -8, 1.00, 0), (2800, 1, 1.00, 0),
        (12000, 1, 0.80, 0), (5300, -3, 2.00, 0), (60, -2, 0.50, 0),
    )),
    EqPreset(0x06, "classic", "클래식", _bands(
        (30, 0, 0.70, 4), (220, -5, 1.00, 0), (2800, 1, 1.00, 0),
        (12000, 1, 0.80, 0), (5300, -5, 2.00, 0), (60, 2, 0.60, 0),
    )),
)


@dataclass(frozen=True)
class Model:
    vendor_id: int
    name: str
    eq_presets: tuple[EqPreset, ...]

    def preset_by_id(self, preset_id: int) -> EqPreset | None:
        return next((p for p in self.eq_presets if p.id == preset_id), None)

    def preset_by_key(self, key: str) -> EqPreset | None:
        return next((p for p in self.eq_presets if p.key == key), None)

    def capabilities(self) -> dict:
        """Static description the UI renders from (labels, ranges, presets)."""
        return {
            "vendorId": self.vendor_id,
            "model": self.name,
            "eqPresets": [
                {"key": p.key, "label": p.label, "bands": [[b.freq, b.gain_db, b.q, b.kind] for b in p.bands]}
                for p in self.eq_presets
            ],
            "eqFreqs": list(EQ_FREQS),
            "eqGainLimit": EQ_GAIN_LIMIT_DB,
        }


# The MeloBuds Pro and the Pro Plus share the HT08 firmware family and the
# identical control-panel definition on QCY's product server.
MODELS: dict[int, Model] = {
    19790: Model(19790, "QCY HT08 MeloBuds Pro Plus", HT08_EQ_PRESETS),
    19786: Model(19786, "QCY MeloBuds Pro", HT08_EQ_PRESETS),
}


def model_for(vendor_id: int) -> Model | None:
    return MODELS.get(vendor_id)
