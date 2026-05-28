"""test_reduce.py — Pure unit tests for eden.reduce."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from eden.state import (
    AppState,
    DrumTrack,
    InstrumentSubmode,
    Loop,
    Mode,
    default_loop,
    default_state,
    default_track_loops,
)
from eden.events import (
    ClockTicked,
    EncoderTurned,
    ModeButtonPressed,
    PadPressed,
    SoftkeyPressed,
    TouchbarMoved,
    TransportPressed,
    ShiftChanged,
)
from eden.reduce import reduce


# ── Helpers ───────────────────────────────────────────────────────────────────


def _playing_session() -> AppState:
    """SESSION state with is_playing=True, playhead=0."""
    return dataclasses.replace(default_state(), is_playing=True, playhead=0)


def _armed_instrument(armed: tuple[int, ...] = (0,)) -> AppState:
    """INSTRUMENT state with given armed_tracks. Uses selected_loop=1 (empty)."""
    return dataclasses.replace(
        default_state(),
        mode=Mode.INSTRUMENT,
        armed_tracks=armed,
        instrument_submode=InstrumentSubmode.STEPS,
        selected_loop=1,  # loop 0 has starter patterns; use empty loop 1
    )


def _step_on(state: AppState, track_idx: int, loop_idx: int, step: int) -> AppState:
    """Return state with a specific step forced ON (helper for test setup)."""
    track = state.tracks[track_idx]
    assert isinstance(track, DrumTrack)
    loop = track.loops[loop_idx]
    new_steps = loop.steps[:step] + (True,) + loop.steps[step + 1:]
    new_loop = dataclasses.replace(loop, steps=new_steps)
    new_loops = track.loops[:loop_idx] + (new_loop,) + track.loops[loop_idx + 1:]
    new_track = dataclasses.replace(track, loops=new_loops)
    new_tracks = state.tracks[:track_idx] + (new_track,) + state.tracks[track_idx + 1:]
    return dataclasses.replace(state, tracks=new_tracks)


# ── ClockTicked ───────────────────────────────────────────────────────────────


def test_clock_noop_when_stopped():
    """ClockTicked is a no-op when is_playing=False."""
    state = dataclasses.replace(default_state(), is_playing=False)
    result = reduce(state, ClockTicked())
    assert result.playhead == 0
    assert result is state


def test_clock_advances_playhead_session():
    """Playhead advances 0→1 when playing in SESSION mode."""
    state = _playing_session()
    result = reduce(state, ClockTicked())
    assert result.playhead == 1


def test_clock_wraps_at_32_in_session():
    """Playhead wraps 31→0 in SESSION mode (32-tick bar)."""
    state = dataclasses.replace(_playing_session(), playhead=31)
    result = reduce(state, ClockTicked())
    assert result.playhead == 0


def test_clock_wraps_at_32_in_dual_arm_instrument():
    """Playhead wraps 31→0 in dual-arm INSTRUMENT mode (32-tick bar)."""
    state = dataclasses.replace(
        _armed_instrument(armed=(0, 1)),
        is_playing=True,
        playhead=31,
    )
    result = reduce(state, ClockTicked())
    assert result.playhead == 0


def test_clock_wraps_at_32_in_single_arm_instrument_with_16step_loop():
    """Playhead wraps 31→0 for any loop size (32-tick bar)."""
    state = dataclasses.replace(
        _armed_instrument(armed=(0,)),
        is_playing=True,
        playhead=31,
    )
    result = reduce(state, ClockTicked())
    assert result.playhead == 0


def test_clock_always_wraps_at_32_for_multi_measure_loop():
    """Global playhead wraps at 32 (one bar) even when a playing loop spans multiple bars."""
    state = default_state()
    # Make track 0 loop 0 a 32-step SIZE=16 loop spanning 2 bars
    t0 = state.tracks[0]
    long_loop = Loop(steps=tuple(i % 2 == 0 for i in range(32)), bars=2)
    new_loops = (long_loop,) + t0.loops[1:]
    t0_new = dataclasses.replace(t0, loops=new_loops)
    state = dataclasses.replace(
        state,
        tracks=(t0_new,) + state.tracks[1:],
        is_playing=True,
        playhead=31,
    )
    result = reduce(state, ClockTicked())
    assert result.playhead == 0
    # Measure offset for (0,0) advances to 1 on wrap
    offsets = dict(result.loop_measure_offsets)
    assert offsets.get((0, 0), 0) == 1


# ── ShiftChanged ──────────────────────────────────────────────────────────────


def test_shift_set_true():
    """ShiftChanged(held=True) sets shift_held=True."""
    state = default_state()
    result = reduce(state, ShiftChanged(held=True))
    assert result.shift_held is True


def test_shift_set_false():
    """ShiftChanged(held=False) sets shift_held=False."""
    state = dataclasses.replace(default_state(), shift_held=True)
    result = reduce(state, ShiftChanged(held=False))
    assert result.shift_held is False


# ── ModeButtonPressed ─────────────────────────────────────────────────────────


def test_inst_button_switches_to_instrument_when_armed():
    """INST button switches to INSTRUMENT mode when armed_tracks is non-empty."""
    state = dataclasses.replace(default_state(), armed_tracks=(0,))
    result = reduce(state, ModeButtonPressed(button="INST", pressed=True))
    assert result.mode is Mode.INSTRUMENT


def test_inst_button_arms_selected_and_enters_instrument_when_not_armed():
    """INST button with no armed tracks arms selected_track and enters INSTRUMENT."""
    state = dataclasses.replace(default_state(), armed_tracks=(), selected_track=1)
    result = reduce(state, ModeButtonPressed(button="INST", pressed=True))
    assert result.mode is Mode.INSTRUMENT
    assert result.armed_tracks == (1,)
    assert result.instrument_submode is InstrumentSubmode.STEPS


def test_song_button_switches_to_session():
    """SONG button always switches to SESSION mode."""
    state = _armed_instrument()
    result = reduce(state, ModeButtonPressed(button="SONG", pressed=True))
    assert result.mode is Mode.SESSION


def test_back_button_noop():
    """BACK button (and FORWARD, EDIT, USER) is a no-op in M1/M2."""
    state = default_state()
    for btn in ("BACK", "FORWARD", "EDIT", "USER"):
        result = reduce(state, ModeButtonPressed(button=btn, pressed=True))
        assert result.mode is Mode.SESSION
        assert result is state


def test_mode_button_release_noop():
    """Mode button release (pressed=False) is always a no-op."""
    state = dataclasses.replace(default_state(), armed_tracks=(0,))
    result = reduce(state, ModeButtonPressed(button="INST", pressed=False))
    assert result.mode is Mode.SESSION


# ── Session PadPressed ────────────────────────────────────────────────────────


def test_session_pad_bottom_row_selects_track_0():
    """Bottom-row pad 0 selects track 0."""
    state = dataclasses.replace(default_state(), selected_track=5)
    result = reduce(state, PadPressed(pad_index=0, velocity=100))
    assert result.selected_track == 0


def test_session_pad_bottom_row_selects_track_15():
    """Bottom-row pad 15 selects track 15."""
    state = default_state()
    result = reduce(state, PadPressed(pad_index=15, velocity=100))
    assert result.selected_track == 15


def test_session_pad_bottom_row_selects_empty_slot_without_creating_track():
    """Pressing an empty track slot selects it and opens the new-instrument picker."""
    state = default_state()
    assert state.tracks[2] is None
    result = reduce(state, PadPressed(pad_index=2, velocity=100))
    assert result.tracks[2] is None          # track NOT created yet
    assert result.selected_track == 2        # slot is selected
    assert result.new_slot_active_ctrl == "" # picker visible but no ctrl active


def test_session_new_slot_sk5_creates_track():
    """SK5 (CREATE) in new-instrument picker creates a DrumTrack at the selected slot."""
    from eden.state import DrumTrack
    from eden.events import SoftkeyPressed
    state = default_state()
    state = reduce(state, PadPressed(pad_index=2, velocity=100))  # select empty slot
    assert state.tracks[2] is None
    result = reduce(state, SoftkeyPressed(key=4))  # SK5 = CREATE
    assert isinstance(result.tracks[2], DrumTrack)
    assert result.tracks[2].name == "KICK"   # default: type=DRUMS, cat=Kick, var=Techno


def test_session_new_slot_encoder_changes_category():
    """Enc9 jog changes category when CAT ctrl is active in new-instrument picker."""
    from eden.events import SoftkeyPressed, EncoderTurned
    state = default_state()
    state = reduce(state, PadPressed(pad_index=2, velocity=100))
    state = reduce(state, SoftkeyPressed(key=1))    # activate CAT ctrl
    assert state.new_slot_active_ctrl == "CAT"
    result = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert result.new_slot_cat_idx == 1             # moved from Kick to Snare


def test_session_pad_top_row_adds_to_playing():
    """Top-row pad 16 (= loop 0, has kick pattern) adds (0, 0) to playing_loops."""
    # Start with loop 0 not playing so we can test adding it
    state = dataclasses.replace(
        default_state(),
        selected_track=0,
        playing_loops=frozenset(),
    )
    result = reduce(state, PadPressed(pad_index=16, velocity=100))
    assert (0, 0) in result.playing_loops


def test_session_pad_top_row_removes_when_already_playing():
    """Top-row pad 16 (= loop 0) removes (0, 0) when already playing."""
    state = dataclasses.replace(
        default_state(),
        selected_track=0,
        playing_loops=frozenset({(0, 0)}),
    )
    result = reduce(state, PadPressed(pad_index=16, velocity=100))
    assert (0, 0) not in result.playing_loops


def test_session_pad_top_row_selects_loop():
    """Top-row pad always updates selected_loop, even for empty loops."""
    state = dataclasses.replace(default_state(), selected_track=0, selected_loop=0)
    result = reduce(state, PadPressed(pad_index=21, velocity=100))  # loop 5
    assert result.selected_loop == 5


def test_session_pad_top_row_empty_loop_does_not_start_playing():
    """Top-row pad on an empty loop selects it but does NOT add to playing_loops."""
    state = dataclasses.replace(default_state(), selected_track=0)
    # Loop 5 of track 0 is empty
    result = reduce(state, PadPressed(pad_index=21, velocity=100))
    assert (0, 5) not in result.playing_loops
    assert result.selected_loop == 5


def test_session_pad_top_row_initializes_plays_remaining_when_loop_count_set():
    """Starting a finite-count loop (non-empty) initializes plays_remaining."""
    # Loop 0 of track 0 has the kick pattern (non-empty); start with it not playing
    s = dataclasses.replace(
        default_state(),
        selected_track=0,
        selected_loop=0,
        playing_loops=frozenset(),
    )
    s = reduce(s, SoftkeyPressed(key=2))  # loop_count 0→1
    s = reduce(s, SoftkeyPressed(key=2))  # loop_count 1→2
    assert s.tracks[0].loops[0].loop_count == 2
    result = reduce(s, PadPressed(pad_index=16, velocity=100))  # pad 16 = loop 0
    assert any(k == (0, 0) for k, _ in result.plays_remaining)


def test_plays_remaining_decrements_on_wrap():
    """plays_remaining decrements when playhead wraps to 0."""
    s = dataclasses.replace(
        default_state(),
        selected_track=0,
        playing_loops=frozenset({(0, 0)}),
        plays_remaining=(((0, 0), 2),),
        playhead=31,
        is_playing=True,
    )
    result = reduce(s, ClockTicked())
    assert result.playhead == 0
    remaining = dict(result.plays_remaining)
    assert remaining.get((0, 0)) == 1


def test_plays_remaining_stops_loop_at_zero():
    """Loop is removed from playing_loops when plays_remaining hits 0."""
    s = dataclasses.replace(
        default_state(),
        selected_track=0,
        playing_loops=frozenset({(0, 0)}),
        plays_remaining=(((0, 0), 1),),
        playhead=31,
        is_playing=True,
    )
    result = reduce(s, ClockTicked())
    assert (0, 0) not in result.playing_loops


# ── Session SoftkeyPressed ────────────────────────────────────────────────────


def test_sk1_mutes_selected_track():
    """SK1 adds selected track to muted_tracks."""
    state = dataclasses.replace(default_state(), selected_track=0)
    result = reduce(state, SoftkeyPressed(key=0))
    assert 0 in result.muted_tracks


def test_sk1_unmutes_already_muted_track():
    """SK1 again removes selected track from muted_tracks."""
    state = dataclasses.replace(
        default_state(), selected_track=0, muted_tracks=frozenset({0})
    )
    result = reduce(state, SoftkeyPressed(key=0))
    assert 0 not in result.muted_tracks


def test_sk2_solos_selected_track():
    """SK2 adds selected track to soloed_tracks."""
    state = dataclasses.replace(default_state(), selected_track=1)
    result = reduce(state, SoftkeyPressed(key=1))
    assert 1 in result.soloed_tracks


def test_sk2_unsolos_already_soloed_track():
    """SK2 again removes selected track from soloed_tracks."""
    state = dataclasses.replace(
        default_state(), selected_track=1, soloed_tracks=frozenset({1})
    )
    result = reduce(state, SoftkeyPressed(key=1))
    assert 1 not in result.soloed_tracks


def test_sk3_cycles_loop_count_0_to_1():
    """SK3 cycles loop_count 0→1 on a DrumTrack loop."""
    state = dataclasses.replace(default_state(), selected_track=0, selected_loop=0)
    result = reduce(state, SoftkeyPressed(key=2))
    loop = result.tracks[0].loops[0]
    assert loop.loop_count == 1


def test_sk3_cycles_loop_count_full_sequence():
    """SK3 cycles loop_count: 1→2→4→8→0."""
    state = dataclasses.replace(default_state(), selected_track=0, selected_loop=0)
    # Start at 0, advance to 1
    s1 = reduce(state, SoftkeyPressed(key=2))
    assert s1.tracks[0].loops[0].loop_count == 1
    # 1→2
    s2 = reduce(s1, SoftkeyPressed(key=2))
    assert s2.tracks[0].loops[0].loop_count == 2
    # 2→4
    s3 = reduce(s2, SoftkeyPressed(key=2))
    assert s3.tracks[0].loops[0].loop_count == 4
    # 4→8
    s4 = reduce(s3, SoftkeyPressed(key=2))
    assert s4.tracks[0].loops[0].loop_count == 8
    # 8→0
    s5 = reduce(s4, SoftkeyPressed(key=2))
    assert s5.tracks[0].loops[0].loop_count == 0


def test_sk4_sets_arm1_stays_in_session():
    """SK4 sets arm1 to selected track and stays in SESSION."""
    state = dataclasses.replace(default_state(), selected_track=1)
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.armed_tracks == (1,)
    assert result.mode is Mode.SESSION


def test_sk4_replaces_arm1_with_different_track():
    """SK4 on a different track replaces arm1."""
    # Use track 1 (snare, not empty) as the new arm1 target.
    state = dataclasses.replace(default_state(), selected_track=1, armed_tracks=(0,))
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.armed_tracks == (1,)
    assert result.mode is Mode.SESSION


def _state_with_track2() -> AppState:
    """default_state() with an extra DrumTrack at slot 2 for multi-arm tests."""
    from eden.state import DrumTrack, default_track_loops
    s = default_state()
    t2 = DrumTrack(name="HAT", sample_name="clhat_techno", loops=default_track_loops())
    new_tracks = s.tracks[:2] + (t2,) + s.tracks[3:]
    return dataclasses.replace(s, tracks=new_tracks)


def test_sk4_replaces_arm1_preserves_arm2():
    """SK4 replacing arm1 keeps arm2 if arm2 differs from the new arm1."""
    state = dataclasses.replace(_state_with_track2(), selected_track=2, armed_tracks=(0, 1))
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.armed_tracks == (2, 1)


def test_sk4_replaces_arm1_drops_arm2_if_conflict():
    """SK4 replacing arm1 drops arm2 when new arm1 == arm2."""
    state = dataclasses.replace(default_state(), selected_track=1, armed_tracks=(0, 1))
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.armed_tracks == (1,)


def test_sk5_requires_arm1_first():
    """SK5 is a no-op when no arm1 is set."""
    state = dataclasses.replace(default_state(), selected_track=1, armed_tracks=())
    result = reduce(state, SoftkeyPressed(key=4))
    assert result.armed_tracks == ()


def test_sk5_sets_arm2_stays_in_session():
    """SK5 sets arm2 and stays in SESSION."""
    state = dataclasses.replace(default_state(), selected_track=1, armed_tracks=(0,))
    result = reduce(state, SoftkeyPressed(key=4))
    assert result.armed_tracks == (0, 1)
    assert result.mode is Mode.SESSION


def test_sk5_replaces_arm2_with_different_track():
    """SK5 on a new track replaces arm2."""
    state = dataclasses.replace(_state_with_track2(), selected_track=2, armed_tracks=(0, 1))
    result = reduce(state, SoftkeyPressed(key=4))
    assert result.armed_tracks == (0, 2)


def test_sk5_ignores_arm1_track():
    """SK5 is a no-op when selected track is already arm1."""
    state = dataclasses.replace(default_state(), selected_track=0, armed_tracks=(0,))
    result = reduce(state, SoftkeyPressed(key=4))
    assert result.armed_tracks == (0,)


def test_sk4_disarms_when_selected_is_arm1():
    """SK4 clears armed_tracks when the selected track is already arm1."""
    state = dataclasses.replace(default_state(), selected_track=0, armed_tracks=(0,))
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.armed_tracks == ()


def test_sk5_disarms_arm2_when_selected_is_arm2():
    """SK5 removes arm2 when the selected track is already arm2."""
    state = dataclasses.replace(default_state(), selected_track=1, armed_tracks=(0, 1))
    result = reduce(state, SoftkeyPressed(key=4))
    assert result.armed_tracks == (0,)


# ── Session TransportPressed ──────────────────────────────────────────────────


def test_transport_play_sets_is_playing():
    """PLAY sets is_playing=True."""
    state = default_state()
    result = reduce(state, TransportPressed(button="PLAY", pressed=True))
    assert result.is_playing is True


def test_transport_stop_clears_is_playing_and_resets_playhead():
    """STOP sets is_playing=False and resets playhead to 0."""
    state = dataclasses.replace(default_state(), is_playing=True, playhead=7)
    result = reduce(state, TransportPressed(button="STOP", pressed=True))
    assert result.is_playing is False
    assert result.playhead == 0


# ── Session EncoderTurned ─────────────────────────────────────────────────────


def test_encoder9_increases_bpm():
    """Encoder 9 delta +5 increases BPM by 5."""
    state = default_state()  # 120.0 BPM
    result = reduce(state, EncoderTurned(encoder=9, delta=5))
    assert result.tempo_bpm == 125.0


def test_encoder9_decreases_bpm():
    """Encoder 9 delta -5 decreases BPM by 5."""
    state = default_state()  # 120.0 BPM
    result = reduce(state, EncoderTurned(encoder=9, delta=-5))
    assert result.tempo_bpm == 115.0


def test_encoder9_bpm_clamped_at_200():
    """BPM is clamped to 200."""
    state = dataclasses.replace(default_state(), tempo_bpm=198.0)
    result = reduce(state, EncoderTurned(encoder=9, delta=10))
    assert result.tempo_bpm == 200.0


def test_encoder9_bpm_clamped_at_60():
    """BPM is clamped to 60."""
    state = dataclasses.replace(default_state(), tempo_bpm=62.0)
    result = reduce(state, EncoderTurned(encoder=9, delta=-10))
    assert result.tempo_bpm == 60.0


def test_non_encoder9_is_noop():
    """Encoders other than 9 are no-ops for session tempo."""
    state = default_state()
    for enc in range(1, 9):
        result = reduce(state, EncoderTurned(encoder=enc, delta=5))
        assert result.tempo_bpm == state.tempo_bpm


# ── Instrument PadPressed (single-arm) ───────────────────────────────────────


def test_instrument_pad0_toggles_step0_single_arm():
    """Pad 0 toggles step 0 in the armed track's loop (single-arm)."""
    state = _armed_instrument(armed=(0,))
    result = reduce(state, PadPressed(pad_index=0, velocity=100))
    assert result.tracks[0].loops[1].steps[0] is True


