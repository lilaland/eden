"""
generate_drums.py — Synthesize genre-specific drum samples for Eden.

Run from the repo root:
    python scripts/generate_drums.py

Generates WAV files (44100 Hz, mono float32) with naming convention:
    {drum_type}_{genre}.wav

Drum types: kick, snare, clhat, ophat, clap, tom_hi, tom_lo, rim, cowbell, cymbal,
            shaker, tambourn, conga_hi, conga_lo, bongo_hi, bongo_lo,
            cabasa, maracas, woodblk, agogo, crash, ride
Genres: techno, house, disco, jazz, rnb, afro, latin, funk, rock

Skips any file that already exists in samples/.
"""

from __future__ import annotations
import os
import numpy as np
import soundfile as sf

SR = 44100
OUT_DIR = "/Users/lilaland/Documents/eden/samples"


def _write(name: str, signal: np.ndarray) -> None:
    path = os.path.join(OUT_DIR, f"{name}.wav")
    if os.path.exists(path):
        print(f"  skip  {name}.wav (exists)")
        return
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak * 0.85
    sf.write(path, signal.astype(np.float32), SR, subtype='FLOAT')
    print(f"  wrote {name}.wav")


def _t(dur: float) -> np.ndarray:
    return np.linspace(0, dur, int(dur * SR), endpoint=False)


def _env_exp(t: np.ndarray, attack: float, decay: float) -> np.ndarray:
    """Exponential decay envelope with optional attack ramp."""
    env = np.exp(-decay * t)
    atk_samples = int(attack * SR)
    if atk_samples > 0:
        atk_samples = min(atk_samples, len(t))
        env[:atk_samples] *= np.linspace(0, 1, atk_samples)
    return env


def _bandpass_noise(t: np.ndarray, center: float, bw: float, rng: np.random.Generator) -> np.ndarray:
    """Simple bandpass filtered noise via sum of sinusoids (no scipy needed)."""
    noise = rng.standard_normal(len(t))
    # Approximate bandpass: modulate noise with a carrier at center freq
    # Use a narrow-band approach: cosine-modulated noise
    carrier = np.cos(2 * np.pi * center * t)
    # Low-pass the noise at bw/2 by simple running-average approximation
    # For musical purposes, sinusoidal interference pattern is sufficient
    # More accurate: use scipy if available
    try:
        from scipy.signal import butter, sosfilt
        nyq = SR / 2
        low = max(0.001, (center - bw / 2) / nyq)
        high = min(0.999, (center + bw / 2) / nyq)
        if low >= high:
            low = max(0.001, high - 0.01)
        sos = butter(2, [low, high], btype='band', output='sos')
        return sosfilt(sos, noise)
    except ImportError:
        # Fallback: modulate noise around carrier
        return noise * carrier * 2.0


def _highpass_noise(t: np.ndarray, cutoff: float, rng: np.random.Generator) -> np.ndarray:
    """High-pass filtered noise."""
    noise = rng.standard_normal(len(t))
    try:
        from scipy.signal import butter, sosfilt
        nyq = SR / 2
        sos = butter(2, min(0.999, cutoff / nyq), btype='high', output='sos')
        return sosfilt(sos, noise)
    except ImportError:
        # Rough highpass: subtract a smoothed version
        window = max(1, int(SR / cutoff / 4))
        smoothed = np.convolve(noise, np.ones(window) / window, mode='same')
        return noise - smoothed


def _lowpass_noise(t: np.ndarray, cutoff: float, rng: np.random.Generator) -> np.ndarray:
    """Low-pass filtered noise."""
    noise = rng.standard_normal(len(t))
    try:
        from scipy.signal import butter, sosfilt
        nyq = SR / 2
        sos = butter(2, min(0.999, cutoff / nyq), btype='low', output='sos')
        return sosfilt(sos, noise)
    except ImportError:
        window = max(1, int(SR / cutoff / 4))
        return np.convolve(noise, np.ones(window) / window, mode='same')


# ──────────────────────────────────────────────────────────────────────────────
# KICK DRUMS
# ──────────────────────────────────────────────────────────────────────────────

def kick_techno() -> np.ndarray:
    """
    Techno kick: punchy sub-heavy. Long sine sweep 80→28Hz (drops deep).
    Very tight click transient, hard punch, long sub tail.
    Classic Roland TR-909 / Neu-era techno character.
    """
    rng = np.random.default_rng(100)
    dur = 0.65
    t = _t(dur)

    # Pitch envelope: starts at 80Hz, drops exponentially to 28Hz
    f_start, f_end = 80.0, 28.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-18.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    # Amplitude: tight punch with long sub sustain
    amp = np.exp(-6.0 * t)

    # Click transient: very short noise burst (3ms), shaped with fast decay
    click_len = int(0.003 * SR)
    click_noise = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))
    click = click_noise * click_env

    # Add second harmonic distortion for punch
    distort = np.tanh(body * 2.0) * 0.15

    sig = body * amp * 0.85 + click * 0.35 + distort * amp
    return sig


