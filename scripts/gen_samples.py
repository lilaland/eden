"""
gen_samples.py — Synthesize missing drum/instrument samples for Eden.

Run from the repo root:
    python scripts/gen_samples.py

Skips any file that already exists in samples/.
All samples are mono float32 WAV at 44100 Hz.
"""

from __future__ import annotations
import os
import numpy as np
import soundfile as sf

SR = 44100
OUT_DIR = "samples"


def _write(name: str, signal: np.ndarray) -> None:
    path = os.path.join(OUT_DIR, f"{name}.wav")
    if os.path.exists(path):
        print(f"  skip  {name}.wav (exists)")
        return
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.85
    sf.write(path, signal.astype(np.float32), SR)
    print(f"  wrote {name}.wav")


def _t(dur: float) -> np.ndarray:
    return np.linspace(0, dur, int(dur * SR), endpoint=False)


# ── Synthesis functions ───────────────────────────────────────────────────────


def clap() -> np.ndarray:
    """Multi-burst filtered noise snap."""
    rng = np.random.default_rng(42)
    t = _t(0.30)
    noise = rng.standard_normal(len(t))
    # 3 staggered burst peaks ~12 ms apart
    env = sum(np.exp(-900 * (t - d) ** 2) for d in [0.0, 0.012, 0.024])
    env *= np.exp(-11 * t)
    return noise * env


def ride() -> np.ndarray:
    """Inharmonic metallic partials with shimmer noise, medium sustain."""
    rng = np.random.default_rng(1)
    t = _t(1.1)
    partials = [620, 1180, 1850, 2500, 3400, 4700]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.55 ** i) for i, f in enumerate(partials))
    sig += rng.standard_normal(len(t)) * 0.12
    return sig * np.exp(-3.2 * t)


def crash() -> np.ndarray:
    """Noisy cymbal with broad spectrum and long decay."""
    rng = np.random.default_rng(2)
    t = _t(2.0)
    partials = [380, 760, 1300, 2200, 4000, 6500, 9000]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.5 ** i) for i, f in enumerate(partials))
    sig += rng.standard_normal(len(t)) * 0.45
    return sig * np.exp(-1.6 * t)


def _tom(fund: float, decay: float) -> np.ndarray:
    """Generic tom: pitch-swept sine + click attack."""
    rng = np.random.default_rng(int(fund))
    t = _t(0.55)
    # pitch sweeps from 2× fund down toward fund
    pitch = fund * (1.0 + np.exp(-18 * t))
    sig = np.sin(2 * np.pi * np.cumsum(pitch) / SR)
    # click component
    n_click = int(0.007 * SR)
    click_noise = rng.standard_normal(len(t))
    click_noise[n_click:] *= 0.04
    click_noise[:n_click] *= np.exp(-600 * t[:n_click])
    return (sig * 0.85 + click_noise * 0.5) * np.exp(-decay * t)


def tom_hi() -> np.ndarray:
    return _tom(300, 9)


def tom_mid() -> np.ndarray:
    return _tom(160, 8)


def tom_lo() -> np.ndarray:
    return _tom(85, 7)


def perc1() -> np.ndarray:
    """Short bright cowbell-ish blip."""
    rng = np.random.default_rng(10)
    t = _t(0.18)
    sig = (np.sin(2 * np.pi * 810 * t) * 0.7
           + np.sin(2 * np.pi * 1080 * t) * 0.3)
    sig += rng.standard_normal(len(t)) * 0.25
    return sig * np.exp(-32 * t)


def perc2() -> np.ndarray:
    """Mid-range wooden rimshot blip."""
    rng = np.random.default_rng(11)
    t = _t(0.22)
    sig = (np.sin(2 * np.pi * 420 * t) * 0.75
           + np.sin(2 * np.pi * 630 * t) * 0.25)
    sig += rng.standard_normal(len(t)) * 0.30
    return sig * np.exp(-22 * t)


def bass() -> np.ndarray:
    """Sub bass — pitch sweeps from ~160 Hz down to ~55 Hz."""
    t = _t(0.65)
    pitch = 55 + 105 * np.exp(-22 * t)
    sig = np.sin(2 * np.pi * np.cumsum(pitch) / SR)
    # gentle attack
    atk = int(0.003 * SR)
    env = np.exp(-4.5 * t)
    env[:atk] *= np.linspace(0, 1, atk)
    return sig * env


def lead() -> np.ndarray:
    """Bright sawtooth-ish tone at 440 Hz with harmonics."""
    t = _t(0.45)
    sig = (np.sin(2 * np.pi * 440 * t) * 0.55
           + np.sin(2 * np.pi * 880 * t) * 0.28
           + np.sin(2 * np.pi * 1320 * t) * 0.12
           + np.sin(2 * np.pi * 1760 * t) * 0.05)
    atk = int(0.008 * SR)
    env = np.exp(-5.5 * t)
    env[:atk] *= np.linspace(0, 1, atk)
    return sig * env


def pad() -> np.ndarray:
    """Soft chord pad at 220/330/440 Hz with slow attack."""
    t = _t(0.9)
    sig = (np.sin(2 * np.pi * 220 * t) * 0.50
           + np.sin(2 * np.pi * 277 * t) * 0.30
           + np.sin(2 * np.pi * 330 * t) * 0.20)
    atk = int(0.06 * SR)
    env = np.exp(-1.8 * t)
    env[:atk] *= np.linspace(0, 1, atk)
    return sig * env


def fx1() -> np.ndarray:
    """Downward laser sweep."""
    rng = np.random.default_rng(20)
    t = _t(0.40)
    pitch = np.linspace(2400, 120, len(t)) + rng.standard_normal(len(t)) * 30
    sig = np.sin(2 * np.pi * np.cumsum(pitch) / SR)
    return sig * np.exp(-3.5 * t)


def fx2() -> np.ndarray:
    """Upward zap."""
    rng = np.random.default_rng(21)
    t = _t(0.30)
    pitch = np.linspace(150, 3000, len(t)) + rng.standard_normal(len(t)) * 40
    sig = np.sin(2 * np.pi * np.cumsum(pitch) / SR)
    noise = rng.standard_normal(len(t)) * 0.15
    return (sig + noise) * np.exp(-5 * t)


# ── Main ──────────────────────────────────────────────────────────────────────


GENERATORS = {
    "clap":     clap,
    "ride":     ride,
    "crash":    crash,
    "tom_hi":   tom_hi,
    "tom_mid":  tom_mid,
    "tom_lo":   tom_lo,
    "perc1":    perc1,
    "perc2":    perc2,
    "bass":     bass,
    "lead":     lead,
    "pad":      pad,
    "fx1":      fx1,
    "fx2":      fx2,
}


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Generating samples into ./{OUT_DIR}/")
    for name, fn in GENERATORS.items():
        _write(name, fn())
    print("Done.")