def test_instrument_pad15_toggles_step15_single_arm():
    """Pad 15 toggles step 15 in single-arm mode."""
    state = _armed_instrument(armed=(0,))
    result = reduce(state, PadPressed(pad_index=15, velocity=100))
    assert result.tracks[0].loops[1].steps[15] is True


def test_instrument_pad16_toggles_step16_single_arm():
    """Pad 16 (top row) toggles step 16 in single-arm 32-step mode."""
    # Track 0's loops are 16-step by default; replace loop 1 (selected) with 32-step.
    base_state = _armed_instrument(armed=(0,))
    track = base_state.tracks[0]
    assert isinstance(track, DrumTrack)
    long_loop = default_loop(32)
    new_loops = track.loops[:1] + (long_loop,) + track.loops[2:]
    new_track = dataclasses.replace(track, loops=new_loops)
    new_tracks = (new_track,) + base_state.tracks[1:]
    state = dataclasses.replace(base_state, tracks=new_tracks)

    result = reduce(state, PadPressed(pad_index=16, velocity=100))
    assert result.tracks[0].loops[1].steps[16] is True


def test_instrument_pad31_toggles_step31_single_arm():
    """Pad 31 (top row) toggles step 31 in single-arm 32-step mode."""
    base_state = _armed_instrument(armed=(0,))
    track = base_state.tracks[0]
    assert isinstance(track, DrumTrack)
    long_loop = default_loop(32)
    new_loops = track.loops[:1] + (long_loop,) + track.loops[2:]
    new_track = dataclasses.replace(track, loops=new_loops)
    new_tracks = (new_track,) + base_state.tracks[1:]
    state = dataclasses.replace(base_state, tracks=new_tracks)

    result = reduce(state, PadPressed(pad_index=31, velocity=100))
    assert result.tracks[0].loops[1].steps[31] is True