def kick_house() -> np.ndarray:
    """
    House kick: warm, round, punchy. Softer pitch drop 120→50Hz.
    More mid-range presence, slightly shorter decay, Roland TR-909 style.
    """
    rng = np.random.default_rng(101)
    dur = 0.55
    t = _t(dur)

    # Pitch: starts higher, warmer curve
    f_start, f_end = 120.0, 50.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-22.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    # Amplitude: medium punch, warm decay
    amp = np.exp(-7.5 * t)

    # Click transient: slightly longer (4ms), softer
    click_len = int(0.004 * SR)
    click_noise = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 6, click_len))
    click = click_noise * click_env

    # Second harmonic for warmth
    warm = np.sin(phase * 2) * 0.08 * amp

    sig = body * amp * 0.82 + click * 0.28 + warm
    return sig


def kick_disco() -> np.ndarray:
    """
    Disco kick: bouncy, medium pitch drop 100→55Hz, punchy mid-range.
    Characteristic 70s bouncy feel — not too deep, not too sharp.
    """
    rng = np.random.default_rng(102)
    dur = 0.50
    t = _t(dur)

    # Pitch: medium drop, bouncy character
    f_start, f_end = 100.0, 55.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-15.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    # Amplitude: quick punch, medium sustain
    amp = np.exp(-8.5 * t)

    # Attack pop
    click_len = int(0.005 * SR)
    click_noise = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))
    click = click_noise * click_env

    # Second harmonic adds that 70s warmth
    second = np.sin(phase * 2) * 0.12 * amp

    sig = body * amp * 0.80 + click * 0.30 + second
    return sig


def kick_jazz() -> np.ndarray:
    """
    Jazz kick: soft, round, low-volume. Pitch 70→45Hz, gentle envelope.
    Acoustic kick character — no sharp click, more thud-like.
    """
    rng = np.random.default_rng(103)
    dur = 0.45
    t = _t(dur)

    # Pitch: modest drop, round
    f_start, f_end = 70.0, 45.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-10.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    # Amplitude: soft attack, medium decay
    amp = np.exp(-9.0 * t)
    # Soft attack: brief ramp
    atk = int(0.006 * SR)
    amp[:atk] *= np.linspace(0.3, 1.0, atk)

    # Subtle beater transient (very soft)
    click_len = int(0.008 * SR)
    click_noise = _lowpass_noise(t, 3000, rng)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 6, click_len))
    click = click_noise * click_env

    # Room-like body resonance
    resonance = np.sin(phase * 1.5) * 0.06 * amp

    sig = body * amp * 0.75 + click * 0.15 + resonance
    return sig


def kick_rnb() -> np.ndarray:
    """
    R&B kick: deep sub, very low frequency, long decay. 808-style.
    Pitch 65→30Hz, very long sustain, heavy sub presence.
    """
    rng = np.random.default_rng(104)
    dur = 1.0
    t = _t(dur)

    # Pitch: deep, slow drop — 808 style
    f_start, f_end = 65.0, 30.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-8.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    # Amplitude: very long, slow decay for sub rumble
    amp = np.exp(-3.5 * t)

    # Short click transient
    click_len = int(0.004 * SR)
    click_noise = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 10, click_len))
    click = click_noise * click_env

    # Slight distortion for 808 character
    driven = np.tanh(body * 1.5) * 0.10 * amp

    sig = body * amp * 0.88 + click * 0.20 + driven
    return sig


# ──────────────────────────────────────────────────────────────────────────────
# SNARE DRUMS
# ──────────────────────────────────────────────────────────────────────────────

def snare_techno() -> np.ndarray:
    """
    Techno snare: sharp, tight noise burst + resonant body.
    Very short decay, metallic resonator, punchy transient.
    """
    rng = np.random.default_rng(200)
    dur = 0.25
    t = _t(dur)

    # Resonant body: two tuned tones (snare drum modes ~200Hz and ~350Hz)
    body = (np.sin(2 * np.pi * 200 * t) * 0.6
            + np.sin(2 * np.pi * 340 * t) * 0.4)
    body_amp = np.exp(-28.0 * t)

    # Noise burst: tight, bright high-pass noise
    noise = _highpass_noise(t, 3000, rng)
    noise_amp = np.exp(-22.0 * t)

    # Hard transient click
    click_len = int(0.002 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))

    sig = body * body_amp * 0.5 + noise * noise_amp * 0.7 + click * click_env * 0.4
    return sig


def snare_house() -> np.ndarray:
    """
    House snare/clap-snare: snappy, with slight room, TR-909 style.
    Medium decay noise, warm body resonance, classic house punch.
    """
    rng = np.random.default_rng(201)
    dur = 0.35
    t = _t(dur)

    # Body resonance: warmer tuning (~180Hz, ~290Hz)
    body = (np.sin(2 * np.pi * 180 * t) * 0.55
            + np.sin(2 * np.pi * 290 * t) * 0.45)
    body_amp = np.exp(-18.0 * t)

    # Noise: mid-range, warm
    noise = _bandpass_noise(t, 3500, 4000, rng)
    noise_amp = np.exp(-14.0 * t)

    # Room tail: slow-decaying noise for body
    room = rng.standard_normal(len(t))
    room_amp = np.exp(-8.0 * t) * 0.15

    sig = body * body_amp * 0.5 + noise * noise_amp * 0.65 + room * room_amp
    return sig


