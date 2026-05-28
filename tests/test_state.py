"""test_state.py — Pure unit tests for Eden state and event dataclasses."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from dataclasses import FrozenInstanceError

from eden.state import (
    AppState,
    DrumTrack,
    InstrumentSubmode,
    Loop,
    Mode,
    SampleTrack,
    SynthTrack,
    default_loop,
    default_state,
    default_track_loops,
)
from eden.events import (
    ClockTicked,
    EncoderTurned,
    ModeButtonPressed,
    PadPressed,
    PadReleased,
    ShiftChanged,
    SoftkeyPressed,
    TransportPressed,
)


# ── default_state() ───────────────────────────────────────────────────────────


def test_default_state_mode():
    assert default_state().mode is Mode.SESSION


def test_default_state_selected_track():
    assert default_state().selected_track == 0


def test_default_state_tempo():
    assert default_state().tempo_bpm == 120.0


def test_default_state_track0_is_drum():
    assert isinstance(default_state().tracks[0], DrumTrack)


def test_default_state_track0_name():
    assert default_state().tracks[0].name == "KICK"


def test_default_state_track1_is_drum():
    assert isinstance(default_state().tracks[1], DrumTrack)


def test_default_state_track1_name():
    assert default_state().tracks[1].name == "SNARE"


def test_default_state_track2_is_none():
    assert default_state().tracks[2] is None


# ── Loop properties ───────────────────────────────────────────────────────────


def test_loop_is_empty_all_false():
    loop = Loop(steps=tuple(False for _ in range(16)))
    assert loop.is_empty is True


def test_loop_is_empty_one_true():
    steps = [False] * 16
    steps[3] = True
    loop = Loop(steps=tuple(steps))
    assert loop.is_empty is False


def test_loop_step_count_16():
    loop = default_loop(16)
    assert loop.step_count == 16


def test_loop_step_count_32():
    loop = default_loop(32)
    assert loop.step_count == 32


def test_default_loop_32_all_false():
    loop = default_loop(32)
    assert len(loop.steps) == 32
    assert all(s is False for s in loop.steps)


# ── Immutability ──────────────────────────────────────────────────────────────


def test_appstate_is_frozen():
    state = default_state()
    with pytest.raises(FrozenInstanceError):
        state.tempo_bpm = 140.0  # type: ignore[misc]


def test_loop_is_frozen():
    loop = default_loop()
    with pytest.raises(FrozenInstanceError):
        loop.loop_count = 4  # type: ignore[misc]


# ── Collection types ──────────────────────────────────────────────────────────


def test_armed_tracks_is_tuple():
    assert isinstance(default_state().armed_tracks, tuple)


def test_playing_loops_is_frozenset():
    assert isinstance(default_state().playing_loops, frozenset)


def test_soloed_tracks_is_frozenset():
    assert isinstance(default_state().soloed_tracks, frozenset)


def test_muted_tracks_is_frozenset():
    assert isinstance(default_state().muted_tracks, frozenset)


# ── DrumTrack loops ───────────────────────────────────────────────────────────


def test_drum_track_has_16_loops():
    track = default_state().tracks[0]
    assert isinstance(track, DrumTrack)
    assert len(track.loops) == 16


def test_default_track_loops_count():
    loops = default_track_loops()
    assert len(loops) == 16


# ── InstrumentSubmode ─────────────────────────────────────────────────────────


def test_instrument_submode_steps_exists():
    assert InstrumentSubmode.STEPS is not None


def test_instrument_submode_pads_exists():
    assert InstrumentSubmode.PADS is not None


# ── Event types ───────────────────────────────────────────────────────────────


def test_pad_pressed_frozen():
    e = PadPressed(pad_index=0, velocity=100)
    with pytest.raises(FrozenInstanceError):
        e.velocity = 0  # type: ignore[misc]


def test_pad_released_instantiates():
    e = PadReleased(pad_index=5)
    assert e.pad_index == 5


def test_encoder_turned_instantiates():
    e = EncoderTurned(encoder=3, delta=-1)
    assert e.delta == -1


def test_transport_pressed_instantiates():
    e = TransportPressed(button="PLAY", pressed=True)
    assert e.button == "PLAY"


def test_clock_ticked_no_args():
    e = ClockTicked()
    assert isinstance(e, ClockTicked)


def test_clock_ticked_is_frozen():
    # Verify the frozen flag is set on the dataclass itself (no fields to mutate)
    assert ClockTicked.__dataclass_params__.frozen is True


def test_mode_button_pressed_instantiates():
    e = ModeButtonPressed(button="SONG", pressed=False)
    assert e.button == "SONG"


def test_shift_changed_held_true():
    e = ShiftChanged(held=True)
    assert e.held is True


def test_softkey_pressed_key():
    e = SoftkeyPressed(key=2)
    assert e.key == 2


def test_softkey_pressed_is_frozen():
    e = SoftkeyPressed(key=1)
    with pytest.raises(FrozenInstanceError):
        e.key = 0  # type: ignore[misc]