def test_instrument_double_toggle_restores_original():
    """Toggling the same step twice returns the step to its original (False) state."""
    state = _armed_instrument(armed=(0,))
    s1 = reduce(state, PadPressed(pad_index=3, velocity=100))
    assert s1.tracks[0].loops[1].steps[3] is True
    s2 = reduce(s1, PadPressed(pad_index=3, velocity=100))
    assert s2.tracks[0].loops[1].steps[3] is False


# ── Instrument PadPressed (dual-arm) ─────────────────────────────────────────


def test_instrument_pad0_dual_arm_toggles_track0_step0():
    """Pad 0 (bottom row) toggles step 0 in armed_tracks[0] during dual-arm."""
    state = _armed_instrument(armed=(0, 1))
    result = reduce(state, PadPressed(pad_index=0, velocity=100))
    assert result.tracks[0].loops[1].steps[0] is True
    # Track 1 (armed_tracks[1]) must be unaffected
    assert result.tracks[1].loops[1].steps[0] is False


def test_instrument_pad16_dual_arm_toggles_track1_step0():
    """Pad 16 (top row) toggles step 0 in armed_tracks[1] during dual-arm."""
    state = _armed_instrument(armed=(0, 1))
    result = reduce(state, PadPressed(pad_index=16, velocity=100))
    assert result.tracks[1].loops[1].steps[0] is True
    # Track 0 must be unaffected
    assert result.tracks[0].loops[1].steps[0] is False


