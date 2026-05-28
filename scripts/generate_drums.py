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
# SHAKER
# Shaker: rapid burst of bandpass-filtered noise (seed frequency 4–8 kHz),
# very short attack, fast exponential decay, slight pitch-modulated hiss.
# ──────────────────────────────────────────────────────────────────────────────

def shaker_techno() -> np.ndarray:
    """Techno shaker: tight, dry, high-frequency click-hiss. Very short."""
    rng = np.random.default_rng(2000)
    dur = 0.06
    t = _t(dur)
    noise = _bandpass_noise(t, 7000, 3000, rng)
    amp = np.exp(-80.0 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp


def shaker_house() -> np.ndarray:
    """House shaker: crisp shuffle shaker, slightly looser than techno."""
    rng = np.random.default_rng(2001)
    dur = 0.09
    t = _t(dur)
    noise = _bandpass_noise(t, 6500, 3500, rng)
    amp = np.exp(-60.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp


def shaker_disco() -> np.ndarray:
    """Disco shaker: bright, slightly longer, swinging groove shaker."""
    rng = np.random.default_rng(2002)
    dur = 0.12
    t = _t(dur)
    noise = _bandpass_noise(t, 6000, 4000, rng)
    amp = np.exp(-50.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp


def shaker_jazz() -> np.ndarray:
    """Jazz shaker: soft, egg-shaker feel, warm mid-high noise."""
    rng = np.random.default_rng(2003)
    dur = 0.14
    t = _t(dur)
    noise = _bandpass_noise(t, 5000, 3000, rng)
    amp = np.exp(-40.0 * t)
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp * 0.75


def shaker_rnb() -> np.ndarray:
    """R&B shaker: smooth laid-back shaker, medium decay."""
    rng = np.random.default_rng(2004)
    dur = 0.10
    t = _t(dur)
    noise = _bandpass_noise(t, 6000, 3000, rng)
    amp = np.exp(-55.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp


def shaker_afro() -> np.ndarray:
    """Afro shaker: long resonant rattle — tuned beads, dual noise burst."""
    rng = np.random.default_rng(2005)
    dur = 0.18
    t = _t(dur)
    noise = _bandpass_noise(t, 5500, 2500, rng)
    # slight pitch shimmer via AM
    shimmer = 1.0 + 0.3 * np.sin(2 * np.pi * 180 * t)
    amp = np.exp(-35.0 * t)
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * shimmer * amp


def shaker_latin() -> np.ndarray:
    """Latin shaker: crisp maraca-like burst, bright attack, fast tail."""
    rng = np.random.default_rng(2006)
    dur = 0.10
    t = _t(dur)
    noise = _bandpass_noise(t, 7500, 4000, rng)
    amp = np.exp(-70.0 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp


def shaker_funk() -> np.ndarray:
    """Funk shaker: punchy, mid-forward, syncopated feel."""
    rng = np.random.default_rng(2007)
    dur = 0.08
    t = _t(dur)
    noise = _bandpass_noise(t, 5500, 3000, rng)
    amp = np.exp(-75.0 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    # slight distortion for funk edge
    return np.tanh(noise * amp * 2.0) * 0.6


def shaker_rock() -> np.ndarray:
    """Rock shaker: dry, hard-hitting, higher-amplitude noise burst."""
    rng = np.random.default_rng(2008)
    dur = 0.07
    t = _t(dur)
    noise = _highpass_noise(t, 6000, rng)
    amp = np.exp(-85.0 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp


# ──────────────────────────────────────────────────────────────────────────────
# TAMBOURINE
# Two-layer synthesis: high-pitched jingle partials (inharmonic metallic
# series around 2–8 kHz) + narrow bandpass noise burst for the skin hit.
# ──────────────────────────────────────────────────────────────────────────────

def _tambourn_base(jingle_decay: float, noise_decay: float, dur: float,
                   base_freq: float = 2400, rng_seed: int = 2100) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    # Jingle: metallic inharmonic partials
    jingle_partials = [1.0, 1.48, 2.13, 2.97, 3.87, 5.02]
    jingle = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.6 ** i)
                 for i, p in enumerate(jingle_partials))
    jingle_amp = np.exp(-jingle_decay * t)
    # Skin hit: bandpass noise burst
    skin = _bandpass_noise(t, 3000, 4000, rng)
    skin_amp = np.exp(-noise_decay * t)
    atk = int(0.001 * SR)
    jingle_amp[:atk] *= np.linspace(0, 1, atk)
    skin_amp[:atk] *= np.linspace(0, 1, atk)
    return jingle * jingle_amp * 0.55 + skin * skin_amp * 0.45


def tambourn_techno() -> np.ndarray:
    """Techno tambourine: tight jingle, very short, metallic click."""
    return _tambourn_base(45.0, 60.0, 0.18, 2600, 2100)


def tambourn_house() -> np.ndarray:
    """House tambourine: crisp jingle, medium-short, TR-909 feel."""
    return _tambourn_base(30.0, 45.0, 0.22, 2400, 2101)


def tambourn_disco() -> np.ndarray:
    """Disco tambourine: bright, longer jingle, swinging 16th-note feel."""
    return _tambourn_base(20.0, 30.0, 0.30, 2300, 2102)


def tambourn_jazz() -> np.ndarray:
    """Jazz tambourine: soft, loose, warm jingle with long sustain."""
    return _tambourn_base(14.0, 22.0, 0.40, 2200, 2103)


def tambourn_rnb() -> np.ndarray:
    """R&B tambourine: smooth, medium-length, laid-back groove."""
    return _tambourn_base(22.0, 35.0, 0.28, 2350, 2104)


def tambourn_afro() -> np.ndarray:
    """Afro tambourine: tuned resonant jingle, long sustain, shimmer."""
    rng = np.random.default_rng(2105)
    dur = 0.50
    t = _t(dur)
    base = 2100.0
    jingle_partials = [1.0, 1.48, 2.13, 2.97, 3.87]
    jingle = sum(np.sin(2 * np.pi * base * p * t) * (0.62 ** i)
                 for i, p in enumerate(jingle_partials))
    shimmer = 1.0 + 0.2 * np.sin(2 * np.pi * 120 * t)
    amp = np.exp(-12.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return jingle * shimmer * amp * 0.7


def tambourn_latin() -> np.ndarray:
    """Latin tambourine: fast bright jingle, very crisp, tight."""
    return _tambourn_base(40.0, 55.0, 0.20, 2700, 2106)


def tambourn_funk() -> np.ndarray:
    """Funk tambourine: punchy jingle burst, mid-high frequency snap."""
    return _tambourn_base(35.0, 50.0, 0.22, 2500, 2107)


def tambourn_rock() -> np.ndarray:
    """Rock tambourine: hard hit, prominent skin attack, short jingle."""
    rng = np.random.default_rng(2108)
    dur = 0.20
    t = _t(dur)
    base = 2800.0
    jingle_partials = [1.0, 1.48, 2.13, 2.97]
    jingle = sum(np.sin(2 * np.pi * base * p * t) * (0.55 ** i)
                 for i, p in enumerate(jingle_partials))
    skin = _highpass_noise(t, 3500, rng)
    jingle_amp = np.exp(-50.0 * t)
    skin_amp = np.exp(-70.0 * t)
    return jingle * jingle_amp * 0.5 + skin * skin_amp * 0.6


# ──────────────────────────────────────────────────────────────────────────────
# CONGA HI
# Conga: pitched membrane drum. Sine + narrow noise transient. High conga
# tuned around 300–500 Hz, pitch sweeping downward quickly.
# ──────────────────────────────────────────────────────────────────────────────

def _conga_hi_base(f_start: float, f_end: float, body_decay: float,
                   dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    pitch_env = f_end + (f_start - f_end) * np.exp(-30.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    # Slap transient: bandpass burst around 800 Hz
    slap = _bandpass_noise(t, 800, 600, rng)
    slap_len = int(0.008 * SR)
    slap_env = np.zeros(len(t))
    slap_env[:slap_len] = np.exp(-np.linspace(0, 8, slap_len))
    amp = np.exp(-body_decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.75 + slap * slap_env * 0.40


def conga_hi_techno() -> np.ndarray:
    """Techno high conga: tight, electronic, short decay."""
    return _conga_hi_base(450, 280, 22.0, 0.25, 2200)


def conga_hi_house() -> np.ndarray:
    """House high conga: warm, medium decay, punchy slap."""
    return _conga_hi_base(430, 270, 16.0, 0.30, 2201)


def conga_hi_disco() -> np.ndarray:
    """Disco high conga: bright, bouncy, longer tail."""
    return _conga_hi_base(460, 290, 13.0, 0.35, 2202)


def conga_hi_jazz() -> np.ndarray:
    """Jazz high conga: soft, open tone, acoustic feel."""
    rng = np.random.default_rng(2203)
    dur = 0.45
    t = _t(dur)
    pitch_env = 310 + (420 - 310) * np.exp(-20.0 * t) * 0
    # jazz: static pitch, soft mallet
    pitch_env = np.full(len(t), 310.0)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-10.0 * t)
    atk = int(0.004 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return body * amp * 0.70


def conga_hi_rnb() -> np.ndarray:
    """R&B high conga: deep resonant tone, longer decay."""
    return _conga_hi_base(400, 250, 12.0, 0.40, 2204)


def conga_hi_afro() -> np.ndarray:
    """Afro high conga: tuned open tone, long sustain, resonant."""
    rng = np.random.default_rng(2205)
    dur = 0.55
    t = _t(dur)
    pitch_env = 380 + (480 - 380) * np.exp(-25.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.15
    amp = np.exp(-9.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.78


def conga_hi_latin() -> np.ndarray:
    """Latin high conga: crisp slap tone, bright attack."""
    return _conga_hi_base(480, 300, 20.0, 0.28, 2206)


def conga_hi_funk() -> np.ndarray:
    """Funk high conga: punchy midrange snap, tight decay."""
    return _conga_hi_base(440, 275, 18.0, 0.28, 2207)


def conga_hi_rock() -> np.ndarray:
    """Rock high conga: hard hit, mid-forward, dry."""
    return _conga_hi_base(470, 295, 25.0, 0.22, 2208)


# ──────────────────────────────────────────────────────────────────────────────
# CONGA LO
# Low conga: lower tuning ~180–280 Hz, longer body resonance.
# ──────────────────────────────────────────────────────────────────────────────

def _conga_lo_base(f_start: float, f_end: float, body_decay: float,
                   dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    pitch_env = f_end + (f_start - f_end) * np.exp(-25.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    slap = _bandpass_noise(t, 500, 400, rng)
    slap_len = int(0.010 * SR)
    slap_env = np.zeros(len(t))
    slap_env[:slap_len] = np.exp(-np.linspace(0, 7, slap_len))
    amp = np.exp(-body_decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.78 + slap * slap_env * 0.35


def conga_lo_techno() -> np.ndarray:
    """Techno low conga: tight, electronic low thud."""
    return _conga_lo_base(280, 160, 18.0, 0.30, 2300)


def conga_lo_house() -> np.ndarray:
    """House low conga: warm, punchy, medium decay."""
    return _conga_lo_base(260, 150, 14.0, 0.38, 2301)


def conga_lo_disco() -> np.ndarray:
    """Disco low conga: bouncy, medium length, broad mid-range."""
    return _conga_lo_base(270, 160, 11.0, 0.42, 2302)


def conga_lo_jazz() -> np.ndarray:
    """Jazz low conga: deep open tone, soft acoustic feel."""
    rng = np.random.default_rng(2303)
    dur = 0.55
    t = _t(dur)
    pitch_env = np.full(len(t), 185.0)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-8.0 * t)
    atk = int(0.005 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return body * amp * 0.72


def conga_lo_rnb() -> np.ndarray:
    """R&B low conga: deep sub-present tone, long decay."""
    return _conga_lo_base(240, 140, 9.0, 0.50, 2304)


def conga_lo_afro() -> np.ndarray:
    """Afro low conga: tuned resonant bass tone, long sustain."""
    rng = np.random.default_rng(2305)
    dur = 0.65
    t = _t(dur)
    pitch_env = 200 + (270 - 200) * np.exp(-20.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.12
    amp = np.exp(-7.5 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.80


def conga_lo_latin() -> np.ndarray:
    """Latin low conga: crisp slap tone, well-defined pitch."""
    return _conga_lo_base(290, 170, 16.0, 0.34, 2306)


def conga_lo_funk() -> np.ndarray:
    """Funk low conga: punchy mid-bass thud, tight."""
    return _conga_lo_base(265, 155, 16.0, 0.33, 2307)


def conga_lo_rock() -> np.ndarray:
    """Rock low conga: hard, dry, mid-forward hit."""
    return _conga_lo_base(275, 165, 20.0, 0.28, 2308)


# ──────────────────────────────────────────────────────────────────────────────
# BONGO HI
# Bongo: smaller, higher-pitched than conga. Pitched membrane, very short
# slap attack, thin body. Hi bongo ~400–700 Hz.
# ──────────────────────────────────────────────────────────────────────────────

def _bongo_hi_base(f_start: float, f_end: float, body_decay: float,
                   dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    pitch_env = f_end + (f_start - f_end) * np.exp(-35.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.10
    # Finger slap: very short high-mid noise
    slap = _bandpass_noise(t, 1200, 800, rng)
    slap_len = int(0.005 * SR)
    slap_env = np.zeros(len(t))
    slap_env[:slap_len] = np.exp(-np.linspace(0, 10, slap_len))
    amp = np.exp(-body_decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.72 + slap * slap_env * 0.38


def bongo_hi_techno() -> np.ndarray:
    """Techno hi bongo: tight, electronic, very short."""
    return _bongo_hi_base(620, 380, 28.0, 0.18, 2400)


def bongo_hi_house() -> np.ndarray:
    """House hi bongo: warm, punchy, short-medium."""
    return _bongo_hi_base(590, 360, 20.0, 0.22, 2401)


def bongo_hi_disco() -> np.ndarray:
    """Disco hi bongo: bright, prominent, grooving."""
    return _bongo_hi_base(640, 400, 17.0, 0.26, 2402)


def bongo_hi_jazz() -> np.ndarray:
    """Jazz hi bongo: soft, open, acoustic finger tone."""
    rng = np.random.default_rng(2403)
    dur = 0.35
    t = _t(dur)
    pitch_env = np.full(len(t), 420.0)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-13.0 * t)
    atk = int(0.004 * SR)
    amp[:atk] *= np.linspace(0.3, 1.0, atk)
    return body * amp * 0.68


def bongo_hi_rnb() -> np.ndarray:
    """R&B hi bongo: deep resonant high bongo, medium decay."""
    return _bongo_hi_base(560, 340, 14.0, 0.30, 2404)


def bongo_hi_afro() -> np.ndarray:
    """Afro hi bongo: tuned, open resonant tone, longer sustain."""
    rng = np.random.default_rng(2405)
    dur = 0.45
    t = _t(dur)
    pitch_env = 420 + (600 - 420) * np.exp(-28.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.14
    amp = np.exp(-11.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.76


def bongo_hi_latin() -> np.ndarray:
    """Latin hi bongo: very crisp slap, bright attack."""
    return _bongo_hi_base(660, 410, 26.0, 0.20, 2406)


def bongo_hi_funk() -> np.ndarray:
    """Funk hi bongo: snappy mid-high ping, punchy."""
    return _bongo_hi_base(600, 375, 24.0, 0.20, 2407)


def bongo_hi_rock() -> np.ndarray:
    """Rock hi bongo: hard, dry, fast decay."""
    return _bongo_hi_base(650, 400, 30.0, 0.17, 2408)


# ──────────────────────────────────────────────────────────────────────────────
# BONGO LO
# Low bongo ~250–450 Hz, slightly heavier attack.
# ──────────────────────────────────────────────────────────────────────────────

def _bongo_lo_base(f_start: float, f_end: float, body_decay: float,
                   dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    pitch_env = f_end + (f_start - f_end) * np.exp(-30.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.08
    slap = _bandpass_noise(t, 900, 600, rng)
    slap_len = int(0.007 * SR)
    slap_env = np.zeros(len(t))
    slap_env[:slap_len] = np.exp(-np.linspace(0, 9, slap_len))
    amp = np.exp(-body_decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.74 + slap * slap_env * 0.36


def bongo_lo_techno() -> np.ndarray:
    """Techno lo bongo: tight, electronic mid-thud."""
    return _bongo_lo_base(420, 240, 24.0, 0.22, 2500)


def bongo_lo_house() -> np.ndarray:
    """House lo bongo: warm, punchy."""
    return _bongo_lo_base(400, 230, 18.0, 0.27, 2501)


def bongo_lo_disco() -> np.ndarray:
    """Disco lo bongo: bright mid-low punch, bouncy."""
    return _bongo_lo_base(430, 250, 14.0, 0.30, 2502)


def bongo_lo_jazz() -> np.ndarray:
    """Jazz lo bongo: soft open tone, acoustic character."""
    rng = np.random.default_rng(2503)
    dur = 0.40
    t = _t(dur)
    pitch_env = np.full(len(t), 270.0)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-10.0 * t)
    atk = int(0.004 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return body * amp * 0.70


def bongo_lo_rnb() -> np.ndarray:
    """R&B lo bongo: deep resonant tone, medium-long decay."""
    return _bongo_lo_base(370, 210, 12.0, 0.38, 2504)


def bongo_lo_afro() -> np.ndarray:
    """Afro lo bongo: resonant open bass tone, long sustain."""
    rng = np.random.default_rng(2505)
    dur = 0.55
    t = _t(dur)
    pitch_env = 270 + (390 - 270) * np.exp(-22.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.10
    amp = np.exp(-9.0 * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.78


def bongo_lo_latin() -> np.ndarray:
    """Latin lo bongo: crisp, well-defined pitch, tight."""
    return _bongo_lo_base(445, 260, 22.0, 0.24, 2506)


def bongo_lo_funk() -> np.ndarray:
    """Funk lo bongo: punchy mid-low snap."""
    return _bongo_lo_base(410, 245, 20.0, 0.25, 2507)


def bongo_lo_rock() -> np.ndarray:
    """Rock lo bongo: hard, dry, forceful hit."""
    return _bongo_lo_base(440, 255, 26.0, 0.20, 2508)


# ──────────────────────────────────────────────────────────────────────────────
# CABASA
# Cabasa: metal-bead rattle. Synthesized as amplitude-modulated bandpass
# noise — a cycling scrape texture with rapid AM at ~20–50 Hz (the rotation
# rate) and bright high-frequency content.
# ──────────────────────────────────────────────────────────────────────────────

def _cabasa_base(scrape_rate: float, noise_center: float, decay: float,
                 dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    noise = _bandpass_noise(t, noise_center, noise_center * 0.5, rng)
    # Scrape AM: rapid amplitude modulation simulates bead rolling
    am = 0.5 + 0.5 * np.sin(2 * np.pi * scrape_rate * t)
    amp = np.exp(-decay * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * am * amp


def cabasa_techno() -> np.ndarray:
    """Techno cabasa: tight, fast scrape, electronic character."""
    return _cabasa_base(40.0, 6000, 45.0, 0.14, 2600)


def cabasa_house() -> np.ndarray:
    """House cabasa: crisp scrape, medium-short, funky groove."""
    return _cabasa_base(32.0, 5500, 35.0, 0.18, 2601)


def cabasa_disco() -> np.ndarray:
    """Disco cabasa: longer scrape, bright shimmer."""
    return _cabasa_base(28.0, 5000, 28.0, 0.24, 2602)


def cabasa_jazz() -> np.ndarray:
    """Jazz cabasa: slow soft scrape, warm bead texture."""
    return _cabasa_base(20.0, 4500, 20.0, 0.30, 2603)


def cabasa_rnb() -> np.ndarray:
    """R&B cabasa: smooth, mid-length scrape, laid-back."""
    return _cabasa_base(25.0, 5000, 30.0, 0.22, 2604)


def cabasa_afro() -> np.ndarray:
    """Afro cabasa: resonant bead scrape, longer sustain."""
    return _cabasa_base(22.0, 4800, 18.0, 0.35, 2605)


def cabasa_latin() -> np.ndarray:
    """Latin cabasa: fast, crisp, tight scrape articulation."""
    return _cabasa_base(38.0, 6200, 42.0, 0.16, 2606)


def cabasa_funk() -> np.ndarray:
    """Funk cabasa: snappy scrape with mid-forward presence."""
    return _cabasa_base(35.0, 5800, 40.0, 0.15, 2607)


def cabasa_rock() -> np.ndarray:
    """Rock cabasa: hard, bright, short scrape."""
    return _cabasa_base(45.0, 6500, 50.0, 0.12, 2608)


# ──────────────────────────────────────────────────────────────────────────────
# MARACAS
# Maracas: rapid seed-rattle burst. Very short high-frequency noise with
# a fast attack and very fast decay — distinct from shaker in being drier,
# harder, with a definite transient crack.
# ──────────────────────────────────────────────────────────────────────────────

def _maracas_base(noise_center: float, decay: float, dur: float,
                  rng_seed: int, crack_level: float = 0.3) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    noise = _bandpass_noise(t, noise_center, noise_center * 0.6, rng)
    # Crack transient
    crack_len = int(0.003 * SR)
    crack_noise = rng.standard_normal(len(t))
    crack_env = np.zeros(len(t))
    crack_env[:crack_len] = np.exp(-np.linspace(0, 12, crack_len))
    amp = np.exp(-decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return noise * amp + crack_noise * crack_env * crack_level


def maracas_techno() -> np.ndarray:
    """Techno maracas: tight, very dry, fast click-rattle."""
    return _maracas_base(8000, 90.0, 0.06, 2700, 0.4)


def maracas_house() -> np.ndarray:
    """House maracas: crisp rattle, short-medium."""
    return _maracas_base(7000, 70.0, 0.08, 2701, 0.35)


def maracas_disco() -> np.ndarray:
    """Disco maracas: bright, slightly longer rattle burst."""
    return _maracas_base(6500, 55.0, 0.10, 2702, 0.30)


def maracas_jazz() -> np.ndarray:
    """Jazz maracas: soft, warm rattle, acoustic character."""
    return _maracas_base(5500, 40.0, 0.12, 2703, 0.20)


def maracas_rnb() -> np.ndarray:
    """R&B maracas: smooth, medium-soft rattle."""
    return _maracas_base(6000, 55.0, 0.09, 2704, 0.25)


def maracas_afro() -> np.ndarray:
    """Afro maracas: resonant seed rattle, slight sustain."""
    return _maracas_base(5800, 38.0, 0.14, 2705, 0.22)


def maracas_latin() -> np.ndarray:
    """Latin maracas: bright, fast, very articulate rattle."""
    return _maracas_base(8500, 85.0, 0.07, 2706, 0.38)


def maracas_funk() -> np.ndarray:
    """Funk maracas: punchy crack, midrange presence."""
    return _maracas_base(7500, 75.0, 0.08, 2707, 0.40)


def maracas_rock() -> np.ndarray:
    """Rock maracas: hard, aggressive rattle, prominent transient."""
    return _maracas_base(8000, 95.0, 0.06, 2708, 0.50)


# ──────────────────────────────────────────────────────────────────────────────
# WOODBLOCK
# Woodblock: hard two-tone resonator. Two closely-spaced sine tones that
# produce a sharp, boxy click with very fast decay. Minimal noise.
# ──────────────────────────────────────────────────────────────────────────────

def _woodblk_base(f1: float, f2: float, decay: float, dur: float,
                  rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    body = (np.sin(2 * np.pi * f1 * t) * 0.6
            + np.sin(2 * np.pi * f2 * t) * 0.4)
    # Hard transient click
    click_len = int(0.002 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 12, click_len))
    amp = np.exp(-decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.75 + click * click_env * 0.35


def woodblk_techno() -> np.ndarray:
    """Techno woodblock: tight, hard, very short clatter."""
    return _woodblk_base(900, 1350, 55.0, 0.10, 2800)


def woodblk_house() -> np.ndarray:
    """House woodblock: crisp click, medium-short."""
    return _woodblk_base(820, 1230, 45.0, 0.12, 2801)


def woodblk_disco() -> np.ndarray:
    """Disco woodblock: bright, with slight body resonance."""
    return _woodblk_base(780, 1170, 38.0, 0.14, 2802)


def woodblk_jazz() -> np.ndarray:
    """Jazz woodblock: soft hollow knock, lower pitch."""
    return _woodblk_base(650, 980, 28.0, 0.18, 2803)


def woodblk_rnb() -> np.ndarray:
    """R&B woodblock: deep hollow click, slight resonance."""
    return _woodblk_base(700, 1050, 35.0, 0.15, 2804)


def woodblk_afro() -> np.ndarray:
    """Afro woodblock: tuned hollow log drum, resonant."""
    t = _t(0.22)
    f1, f2 = 600, 900
    body = (np.sin(2 * np.pi * f1 * t) * 0.65
            + np.sin(2 * np.pi * f2 * t) * 0.35
            + np.sin(2 * np.pi * f1 * 3 * t) * 0.08)
    amp = np.exp(-22.0 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return body * amp * 0.80


def woodblk_latin() -> np.ndarray:
    """Latin woodblock: crisp, very high-pitched, fast decay."""
    return _woodblk_base(1050, 1580, 60.0, 0.09, 2806)


def woodblk_funk() -> np.ndarray:
    """Funk woodblock: punchy mid-high click."""
    return _woodblk_base(860, 1290, 50.0, 0.11, 2807)


def woodblk_rock() -> np.ndarray:
    """Rock woodblock: hard, forceful knock."""
    return _woodblk_base(950, 1425, 58.0, 0.09, 2808)


# ──────────────────────────────────────────────────────────────────────────────
# AGOGO (cowbell-family metal bell)
# Agogo: two tuned metal bells, each a damped sinusoidal oscillator
# with harmonic partial stack. Higher pitched than cowbell (~800–1400 Hz).
# ──────────────────────────────────────────────────────────────────────────────

def _agogo_base(f_hi: float, f_lo: float, decay: float, dur: float,
                use_hi: bool = True) -> np.ndarray:
    """Single agogo bell hit — hi or lo pitch."""
    f = f_hi if use_hi else f_lo
    t = _t(dur)
    # Metallic partials with slight inharmonicity
    partials = [1.0, 2.76, 5.40, 8.93]
    sig = sum(np.sin(2 * np.pi * f * p * t) * (0.55 ** i)
              for i, p in enumerate(partials))
    sig = np.tanh(sig * 1.2)
    amp = np.exp(-decay * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return sig * amp


def agogo_techno() -> np.ndarray:
    """Techno agogo: tight, high metal ting, short decay."""
    return _agogo_base(1300, 900, 40.0, 0.18, use_hi=True)


def agogo_house() -> np.ndarray:
    """House agogo: crisp, medium-short, funky bell hit."""
    return _agogo_base(1200, 850, 30.0, 0.24, use_hi=True)


def agogo_disco() -> np.ndarray:
    """Disco agogo: bright bell, longer decay, mid-high ting."""
    return _agogo_base(1100, 800, 22.0, 0.32, use_hi=True)


def agogo_jazz() -> np.ndarray:
    """Jazz agogo: soft bell tone, lower pitch, longer sustain."""
    return _agogo_base(900, 650, 15.0, 0.45, use_hi=False)


def agogo_rnb() -> np.ndarray:
    """R&B agogo: medium-low bell, warm decay."""
    return _agogo_base(1000, 720, 20.0, 0.35, use_hi=False)


def agogo_afro() -> np.ndarray:
    """Afro agogo: resonant tuned metal bell, long sustain."""
    t = _t(0.55)
    f = 950.0
    partials = [1.0, 2.76, 5.40, 8.93, 13.2]
    sig = sum(np.sin(2 * np.pi * f * p * t) * (0.58 ** i)
              for i, p in enumerate(partials))
    amp = np.exp(-12.0 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0, 1, atk)
    return sig * amp


def agogo_latin() -> np.ndarray:
    """Latin agogo: very high, crisp, sharp bell articulation."""
    return _agogo_base(1500, 1050, 45.0, 0.16, use_hi=True)


def agogo_funk() -> np.ndarray:
    """Funk agogo: punchy metal ting, mid-forward."""
    return _agogo_base(1150, 820, 35.0, 0.20, use_hi=True)


def agogo_rock() -> np.ndarray:
    """Rock agogo: hard, forceful bell hit, short decay."""
    return _agogo_base(1350, 950, 48.0, 0.15, use_hi=True)


# ──────────────────────────────────────────────────────────────────────────────
# CRASH CYMBAL
# Crash: broad-spectrum inharmonic partials + lots of high-frequency noise.
# Bright attack, fast initial burst, longer noise tail. Distinct from the
# existing "Cymbal" (which is a ride/crash hybrid) — crash has a much faster
# attack explosion and shorter overall shape.
# ──────────────────────────────────────────────────────────────────────────────

def _crash_base(partial_freqs: list, noise_cutoff: float, decay: float,
                dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    sig = sum(np.sin(2 * np.pi * f * t) * (0.5 ** i)
              for i, f in enumerate(partial_freqs))
    noise = _highpass_noise(t, noise_cutoff, rng)
    # Bright initial burst
    burst = _highpass_noise(t, noise_cutoff * 1.5, rng)
    burst_amp = np.exp(-noise_cutoff * 0.0005 * t) * np.exp(-30.0 * t)
    amp = np.exp(-decay * t)
    return (sig * 0.35 + noise * 0.55) * amp + burst * burst_amp * 0.25


def crash_techno() -> np.ndarray:
    """Techno crash: sharp, metallic, industrial crash. Medium length."""
    return _crash_base([420, 780, 1300, 2200, 3700, 6000, 9500],
                       5500, 7.0, 0.80, 3000)


def crash_house() -> np.ndarray:
    """House crash: bright, clean crash with medium-fast decay."""
    return _crash_base([400, 760, 1250, 2100, 3500, 5800],
                       5000, 5.5, 1.0, 3001)


def crash_disco() -> np.ndarray:
    """Disco crash: wide, shimmering, long bright tail."""
    return _crash_base([380, 720, 1180, 2000, 3300, 5500, 8500],
                       4500, 4.0, 1.4, 3002)


def crash_jazz() -> np.ndarray:
    """Jazz crash: warm, musical crash. More harmonic, longer sustain."""
    rng = np.random.default_rng(3003)
    dur = 2.0
    t = _t(dur)
    partials = [620, 1180, 1850, 2600, 3700]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.54 ** i)
              for i, f in enumerate(partials))
    noise = _bandpass_noise(t, 3500, 4000, rng) * 0.30
    amp = np.exp(-2.8 * t)
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return (sig * 0.5 + noise) * amp


def crash_rnb() -> np.ndarray:
    """R&B crash: smooth, warm crash, medium-long decay."""
    return _crash_base([440, 830, 1380, 2350, 3900, 6500],
                       4200, 4.5, 1.2, 3004)


def crash_afro() -> np.ndarray:
    """Afro crash: large, resonant, slow-building crash with long tail."""
    rng = np.random.default_rng(3005)
    dur = 2.2
    t = _t(dur)
    partials = [360, 680, 1120, 1900, 3200, 5200]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.56 ** i)
              for i, f in enumerate(partials))
    noise = _highpass_noise(t, 4000, rng)
    amp = np.exp(-2.5 * t)
    atk = int(0.008 * SR)
    amp[:atk] *= np.linspace(0.1, 1.0, atk)
    return (sig * 0.4 + noise * 0.6) * amp


def crash_latin() -> np.ndarray:
    """Latin crash: bright, tight, fast decay."""
    return _crash_base([450, 860, 1440, 2450, 4100, 6800],
                       5800, 8.0, 0.70, 3006)


def crash_funk() -> np.ndarray:
    """Funk crash: punchy, forward, medium decay."""
    return _crash_base([430, 820, 1360, 2300, 3850, 6400],
                       5200, 6.0, 0.90, 3007)


def crash_rock() -> np.ndarray:
    """Rock crash: loud, aggressive, wall-of-sound crash."""
    rng = np.random.default_rng(3008)
    dur = 1.6
    t = _t(dur)
    partials = [380, 720, 1200, 2050, 3450, 5700, 9000]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.50 ** i)
              for i, f in enumerate(partials))
    noise = _highpass_noise(t, 4800, rng)
    burst = _highpass_noise(t, 7000, rng) * np.exp(-25.0 * t)
    amp = np.exp(-5.5 * t)
    return (sig * 0.38 + noise * 0.60) * amp + burst * 0.3


# ──────────────────────────────────────────────────────────────────────────────
# RIDE CYMBAL
# Ride: steady metallic shimmer, defined attack ping, long sustain.
# Higher pitched bell partials, moderate noise content, very long decay.
# Distinctly different from crash — less noise explosion, more tonal ping.
# ──────────────────────────────────────────────────────────────────────────────

def _ride_base(bell_freq: float, noise_center: float, decay: float,
               dur: float, rng_seed: int) -> np.ndarray:
    rng = np.random.default_rng(rng_seed)
    t = _t(dur)
    # Bell partials — ride has a very clear "ping" tone
    partials = [1.0, 2.25, 3.87, 5.40, 7.12, 9.80]
    bell = sum(np.sin(2 * np.pi * bell_freq * p * t) * (0.56 ** i)
               for i, p in enumerate(partials))
    # Wash noise
    noise = _bandpass_noise(t, noise_center, noise_center * 0.4, rng)
    amp = np.exp(-decay * t)
    atk = int(0.002 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return (bell * 0.55 + noise * 0.40) * amp


def ride_techno() -> np.ndarray:
    """Techno ride: metallic, industrial, medium-long sustain."""
    return _ride_base(780, 6000, 4.0, 1.5, 3100)


def ride_house() -> np.ndarray:
    """House ride: crisp bell, open shimmer, shuffling character."""
    return _ride_base(720, 5500, 3.2, 1.8, 3101)


def ride_disco() -> np.ndarray:
    """Disco ride: bright, long shimmer, prominent bell ping."""
    return _ride_base(680, 5000, 2.5, 2.2, 3102)


def ride_jazz() -> np.ndarray:
    """Jazz ride: the classic — warm, long, musical bell ring."""
    rng = np.random.default_rng(3103)
    dur = 3.0
    t = _t(dur)
    # Jazz ride: more harmonic partials, warmer
    partials = [1.0, 2.25, 3.87, 5.40, 7.12, 9.80, 12.5]
    bell = sum(np.sin(2 * np.pi * 620 * p * t) * (0.58 ** i)
               for i, p in enumerate(partials))
    noise = _bandpass_noise(t, 3500, 1500, rng) * 0.20
    amp = np.exp(-1.8 * t)
    atk = int(0.004 * SR)
    amp[:atk] *= np.linspace(0.1, 1.0, atk)
    return (bell * 0.60 + noise) * amp


def ride_rnb() -> np.ndarray:
    """R&B ride: smooth, musical, medium-long decay."""
    return _ride_base(660, 5200, 3.0, 2.0, 3104)


def ride_afro() -> np.ndarray:
    """Afro ride: large resonant bell, very long sustain."""
    rng = np.random.default_rng(3105)
    dur = 3.5
    t = _t(dur)
    partials = [1.0, 2.25, 3.87, 5.40, 7.12]
    bell = sum(np.sin(2 * np.pi * 580 * p * t) * (0.60 ** i)
               for i, p in enumerate(partials))
    shimmer = 1.0 + 0.1 * np.sin(2 * np.pi * 80 * t)
    amp = np.exp(-1.5 * t)
    atk = int(0.005 * SR)
    amp[:atk] *= np.linspace(0.1, 1.0, atk)
    return bell * shimmer * amp * 0.72


def ride_latin() -> np.ndarray:
    """Latin ride: bright, tight bell ping, clear articulation."""
    return _ride_base(820, 6500, 4.5, 1.3, 3106)


def ride_funk() -> np.ndarray:
    """Funk ride: punchy bell, forward presence, medium sustain."""
    return _ride_base(750, 5800, 3.8, 1.6, 3107)


def ride_rock() -> np.ndarray:
    """Rock ride: loud, defined bell ping, aggressive wash."""
    rng = np.random.default_rng(3108)
    dur = 2.0
    t = _t(dur)
    partials = [1.0, 2.25, 3.87, 5.40, 7.12, 9.80]
    bell = sum(np.sin(2 * np.pi * 800 * p * t) * (0.54 ** i)
               for i, p in enumerate(partials))
    noise = _highpass_noise(t, 5500, rng)
    amp = np.exp(-3.5 * t)
    atk = int(0.001 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return (bell * 0.55 + noise * 0.50) * amp


# ──────────────────────────────────────────────────────────────────────────────
# NEW VARIATIONS for existing 10 categories
# (Afro, Latin, Funk, Rock × Kick, Snare, Cl.Hat, Op.Hat, Clap,
#  Tom Hi, Tom Lo, Rim, Cowbell, Cymbal)
# ──────────────────────────────────────────────────────────────────────────────

# ── KICK: Afro, Latin, Funk, Rock ─────────────────────────────────────────────

def kick_afro() -> np.ndarray:
    """Afro kick: tuned resonant bass drum, 60Hz, long sustain."""
    rng = np.random.default_rng(105)
    dur = 0.80
    t = _t(dur)
    f_start, f_end = 90.0, 55.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-12.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.08
    amp = np.exp(-5.0 * t)
    click_len = int(0.005 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))
    return body * amp * 0.82 + click * click_env * 0.20


def kick_latin() -> np.ndarray:
    """Latin kick: punchy, mid-pitch, tight decay — tumbao feel."""
    rng = np.random.default_rng(106)
    dur = 0.40
    t = _t(dur)
    f_start, f_end = 110.0, 60.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-20.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-10.0 * t)
    click_len = int(0.003 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 9, click_len))
    return body * amp * 0.83 + click * click_env * 0.28


def kick_funk() -> np.ndarray:
    """Funk kick: tight, punchy, mid-forward. JB/Maceo style."""
    rng = np.random.default_rng(107)
    dur = 0.45
    t = _t(dur)
    f_start, f_end = 105.0, 55.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-22.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    distort = np.tanh(body * 1.8) * 0.12
    amp = np.exp(-9.0 * t)
    click_len = int(0.003 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 10, click_len))
    return (body * amp * 0.82 + distort * amp + click * click_env * 0.30)


def kick_rock() -> np.ndarray:
    """Rock kick: loud, punchy, big mid-bass thud. Bonham-esque."""
    rng = np.random.default_rng(108)
    dur = 0.55
    t = _t(dur)
    f_start, f_end = 95.0, 48.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-16.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-7.0 * t)
    click_len = int(0.005 * SR)
    click = _lowpass_noise(t, 5000, rng)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 6, click_len))
    distort = np.tanh(body * 1.3) * 0.18
    return body * amp * 0.85 + click * click_env * 0.32 + distort * amp


# ── SNARE: Afro, Latin, Funk, Rock ────────────────────────────────────────────

def snare_afro() -> np.ndarray:
    """Afro snare: warm resonant snare, medium decay, open sound."""
    rng = np.random.default_rng(205)
    dur = 0.45
    t = _t(dur)
    body = (np.sin(2 * np.pi * 170 * t) * 0.55
            + np.sin(2 * np.pi * 270 * t) * 0.45)
    body_amp = np.exp(-12.0 * t)
    noise = _bandpass_noise(t, 2500, 3500, rng)
    noise_amp = np.exp(-9.0 * t)
    return body * body_amp * 0.48 + noise * noise_amp * 0.60


def snare_latin() -> np.ndarray:
    """Latin snare: tight rimshot-influenced, crisp, dry."""
    rng = np.random.default_rng(206)
    dur = 0.25
    t = _t(dur)
    body = (np.sin(2 * np.pi * 220 * t) * 0.55
            + np.sin(2 * np.pi * 380 * t) * 0.45)
    body_amp = np.exp(-28.0 * t)
    noise = _highpass_noise(t, 3500, rng)
    noise_amp = np.exp(-22.0 * t)
    click_len = int(0.002 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 10, click_len))
    return body * body_amp * 0.5 + noise * noise_amp * 0.65 + click * click_env * 0.35


def snare_funk() -> np.ndarray:
    """Funk snare: fat, cracking snare. Deep resonance, bright crack."""
    rng = np.random.default_rng(207)
    dur = 0.35
    t = _t(dur)
    body = (np.sin(2 * np.pi * 175 * t) * 0.60
            + np.sin(2 * np.pi * 280 * t) * 0.40)
    body_amp = np.exp(-16.0 * t)
    noise = _highpass_noise(t, 2500, rng)
    noise_amp = np.exp(-14.0 * t)
    # Crack layer
    crack_len = int(0.003 * SR)
    crack = rng.standard_normal(len(t))
    crack_env = np.zeros(len(t))
    crack_env[:crack_len] = np.exp(-np.linspace(0, 9, crack_len))
    return body * body_amp * 0.50 + noise * noise_amp * 0.65 + crack * crack_env * 0.45


def snare_rock() -> np.ndarray:
    """Rock snare: loud, fat backbeat snare. Full body, bright crack."""
    rng = np.random.default_rng(208)
    dur = 0.50
    t = _t(dur)
    body = (np.sin(2 * np.pi * 185 * t) * 0.55
            + np.sin(2 * np.pi * 310 * t) * 0.35
            + np.sin(2 * np.pi * 480 * t) * 0.10)
    body_amp = np.exp(-11.0 * t)
    noise = _highpass_noise(t, 2200, rng)
    noise_amp = np.exp(-10.0 * t)
    reverb = rng.standard_normal(len(t)) * np.exp(-5.0 * t) * 0.20
    return body * body_amp * 0.52 + noise * noise_amp * 0.62 + reverb


# ── CLHAT: Afro, Latin, Funk, Rock ────────────────────────────────────────────

def clhat_afro() -> np.ndarray:
    """Afro closed hi-hat: slightly warm, medium-short, crisp."""
    rng = np.random.default_rng(305)
    dur = 0.14
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 560.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.56 ** i)
              for i, p in enumerate(partials))
    noise = _bandpass_noise(t, 4800, 3500, rng)
    amp = np.exp(-58.0 * t)
    return (sig * 0.48 + noise * 0.60) * amp


def clhat_latin() -> np.ndarray:
    """Latin closed hi-hat: very tight, sharp, fast articulation."""
    rng = np.random.default_rng(306)
    dur = 0.07
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53, 8.19]
    base_freq = 660.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.58 ** i)
              for i, p in enumerate(partials))
    noise = _highpass_noise(t, 6500, rng)
    amp = np.exp(-100.0 * t)
    return (sig * 0.50 + noise * 0.60) * amp


def clhat_funk() -> np.ndarray:
    """Funk closed hi-hat: tight chick, punchy, mid-forward."""
    rng = np.random.default_rng(307)
    dur = 0.10
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67]
    base_freq = 590.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.57 ** i)
              for i, p in enumerate(partials))
    noise = _bandpass_noise(t, 5000, 3000, rng)
    amp = np.exp(-75.0 * t)
    return (sig * 0.52 + noise * 0.58) * amp


def clhat_rock() -> np.ndarray:
    """Rock closed hi-hat: hard, dry, tight."""
    rng = np.random.default_rng(308)
    dur = 0.08
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 620.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.58 ** i)
              for i, p in enumerate(partials))
    noise = _highpass_noise(t, 6000, rng)
    amp = np.exp(-90.0 * t)
    return (sig * 0.50 + noise * 0.62) * amp


# ── OPHAT: Afro, Latin, Funk, Rock ────────────────────────────────────────────

def ophat_afro() -> np.ndarray:
    """Afro open hi-hat: warm shimmer, long, resonant sustain."""
    rng = np.random.default_rng(405)
    dur = 0.85
    t = _t(dur)
    partials = [1.0, 1.8, 2.7, 3.9, 5.1, 6.7]
    base_freq = 530.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.53 ** i)
              for i, p in enumerate(partials))
    noise = _bandpass_noise(t, 4000, 3000, rng)
    amp = np.exp(-5.5 * t)
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0.3, 1.0, atk)
    return (sig * 0.48 + noise * 0.52) * amp


def ophat_latin() -> np.ndarray:
    """Latin open hi-hat: bright, crisp, fast decay."""
    rng = np.random.default_rng(406)
    dur = 0.35
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 660.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.56 ** i)
              for i, p in enumerate(partials))
    noise = _highpass_noise(t, 5500, rng)
    amp = np.exp(-14.0 * t)
    return (sig * 0.5 + noise * 0.65) * amp


def ophat_funk() -> np.ndarray:
    """Funk open hi-hat: medium-length, punchy, 16th-note groove."""
    rng = np.random.default_rng(407)
    dur = 0.50
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53]
    base_freq = 590.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.57 ** i)
              for i, p in enumerate(partials))
    noise = _bandpass_noise(t, 5000, 3500, rng)
    amp = np.exp(-10.0 * t)
    return (sig * 0.50 + noise * 0.62) * amp


def ophat_rock() -> np.ndarray:
    """Rock open hi-hat: bright, aggressive, hard-struck."""
    rng = np.random.default_rng(408)
    dur = 0.55
    t = _t(dur)
    partials = [2.0, 3.14, 4.28, 5.67, 6.53, 8.19]
    base_freq = 620.0
    sig = sum(np.sin(2 * np.pi * base_freq * p * t) * (0.58 ** i)
              for i, p in enumerate(partials))
    noise = _highpass_noise(t, 5800, rng)
    amp = np.exp(-9.5 * t)
    return (sig * 0.50 + noise * 0.68) * amp


# ── CLAP: Afro, Latin, Funk, Rock ─────────────────────────────────────────────

def clap_afro() -> np.ndarray:
    """Afro clap: warm handclap, resonant, slightly hollow."""
    rng = np.random.default_rng(505)
    dur = 0.35
    t = _t(dur)
    noise = _bandpass_noise(t, 2000, 3500, rng)
    offsets = [0.000, 0.011, 0.022]
    env = sum(np.exp(-450 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-10.0 * t)
    return noise * env * 0.80


def clap_latin() -> np.ndarray:
    """Latin clap: dry, sharp, very fast burst."""
    rng = np.random.default_rng(506)
    dur = 0.15
    t = _t(dur)
    noise = _highpass_noise(t, 2500, rng)
    offsets = [0.000, 0.006, 0.012]
    env = sum(np.exp(-900 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-22.0 * t)
    return noise * env


def clap_funk() -> np.ndarray:
    """Funk clap: fat, snapping, layered clap. Classic funk snap."""
    rng = np.random.default_rng(507)
    dur = 0.30
    t = _t(dur)
    noise_hi = _highpass_noise(t, 2800, rng)
    noise_mid = _bandpass_noise(t, 1500, 2800, rng)
    offsets = [0.000, 0.008, 0.016, 0.024]
    env = sum(np.exp(-600 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-14.0 * t)
    reverb = rng.standard_normal(len(t)) * np.exp(-7.0 * t) * 0.18
    return (noise_hi * 0.55 + noise_mid * 0.45) * env + reverb


def clap_rock() -> np.ndarray:
    """Rock clap: loud, forceful, wide-frequency handclap."""
    rng = np.random.default_rng(508)
    dur = 0.40
    t = _t(dur)
    noise = _bandpass_noise(t, 2200, 5000, rng)
    offsets = [0.000, 0.010, 0.020, 0.030]
    env = sum(np.exp(-550 * (t - d) ** 2) for d in offsets)
    env *= np.exp(-11.0 * t)
    tail = rng.standard_normal(len(t)) * np.exp(-6.5 * t) * 0.22
    return noise * env + tail


# ── TOM HI: Afro, Latin, Funk, Rock ───────────────────────────────────────────

def tom_hi_afro() -> np.ndarray:
    """Afro hi tom: tuned, resonant, long sustain."""
    rng = np.random.default_rng(605)
    dur = 0.55
    t = _t(dur)
    f_start, f_end = 300.0, 195.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-14.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.10
    amp = np.exp(-9.0 * t)
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return body * amp * 0.78


def tom_hi_latin() -> np.ndarray:
    """Latin hi tom: tight, bright, rimshot-like character."""
    rng = np.random.default_rng(606)
    dur = 0.28
    t = _t(dur)
    f_start, f_end = 360.0, 215.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-22.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    noise = rng.standard_normal(len(t))
    click_len = int(0.003 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 9, click_len))
    amp = np.exp(-20.0 * t)
    return body * amp * 0.84 + noise * click_env * 0.32


def tom_hi_funk() -> np.ndarray:
    """Funk hi tom: punchy, mid-forward, tight pop."""
    rng = np.random.default_rng(607)
    dur = 0.32
    t = _t(dur)
    f_start, f_end = 330.0, 200.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-20.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    noise = rng.standard_normal(len(t))
    click_len = int(0.003 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))
    amp = np.exp(-17.0 * t)
    return body * amp * 0.85 + noise * click_env * 0.30


def tom_hi_rock() -> np.ndarray:
    """Rock hi tom: big, loud, full-frequency tom crack."""
    rng = np.random.default_rng(608)
    dur = 0.50
    t = _t(dur)
    f_start, f_end = 320.0, 190.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-14.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.08
    noise = _lowpass_noise(t, 5000, rng)
    click_len = int(0.005 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 6, click_len))
    amp = np.exp(-11.0 * t)
    return body * amp * 0.82 + noise * click_env * 0.32


# ── TOM LO: Afro, Latin, Funk, Rock ───────────────────────────────────────────

def tom_lo_afro() -> np.ndarray:
    """Afro lo tom: deep resonant floor tom, long sustain."""
    rng = np.random.default_rng(705)
    dur = 0.70
    t = _t(dur)
    f_start, f_end = 130.0, 75.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-12.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.10
    amp = np.exp(-7.0 * t)
    atk = int(0.003 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return body * amp * 0.80


def tom_lo_latin() -> np.ndarray:
    """Latin lo tom: tight, defined pitch, crisp attack."""
    rng = np.random.default_rng(706)
    dur = 0.38
    t = _t(dur)
    f_start, f_end = 155.0, 88.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-18.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    noise = rng.standard_normal(len(t))
    click_len = int(0.003 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))
    amp = np.exp(-16.0 * t)
    return body * amp * 0.86 + noise * click_env * 0.28


def tom_lo_funk() -> np.ndarray:
    """Funk lo tom: punchy mid-bass thud."""
    rng = np.random.default_rng(707)
    dur = 0.45
    t = _t(dur)
    f_start, f_end = 145.0, 82.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-16.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase)
    amp = np.exp(-13.0 * t)
    noise = rng.standard_normal(len(t))
    click_len = int(0.003 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 8, click_len))
    return body * amp * 0.86 + noise * click_env * 0.28


