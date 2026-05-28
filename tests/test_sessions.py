"""tests/test_sessions.py — Session serialization roundtrip and slot-transition logic."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eden.state import default_state, AppState, DrumTrack, Loop, default_loop
from eden.events import SessionLoaded, TransportPressed, ShiftChanged
from eden.reduce import reduce
import eden.sessions as sessions


# ── Serialization helpers ─────────────────────────────────────────────────────

def _roundtrip(state: AppState, slot: int = 0) -> AppState:
    """Serialize state to a session dict and deserialize back into a new state."""
    data = sessions.state_to_session(state, "test")
    patch = sessions.session_to_state_patch(data, slot)
    return dataclasses.replace(state, **patch)


# ── Steps encoding ────────────────────────────────────────────────────────────

def test_steps_roundtrip_all_off():
    loop = default_loop(16)
    d = sessions._loop_to_dict(loop)
    assert d is None  # empty loops serialize as null


def test_steps_roundtrip_pattern():
    steps = tuple(i in (0, 4, 8, 12) for i in range(16))
    loop = Loop(steps=steps)
    d = sessions._loop_to_dict(loop)
    assert d is not None
    assert d["steps"] == "1000100010001000"
    back = sessions._dict_to_loop(d)
    assert back.steps == steps


def test_steps_roundtrip_32_step():
    steps = tuple(i % 2 == 0 for i in range(32))
    loop = Loop(steps=steps, step_size=32)
    d = sessions._loop_to_dict(loop)
    assert len(d["steps"]) == 32
    back = sessions._dict_to_loop(d)
    assert back.steps == steps


# ── Track serialization ───────────────────────────────────────────────────────

def test_track_roundtrip_drum():
    state = default_state()
    data = sessions._track_to_dict(state.tracks[0])
    assert data["type"] == "drum"
    assert data["name"] == "KICK"
    back = sessions._dict_to_track(data)
    assert isinstance(back, DrumTrack)
    assert back.name == "KICK"
    assert back.loops[0].steps == state.tracks[0].loops[0].steps


def test_track_roundtrip_none():
    assert sessions._track_to_dict(None) is None
    assert sessions._dict_to_track(None) is None


def test_track_loops_padded_to_16():
    data = {"type": "drum", "name": "KICK", "sample_name": "kick", "loops": []}
    track = sessions._dict_to_track(data)
    assert len(track.loops) == 16


# ── Full state roundtrip ──────────────────────────────────────────────────────

def test_session_roundtrip_bpm():
    state = dataclasses.replace(default_state(), tempo_bpm=140.0)
    back = _roundtrip(state)
    assert back.tempo_bpm == 140.0


def test_session_roundtrip_tracks():
    state = default_state()
    back = _roundtrip(state)
    assert back.tracks[0].name == "KICK"
    assert back.tracks[1].name == "SNARE"
    assert back.tracks[2] is None


def test_session_roundtrip_active_loops():
    state = dataclasses.replace(default_state(), active_loops=frozenset({(0, 0), (1, 2)}))
    back = _roundtrip(state)
    assert back.active_loops == frozenset({(0, 0), (1, 2)})


def test_session_roundtrip_playing_loops_set_from_active():
    state = dataclasses.replace(default_state(), active_loops=frozenset({(0, 3)}))
    back = _roundtrip(state)
    assert back.playing_loops == frozenset({(0, 3)})


def test_session_roundtrip_muted_tracks():
    state = dataclasses.replace(default_state(), muted_tracks=frozenset({1, 3}))
    back = _roundtrip(state)
    assert back.muted_tracks == frozenset({1, 3})


def test_session_roundtrip_sets_active_slot():
    state = default_state()
    back = _roundtrip(state, slot=3)
    assert back.active_session_slot == 3


def test_session_roundtrip_resets_runtime_state():
    state = dataclasses.replace(default_state(), playhead=15, armed_tracks=(0, 1))
    back = _roundtrip(state)
    assert back.playhead == 0
    assert back.armed_tracks == ()


# ── slot_letter / slot_from_letter ────────────────────────────────────────────

def test_slot_letter():
    assert sessions.slot_letter(0) == "A"
    assert sessions.slot_letter(7) == "H"


def test_slot_from_letter():
    assert sessions.slot_from_letter("A") == 0
    assert sessions.slot_from_letter("h") == 7
    assert sessions.slot_from_letter("Z") is None


# ── SessionLoaded reducer ─────────────────────────────────────────────────────

def _session_loaded_event(slot: int = 2, immediate: bool = False) -> SessionLoaded:
    """Build a minimal SessionLoaded event for testing."""
    s = default_state()
    return SessionLoaded(
        slot=slot,
        tracks=s.tracks,
        tempo_bpm=130.0,
        swing=0.0,
        active_loops=frozenset({(0, 0)}),
        muted_tracks=frozenset(),
        soloed_tracks=frozenset(),
        immediate=immediate,
    )


def test_session_loaded_switches_slot():
    s = default_state()  # active_session_slot=0
    s2 = reduce(s, _session_loaded_event(slot=2))
    assert s2.active_session_slot == 2


def test_session_loaded_applies_new_tempo():
    s = default_state()
    s2 = reduce(s, _session_loaded_event(slot=2))
    assert s2.tempo_bpm == 130.0


def test_session_loaded_graceful_marks_infinite_loops():
    """Graceful switch: infinite playing loops moved to finishing_loops with plays=1."""
    s = default_state()  # playing_loops = {(0,0),(1,0)}, both infinite
    s2 = reduce(s, _session_loaded_event(slot=1, immediate=False))
    assert (0, 0) in s2.finishing_loops
    assert (1, 0) in s2.finishing_loops
    remaining = dict(s2.finishing_plays_remaining)
    assert remaining.get((0, 0)) == 1
    assert remaining.get((1, 0)) == 1


def test_session_loaded_graceful_preserves_tracks_snapshot():
    """finishing_tracks should snapshot the old tracks for audio."""
    s = default_state()
    s2 = reduce(s, _session_loaded_event(slot=1, immediate=False))
    assert s2.finishing_tracks == s.tracks


def test_session_loaded_immediate_clears_finishing():
    """Immediate (Shift) switch: no finishing loops at all."""
    s = default_state()
    s2 = reduce(s, _session_loaded_event(slot=2, immediate=True))
    assert s2.finishing_loops == frozenset()
    assert s2.finishing_tracks == ()


def test_session_loaded_sets_playing_loops_from_active():
    """New session's active_loops become playing_loops."""
    s = default_state()
    ev = _session_loaded_event(slot=2)
    s2 = reduce(s, ev)
    assert s2.playing_loops == ev.active_loops


# ── Shift+REC sets active_loops ───────────────────────────────────────────────

def test_shift_rec_updates_active_loops():
    s = dataclasses.replace(
        default_state(),
        shift_held=True,
        playing_loops=frozenset({(0, 2), (1, 0)}),
        active_loops=frozenset(),
    )
    s2 = reduce(s, TransportPressed(button="REC", pressed=True))
    assert s2.active_loops == frozenset({(0, 2), (1, 0)})


def test_shift_rec_does_not_change_playing_loops():
    s = dataclasses.replace(default_state(), shift_held=True)
    orig_playing = s.playing_loops
    s2 = reduce(s, TransportPressed(button="REC", pressed=True))
    assert s2.playing_loops == orig_playing


def test_rec_without_shift_no_state_change():
    s = default_state()
    s2 = reduce(s, TransportPressed(button="REC", pressed=True))
    assert s2 is s  # pure no-op (save is app layer's job)