def snare_disco() -> np.ndarray:
    """
    Disco snare: bright, crisp, with reverb-like tail, wide sound.
    Multiple body resonances, bright sizzle, classic 70s snare.
    """
    rng = np.random.default_rng(202)
    dur = 0.45
    t = _t(dur)

    # Body: multiple resonant frequencies for fullness
    body = (np.sin(2 * np.pi * 190 * t) * 0.5
            + np.sin(2 * np.pi * 300 * t) * 0.35
            + np.sin(2 * np.pi * 450 * t) * 0.15)
    body_amp = np.exp(-14.0 * t)

    # Bright noise burst
    noise = _highpass_noise(t, 2000, rng)
    noise_amp = np.exp(-10.0 * t)

    # Reverb tail: long decaying noise at medium freq
    reverb = _bandpass_noise(t, 2500, 3000, rng)
    reverb_amp = np.exp(-5.5 * t) * 0.25

    sig = body * body_amp * 0.5 + noise * noise_amp * 0.6 + reverb * reverb_amp
    return sig


def snare_jazz() -> np.ndarray:
    """
    Jazz snare: soft brushed sound, lower frequency noise, subtle body.
    Low amplitude, warm, brushed character — acoustic drum feel.
    """
    rng = np.random.default_rng(203)
    dur = 0.40
    t = _t(dur)

    # Body: low, warm resonance
    body = (np.sin(2 * np.pi * 150 * t) * 0.6
            + np.sin(2 * np.pi * 220 * t) * 0.4)
    body_amp = np.exp(-12.0 * t)
    # Soft attack
    atk = int(0.005 * SR)
    body_amp[:atk] *= np.linspace(0.2, 1.0, atk)

    # Brush noise: lower frequency, soft
    noise = _bandpass_noise(t, 1500, 2500, rng)
    noise_amp = np.exp(-9.0 * t) * 0.8

    # Subtle wire rattle
    wire = _highpass_noise(t, 4000, rng)
    wire_amp = np.exp(-18.0 * t) * 0.2

    sig = body * body_amp * 0.4 + noise * noise_amp * 0.5 + wire * wire_amp
    return sig


def snare_rnb() -> np.ndarray:
    """
    R&B snare: layered snare + clap character, fat and deep.
    Deep body resonance + multiple noise layers.
    """
    rng = np.random.default_rng(204)
    dur = 0.40
    t = _t(dur)

    # Deep body resonance
    body = (np.sin(2 * np.pi * 160 * t) * 0.65
            + np.sin(2 * np.pi * 250 * t) * 0.35)
    body_amp = np.exp(-15.0 * t)

    # Layered noise: mid and high
    noise_mid = _bandpass_noise(t, 2500, 3000, rng)
    noise_hi = _highpass_noise(t, 5000, rng)
    noise_amp = np.exp(-12.0 * t)

    # Clap-like burst at onset (3 micro-bursts)
    clap_env = sum(np.exp(-400 * (t - d) ** 2) for d in [0.0, 0.008, 0.016])
    clap_noise = rng.standard_normal(len(t))
    clap = clap_noise * clap_env * 0.3

    sig = (body * body_amp * 0.45
           + noise_mid * noise_amp * 0.4
           + noise_hi * noise_amp * 0.25
           + clap)
    return sig


# ──────────────────────────────────────────────────────────────────────────────
# CLOSED HI-HAT
# ──────────────────────────────────────────────────────────────────────────────

def clhat_techno() -> np.ndarray:
    """
    Techno closed hi-hat: very tight, metallic, sharp attack.
    Short decay, high-frequency emphasis, metallic partials.
    """
    rng = np.random.default_rng(300)
    dur = 0.08
    t = _t(dur)

    # Metallic inharmonic partials (TR-909 hi-hat partial ratios)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53, 8.19]
    base_freq = 620.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.6 ** i)
              for i, p in enumerate(partials))

    # High-pass noise layer
    noise = _highpass_noise(t, 6000, rng)

    # Very tight envelope
    amp = np.exp(-90.0 * t)
    return (sig * 0.5 + noise * 0.6) * amp


def clhat_house() -> np.ndarray:
    """
    House closed hi-hat: crisp, slightly longer than techno, TR-909 character.
    """
    rng = np.random.default_rng(301)
    dur = 0.12
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53, 8.19]
    base_freq = 580.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.58 ** i)
              for i, p in enumerate(partials))

    noise = _highpass_noise(t, 5500, rng)
    amp = np.exp(-65.0 * t)
    return (sig * 0.5 + noise * 0.6) * amp