# ── Instrument SoftkeyPressed ─────────────────────────────────────────────────


def test_instrument_sk4_back_returns_to_session():
    """SK4 (BACK) switches mode to SESSION."""
    state = _armed_instrument()
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.mode is Mode.SESSION


def test_instrument_pad_press_starts_loop_on_first_step():
    """Toggling the first step on an empty loop immediately adds it to playing_loops."""
    state = _armed_instrument(armed=(0,))  # loop 1 is empty, not playing
    assert (0, 1) not in state.playing_loops
    result = reduce(state, PadPressed(pad_index=0, velocity=100))
    assert (0, 1) in result.playing_loops


def test_instrument_pad_press_does_not_double_add_already_playing():
    """Toggling a step on an already-playing loop leaves playing_loops unchanged."""
    state = _step_on(_armed_instrument(armed=(0,)), track_idx=0, loop_idx=1, step=0)
    state = dataclasses.replace(state, playing_loops=frozenset({(0, 1)}))
    result = reduce(state, PadPressed(pad_index=2, velocity=100))
    assert result.playing_loops == frozenset({(0, 1)})


def test_instrument_pad_press_empty_after_toggle_does_not_start():
    """Toggling a step OFF that leaves the loop empty does not add it to playing_loops."""
    # Start with one step ON, then toggle it OFF
    state = _step_on(_armed_instrument(armed=(0,)), track_idx=0, loop_idx=1, step=0)
    assert (0, 1) not in state.playing_loops
    result = reduce(state, PadPressed(pad_index=0, velocity=100))  # toggles step 0 OFF
    assert (0, 1) not in result.playing_loops


