"""tests/test_engines.py — Unit tests for DrumEngine, SynthVoice, SynthEngine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest

from eden.engines import DrumEngine, SynthEngine, SynthVoice, midi_to_hz
from eden.engines import _SampleVoice


# ── midi_to_hz ────────────────────────────────────────────────────────────────


def test_midi_to_hz_a4():
    assert midi_to_hz(69) == pytest.approx(440.0)


def test_midi_to_hz_a3():
    assert midi_to_hz(57) == pytest.approx(220.0)


def test_midi_to_hz_c4():
    assert midi_to_hz(60) == pytest.approx(261.626, rel=1e-4)


# ── DrumEngine ────────────────────────────────────────────────────────────────


def _make_drum_engine(name="kick"):
    sample = np.ones((1024, 2), dtype=np.float64) * 0.5
    samples = {name: sample}
    return DrumEngine(name, samples), samples


def test_drum_engine_silent_initially():
    engine, _ = _make_drum_engine()
    assert engine.is_silent


def test_drum_engine_note_on_enqueues():
    engine, _ = _make_drum_engine()
    engine.note_on(60, 1.0, 0, None)
    assert not engine.is_silent


def test_drum_engine_fill_produces_audio():
    engine, _ = _make_drum_engine()
    engine.note_on(60, 1.0, 0, None)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert np.any(buf != 0.0)


def test_drum_engine_velocity_scales_output():
    engine_full, samples = _make_drum_engine()
    engine_half = DrumEngine("kick", samples)

    engine_full.note_on(60, 1.0, 0, None)
    engine_half.note_on(60, 0.5, 0, None)

    buf_full = np.zeros((256, 2), dtype=np.float64)
    buf_half = np.zeros((256, 2), dtype=np.float64)
    engine_full.fill_block(buf_full, 256)
    engine_half.fill_block(buf_half, 256)

    assert np.allclose(buf_half, buf_full * 0.5)


def test_drum_engine_missing_sample_is_silent():
    engine = DrumEngine("nonexistent", {})
    engine.note_on(60, 1.0, 0, None)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert np.all(buf == 0.0)


def test_drum_engine_all_notes_off():
    engine, _ = _make_drum_engine()
    engine.note_on(60, 1.0, 0, None)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)  # starts voice
    engine.all_notes_off()
    buf2 = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf2, 256)  # sentinel clears voices
    assert np.all(buf2 == 0.0)
    assert engine.is_silent


def test_drum_engine_voice_cap():
    """Engine should not exceed _MAX_DRUM_VOICES simultaneous voices."""
    sample = np.ones((44100, 2), dtype=np.float64)  # 1-second sample
    samples = {"kick": sample}
    engine = DrumEngine("kick", samples)
    for _ in range(12):
        engine.note_on(60, 1.0, 0, None)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert len(engine._voices) <= 8


# ── SynthVoice ────────────────────────────────────────────────────────────────


class _FakeTrack:
    amp_attack = 0.001
    amp_decay = 0.05
    amp_sustain = 0.7
    amp_release = 0.1
    osc_type = "saw"
    volume = 0.8
    filter_cutoff = 4000.0
    filter_res = 0.1
    max_voices = 4


def _make_voice(osc_type="saw", gate=4410):
    track = _FakeTrack()
    track.osc_type = osc_type
    return SynthVoice(69, 1.0, gate, track, 44100)


def test_synth_voice_not_done_initially():
    v = _make_voice()
    assert not v.is_done


def test_synth_voice_produces_audio():
    v = _make_voice(gate=44100)
    buf = np.zeros((256, 2), dtype=np.float64)
    v.fill_block(buf, 256)
    assert np.any(buf != 0.0)


def test_synth_voice_all_osc_types_run():
    for osc in ("saw", "square", "sine", "triangle"):
        v = _make_voice(osc_type=osc, gate=44100)
        buf = np.zeros((256, 2), dtype=np.float64)
        v.fill_block(buf, 256)
        assert np.any(buf != 0.0), f"osc={osc} produced silence"


def test_synth_voice_done_after_release():
    """Voice with very short gate should reach DONE within a reasonable time."""
    v = _make_voice(gate=1)
    buf = np.zeros((4096, 2), dtype=np.float64)
    # Fill enough blocks to let release complete (release=0.1s → 4410 samples)
    for _ in range(20):
        if v.is_done:
            break
        v.fill_block(buf[:256], 256)
    assert v.is_done


def test_synth_voice_stereo():
    v = _make_voice(gate=44100)
    buf = np.zeros((256, 2), dtype=np.float64)
    v.fill_block(buf, 256)
    # Mono synth writes same value to both channels
    assert np.allclose(buf[:, 0], buf[:, 1])


def test_synth_voice_defaults_without_track():
    """SynthVoice must not raise when track_state has no synth params."""

    class _EmptyTrack:
        pass

    v = SynthVoice(60, 0.8, 2205, _EmptyTrack(), 44100)
    buf = np.zeros((256, 2), dtype=np.float64)
    v.fill_block(buf, 256)  # should not raise


# ── SynthEngine ───────────────────────────────────────────────────────────────


def test_synth_engine_silent_initially():
    engine = SynthEngine(44100)
    assert engine.is_silent


def test_synth_engine_note_on_produces_audio():
    engine = SynthEngine(44100)
    engine.note_on(69, 1.0, 4410, _FakeTrack())
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert np.any(buf != 0.0)


def test_synth_engine_all_notes_off():
    engine = SynthEngine(44100)
    engine.note_on(69, 1.0, 44100, _FakeTrack())
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    engine.all_notes_off()
    buf2 = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf2, 256)
    assert engine.is_silent


def test_synth_engine_polyphonic():
    engine = SynthEngine(44100)
    track = _FakeTrack()
    track.max_voices = 4
    engine.note_on(60, 1.0, 44100, track)
    engine.note_on(64, 1.0, 44100, track)
    engine.note_on(67, 1.0, 44100, track)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert len(engine._voices) == 3


def test_synth_engine_voice_stealing():
    """When at max_voices, oldest voice is stolen."""
    engine = SynthEngine(44100)
    track = _FakeTrack()
    track.max_voices = 2
    engine.note_on(60, 1.0, 44100, track)
    engine.note_on(64, 1.0, 44100, track)
    engine.note_on(67, 1.0, 44100, track)  # steals oldest
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert len(engine._voices) == 2


def test_synth_engine_not_silent_while_releasing():
    """Voice in release stage keeps engine non-silent."""
    engine = SynthEngine(44100)
    track = _FakeTrack()
    engine.note_on(69, 1.0, 1, track)  # gate=1 → immediately enters release
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    # After one block, voice is in release but not done yet (release=0.1s)
    assert not engine.is_silent


def test_synth_engine_release_all_sends_voices_to_release():
    """release_all() drives every gated voice into its release phase."""
    from eden.engines import _ENV_RELEASE
    engine = SynthEngine(44100)
    track = _FakeTrack()
    engine.note_on(60, 1.0, 44100, track)
    engine.note_on(64, 1.0, 44100, track)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    assert all(v._env_stage < _ENV_RELEASE for v in engine._voices)
    engine.release_all()
    engine.fill_block(buf, 256)
    assert all(v._env_stage >= _ENV_RELEASE for v in engine._voices)


def test_synth_engine_retrigger_layers_new_chord():
    """A note_on after release_all still plays — prior voices release, new ones layer."""
    engine = SynthEngine(44100)
    track = _FakeTrack()
    engine.note_on(60, 1.0, 44100, track)
    buf = np.zeros((256, 2), dtype=np.float64)
    engine.fill_block(buf, 256)
    # Retrigger: release prior voice, then fire a two-note chord in one batch.
    engine.release_all()
    engine.note_on(64, 1.0, 44100, track)
    engine.note_on(67, 1.0, 44100, track)
    engine.fill_block(buf, 256)
    # Old voice (releasing) + two fresh chord voices all coexist.
    assert len(engine._voices) == 3


# ── _SampleVoice vectorized fill ──────────────────────────────────────────────


def _make_sample_data(n, seed):
    """Deterministic float64 stereo sample data with distinct L/R content."""
    rng = np.random.default_rng(seed)
    left = rng.standard_normal(n)
    right = rng.standard_normal(n)
    return np.stack([left, right], axis=1).astype(np.float64)


def _run_voice(voice, n_blocks, block, note_off_block=None):
    """Render a voice across blocks via its public fill(); return concatenated output."""
    out = []
    for b in range(n_blocks):
        if note_off_block is not None and b == note_off_block:
            voice.note_off()
        buf = np.zeros((block, 2), dtype=np.float64)
        voice.fill(buf, block)
        out.append(buf.copy())
    return np.concatenate(out, axis=0)


def _run_voice_slow(voice, n_blocks, block, note_off_block=None):
    """Same as _run_voice but forcing the reference per-sample path every block."""
    out = []
    for b in range(n_blocks):
        if note_off_block is not None and b == note_off_block:
            voice.note_off()
        buf = np.zeros((block, 2), dtype=np.float64)
        voice._fill_slow(buf, block)
        out.append(buf.copy())
    return np.concatenate(out, axis=0)


_VOICE_CASES = [
    # (n, pitch_rate, attack, release, gate, play_mode, note_off_block)
    (8000, 1.0, 0, 2205, 4410, "gate", None),       # unity pitch, gate→release
    (8000, 2.0, 0, 2205, 4410, "gate", None),       # octave up (skips samples)
    (8000, 0.5, 0, 2205, 4410, "gate", None),       # octave down (interpolates)
    (8000, 1.5, 441, 2205, 6000, "gate", None),     # short attack + gate
    (8000, 1.0, 0, 1, 0, "oneshot", None),          # oneshot, plays to end
    (8000, 1.0, 0, 4410, 0, "oneshot", 3),          # oneshot, explicit note_off
    (8000, 1.0, 0, 4410, 0, "legato", 2),           # legato, note_off mid-flight
    (3000, 1.0, 0, 2205, 1000, "gate", None),       # release outlives source
    (8000, 1.0, 100, 88200, 512, "gate", None),     # release longer than source
    (500, 3.0, 0, 2205, 0, "oneshot", None),        # tiny source, fast read
    (8000, 0.75, 0, 2205, 300, "gate", 0),          # note_off on first block
]


@pytest.mark.parametrize("case", _VOICE_CASES)
def test_sample_voice_vectorized_matches_slow(case):
    n, rate, attack, release, gate, play_mode, noff = case
    data = _make_sample_data(n, seed=hash(case) & 0xFFFF)
    block = 256
    n_blocks = (n + block) // block + 4

    def mk():
        v = _SampleVoice(
            data, gain=0.8, pan_l=0.9, pan_r=0.6, pitch_rate=rate,
            attack_samples=attack, release_samples=release,
            gate_samples=gate, play_mode=play_mode,
        )
        return v

    fast = _run_voice(mk(), n_blocks, block, note_off_block=noff)
    slow = _run_voice_slow(mk(), n_blocks, block, note_off_block=noff)
    assert fast.shape == slow.shape
    assert np.allclose(fast, slow, atol=1e-9), (
        f"max diff {np.abs(fast - slow).max():.2e} for {case}"
    )


def test_sample_voice_done_state_matches_slow():
    """The vectorized path must reach `done` on the same block as the slow path."""
    data = _make_sample_data(5000, seed=7)
    block = 256

    def done_block(use_slow):
        v = _SampleVoice(
            data, gain=1.0, pan_l=1.0, pan_r=1.0, pitch_rate=1.0,
            attack_samples=0, release_samples=2205, gate_samples=2000,
            play_mode="gate",
        )
        buf = np.zeros((block, 2), dtype=np.float64)
        for b in range(100):
            (v._fill_slow if use_slow else v.fill)(buf, block)
            if v.done:
                return b
        return -1

    assert done_block(False) == done_block(True)