def clhat_disco() -> np.ndarray:
    """
    Disco closed hi-hat: bright, with slight swing character.
    Medium-short, crisp, emphasizes upper mids.
    """
    rng = np.random.default_rng(302)
    dur = 0.14
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 650.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.55 ** i)
              for i, p in enumerate(partials))

    noise = _highpass_noise(t, 5000, rng)
    amp = np.exp(-55.0 * t)
    return (sig * 0.5 + noise * 0.65) * amp


def clhat_jazz() -> np.ndarray:
    """
    Jazz closed hi-hat: soft, ride-like short chick sound.
    Lower amplitude, warmer, less metallic.
    """
    rng = np.random.default_rng(303)
    dur = 0.18
    t = _t(dur)

    # Less inharmonic: closer to harmonic ratios for warmer cymbal
    partials = [1.0, 1.8, 2.7, 3.9, 5.1]
    base_freq = 540.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.52 ** i)
              for i, p in enumerate(partials))

    noise = _bandpass_noise(t, 4000, 5000, rng)
    amp = np.exp(-40.0 * t)
    # Soft attack
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0.4, 1.0, atk)
    return (sig * 0.45 + noise * 0.5) * amp


def clhat_rnb() -> np.ndarray:
    """
    R&B closed hi-hat: smooth, with slight shuffle feel.
    Medium decay, not too sharp, laid-back character.
    """
    rng = np.random.default_rng(304)
    dur = 0.15
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 560.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.56 ** i)
              for i, p in enumerate(partials))

    noise = _bandpass_noise(t, 4500, 5500, rng)
    amp = np.exp(-52.0 * t)
    return (sig * 0.48 + noise * 0.58) * amp


# ──────────────────────────────────────────────────────────────────────────────
# OPEN HI-HAT
# ──────────────────────────────────────────────────────────────────────────────

def ophat_techno() -> np.ndarray:
    """
    Techno open hi-hat: harsh, metallic, medium-long decay.
    Industrial character, high-pass emphasis, aggressive.
    """
    rng = np.random.default_rng(400)
    dur = 0.45
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53, 8.19]
    base_freq = 620.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.6 ** i)
              for i, p in enumerate(partials))

    noise = _highpass_noise(t, 6000, rng)
    amp = np.exp(-12.0 * t)
    return (sig * 0.5 + noise * 0.65) * amp


def ophat_house() -> np.ndarray:
    """
    House open hi-hat: open, shuffling, medium sustain.
    Classic TR-909 open hat character, slightly swung feel.
    """
    rng = np.random.default_rng(401)
    dur = 0.55
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53, 8.19]
    base_freq = 580.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.58 ** i)
              for i, p in enumerate(partials))

    noise = _highpass_noise(t, 5500, rng)
    amp = np.exp(-9.0 * t)
    return (sig * 0.5 + noise * 0.65) * amp


def ophat_disco() -> np.ndarray:
    """
    Disco open hi-hat: swung, bright, longer decay.
    Classic disco groove feel, shimmering top end.
    """
    rng = np.random.default_rng(402)
    dur = 0.70
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 650.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.55 ** i)
              for i, p in enumerate(partials))

    noise = _highpass_noise(t, 5000, rng)
    amp = np.exp(-7.5 * t)
    return (sig * 0.5 + noise * 0.70) * amp


def ophat_jazz() -> np.ndarray:
    """
    Jazz open hi-hat: long, ride-like, warm shimmer.
    Soft metallic ring, lower base frequency, much longer decay.
    """
    rng = np.random.default_rng(403)
    dur = 1.2
    t = _t(dur)

    # Jazz uses less inharmonic ratios — more musical/warm
    partials = [1.0, 1.8, 2.7, 3.9, 5.1, 6.7]
    base_freq = 520.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.52 ** i)
              for i, p in enumerate(partials))

    noise = _bandpass_noise(t, 3500, 4500, rng)
    amp = np.exp(-4.5 * t)
    # Soft attack
    atk = int(0.004 * SR)
    amp[:atk] *= np.linspace(0.3, 1.0, atk)
    return (sig * 0.45 + noise * 0.5) * amp


def ophat_rnb() -> np.ndarray:
    """
    R&B open hi-hat: smooth, medium-long, shuffle groove.
    Laid-back feel, medium decay, not too sharp.
    """
    rng = np.random.default_rng(404)
    dur = 0.60
    t = _t(dur)

    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 560.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.56 ** i)
              for i, p in enumerate(partials))

    noise = _bandpass_noise(t, 4500, 5500, rng)
    amp = np.exp(-8.0 * t)
    return (sig * 0.48 + noise * 0.60) * amp


# ──────────────────────────────────────────────────────────────────────────────
# CLAP
# ──────────────────────────────────────────────────────────────────────────────