def test_instrument_pad_press_dual_arm_starts_both():
    """First step on each row in dual-arm starts both loops."""
    state = _armed_instrument(armed=(0, 1))
    result = reduce(state, PadPressed(pad_index=0, velocity=100))   # step on track 0
    assert (0, 1) in result.playing_loops
    result2 = reduce(result, PadPressed(pad_index=16, velocity=100))  # step on track 1
    assert (1, 1) in result2.playing_loops


def test_instrument_sk5_clear_without_shift_is_noop():
    """SK5 (CLEAR) without shift held does nothing."""
    state = _step_on(_armed_instrument(), track_idx=0, loop_idx=1, step=4)
    result = reduce(state, SoftkeyPressed(key=4))
    # Step should remain set
    assert result.tracks[0].loops[1].steps[4] is True


def test_instrument_sk5_clear_with_shift_clears_all_steps():
    """SK5 (CLEAR) with shift held clears all steps in selected_loop for armed tracks."""
    state = _step_on(_armed_instrument(), track_idx=0, loop_idx=1, step=4)
    state = _step_on(state, track_idx=0, loop_idx=1, step=7)
    state = dataclasses.replace(state, shift_held=True)
    result = reduce(state, SoftkeyPressed(key=4))
    assert all(s is False for s in result.tracks[0].loops[1].steps)


def test_instrument_sk5_clear_dual_arm_clears_both_tracks():
    """SK5 with shift clears selected_loop for all armed tracks in dual-arm."""
    state = _armed_instrument(armed=(0, 1))
    state = _step_on(state, track_idx=0, loop_idx=1, step=2)
    state = _step_on(state, track_idx=1, loop_idx=1, step=5)
    state = dataclasses.replace(state, shift_held=True)
    result = reduce(state, SoftkeyPressed(key=4))
    assert all(s is False for s in result.tracks[0].loops[1].steps)
    assert all(s is False for s in result.tracks[1].loops[1].steps)


