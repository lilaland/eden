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


def eden_riser() -> np.ndarray:
    """Exponential frequency sweep 80 Hz → 2 kHz over 2.5 s with overtones."""
    t = _t(2.5)
    # log-sweep from 80 to 2000 Hz
    freq = 80.0 * np.exp(np.log(2000.0 / 80.0) * t / 2.5)
    phase = np.cumsum(freq) / SR
    sig = (np.sin(2 * np.pi * phase) * 0.6
           + np.sin(2 * np.pi * phase * 2) * 0.25
           + np.sin(2 * np.pi * phase * 3) * 0.10)
    # slow fade-in, hard cutoff at end
    env = np.linspace(0.0, 1.0, len(t)) ** 1.5
    return sig * env


def eden_vocal_hey() -> np.ndarray:
    """0.6 s formant burst: 3 sine partials (700 + 1220 + 2600 Hz), fast decay."""
    t = _t(0.6)
    sig = (np.sin(2 * np.pi * 700 * t) * 0.55
           + np.sin(2 * np.pi * 1220 * t) * 0.30
           + np.sin(2 * np.pi * 2600 * t) * 0.15)
    # sharp transient attack, fast exponential decay
    atk = int(0.004 * SR)
    env = np.exp(-6.5 * t)
    env[:atk] *= np.linspace(0, 1, atk)
    return sig * env


def eden_break_hit() -> np.ndarray:
    """Single punchy break hit: tight kick + snare layer."""
    rng = np.random.default_rng(55)
    t = _t(0.45)
    # Kick: pitch-swept sine 120→55 Hz
    pitch = 55 + 65 * np.exp(-25 * t)
    kick = np.sin(2 * np.pi * np.cumsum(pitch) / SR) * np.exp(-9 * t)
    # Snare: tone + broadband noise
    snare_t = _t(0.18)
    snare_tone = np.sin(2 * np.pi * 200 * snare_t) * 0.35
    snare_noise = rng.standard_normal(len(snare_t)) * 0.8
    snare = (snare_tone + snare_noise) * np.exp(-18 * snare_t)
    sig = np.zeros(len(t))
    sig += kick * 0.85
    sig[:len(snare)] += snare * 0.6
    # Click transient
    n_click = int(0.005 * SR)
    sig[:n_click] += rng.standard_normal(n_click) * np.exp(-500 * t[:n_click]) * 0.5
    return sig


def eden_piano_hit() -> np.ndarray:
    """Bright piano-style pluck: decaying harmonics."""
    t = _t(1.4)
    # Harmonic series with rapid amplitude decay
    freqs_amps = [(261.6, 0.50), (523.3, 0.28), (784.9, 0.14),
                  (1047, 0.06), (1308, 0.02)]
    sig = sum(a * np.sin(2 * np.pi * f * t) for f, a in freqs_amps)
    # Per-harmonic decay — higher harmonics die faster
    env = sum(a * np.exp(-(3 + i * 4) * t) * np.sin(2 * np.pi * f * t)
              for i, (f, a) in enumerate(freqs_amps))
    atk = int(0.002 * SR)
    env[:atk] *= np.linspace(0, 1, atk)
    # Use the per-harmonic envelope version for realistic decay
    sig = env
    return sig


def eden_vinyl() -> np.ndarray:
    """Vinyl texture: low broadband crackle + rumble."""
    rng = np.random.default_rng(77)
    t = _t(3.0)
    # Sub rumble (turntable motor)
    rumble = np.sin(2 * np.pi * 28 * t) * 0.08
    # Surface noise: filtered broadband
    noise = rng.standard_normal(len(t))
    # Crude low-pass: 3-point moving average, repeated
    for _ in range(6):
        noise = np.convolve(noise, [0.25, 0.5, 0.25], mode='same')
    # Random crackle bursts
    crackle = np.zeros(len(t))
    rng2 = np.random.default_rng(78)
    for _ in range(40):
        pos = rng2.integers(0, len(t) - 100)
        w = rng2.integers(20, 80)
        amp = rng2.uniform(0.3, 1.0)
        crackle[pos:pos + w] += rng2.standard_normal(w) * amp * np.exp(
            -np.arange(w) * 0.15)
    return rumble + noise * 0.3 + crackle * 0.4