def clap_techno() -> np.ndarray:
    """
    Techno clap: sharp, fast, tight. Multiple micro-bursts 6ms apart.
    High-pass noise, very short decay.
    """
    rng = np.random.default_rng(500)
    dur = 0.20
    t = _t(dur)

    noise = _highpass_noise(t, 2000, rng)
    # 4 tight bursts very close together
    offsets = [0.000, 0.006, 0.012, 0.018]
    env = sum(np.exp(-800 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-18.0 * t)
    return noise * env


def clap_house() -> np.ndarray:
    """
    House clap: snappy with room tail. TR-909 style.
    Medium bursts with slight reverb, classic house feel.
    """
    rng = np.random.default_rng(501)
    dur = 0.35
    t = _t(dur)

    noise = _bandpass_noise(t, 3000, 5000, rng)
    # 3 bursts with slight room
    offsets = [0.000, 0.009, 0.018]
    env = sum(np.exp(-600 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-11.0 * t)

    # Room tail
    room_noise = rng.standard_normal(len(t))
    room_amp = np.exp(-7.0 * t) * 0.20

    return noise * env + room_noise * room_amp


def clap_disco() -> np.ndarray:
    """
    Disco clap: bright, wide sound with decay. Multiple layers.
    More sizzle, longer decay tail for that 70s room sound.
    """
    rng = np.random.default_rng(502)
    dur = 0.45
    t = _t(dur)

    noise = _bandpass_noise(t, 2500, 5000, rng)
    offsets = [0.000, 0.010, 0.020, 0.030]
    env = sum(np.exp(-500 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-9.0 * t)

    # Extra high sizzle
    sizzle = _highpass_noise(t, 4500, rng) * np.exp(-7.0 * t) * 0.3

    return noise * env + sizzle


def clap_jazz() -> np.ndarray:
    """
    Jazz clap: soft, loose, brush-like hit. Lower freq noise.
    Acoustic hand-clap character, more organic.
    """
    rng = np.random.default_rng(503)
    dur = 0.30
    t = _t(dur)

    noise = _bandpass_noise(t, 1500, 4000, rng)
    offsets = [0.000, 0.012, 0.024]
    env = sum(np.exp(-400 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-10.0 * t)

    # Soft decay tail
    tail = rng.standard_normal(len(t)) * np.exp(-6.0 * t) * 0.15

    return noise * env * 0.7 + tail


def clap_rnb() -> np.ndarray:
    """
    R&B clap: layered, fat, with tail. Classic hip-hop/RnB snap.
    Combines tight burst with reverberant tail.
    """
    rng = np.random.default_rng(504)
    dur = 0.40
    t = _t(dur)

    noise_hi = _highpass_noise(t, 3000, rng)
    noise_mid = _bandpass_noise(t, 1500, 3000, rng)
    offsets = [0.000, 0.008, 0.016, 0.024]
    env = sum(np.exp(-500 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-10.0 * t)

    # Longer reverb tail for that RnB space
    reverb = rng.standard_normal(len(t)) * np.exp(-5.5 * t) * 0.25

    return (noise_hi * 0.5 + noise_mid * 0.5) * env + reverb


# ──────────────────────────────────────────────────────────────────────────────
# TOM HI
# ──────────────────────────────────────────────────────────────────────────────

def tom_hi_techno() -> np.ndarray:
    """
    Techno hi tom: tight, short, high-pitched. Electronic character.
    Fundamental ~260Hz, fast decay, minimal noise.
    """
    rng = np.random.default_rng(600)
    dur = 0.30
    t = _t(dur)

    f_start, f_end = 340.0, 200.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-20.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.003 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))

    amp = np.exp(-18.0 * t)
    return body * amp * 0.85 + noise * click_env * 0.35


def tom_hi_house() -> np.ndarray:
    """
    House hi tom: warm, punchy, medium decay.
    """
    rng = np.random.default_rng(601)
    dur = 0.35
    t = _t(dur)

    f_start, f_end = 320.0, 190.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-18.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.004 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))

    amp = np.exp(-14.0 * t)
    return body * amp * 0.82 + noise * click_env * 0.30


def tom_hi_disco() -> np.ndarray:
    """
    Disco hi tom: bright, punchy, with reverb tail.
    """
    rng = np.random.default_rng(602)
    dur = 0.40
    t = _t(dur)

    f_start, f_end = 350.0, 210.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-16.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.005 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))

    # Reverb-like extra decay layer
    body2 = np.sin(2 * np.pi * np.cumsum(pitch_env) / SR * 1.5) * 0.12
    amp = np.exp(-12.0 * t)
    return (body + body2) * amp * 0.80 + noise * click_env * 0.30


def tom_hi_jazz() -> np.ndarray:
    """
    Jazz hi tom: soft, acoustic character, brush-like attack.
    Lower amplitude, gentle transient.
    """
    rng = np.random.default_rng(603)
    dur = 0.45
    t = _t(dur)

    f_start, f_end = 280.0, 180.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-12.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    # Soft noise transient
    noise = _lowpass_noise(t, 4000, rng)
    click_len = int(0.007 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 6, click_len))

    amp = np.exp(-10.0 * t)
    atk = int(0.005 * SR)
    amp[:atk] *= np.linspace(0.3, 1.0, atk)
    return body * amp * 0.72 + noise * click_env * 0.22