def test_clear_armed_track_persists_until_back():
    """CLEAR empties the steps but the armed slot stays alive until BACK is pressed."""
    state = _armed_instrument(armed=(0,))
    t0 = state.tracks[0]
    blank_loop0 = default_loop(16)
    new_loops = (blank_loop0,) + t0.loops[1:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    state = dataclasses.replace(state, tracks=(new_t0,) + state.tracks[1:])
    state = _step_on(state, track_idx=0, loop_idx=1, step=3)
    state = dataclasses.replace(state, shift_held=True)
    after_clear = reduce(state, SoftkeyPressed(key=4))  # SK5 CLEAR
    # Steps cleared, but track and mode persist.
    assert all(s is False for s in after_clear.tracks[0].loops[1].steps)
    assert after_clear.tracks[0] is not None
    assert after_clear.mode is Mode.INSTRUMENT
    # BACK now GCs the empty armed track.
    after_back = reduce(after_clear, SoftkeyPressed(key=3))
    assert after_back.tracks[0] is None
    assert after_back.mode is Mode.SESSION


def test_pad_toggle_armed_track_persists_until_back():
    """Toggling off the last step keeps the armed slot alive; BACK GCs it."""
    state = _armed_instrument(armed=(0,))
    t0 = state.tracks[0]
    blank_loop0 = default_loop(16)
    new_loops = (blank_loop0,) + t0.loops[1:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    state = dataclasses.replace(state, tracks=(new_t0,) + state.tracks[1:])
    state = _step_on(state, track_idx=0, loop_idx=1, step=2)
    after_toggle = reduce(state, PadPressed(pad_index=2, velocity=100))  # step off
    assert after_toggle.tracks[0] is not None
    assert after_toggle.mode is Mode.INSTRUMENT
    after_back = reduce(after_toggle, SoftkeyPressed(key=3))
    assert after_back.tracks[0] is None
    assert after_back.mode is Mode.SESSION


def test_dual_arm_track2_all_empty_stays_armed():
    """Removing all steps from arm2 does NOT disarm it — dual editing persists."""
    state = _armed_instrument(armed=(0, 1))
    # Blank every loop of track 1 so it has zero content anywhere.
    t1 = state.tracks[1]
    blank_loops = tuple(default_loop(16) for _ in range(16))
    t1_blank = dataclasses.replace(t1, loops=blank_loops)
    state = dataclasses.replace(state, tracks=(state.tracks[0], t1_blank) + state.tracks[2:])
    # Add one step to the selected loop, then toggle it back off.
    state = _step_on(state, track_idx=1, loop_idx=1, step=5)
    # In dual-arm INSTRUMENT: top-row pad (pad >= 16) → armed_tracks[1], step = pad % 16
    after_toggle = reduce(state, PadPressed(pad_index=16 + 5, velocity=100))
    # Track 1 is now fully empty but must stay alive (still armed).
    assert after_toggle.armed_tracks == (0, 1)
    assert after_toggle.tracks[1] is not None
    assert after_toggle.mode is Mode.INSTRUMENT


def test_instrument_touchbar_sets_view_measure():
    """TouchbarMoved updates instrument_view_measure proportionally."""
    state = _armed_instrument(armed=(0,))
    # Extend to 4 bars
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    for _ in range(3):
        state = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert state.tracks[0].loops[1].step_count == 64  # 4 bars * 4 beats * 4 = 64
    state = dataclasses.replace(state, instrument_active_ctrl="")
    # TouchbarMoved at 0.75 → should select measure 3 (of 4)
    result = reduce(state, TouchbarMoved(position=0.75))
    assert result.instrument_view_measure == 3


def test_instrument_pad_uses_view_measure():
    """Pad press in INSTRUMENT mode uses instrument_view_measure to offset step index."""
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    state = reduce(state, EncoderTurned(encoder=9, delta=1))  # extend to 2 bars = 32 steps
    state = dataclasses.replace(state, instrument_active_ctrl="", instrument_view_measure=1)
    # Press pad 0 with view_measure=1 → should toggle step 16 (not step 0)
    result = reduce(state, PadPressed(pad_index=0, velocity=100))
    assert result.tracks[0].loops[1].steps[16] is True
    assert result.tracks[0].loops[1].steps[0] is False


def test_instrument_pad_auto_extends_loop_when_editing_beyond_length():
    """Pressing a pad beyond the current loop length auto-extends it."""
    state = _armed_instrument(armed=(0,))
    # Loop 1 has 16 steps. Set view_measure=1 and press pad 0 → step 16.
    state = dataclasses.replace(state, instrument_view_measure=1)
    result = reduce(state, PadPressed(pad_index=0, velocity=100))
    # Loop should have been extended to at least 32 steps (2 bars)
    assert result.tracks[0].loops[1].step_count == 32
    assert result.tracks[0].loops[1].steps[16] is True


# ── BARS control ─────────────────────────────────────────────────────────────


def test_instrument_sk0_activates_bars_ctrl():
    state = _armed_instrument(armed=(0,))
    result = reduce(state, SoftkeyPressed(key=0))
    assert result.instrument_active_ctrl == "BARS"
    result2 = reduce(result, SoftkeyPressed(key=0))
    assert result2.instrument_active_ctrl == ""


def test_instrument_bars_jogwheel_extends():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    assert state.tracks[0].loops[1].bars == 1
    result = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert result.tracks[0].loops[1].bars == 2
    assert result.tracks[0].loops[1].step_count == 32


def test_instrument_bars_jogwheel_shrinks():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    state = reduce(state, EncoderTurned(encoder=9, delta=1))
    result = reduce(state, EncoderTurned(encoder=9, delta=-1))
    assert result.tracks[0].loops[1].bars == 1
    assert result.tracks[0].loops[1].step_count == 16


def test_instrument_bars_min_is_1():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    result = reduce(state, EncoderTurned(encoder=9, delta=-1))
    assert result.tracks[0].loops[1].bars == 1


def test_instrument_bars_max_is_8():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    for _ in range(10):
        state = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert state.tracks[0].loops[1].bars == 8
    assert state.tracks[0].loops[1].step_count == 128


def test_instrument_bars_applies_to_both_armed_tracks():
    state = _armed_instrument(armed=(0, 1))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    result = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert result.tracks[0].loops[1].bars == 2
    assert result.tracks[1].loops[1].bars == 2


def test_instrument_bars_works_in_dual_arm():
    """BARS is not disabled in dual-arm mode."""
    state = _armed_instrument(armed=(0, 1))
    result = reduce(state, SoftkeyPressed(key=0))
    assert result.instrument_active_ctrl == "BARS"


# ── NUMER control ─────────────────────────────────────────────────────────────


def test_instrument_sk1_activates_numer_ctrl():
    state = _armed_instrument(armed=(0,))
    result = reduce(state, SoftkeyPressed(key=1))
    assert result.instrument_active_ctrl == "NUMER"
    result2 = reduce(result, SoftkeyPressed(key=1))
    assert result2.instrument_active_ctrl == ""


def test_instrument_numer_jogwheel_changes_numerator():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="NUMER")
    assert state.tracks[0].loops[1].numerator == 4
    result = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert result.tracks[0].loops[1].numerator == 5
    assert result.tracks[0].loops[1].step_count == 20  # 1*5*(16//4)=20


def test_instrument_numer_jogwheel_three_four():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="NUMER")
    result = reduce(state, EncoderTurned(encoder=9, delta=-1))
    assert result.tracks[0].loops[1].numerator == 3
    assert result.tracks[0].loops[1].step_count == 12  # 1*3*4=12