def eden_rhodes() -> np.ndarray:
    """Rhodes-style electric piano note at C4 (261.63 Hz).

    FM-ish: a sine carrier plus a bell-like upper partial, with a short
    percussive 'tine' attack (bright noise burst + high partial) layered on
    top. Per-partial exponential decay so the tone darkens as it sustains —
    the classic mellow Rhodes character. Played pitched, so a single clean
    note near the default root (MIDI 60 = C4) sounds natural.
    """
    f0 = 261.63  # C4
    t = _t(2.5)
    # Carrier + harmonics with bell-like partials (slight inharmonicity)
    partials = [
        (1.00, 0.60, 3.2),   # fundamental, slow decay
        (2.00, 0.22, 4.5),   # octave
        (3.01, 0.12, 6.0),   # bell-ish 3rd partial (slightly sharp)
        (4.02, 0.06, 8.0),   # bright upper
        (6.05, 0.03, 11.0),  # shimmer
    ]
    sig = np.zeros(len(t))
    for mult, amp, dec in partials:
        sig += amp * np.sin(2 * np.pi * f0 * mult * t) * np.exp(-dec * t)
    # Tine attack — brief metallic 'bark' at note onset
    tine = (np.sin(2 * np.pi * f0 * 8.0 * t) * 0.10
            + np.sin(2 * np.pi * f0 * 5.0 * t) * 0.06)
    sig += tine * np.exp(-45 * t)
    # Soft attack to remove click
    atk = int(0.004 * SR)
    env = np.ones(len(t))
    env[:atk] = np.linspace(0, 1, atk)
    sig *= env
    # Gentle tail fade
    nfo = int(0.2 * SR)
    sig[-nfo:] *= np.linspace(1.0, 0.0, nfo)
    return sig


def eden_loop() -> np.ndarray:
    """2 s at 120 BPM loop: kick+snare+hats using additive synthesis."""
    rng = np.random.default_rng(99)
    dur = 2.0  # one 2-bar loop at 120 BPM
    n = int(dur * SR)
    sig = np.zeros(n)
    beat = SR / 2  # 120 BPM → 0.5 s per beat

    def _kick(offset: int) -> None:
        if offset >= n:
            return
        length = min(int(0.35 * SR), n - offset)
        t_k = np.arange(length) / SR
        p = 55 + 80 * np.exp(-20 * t_k)
        k = np.sin(2 * np.pi * np.cumsum(p) / SR) * np.exp(-8 * t_k)
        sig[offset:offset + length] += k * 0.9

    def _snare(offset: int) -> None:
        if offset >= n:
            return
        length = min(int(0.20 * SR), n - offset)
        t_s = np.arange(length) / SR
        tone = np.sin(2 * np.pi * 220 * t_s) * 0.4
        noise = rng.standard_normal(length) * 0.7
        env = np.exp(-14 * t_s)
        sig[offset:offset + length] += (tone + noise) * env * 0.7

    def _hat(offset: int, closed: bool = True) -> None:
        if offset >= n:
            return
        decay = 25 if closed else 7
        length = min(int(0.15 * SR), n - offset)
        t_h = np.arange(length) / SR
        noise = rng.standard_normal(length)
        sig[offset:offset + length] += noise * np.exp(-decay * t_h) * 0.35

    # Beats 1+3 = kick, beats 2+4 = snare
    for beat_idx in range(4):
        pos = int(beat_idx * beat)
        if beat_idx % 2 == 0:
            _kick(pos)
        else:
            _snare(pos)
        # 8th-note hats
        _hat(pos)
        _hat(pos + int(beat / 2))

    return sig


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
    "eden_riser":      eden_riser,
    "eden_vocal_hey":  eden_vocal_hey,
    "eden_break_hit":  eden_break_hit,
    "eden_piano_hit":  eden_piano_hit,
    "eden_vinyl":      eden_vinyl,
    "eden_rhodes":     eden_rhodes,
    "eden_loop":       eden_loop,
}


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Generating samples into ./{OUT_DIR}/")
    for name, fn in GENERATORS.items():
        _write(name, fn())
    print("Done.")