def tom_hi_rnb() -> np.ndarray:
    """
    R&B hi tom: punchy, fat, with sub presence.
    Deep pitch sweep, medium-long decay.
    """
    rng = np.random.default_rng(604)
    dur = 0.45
    t = _t(dur)

    f_start, f_end = 300.0, 170.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-14.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.004 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))

    amp = np.exp(-11.0 * t)
    return body * amp * 0.85 + noise * click_env * 0.32


# ──────────────────────────────────────────────────────────────────────────────
# TOM LO
# ──────────────────────────────────────────────────────────────────────────────

def tom_lo_techno() -> np.ndarray:
    """
    Techno lo tom: tight, electronic, sub-heavy. ~90Hz.
    """
    rng = np.random.default_rng(700)
    dur = 0.40
    t = _t(dur)

    f_start, f_end = 140.0, 80.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-20.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.003 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))

    amp = np.exp(-14.0 * t)
    return body * amp * 0.88 + noise * click_env * 0.35


def tom_lo_house() -> np.ndarray:
    """
    House lo tom: warm, round, punchy. ~85Hz.
    """
    rng = np.random.default_rng(701)
    dur = 0.45
    t = _t(dur)

    f_start, f_end = 130.0, 75.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-17.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.004 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))

    amp = np.exp(-11.0 * t)
    return body * amp * 0.85 + noise * click_env * 0.30


def tom_lo_disco() -> np.ndarray:
    """
    Disco lo tom: bouncy, medium decay, bright attack. ~95Hz.
    """
    rng = np.random.default_rng(702)
    dur = 0.50
    t = _t(dur)

    f_start, f_end = 150.0, 90.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-15.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.005 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))

    amp = np.exp(-10.0 * t)
    return body * amp * 0.82 + noise * click_env * 0.30


def tom_lo_jazz() -> np.ndarray:
    """
    Jazz lo tom: deep, acoustic, soft mallet character. ~75Hz.
    """
    rng = np.random.default_rng(703)
    dur = 0.55
    t = _t(dur)

    f_start, f_end = 110.0, 65.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-10.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = _lowpass_noise(t, 3500, rng)
    click_len = int(0.008 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 5, click_len))

    amp = np.exp(-8.0 * t)
    atk = int(0.006 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return body * amp * 0.75 + noise * click_env * 0.20


def tom_lo_rnb() -> np.ndarray:
    """
    R&B lo tom: very deep, long decay, sub presence. 808-like. ~70Hz.
    """
    rng = np.random.default_rng(704)
    dur = 0.65
    t = _t(dur)

    f_start, f_end = 120.0, 60.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-12.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)

    noise = rng.standard_normal(len(t))
    click_len = int(0.004 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 9, click_len))

    amp = np.exp(-7.5 * t)
    return body * amp * 0.88 + noise * click_env * 0.28


# ──────────────────────────────────────────────────────────────────────────────
# RIMSHOT
# ──────────────────────────────────────────────────────────────────────────────

def rim_techno() -> np.ndarray:
    """
    Techno rim: very short, metallic click. Tight transient + resonator.
    """
    rng = np.random.default_rng(800)
    dur = 0.12
    t = _t(dur)

    # Resonant body: rim-shot frequencies
    body = (np.sin(2 * np.pi * 1050 * t) * 0.6
            + np.sin(2 * np.pi * 1650 * t) * 0.4)
    body_amp = np.exp(-45.0 * t)

    # Short click transient
    click_len = int(0.002 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 10, click_len))

    return body * body_amp * 0.7 + click * click_env * 0.5


def rim_house() -> np.ndarray:
    """
    House rim: snappy click, slightly warmer than techno.
    """
    rng = np.random.default_rng(801)
    dur = 0.15
    t = _t(dur)

    body = (np.sin(2 * np.pi * 900 * t) * 0.6
            + np.sin(2 * np.pi * 1400 * t) * 0.4)
    body_amp = np.exp(-38.0 * t)

    click_len = int(0.003 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 9, click_len))

    return body * body_amp * 0.68 + click * click_env * 0.48


def rim_disco() -> np.ndarray:
    """
    Disco rim: bright, medium-length click with slight tail.
    """
    rng = np.random.default_rng(802)
    dur = 0.18
    t = _t(dur)

    body = (np.sin(2 * np.pi * 950 * t) * 0.55
            + np.sin(2 * np.pi * 1500 * t) * 0.35
            + np.sin(2 * np.pi * 2200 * t) * 0.10)
    body_amp = np.exp(-32.0 * t)

    click_len = int(0.003 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))

    return body * body_amp * 0.65 + click * click_env * 0.45