def tom_lo_rock() -> np.ndarray:
    """Rock lo tom: massive floor tom, long booming decay."""
    rng = np.random.default_rng(708)
    dur = 0.80
    t = _t(dur)
    f_start, f_end = 140.0, 72.0
    pitch_env = f_end + (f_start - f_end) * np.exp(-12.0 * t)
    phase = 2 * np.pi * np.cumsum(pitch_env) / SR
    body = np.sin(phase) + np.sin(phase * 2) * 0.10
    noise = _lowpass_noise(t, 4500, rng)
    click_len = int(0.006 * SR)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 5, click_len))
    amp = np.exp(-6.5 * t)
    return body * amp * 0.84 + noise * click_env * 0.28


# ── RIM: Afro, Latin, Funk, Rock ──────────────────────────────────────────────

def rim_afro() -> np.ndarray:
    """Afro rim: warm stick-on-rim, medium decay."""
    rng = np.random.default_rng(805)
    dur = 0.22
    t = _t(dur)
    body = (np.sin(2 * np.pi * 780 * t) * 0.58
            + np.sin(2 * np.pi * 1200 * t) * 0.42)
    body_amp = np.exp(-26.0 * t)
    click_len = int(0.004 * SR)
    click = _lowpass_noise(t, 5500, rng)
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 7, click_len))
    return body * body_amp * 0.62 + click * click_env * 0.36


