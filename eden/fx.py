"""fx.py — pedalboard-backed FX processing for Eden."""
from __future__ import annotations

import threading

import numpy as np

try:
    from pedalboard import (
        Pedalboard, LowShelfFilter, HighShelfFilter, PeakFilter,
        Delay, Chorus, Reverb, Distortion, Phaser,
        HighpassFilter, LowpassFilter, Bitcrush,
        Compressor, NoiseGate,
    )
    _PEDALBOARD = True
except ImportError:
    _PEDALBOARD = False

_DEFAULT_PAGE1 = (0.5, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0)
_DEFAULT_PAGE2 = (0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0)


def _chain_is_bypass(chain) -> bool:
    return chain.page1 == _DEFAULT_PAGE1 and chain.page2 == _DEFAULT_PAGE2


FX_LABELS = [
    ("LOW EQ", "MID EQ", "HI EQ", "DELAY", "CHORUS", "REVERB", "DIST", "PHASE"),
    ("HPF", "LPF", "CRUSH", "PITCH", "COMP", "TAPE", "GATE", "RSAMP"),
]


def fmt_fx_val(page: int, idx: int, val: float) -> str:
    name = FX_LABELS[page][idx]
    if name in ("LOW EQ", "MID EQ", "HI EQ"):
        db = round((val - 0.5) * 36)
        return "0dB" if db == 0 else f"{db:+d}dB"
    if name == "PITCH":
        st = round((val - 0.5) * 24)
        return "0st" if st == 0 else f"{st:+d}st"
    if name == "HPF":
        hz = int(30 * (2000 / 30) ** val)
        return f"{hz}Hz" if hz < 1000 else f"{hz // 1000}k"
    if name == "LPF":
        hz = int(18000 * max(1e-6, (150 / 18000)) ** val)
        return f"{hz}Hz" if hz < 1000 else f"{hz // 1000}k"
    if name == "CRUSH":
        return f"{max(1, int(1 + (1 - val) * 23))}bit"
    if name == "RSAMP":
        if val < 0.01:
            return "OFF"
        sr = int(44100 * max(1e-9, (1000 / 44100)) ** val)
        return f"{sr // 1000}k" if sr >= 1000 else f"{sr}Hz"
    return f"{val:.0%}"


class FXProcessor:
    """Thread-safe pedalboard FX chain. update_async from main thread, process from audio thread.

    PITCH (page2[3]) and RSAMP (page2[7]) are not in the live board — PitchShift uses a
    phase vocoder too slow for real-time callbacks, and Resample causes variable frame counts.
    Their UI slots display values but do not affect audio.
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        self._sr = sample_rate
        self._lock = threading.Lock()
        self._pending = None
        self._bypassed = True  # skip board until a non-default chain is applied

        if not _PEDALBOARD:
            self._board = None
            self._p1 = []
            self._p2 = []
            return

        self._p1 = [
            LowShelfFilter(cutoff_frequency_hz=300, gain_db=0),   # LOW EQ
            PeakFilter(cutoff_frequency_hz=1000, gain_db=0),      # MID EQ
            HighShelfFilter(cutoff_frequency_hz=3000, gain_db=0), # HI EQ
            Delay(delay_seconds=0.3, feedback=0.0, mix=0.0),      # DELAY
            Chorus(rate_hz=1.5, depth=0.25, mix=0.0),             # CHORUS
            Reverb(room_size=0.5, wet_level=0.0, dry_level=1.0),  # REVERB
            Distortion(drive_db=0.001),                            # DIST
            Phaser(rate_hz=1.5, depth=0.5, mix=0.0),              # PHASE
        ]
        self._p2 = [
            HighpassFilter(cutoff_frequency_hz=30),     # HPF   page2[0]
            LowpassFilter(cutoff_frequency_hz=18000),   # LPF   page2[1]
            Bitcrush(bit_depth=24),                     # CRUSH page2[2]
            # PITCH page2[3] — omitted (PitchShift too expensive for real-time)
            Compressor(threshold_db=0, ratio=1),        # COMP  page2[4]
            Distortion(drive_db=0.001),                 # TAPE  page2[5]
            NoiseGate(threshold_db=-100),               # GATE  page2[6]
            # RSAMP page2[7] — omitted (Resample causes variable frame counts)
        ]
        self._board = Pedalboard(self._p1 + self._p2)

    def update_async(self, chain) -> None:
        """Store pending FXChain; picked up on next process() call."""
        with self._lock:
            self._pending = chain

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply FX. Called from audio thread. audio is float32 (frames, 2)."""
        with self._lock:
            chain = self._pending
            self._pending = None
        if chain is not None and self._board is not None:
            self._apply(chain)
            self._bypassed = _chain_is_bypass(chain)
        if self._board is None or self._bypassed:
            return audio
        try:
            result = self._board(audio, self._sr, reset=False)
            if result.shape[0] != audio.shape[0]:
                return audio
            return result
        except Exception:
            return audio

    def _apply(self, chain) -> None:
        p1 = chain.page1
        self._p1[0].gain_db = (p1[0] - 0.5) * 36
        self._p1[1].gain_db = (p1[1] - 0.5) * 36
        self._p1[2].gain_db = (p1[2] - 0.5) * 36
        self._p1[3].mix = p1[3]
        self._p1[3].feedback = p1[3] * 0.5      # no buffer buildup when mix is 0
        self._p1[4].mix = p1[4]
        self._p1[5].wet_level = p1[5]
        self._p1[5].dry_level = 1.0 - p1[5]    # crossfade; additive would clip
        self._p1[6].drive_db = max(0.001, p1[6] * 40)
        self._p1[7].mix = p1[7]

        p2 = chain.page2
        hz = max(30, int(30 * (2000 / 30) ** p2[0]))
        self._p2[0].cutoff_frequency_hz = hz                            # HPF
        hz = max(150, int(18000 * max(1e-9, (150 / 18000)) ** p2[1]))
        self._p2[1].cutoff_frequency_hz = min(18000, hz)                # LPF
        self._p2[2].bit_depth = max(1.0, 1.0 + (1.0 - p2[2]) * 23.0)  # CRUSH
        # p2[3] PITCH — not in board
        self._p2[3].threshold_db = -60.0 * p2[4]                       # COMP threshold
        self._p2[3].ratio = max(1.001, 1.0 + p2[4] * 15.0)             # COMP ratio
        self._p2[4].drive_db = max(0.001, p2[5] * 20)                  # TAPE
        self._p2[5].threshold_db = -100.0 + p2[6] * 80.0               # GATE
        # p2[7] RSAMP — not in board