def test_instrument_numer_min_is_1():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="NUMER")
    for _ in range(5):
        state = reduce(state, EncoderTurned(encoder=9, delta=-1))
    assert state.tracks[0].loops[1].numerator == 1


def test_instrument_numer_max_is_16():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="NUMER")
    for _ in range(20):
        state = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert state.tracks[0].loops[1].numerator == 16


# ── SIZE control ──────────────────────────────────────────────────────────────


def test_instrument_sk2_activates_size_ctrl():
    state = _armed_instrument(armed=(0,))
    result = reduce(state, SoftkeyPressed(key=2))
    assert result.instrument_active_ctrl == "SIZE"
    result2 = reduce(result, SoftkeyPressed(key=2))
    assert result2.instrument_active_ctrl == ""


def test_instrument_size_jogwheel_increases_resolution():
    """step_size 16 → 32 doubles total steps."""
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="SIZE")
    assert state.tracks[0].loops[1].step_size == 16
    result = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert result.tracks[0].loops[1].step_size == 32
    assert result.tracks[0].loops[1].step_count == 32  # 1*4*8=32


def test_instrument_size_jogwheel_decreases_resolution():
    """step_size 16 → 8 halves total steps."""
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="SIZE")
    result = reduce(state, EncoderTurned(encoder=9, delta=-1))
    assert result.tracks[0].loops[1].step_size == 8
    assert result.tracks[0].loops[1].step_count == 8  # 1*4*2=8


def test_instrument_size_min_is_4():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="SIZE")
    for _ in range(5):
        state = reduce(state, EncoderTurned(encoder=9, delta=-1))
    assert state.tracks[0].loops[1].step_size == 4


def test_instrument_size_max_is_32():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="SIZE")
    for _ in range(5):
        state = reduce(state, EncoderTurned(encoder=9, delta=1))
    assert state.tracks[0].loops[1].step_size == 32


# ── Playhead reset on shrink ──────────────────────────────────────────────────


def test_bars_shrink_resets_playing_measure_offset():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="BARS")
    state = reduce(state, EncoderTurned(encoder=9, delta=1))  # 2 bars
    key = (0, 1)
    state = dataclasses.replace(
        state, playing_loops=frozenset({key}), loop_measure_offsets=((key, 1),)
    )
    result = reduce(state, EncoderTurned(encoder=9, delta=-1))  # back to 1 bar
    assert result.tracks[0].loops[1].bars == 1
    assert dict(result.loop_measure_offsets).get(key, 0) == 0


def test_size_shrink_resets_playing_measure_offset():
    state = _armed_instrument(armed=(0,))
    state = dataclasses.replace(state, instrument_active_ctrl="SIZE")
    state = reduce(state, EncoderTurned(encoder=9, delta=1))  # size=32, step_count=32
    key = (0, 1)
    state = dataclasses.replace(
        state, playing_loops=frozenset({key}), loop_measure_offsets=((key, 1),)
    )
    result = reduce(state, EncoderTurned(encoder=9, delta=-1))  # back to size=16, step_count=16
    assert result.tracks[0].loops[1].step_count == 16
    assert dict(result.loop_measure_offsets).get(key, 0) == 0