def rim_latin() -> np.ndarray:
    """Latin rim: very tight, high-pitched, bright click."""
    rng = np.random.default_rng(806)
    dur = 0.10
    t = _t(dur)
    body = (np.sin(2 * np.pi * 1200 * t) * 0.6
            + np.sin(2 * np.pi * 1900 * t) * 0.4)
    body_amp = np.exp(-55.0 * t)
    click_len = int(0.002 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 12, click_len))
    return body * body_amp * 0.68 + click * click_env * 0.50


def rim_funk() -> np.ndarray:
    """Funk rim: snappy cross-stick with mid-presence."""
    rng = np.random.default_rng(807)
    dur = 0.14
    t = _t(dur)
    body = (np.sin(2 * np.pi * 920 * t) * 0.58
            + np.sin(2 * np.pi * 1460 * t) * 0.42)
    body_amp = np.exp(-42.0 * t)
    click_len = int(0.003 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 10, click_len))
    return body * body_amp * 0.65 + click * click_env * 0.48


def rim_rock() -> np.ndarray:
    """Rock rim: hard cross-stick, very snappy."""
    rng = np.random.default_rng(808)
    dur = 0.12
    t = _t(dur)
    body = (np.sin(2 * np.pi * 1100 * t) * 0.58
            + np.sin(2 * np.pi * 1750 * t) * 0.42)
    body_amp = np.exp(-50.0 * t)
    click_len = int(0.002 * SR)
    click = rng.standard_normal(len(t))
    click_env = np.zeros(len(t))
    click_env[:click_len] = np.exp(-np.linspace(0, 11, click_len))
    return body * body_amp * 0.67 + click * click_env * 0.52


