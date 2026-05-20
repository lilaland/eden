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


def test_clock_wraps_at_16_in_session():
    """Playhead wraps 15→0 in SESSION mode (16-step)."""
    state = dataclasses.replace(_playing_session(), playhead=15)
    result = reduce(state, ClockTicked())
    assert result.playhead == 0


def test_clock_wraps_at_16_in_dual_arm_instrument():
    """Playhead wraps 15→0 in dual-arm INSTRUMENT mode (16-step)."""
    state = dataclasses.replace(
        _armed_instrument(armed=(0, 1)),
        is_playing=True,
        playhead=15,
    )
    result = reduce(state, ClockTicked())
    assert result.playhead == 0


def test_clock_wraps_at_16_in_single_arm_instrument_with_16step_loop():
    """Playhead wraps 15→0 in single-arm INSTRUMENT when the loop is 16-step."""
    state = dataclasses.replace(
        _armed_instrument(armed=(0,)),
        is_playing=True,
        playhead=15,
    )
    result = reduce(state, ClockTicked())
    assert result.playhead == 0  # wraps at 16, not 32


def test_clock_wraps_at_32_in_single_arm_instrument():
    """Playhead wraps 31→0 in single-arm INSTRUMENT when the loop is 32-step."""
    base = _armed_instrument(armed=(0,))
    track = base.tracks[0]
    assert isinstance(track, DrumTrack)
    long_loop = default_loop(32)
    new_loops = track.loops[:1] + (long_loop,) + track.loops[2:]  # replace loop 1 (selected)
    new_track = dataclasses.replace(track, loops=new_loops)
    state = dataclasses.replace(
        base,
        tracks=(new_track,) + base.tracks[1:],
        is_playing=True,
        playhead=31,
    )
    result = reduce(state, ClockTicked())
    assert result.playhead == 0


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


def test_session_pad_bottom_row_selects_empty_slot():
    """Pressing an empty track slot selects it (green highlight); does not auto-create."""
    state = default_state()
    assert state.tracks[2] is None
    result = reduce(state, PadPressed(pad_index=2, velocity=100))
    assert result.tracks[2] is None        # no auto-creation
    assert result.selected_track == 2      # slot is selected


def test_session_sk1_creates_drum_for_empty_slot():
    """SK1 (DRUMS) creates a DrumTrack when the selected track slot is empty."""
    state = dataclasses.replace(default_state(), selected_track=2)
    assert state.tracks[2] is None
    result = reduce(state, SoftkeyPressed(key=0))
    assert isinstance(result.tracks[2], DrumTrack)


def test_session_sk1_mute_when_track_exists():
    """SK1 still mutes the selected track when a track is present."""
    state = default_state()  # track 0 is DrumTrack
    assert state.tracks[0] is not None
    result = reduce(state, SoftkeyPressed(key=0))
    assert 0 in result.muted_tracks


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
    # Set up: track 0, loop 0 playing with loop_count=2
    s = dataclasses.replace(
        default_state(),
        selected_track=0,
        playing_loops=frozenset({(0, 0)}),
        plays_remaining=(((0, 0), 2),),
        playhead=15,
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
        playhead=15,
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


def test_sk4_arms_single_and_enters_instrument():
    """SK4 arms selected track, switches mode to INSTRUMENT, sets single-arm."""
    state = dataclasses.replace(default_state(), selected_track=1)
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.armed_tracks == (1,)
    assert result.mode is Mode.INSTRUMENT
    assert result.instrument_submode is InstrumentSubmode.STEPS


def test_sk5_arms_two_tracks_and_enters_instrument():
    """SK5 adds tracks one at a time; two presses arms 2 tracks and enters INSTRUMENT."""
    state = dataclasses.replace(default_state(), selected_track=0)
    # First press on track 0
    s1 = reduce(state, SoftkeyPressed(key=4))
    assert s1.armed_tracks == (0,)
    assert s1.mode is Mode.SESSION  # still waiting for second

    # Move to track 1, second press
    s1 = dataclasses.replace(s1, selected_track=1)
    s2 = reduce(s1, SoftkeyPressed(key=4))
    assert s2.armed_tracks == (0, 1)
    assert s2.mode is Mode.INSTRUMENT
    assert s2.instrument_submode is InstrumentSubmode.STEPS


def test_sk5_ignores_already_armed_track():
    """SK5 is a no-op when selected track is already arm1 (not arm2)."""
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


def test_instrument_sk4_back_starts_nonempty_loop():
    """SK4 (BACK) auto-adds the armed track's non-empty loop to playing_loops."""
    state = _step_on(_armed_instrument(armed=(0,)), track_idx=0, loop_idx=1, step=0)
    # Loop 1 of track 0 now has a step; it should be auto-started on BACK
    assert (0, 1) not in state.playing_loops
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.mode is Mode.SESSION
    assert (0, 1) in result.playing_loops


def test_instrument_sk4_back_does_not_start_empty_loop():
    """SK4 (BACK) leaves empty loops out of playing_loops."""
    state = _armed_instrument(armed=(0,))  # loop 1 is empty
    result = reduce(state, SoftkeyPressed(key=3))
    assert (0, 1) not in result.playing_loops


def test_instrument_sk4_back_dual_arm_starts_both_nonempty():
    """SK4 (BACK) auto-starts non-empty loops for all armed tracks in dual-arm."""
    state = _armed_instrument(armed=(0, 1))
    state = _step_on(state, track_idx=0, loop_idx=1, step=0)
    state = _step_on(state, track_idx=1, loop_idx=1, step=2)
    result = reduce(state, SoftkeyPressed(key=3))
    assert result.mode is Mode.SESSION
    assert (0, 1) in result.playing_loops
    assert (1, 1) in result.playing_loops


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


# ── Instrument SK2: EXTEND / SHRINK ──────────────────────────────────────────


def test_instrument_sk2_extends_loop_from_16_to_32():
    """SK2 (EXTEND) doubles the selected loop from 16 to 32 steps."""
    state = _armed_instrument(armed=(0,))
    assert state.tracks[0].loops[1].step_count == 16
    result = reduce(state, SoftkeyPressed(key=1))
    assert result.tracks[0].loops[1].step_count == 32
    assert len(result.tracks[0].loops[1].steps) == 32


def test_instrument_sk2_shrinks_loop_from_32_to_16():
    """SK2 (SHRINK) halves the selected loop from 32 to 16 steps."""
    state = _armed_instrument(armed=(0,))
    extended = reduce(state, SoftkeyPressed(key=1))
    assert extended.tracks[0].loops[1].step_count == 32
    shrunk = reduce(extended, SoftkeyPressed(key=1))
    assert shrunk.tracks[0].loops[1].step_count == 16


def test_instrument_sk2_extend_applies_to_both_armed_tracks():
    """SK2 extends the selected loop for all armed DrumTracks simultaneously."""
    state = _armed_instrument(armed=(0, 1))
    result = reduce(state, SoftkeyPressed(key=1))
    assert result.tracks[0].loops[1].step_count == 32
    assert result.tracks[1].loops[1].step_count == 32


# ── Immutability ──────────────────────────────────────────────────────────────


def test_reduce_does_not_mutate_input_state():
    """reduce() never mutates the input state object after a step toggle."""
    state = _armed_instrument(armed=(0,))
    # Capture original steps tuple for track 0 loop 1 (the selected empty loop)
    original_steps = state.tracks[0].loops[1].steps

    _ = reduce(state, PadPressed(pad_index=0, velocity=100))

    # Input state must be entirely unchanged
    assert state.tracks[0].loops[1].steps == original_steps
    assert state.tracks[0].loops[1].steps[0] is False