def rim_jazz() -> np.ndarray:
    """
    Jazz rim: soft stick-on-rim sound. Lower freq, gentle transient.
    """
    rng = np.random.default_rng(803)
    dur = 0.20
    t = _t(dur)

    body = (np.sin(2 * np.pi * 700 * t) * 0.6
            + np.sin(2 * np.pi * 1100 * t) * 0.4)
    body_amp = np.exp(-25.0 * t)
    atk = int(0.004 * SR)
    body_amp[:atk] *= np.linspace(0.2, 1.0, atk)

    click_len = int(0.004 * SR)
    click = _lowpass_noise(t, 5000, rng)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))

    return body * body_amp * 0.60 + click * click_env * 0.35


def rim_rnb() -> np.ndarray:
    """
    R&B rim: medium snappy, with slight body. Crisp click feel.
    """
    rng = np.random.default_rng(804)
    dur = 0.16
    t = _t(dur)

    body = (np.sin(2 * np.pi * 850 * t) * 0.55
            + np.sin(2 * np.pi * 1350 * t) * 0.45)
    body_amp = np.exp(-36.0 * t)

    click_len = int(0.003 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 9, click_len))

    return body * body_amp * 0.65 + click * click_env * 0.46


# ──────────────────────────────────────────────────────────────────────────────
# COWBELL
# ──────────────────────────────────────────────────────────────────────────────
# Classic cowbell: two detuned square/triangle waves at 562Hz and 845Hz
# Real TR-808 cowbell uses two square wave oscillators at these frequencies.

def _cowbell_base(f1: float, f2: float, decay: float, dur: float,
                  mix1: float = 0.6, mix2: float = 0.4) -> np.ndarray:
    """Base cowbell synthesis: two oscillators with metal envelope."""
    t = _t(dur)
    # Square-wave approximation (odd harmonics)
    osc1 = sum(np.sin(2 * np.pi * f1 * (2*k+1) * t) / (2*k+1)
               for k in range(5)) * mix1
    osc2 = sum(np.sin(2 * np.pi * f2 * (2*k+1) * t) / (2*k+1)
               for k in range(5)) * mix2
    sig = osc1 + osc2
    # Hard clip / saturation for metallic character
    sig = np.tanh(sig * 1.5)
    amp = np.exp(-decay * t)
    # Fast attack
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0.0, 1.0, atk)
    return sig * amp


def cowbell_techno() -> np.ndarray:
    """
    Techno cowbell: sharp, tight, industrial. Short decay, metallic zing.
    """
    return _cowbell_base(562, 845, 35.0, 0.25)


def cowbell_house() -> np.ndarray:
    """
    House cowbell: funky, medium decay. Classic house groove element.
    Slightly detuned for extra character.
    """
    return _cowbell_base(540, 810, 18.0, 0.40, mix1=0.55, mix2=0.45)


def cowbell_disco() -> np.ndarray:
    """
    Disco cowbell: prominent, longer decay, warm. Heavy cowbell use.
    Classic disco groove — the cowbell is up front.
    """
    return _cowbell_base(520, 780, 12.0, 0.55, mix1=0.58, mix2=0.42)


def cowbell_jazz() -> np.ndarray:
    """
    Jazz cowbell: softer, more bell-like, longer sustain.
    Lower oscillator frequencies, more harmonic.
    """
    return _cowbell_base(480, 720, 8.0, 0.70, mix1=0.5, mix2=0.5)


def cowbell_rnb() -> np.ndarray:
    """
    R&B cowbell: medium punch, warm, funky. Sits in the groove.
    """
    return _cowbell_base(550, 825, 15.0, 0.45, mix1=0.55, mix2=0.45)


# ──────────────────────────────────────────────────────────────────────────────
# CYMBAL (ride/crash hybrid)
# ──────────────────────────────────────────────────────────────────────────────

def cymbal_techno() -> np.ndarray:
    """
    Techno cymbal: harsh crash, metallic, aggressive. Long noisy decay.
    Industrial character, high-frequency emphasis.
    """
    rng = np.random.default_rng(1000)
    dur = 1.2
    t = _t(dur)

    # Inharmonic metallic partials
    partials = [380, 720, 1200, 2100, 3500, 5800, 9200]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.52 ** i)
              for i, f in enumerate(partials))

    # Lots of noise
    noise = _highpass_noise(t, 5000, rng)
    amp = np.exp(-5.5 * t)
    return (sig * 0.4 + noise * 0.7) * amp


def cymbal_house() -> np.ndarray:
    """
    House cymbal: bright crash with medium decay. TR-909 style.
    """
    rng = np.random.default_rng(1001)
    dur = 1.4
    t = _t(dur)

    partials = [400, 760, 1280, 2200, 3700, 6200]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.53 ** i)
              for i, f in enumerate(partials))

    noise = _highpass_noise(t, 4500, rng)
    amp = np.exp(-4.5 * t)
    return (sig * 0.45 + noise * 0.65) * amp


def cymbal_disco() -> np.ndarray:
    """
    Disco cymbal: shimmer, broad spectrum, long tail.
    Classic disco crash — wide and bright.
    """
    rng = np.random.default_rng(1002)
    dur = 1.8
    t = _t(dur)

    partials = [360, 700, 1150, 2000, 3400, 5500, 8500]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.55 ** i)
              for i, f in enumerate(partials))

    noise = _highpass_noise(t, 4000, rng)
    amp = np.exp(-3.5 * t)
    return (sig * 0.45 + noise * 0.65) * amp