# ── COWBELL: Afro, Latin, Funk, Rock ──────────────────────────────────────────

def cowbell_afro() -> np.ndarray:
    """Afro cowbell: resonant, lower pitch, long sustain."""
    return _cowbell_base(460, 690, 7.0, 0.80, mix1=0.52, mix2=0.48)


def cowbell_latin() -> np.ndarray:
    """Latin cowbell: high, crisp, very tight — clave-adjacent."""
    return _cowbell_base(600, 900, 30.0, 0.20, mix1=0.58, mix2=0.42)


def cowbell_funk() -> np.ndarray:
    """Funk cowbell: medium punch, wide groove, mid-range."""
    return _cowbell_base(555, 832, 17.0, 0.42, mix1=0.56, mix2=0.44)


def cowbell_rock() -> np.ndarray:
    """Rock cowbell: bright, punchy, short decay."""
    return _cowbell_base(580, 870, 28.0, 0.28, mix1=0.60, mix2=0.40)


# ── CYMBAL: Afro, Latin, Funk, Rock ───────────────────────────────────────────

def cymbal_afro() -> np.ndarray:
    """Afro cymbal: large, warm, very long sustain — gong-like shimmer."""
    rng = np.random.default_rng(1005)
    dur = 3.0
    t = _t(dur)
    partials = [350, 680, 1100, 1900, 3100, 5000, 7800]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.57 ** i)
              for i, f in enumerate(partials))
    noise = _bandpass_noise(t, 3500, 4500, rng) * 0.20
    amp = np.exp(-2.0 * t)
    atk = int(0.006 * SR)
    amp[:atk] *= np.linspace(0.2, 1.0, atk)
    return (sig * 0.55 + noise) * amp