# ── Garbage collection of empty tracks ───────────────────────────────────────


def test_session_pad_switch_gcs_empty_track():
    """Pressing a different bottom pad nulls out the previous selected track if all its loops are empty."""
    s = default_state()
    # Select empty slot 2, then CREATE the track via SK5.
    s = reduce(s, PadPressed(pad_index=2, velocity=100))
    s = reduce(s, SoftkeyPressed(key=4))  # SK5 = CREATE
    assert s.tracks[2] is not None
    assert s.selected_track == 2
    # Now press pad 0 — track 2 has no steps, so it should be GC'd back to None.
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s.tracks[2] is None


def test_session_pad_switch_preserves_nonempty_track():
    """Switching pads does NOT GC a track that has content."""
    s = default_state()  # track 0 has a kick pattern
    s = reduce(s, PadPressed(pad_index=1, velocity=100))
    assert s.tracks[0] is not None


def test_session_pad_same_pad_no_gc():
    """Re-pressing the same pad does not GC the current track."""
    s = default_state()
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s.tracks[0] is not None


def test_session_pad_switch_gcs_muted_empty_track():
    """GC of an empty track also removes it from muted_tracks."""
    s = default_state()
    s = reduce(s, PadPressed(pad_index=2, velocity=100))  # select empty slot 2
    s = reduce(s, SoftkeyPressed(key=4))                  # SK5 = CREATE
    s = dataclasses.replace(s, muted_tracks=frozenset({2}))
    s = reduce(s, PadPressed(pad_index=0, velocity=100))  # switch away → GC track 2
    assert s.tracks[2] is None
    assert 2 not in s.muted_tracks


def test_instrument_back_gcs_empty_armed_track():
    """BACK from INSTRUMENT nulls the armed slot when no steps were added."""
    s = default_state()
    # Select empty slot 2 and enter INSTRUMENT — track is created automatically.
    s = reduce(s, PadPressed(pad_index=2, velocity=100))
    s = reduce(s, ModeButtonPressed(button="INST", pressed=True))
    assert s.mode is Mode.INSTRUMENT
    assert s.tracks[2] is not None
    # Press BACK without adding any steps → track 2 should be GC'd.
    s = reduce(s, SoftkeyPressed(key=3))
    assert s.mode is Mode.SESSION
    assert s.tracks[2] is None


def test_instrument_back_preserves_nonempty_armed_track():
    """BACK from INSTRUMENT keeps the armed track when it has content."""
    s = _armed_instrument(armed=(0,))
    s = reduce(s, PadPressed(pad_index=0, velocity=100))  # add a step
    s = reduce(s, SoftkeyPressed(key=3))                  # BACK
    assert s.tracks[0] is not None


def test_song_button_from_instrument_gcs_empty_armed_track():
    """SONG button from INSTRUMENT also GCs empty armed tracks."""
    s = default_state()
    s = reduce(s, PadPressed(pad_index=2, velocity=100))
    s = reduce(s, ModeButtonPressed(button="INST", pressed=True))
    s = reduce(s, ModeButtonPressed(button="SONG", pressed=True))
    assert s.mode is Mode.SESSION
    assert s.tracks[2] is None


def test_inst_from_empty_slot_creates_track_immediately():
    """Pressing INST on an empty slot creates the track without needing SK5."""
    s = default_state()
    s = reduce(s, PadPressed(pad_index=2, velocity=100))
    s = reduce(s, ModeButtonPressed(button="INST", pressed=True))
    assert s.mode is Mode.INSTRUMENT
    assert s.tracks[2] is not None
    assert s.armed_tracks == (2,)


def test_inst_from_empty_slot_saves_and_restores_armed_tracks():
    """Armed tracks before entering INST from empty slot are restored on BACK."""
    s = dataclasses.replace(default_state(), armed_tracks=(0, 1))
    s = reduce(s, PadPressed(pad_index=2, velocity=100))
    s = reduce(s, ModeButtonPressed(button="INST", pressed=True))
    assert s.armed_tracks == (2,)
    assert s.saved_armed_tracks == (0, 1)
    # BACK → previous arm state restored
    s = reduce(s, SoftkeyPressed(key=3))
    assert s.mode is Mode.SESSION
    assert s.armed_tracks == (0, 1)
    assert s.saved_armed_tracks is None


def test_inst_from_empty_slot_song_restores_armed_tracks():
    """SONG button also restores saved arm state when returning to SESSION."""
    s = dataclasses.replace(default_state(), armed_tracks=(0,))
    s = reduce(s, PadPressed(pad_index=2, velocity=100))
    s = reduce(s, ModeButtonPressed(button="INST", pressed=True))
    # Add a step so track 2 is not GC'd
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    s = reduce(s, ModeButtonPressed(button="SONG", pressed=True))
    assert s.mode is Mode.SESSION
    assert s.armed_tracks == (0,)
    assert s.saved_armed_tracks is None


# ── Immutability ──────────────────────────────────────────────────────────────


def test_reduce_does_not_mutate_input_state():
    """reduce() never mutates the input state object after a step toggle."""
    state = _armed_instrument(armed=(0,))
    original_steps = state.tracks[0].loops[1].steps

    _ = reduce(state, PadPressed(pad_index=0, velocity=100))

    assert state.tracks[0].loops[1].steps == original_steps
    assert state.tracks[0].loops[1].steps[0] is False