def cymbal_jazz() -> np.ndarray:
    """
    Jazz cymbal: ride-like, musical, long metallic resonance.
    More harmonic partials, warmer, musical sustain.
    """
    rng = np.random.default_rng(1003)
    dur = 2.5
    t = _t(dur)

    # Jazz ride: more harmonic, warmer
    partials = [620, 1180, 1850, 2500, 3400, 4700, 6300]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.55 ** i)
              for i, f in enumerate(partials))

    noise = _bandpass_noise(t, 3000, 4000, rng) * 0.15
    amp = np.exp(-2.2 * t)
    # Soft attack
    atk = int(0.005 * SR)
    amp[:atk] *= np.linspace(0.3, 1.0, atk)
    return (sig * 0.55 + noise) * amp


def cymbal_rnb() -> np.ndarray:
    """
    R&B cymbal: smooth, warm crash, medium-long decay.
    Less harsh than techno, more musical.
    """
    rng = np.random.default_rng(1004)
    dur = 1.5
    t = _t(dur)

    partials = [420, 800, 1350, 2300, 3800, 6400]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.54 ** i)
              for i, f in enumerate(partials))

    noise = _bandpass_noise(t, 4000, 6000, rng)
    amp = np.exp(-4.0 * t)
    return (sig * 0.45 + noise * 0.60) * amp


# ──────────────────────────────────────────────────────────────────────────────
# GENERATOR MAP
# ──────────────────────────────────────────────────────────────────────────────

GENERATORS = {
    # Kicks
    "kick_techno":     kick_techno,
    "kick_house":      kick_house,
    "kick_disco":      kick_disco,
    "kick_jazz":       kick_jazz,
    "kick_rnb":        kick_rnb,
    # Snares
    "snare_techno":    snare_techno,
    "snare_house":     snare_house,
    "snare_disco":     snare_disco,
    "snare_jazz":      snare_jazz,
    "snare_rnb":       snare_rnb,
    # Closed hi-hats
    "clhat_techno":    clhat_techno,
    "clhat_house":     clhat_house,
    "clhat_disco":     clhat_disco,
    "clhat_jazz":      clhat_jazz,
    "clhat_rnb":       clhat_rnb,
    # Open hi-hats
    "ophat_techno":    ophat_techno,
    "ophat_house":     ophat_house,
    "ophat_disco":     ophat_disco,
    "ophat_jazz":      ophat_jazz,
    "ophat_rnb":       ophat_rnb,
    # Claps
    "clap_techno":     clap_techno,
    "clap_house":      clap_house,
    "clap_disco":      clap_disco,
    "clap_jazz":       clap_jazz,
    "clap_rnb":        clap_rnb,
    # Hi toms
    "tom_hi_techno":   tom_hi_techno,
    "tom_hi_house":    tom_hi_house,
    "tom_hi_disco":    tom_hi_disco,
    "tom_hi_jazz":     tom_hi_jazz,
    "tom_hi_rnb":      tom_hi_rnb,
    # Lo toms
    "tom_lo_techno":   tom_lo_techno,
    "tom_lo_house":    tom_lo_house,
    "tom_lo_disco":    tom_lo_disco,
    "tom_lo_jazz":     tom_lo_jazz,
    "tom_lo_rnb":      tom_lo_rnb,
    # Rimshots
    "rim_techno":      rim_techno,
    "rim_house":       rim_house,
    "rim_disco":       rim_disco,
    "rim_jazz":        rim_jazz,
    "rim_rnb":         rim_rnb,
    # Cowbells
    "cowbell_techno":  cowbell_techno,
    "cowbell_house":   cowbell_house,
    "cowbell_disco":   cowbell_disco,
    "cowbell_jazz":    cowbell_jazz,
    "cowbell_rnb":     cowbell_rnb,
    # Cymbals
    "cymbal_techno":   cymbal_techno,
    "cymbal_house":    cymbal_house,
    "cymbal_disco":    cymbal_disco,
    "cymbal_jazz":     cymbal_jazz,
    "cymbal_rnb":      cymbal_rnb,
}


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Generating {len(GENERATORS)} drum samples into {OUT_DIR}/")
    print()

    categories = ["kick", "snare", "clhat", "ophat", "clap",
                  "tom_hi", "tom_lo", "rim", "cowbell", "cymbal"]
    genres = ["techno", "house", "disco", "jazz", "rnb"]

    for cat in categories:
        print(f"  [{cat}]")
        for genre in genres:
            key = f"{cat}_{genre}"
            fn = GENERATORS.get(key)
            if fn is None:
                print(f"    WARNING: no generator for {key}")
                continue
            signal = fn()
            _write(key, signal)
        print()

    print(f"Done. {len(GENERATORS)} samples processed.")