def cymbal_latin() -> np.ndarray:
    """Latin cymbal: bright, tight crash, short decay."""
    rng = np.random.default_rng(1006)
    dur = 0.80
    t = _t(dur)
    partials = [460, 880, 1480, 2520, 4200, 7000]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.52 ** i)
              for i, f in enumerate(partials))
    noise = _highpass_noise(t, 5500, rng)
    amp = np.exp(-7.0 * t)
    return (sig * 0.42 + noise * 0.65) * amp


def cymbal_funk() -> np.ndarray:
    """Funk cymbal: punchy crash, medium decay, forward presence."""
    rng = np.random.default_rng(1007)
    dur = 1.2
    t = _t(dur)
    partials = [420, 800, 1340, 2280, 3820, 6380]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.53 ** i)
              for i, f in enumerate(partials))
    noise = _bandpass_noise(t, 4500, 5500, rng)
    amp = np.exp(-5.0 * t)
    return (sig * 0.44 + noise * 0.62) * amp


def cymbal_rock() -> np.ndarray:
    """Rock cymbal: aggressive, wide-spectrum, long crash."""
    rng = np.random.default_rng(1008)
    dur = 2.0
    t = _t(dur)
    partials = [380, 720, 1200, 2050, 3450, 5700, 9000]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.50 ** i)
              for i, f in enumerate(partials))
    noise = _highpass_noise(t, 4500, rng)
    amp = np.exp(-4.0 * t)
    return (sig * 0.40 + noise * 0.68) * amp


