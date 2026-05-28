"""tests/test_engines.py — Unit tests for DrumEngine, SynthVoice, SynthEngine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest

from eden.engines import DrumEngine, SynthEngine, SynthVoice, midi_to_hz


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