# ──────────────────────────────────────────────────────────────────────────────
# GENERATOR MAP
# ──────────────────────────────────────────────────────────────────────────────

GENERATORS = {
    # ── Kicks ────────────────────────────────────────────────────────────────
    "kick_techno":       kick_techno,
    "kick_house":        kick_house,
    "kick_disco":        kick_disco,
    "kick_jazz":         kick_jazz,
    "kick_rnb":          kick_rnb,
    "kick_afro":         kick_afro,
    "kick_latin":        kick_latin,
    "kick_funk":         kick_funk,
    "kick_rock":         kick_rock,
    # ── Snares ───────────────────────────────────────────────────────────────
    "snare_techno":      snare_techno,
    "snare_house":       snare_house,
    "snare_disco":       snare_disco,
    "snare_jazz":        snare_jazz,
    "snare_rnb":         snare_rnb,
    "snare_afro":        snare_afro,
    "snare_latin":       snare_latin,
    "snare_funk":        snare_funk,
    "snare_rock":        snare_rock,
    # ── Closed hi-hats ───────────────────────────────────────────────────────
    "clhat_techno":      clhat_techno,
    "clhat_house":       clhat_house,
    "clhat_disco":       clhat_disco,
    "clhat_jazz":        clhat_jazz,
    "clhat_rnb":         clhat_rnb,
    "clhat_afro":        clhat_afro,
    "clhat_latin":       clhat_latin,
    "clhat_funk":        clhat_funk,
    "clhat_rock":        clhat_rock,
    # ── Open hi-hats ─────────────────────────────────────────────────────────
    "ophat_techno":      ophat_techno,
    "ophat_house":       ophat_house,
    "ophat_disco":       ophat_disco,
    "ophat_jazz":        ophat_jazz,
    "ophat_rnb":         ophat_rnb,
    "ophat_afro":        ophat_afro,
    "ophat_latin":       ophat_latin,
    "ophat_funk":        ophat_funk,
    "ophat_rock":        ophat_rock,
    # ── Claps ────────────────────────────────────────────────────────────────
    "clap_techno":       clap_techno,
    "clap_house":        clap_house,
    "clap_disco":        clap_disco,
    "clap_jazz":         clap_jazz,
    "clap_rnb":          clap_rnb,
    "clap_afro":         clap_afro,
    "clap_latin":        clap_latin,
    "clap_funk":         clap_funk,
    "clap_rock":         clap_rock,
    # ── Hi toms ──────────────────────────────────────────────────────────────
    "tom_hi_techno":     tom_hi_techno,
    "tom_hi_house":      tom_hi_house,
    "tom_hi_disco":      tom_hi_disco,
    "tom_hi_jazz":       tom_hi_jazz,
    "tom_hi_rnb":        tom_hi_rnb,
    "tom_hi_afro":       tom_hi_afro,
    "tom_hi_latin":      tom_hi_latin,
    "tom_hi_funk":       tom_hi_funk,
    "tom_hi_rock":       tom_hi_rock,
    # ── Lo toms ──────────────────────────────────────────────────────────────
    "tom_lo_techno":     tom_lo_techno,
    "tom_lo_house":      tom_lo_house,
    "tom_lo_disco":      tom_lo_disco,
    "tom_lo_jazz":       tom_lo_jazz,
    "tom_lo_rnb":        tom_lo_rnb,
    "tom_lo_afro":       tom_lo_afro,
    "tom_lo_latin":      tom_lo_latin,
    "tom_lo_funk":       tom_lo_funk,
    "tom_lo_rock":       tom_lo_rock,
    # ── Rimshots ─────────────────────────────────────────────────────────────
    "rim_techno":        rim_techno,
    "rim_house":         rim_house,
    "rim_disco":         rim_disco,
    "rim_jazz":          rim_jazz,
    "rim_rnb":           rim_rnb,
    "rim_afro":          rim_afro,
    "rim_latin":         rim_latin,
    "rim_funk":          rim_funk,
    "rim_rock":          rim_rock,
    # ── Cowbells ─────────────────────────────────────────────────────────────
    "cowbell_techno":    cowbell_techno,
    "cowbell_house":     cowbell_house,
    "cowbell_disco":     cowbell_disco,
    "cowbell_jazz":      cowbell_jazz,
    "cowbell_rnb":       cowbell_rnb,
    "cowbell_afro":      cowbell_afro,
    "cowbell_latin":     cowbell_latin,
    "cowbell_funk":      cowbell_funk,
    "cowbell_rock":      cowbell_rock,
    # ── Cymbals ──────────────────────────────────────────────────────────────
    "cymbal_techno":     cymbal_techno,
    "cymbal_house":      cymbal_house,
    "cymbal_disco":      cymbal_disco,
    "cymbal_jazz":       cymbal_jazz,
    "cymbal_rnb":        cymbal_rnb,
    "cymbal_afro":       cymbal_afro,
    "cymbal_latin":      cymbal_latin,
    "cymbal_funk":       cymbal_funk,
    "cymbal_rock":       cymbal_rock,
    # ── Shakers ──────────────────────────────────────────────────────────────
    "shaker_techno":     shaker_techno,
    "shaker_house":      shaker_house,
    "shaker_disco":      shaker_disco,
    "shaker_jazz":       shaker_jazz,
    "shaker_rnb":        shaker_rnb,
    "shaker_afro":       shaker_afro,
    "shaker_latin":      shaker_latin,
    "shaker_funk":       shaker_funk,
    "shaker_rock":       shaker_rock,
    # ── Tambourines ──────────────────────────────────────────────────────────
    "tambourn_techno":   tambourn_techno,
    "tambourn_house":    tambourn_house,
    "tambourn_disco":    tambourn_disco,
    "tambourn_jazz":     tambourn_jazz,
    "tambourn_rnb":      tambourn_rnb,
    "tambourn_afro":     tambourn_afro,
    "tambourn_latin":    tambourn_latin,
    "tambourn_funk":     tambourn_funk,
    "tambourn_rock":     tambourn_rock,
    # ── Conga Hi ─────────────────────────────────────────────────────────────
    "conga_hi_techno":   conga_hi_techno,
    "conga_hi_house":    conga_hi_house,
    "conga_hi_disco":    conga_hi_disco,
    "conga_hi_jazz":     conga_hi_jazz,
    "conga_hi_rnb":      conga_hi_rnb,
    "conga_hi_afro":     conga_hi_afro,
    "conga_hi_latin":    conga_hi_latin,
    "conga_hi_funk":     conga_hi_funk,
    "conga_hi_rock":     conga_hi_rock,
    # ── Conga Lo ─────────────────────────────────────────────────────────────
    "conga_lo_techno":   conga_lo_techno,
    "conga_lo_house":    conga_lo_house,
    "conga_lo_disco":    conga_lo_disco,
    "conga_lo_jazz":     conga_lo_jazz,
    "conga_lo_rnb":      conga_lo_rnb,
    "conga_lo_afro":     conga_lo_afro,
    "conga_lo_latin":    conga_lo_latin,
    "conga_lo_funk":     conga_lo_funk,
    "conga_lo_rock":     conga_lo_rock,
    # ── Bongo Hi ─────────────────────────────────────────────────────────────
    "bongo_hi_techno":   bongo_hi_techno,
    "bongo_hi_house":    bongo_hi_house,
    "bongo_hi_disco":    bongo_hi_disco,
    "bongo_hi_jazz":     bongo_hi_jazz,
    "bongo_hi_rnb":      bongo_hi_rnb,
    "bongo_hi_afro":     bongo_hi_afro,
    "bongo_hi_latin":    bongo_hi_latin,
    "bongo_hi_funk":     bongo_hi_funk,
    "bongo_hi_rock":     bongo_hi_rock,
    # ── Bongo Lo ─────────────────────────────────────────────────────────────
    "bongo_lo_techno":   bongo_lo_techno,
    "bongo_lo_house":    bongo_lo_house,
    "bongo_lo_disco":    bongo_lo_disco,
    "bongo_lo_jazz":     bongo_lo_jazz,
    "bongo_lo_rnb":      bongo_lo_rnb,
    "bongo_lo_afro":     bongo_lo_afro,
    "bongo_lo_latin":    bongo_lo_latin,
    "bongo_lo_funk":     bongo_lo_funk,
    "bongo_lo_rock":     bongo_lo_rock,
    # ── Cabasa ───────────────────────────────────────────────────────────────
    "cabasa_techno":     cabasa_techno,
    "cabasa_house":      cabasa_house,
    "cabasa_disco":      cabasa_disco,
    "cabasa_jazz":       cabasa_jazz,
    "cabasa_rnb":        cabasa_rnb,
    "cabasa_afro":       cabasa_afro,
    "cabasa_latin":      cabasa_latin,
    "cabasa_funk":       cabasa_funk,
    "cabasa_rock":       cabasa_rock,
    # ── Maracas ──────────────────────────────────────────────────────────────
    "maracas_techno":    maracas_techno,
    "maracas_house":     maracas_house,
    "maracas_disco":     maracas_disco,
    "maracas_jazz":      maracas_jazz,
    "maracas_rnb":       maracas_rnb,
    "maracas_afro":      maracas_afro,
    "maracas_latin":     maracas_latin,
    "maracas_funk":      maracas_funk,
    "maracas_rock":      maracas_rock,
    # ── Woodblock ────────────────────────────────────────────────────────────
    "woodblk_techno":    woodblk_techno,
    "woodblk_house":     woodblk_house,
    "woodblk_disco":     woodblk_disco,
    "woodblk_jazz":      woodblk_jazz,
    "woodblk_rnb":       woodblk_rnb,
    "woodblk_afro":      woodblk_afro,
    "woodblk_latin":     woodblk_latin,
    "woodblk_funk":      woodblk_funk,
    "woodblk_rock":      woodblk_rock,
    # ── Agogo ────────────────────────────────────────────────────────────────
    "agogo_techno":      agogo_techno,
    "agogo_house":       agogo_house,
    "agogo_disco":       agogo_disco,
    "agogo_jazz":        agogo_jazz,
    "agogo_rnb":         agogo_rnb,
    "agogo_afro":        agogo_afro,
    "agogo_latin":       agogo_latin,
    "agogo_funk":        agogo_funk,
    "agogo_rock":        agogo_rock,
    # ── Crash cymbal ─────────────────────────────────────────────────────────
    "crash_techno":      crash_techno,
    "crash_house":       crash_house,
    "crash_disco":       crash_disco,
    "crash_jazz":        crash_jazz,
    "crash_rnb":         crash_rnb,
    "crash_afro":        crash_afro,
    "crash_latin":       crash_latin,
    "crash_funk":        crash_funk,
    "crash_rock":        crash_rock,
    # ── Ride cymbal ──────────────────────────────────────────────────────────
    "ride_techno":       ride_techno,
    "ride_house":        ride_house,
    "ride_disco":        ride_disco,
    "ride_jazz":         ride_jazz,
    "ride_rnb":          ride_rnb,
    "ride_afro":         ride_afro,
    "ride_latin":        ride_latin,
    "ride_funk":         ride_funk,
    "ride_rock":         ride_rock,
}


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Generating up to {len(GENERATORS)} drum samples into {OUT_DIR}/")
    print()

    categories = [
        "kick", "snare", "clhat", "ophat", "clap",
        "tom_hi", "tom_lo", "rim", "cowbell", "cymbal",
        "shaker", "tambourn", "conga_hi", "conga_lo",
        "bongo_hi", "bongo_lo", "cabasa", "maracas",
        "woodblk", "agogo", "crash", "ride",
    ]
    genres = ["techno", "house", "disco", "jazz", "rnb",
              "afro", "latin", "funk", "rock"]

    wrote = 0
    skipped = 0
    warned = 0
    for cat in categories:
        print(f"  [{cat}]")
        for genre in genres:
            key = f"{cat}_{genre}"
            fn = GENERATORS.get(key)
            if fn is None:
                print(f"    WARNING: no generator for {key}")
                warned += 1
                continue
            signal = fn()
            path = os.path.join(OUT_DIR, f"{key}.wav")
            if os.path.exists(path):
                print(f"    skip  {key}.wav (exists)")
                skipped += 1
            else:
                _write(key, signal)
                wrote += 1
        print()

    total = wrote + skipped
    print(f"Done. {total} samples processed ({wrote} written, {skipped} skipped"
          + (f", {warned} warnings" if warned else "") + ").")
