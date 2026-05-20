"""reduce.py — Pure reducer for Eden AppState transitions."""

from __future__ import annotations

import dataclasses

from eden.state import (
    AppState,
    DrumTrack,
    InstrumentSubmode,
    Loop,
    Mode,
    SampleTrack,
    SynthTrack,
    Track,
    default_loop,
    default_track_loops,
)
from eden.events import (
    ClockTicked,
    EncoderTurned,
    Event,
    ModeButtonPressed,
    PadPressed,
    PadReleased,
    ShiftChanged,
    SoftkeyPressed,
    TransportPressed,
)


# Predefined name/sample pairs for each of the 16 track slots.
_TRACK_DEFAULTS: tuple[tuple[str, str], ...] = (
    ("KICK",  "kick"),
    ("SNARE", "snare"),
    ("HAT",   "hihat_closed"),
    ("CLAP",  "clap"),
    ("RIDE",  "ride"),
    ("CRASH", "crash"),
    ("TOM1",  "tom_hi"),
    ("TOM2",  "tom_lo"),
    ("PERC1", "perc1"),
    ("PERC2", "perc2"),
    ("BASS",  "bass"),
    ("LEAD",  "lead"),
    ("PAD",   "pad"),
    ("FX1",   "fx1"),
    ("FX2",   "fx2"),
    ("FX3",   "fx3"),
)


# ── Top-level dispatch ────────────────────────────────────────────────────────


def reduce(state: AppState, event: Event) -> AppState:
    if isinstance(event, ShiftChanged):
        return dataclasses.replace(state, shift_held=event.held)
    if isinstance(event, ClockTicked):
        return _on_clock_ticked(state)
    if isinstance(event, ModeButtonPressed):
        return _on_mode_button(state, event)
    if state.mode == Mode.SESSION:
        return _reduce_session(state, event)
    if state.mode == Mode.INSTRUMENT:
        return _reduce_instrument(state, event)
    return state


# ── Global handlers ───────────────────────────────────────────────────────────


def _on_clock_ticked(state: AppState) -> AppState:
    if not state.is_playing:
        return state
    # In single-arm INSTRUMENT, wrap at the actual loop's step count (16 or 32).
    if state.mode == Mode.INSTRUMENT and len(state.armed_tracks) == 1:
        track = state.tracks[state.armed_tracks[0]]
        max_steps = track.loops[state.selected_loop].step_count if track is not None else 16
    else:
        max_steps = 16
    new_playhead = (state.playhead + 1) % max_steps
    state = dataclasses.replace(state, playhead=new_playhead)
    # On wrap, decrement plays_remaining and stop any finished loops.
    if new_playhead == 0:
        state = _handle_loop_wrap(state)
    return state


def _handle_loop_wrap(state: AppState) -> AppState:
    """Decrement plays_remaining on wrap; remove loops whose count hits zero."""
    remaining = dict(state.plays_remaining)
    loops_to_stop: set[tuple[int, int]] = set()
    for (track_idx, loop_idx) in state.playing_loops:
        track = state.tracks[track_idx]
        if track is None:
            loops_to_stop.add((track_idx, loop_idx))
            continue
        key = (track_idx, loop_idx)
        if key not in remaining:
            continue  # not tracking plays (infinite loop)
        count = remaining[key] - 1
        if count <= 0:
            loops_to_stop.add(key)
            del remaining[key]
        else:
            remaining[key] = count
    return dataclasses.replace(
        state,
        playing_loops=state.playing_loops - loops_to_stop,
        plays_remaining=tuple(remaining.items()),
    )


def _on_mode_button(state: AppState, event: ModeButtonPressed) -> AppState:
    if not event.pressed:
        return state
    if event.button == "INST":
        if state.armed_tracks:
            # Already armed — just switch to INSTRUMENT view.
            return dataclasses.replace(state, mode=Mode.INSTRUMENT)
        # Nothing armed yet — arm selected track and enter INSTRUMENT.
        return dataclasses.replace(
            state,
            armed_tracks=(state.selected_track,),
            mode=Mode.INSTRUMENT,
            instrument_submode=InstrumentSubmode.STEPS,
        )
    if event.button == "SONG":
        return dataclasses.replace(state, mode=Mode.SESSION)
    # EDIT, USER, BACK, FORWARD — no-op for M1/M2
    return state


# ── Session mode ──────────────────────────────────────────────────────────────


def _reduce_session(state: AppState, event: Event) -> AppState:
    if isinstance(event, PadPressed):
        return _session_pad_pressed(state, event)
    if isinstance(event, TransportPressed):
        return _session_transport(state, event)
    if isinstance(event, SoftkeyPressed):
        return _session_softkey(state, event)
    if isinstance(event, EncoderTurned):
        return _session_encoder(state, event)
    return state


def _session_pad_pressed(state: AppState, event: PadPressed) -> AppState:
    pad = event.pad_index
    if pad < 16:
        # Bottom row: select track; auto-select loop 0; create DrumTrack if slot is empty
        track = state.tracks[pad]
        if track is None:
            name, sample = _TRACK_DEFAULTS[pad]
            new_track = DrumTrack(name=name, sample_name=sample, loops=default_track_loops())
            new_tracks = state.tracks[:pad] + (new_track,) + state.tracks[pad + 1:]
            return dataclasses.replace(
                state,
                tracks=new_tracks,
                selected_track=pad,
                selected_loop=0,
                arm_pads_offer_loop=None,
            )
        return dataclasses.replace(
            state,
            selected_track=pad,
            selected_loop=0,
            arm_pads_offer_loop=None,
        )
    else:
        # Top row: always update selected_loop for visual feedback, then toggle
        # playing only if the loop has content.
        loop_idx = pad - 16
        base = dataclasses.replace(state, selected_loop=loop_idx, arm_pads_offer_loop=None)

        # Shift + empty loop → offer ARM PADS mode
        if state.shift_held:
            track = state.tracks[state.selected_track]
            if track is not None and track.loops[loop_idx].is_empty:
                return dataclasses.replace(base, arm_pads_offer_loop=loop_idx)

        track = state.tracks[state.selected_track]
        if track is None or track.loops[loop_idx].is_empty:
            # Empty loop: just select it (green highlight signals it's ready to arm)
            return base

        pair = (state.selected_track, loop_idx)
        if pair in state.playing_loops:
            new_playing = state.playing_loops - {pair}
            new_remaining = tuple(e for e in state.plays_remaining if e[0] != pair)
        else:
            new_playing = state.playing_loops | {pair}
            lc = track.loops[loop_idx].loop_count
            new_remaining = (
                state.plays_remaining + ((pair, lc),) if lc > 0 else state.plays_remaining
            )
        return dataclasses.replace(
            base,
            playing_loops=new_playing,
            plays_remaining=new_remaining,
        )


def _session_transport(state: AppState, event: TransportPressed) -> AppState:
    if not event.pressed:
        return state
    if event.button == "PLAY":
        return dataclasses.replace(state, is_playing=True)
    if event.button == "STOP":
        return dataclasses.replace(state, is_playing=False, playhead=0)
    return state


def _session_softkey(state: AppState, event: SoftkeyPressed) -> AppState:
    t = state.selected_track
    # If ARM PADS offer is active, SK5 accepts it
    if event.key == 4 and state.arm_pads_offer_loop is not None:
        return dataclasses.replace(
            state,
            armed_tracks=(t,),
            selected_loop=state.arm_pads_offer_loop,
            mode=Mode.INSTRUMENT,
            instrument_submode=InstrumentSubmode.PADS,
            arm_pads_offer_loop=None,
        )
    if event.key == 0:  # SK1: MUTE toggle
        new_muted = (
            state.muted_tracks - {t}
            if t in state.muted_tracks
            else state.muted_tracks | {t}
        )
        return dataclasses.replace(state, muted_tracks=new_muted)
    if event.key == 1:  # SK2: SOLO toggle
        new_soloed = (
            state.soloed_tracks - {t}
            if t in state.soloed_tracks
            else state.soloed_tracks | {t}
        )
        return dataclasses.replace(state, soloed_tracks=new_soloed)
    if event.key == 2:  # SK3: LOOPxN — cycle loop_count on selected loop
        return _cycle_loop_count(state)
    if event.key == 3:  # SK4: ARM1 — arm selected track as single, enter INSTRUMENT
        return _arm_single(state)
    if event.key == 4:  # SK5: ARM2 — add to dual-arm list
        return _arm_dual(state)
    return state


def _cycle_loop_count(state: AppState) -> AppState:
    """Cycle loop_count for the selected_loop of the selected_track.

    Cycle order: 0 (∞) → 1 → 2 → 4 → 8 → 0 (∞)
    Only implemented for DrumTrack; raises NotImplementedError for M3 types.
    """
    track = state.tracks[state.selected_track]
    if track is None or not isinstance(track, DrumTrack):
        return state
    if isinstance(track, (SynthTrack, SampleTrack)):
        raise NotImplementedError("SynthTrack/SampleTrack loop cycling is M3")

    _cycle_map = {0: 1, 1: 2, 2: 4, 4: 8, 8: 0}
    loop_idx = state.selected_loop
    loop = track.loops[loop_idx]
    next_count = _cycle_map.get(loop.loop_count, 0)
    new_loop = dataclasses.replace(loop, loop_count=next_count)
    new_loops = track.loops[:loop_idx] + (new_loop,) + track.loops[loop_idx + 1:]
    new_track = dataclasses.replace(track, loops=new_loops)
    new_tracks = state.tracks[:state.selected_track] + (new_track,) + state.tracks[state.selected_track + 1:]
    return dataclasses.replace(state, tracks=new_tracks)


def _arm_single(state: AppState) -> AppState:
    """Arm selected track as arm1; disarm if it is already arm1."""
    t = state.selected_track
    if state.armed_tracks and state.armed_tracks[0] == t:
        # Tap again to disarm — clear all arms, stay in SESSION
        return dataclasses.replace(state, armed_tracks=())
    return dataclasses.replace(
        state,
        armed_tracks=(t,),
        mode=Mode.INSTRUMENT,
        instrument_submode=InstrumentSubmode.STEPS,
    )


def _arm_dual(state: AppState) -> AppState:
    """Add selected_track as arm2; disarm arm2 if it is already arm2."""
    t = state.selected_track
    # Tap again to disarm arm2
    if len(state.armed_tracks) >= 2 and state.armed_tracks[1] == t:
        return dataclasses.replace(state, armed_tracks=state.armed_tracks[:1])
    if t in state.armed_tracks:
        return state  # already arm1 — no-op
    new_armed = state.armed_tracks + (t,)
    if len(new_armed) >= 2:
        return dataclasses.replace(
            state,
            armed_tracks=new_armed[:2],
            mode=Mode.INSTRUMENT,
            instrument_submode=InstrumentSubmode.STEPS,
        )
    return dataclasses.replace(state, armed_tracks=new_armed)


def _session_encoder(state: AppState, event: EncoderTurned) -> AppState:
    if event.encoder == 9:
        new_bpm = max(60.0, min(200.0, state.tempo_bpm + event.delta))
        return dataclasses.replace(state, tempo_bpm=float(new_bpm))
    return state


# ── Instrument mode ───────────────────────────────────────────────────────────


def _reduce_instrument(state: AppState, event: Event) -> AppState:
    if isinstance(event, PadPressed):
        return _instrument_pad_pressed(state, event)
    if isinstance(event, TransportPressed):
        return _instrument_transport(state, event)
    if isinstance(event, SoftkeyPressed):
        return _instrument_softkey(state, event)
    return state


def _instrument_pad_pressed(state: AppState, event: PadPressed) -> AppState:
    pad = event.pad_index
    loop_idx = state.selected_loop

    if len(state.armed_tracks) == 1:
        step = pad
        new_state = _toggle_step(state, state.armed_tracks[0], loop_idx, step)
    else:
        step = pad % 16
        track_idx = state.armed_tracks[0] if pad < 16 else state.armed_tracks[1]
        new_state = _toggle_step(state, track_idx, loop_idx, step)

    # Auto-start any armed loop that just became non-empty.
    new_playing = set(new_state.playing_loops)
    changed = False
    for track_idx in new_state.armed_tracks:
        key = (track_idx, loop_idx)
        if key not in new_playing:
            track = new_state.tracks[track_idx]
            if track is not None and not track.loops[loop_idx].is_empty:
                new_playing.add(key)
                changed = True
    if changed:
        new_state = dataclasses.replace(new_state, playing_loops=frozenset(new_playing))
    return new_state


def _toggle_step(
    state: AppState, track_idx: int, loop_idx: int, step_idx: int
) -> AppState:
    """Return a new AppState with the given step toggled. Pure, no mutation."""
    track = state.tracks[track_idx]
    if track is None:
        return state
    if isinstance(track, (SynthTrack, SampleTrack)):
        raise NotImplementedError("SynthTrack/SampleTrack step editing is M3")
    # DrumTrack path
    loop = track.loops[loop_idx]
    old_steps = loop.steps
    if step_idx >= len(old_steps):
        return state
    new_steps = old_steps[:step_idx] + (not old_steps[step_idx],) + old_steps[step_idx + 1:]
    new_loop = dataclasses.replace(loop, steps=new_steps)
    new_loops = track.loops[:loop_idx] + (new_loop,) + track.loops[loop_idx + 1:]
    new_track = dataclasses.replace(track, loops=new_loops)
    new_tracks = state.tracks[:track_idx] + (new_track,) + state.tracks[track_idx + 1:]
    return dataclasses.replace(state, tracks=new_tracks)


def _instrument_transport(state: AppState, event: TransportPressed) -> AppState:
    if not event.pressed:
        return state
    if event.button == "PLAY":
        return dataclasses.replace(state, is_playing=True)
    if event.button == "STOP":
        return dataclasses.replace(state, is_playing=False, playhead=0)
    return state


def _instrument_softkey(state: AppState, event: SoftkeyPressed) -> AppState:
    if event.key == 0:  # SK1: STEPS — currently active submode; no-op
        return state
    if event.key == 1:  # SK2: EXTEND/SHRINK — toggle selected loop step count 16↔32
        return _toggle_step_count(state)
    if event.key == 2:  # SK3: PADS — placeholder
        return state
    if event.key == 3:  # SK4: BACK — return to SESSION
        return dataclasses.replace(state, mode=Mode.SESSION)
    if event.key == 4:  # SK5: CLEAR — only executes with shift held
        if state.shift_held:
            return _clear_armed_loops(state)
        return state
    return state


def _toggle_step_count(state: AppState) -> AppState:
    """Toggle the selected loop's step count between 16 and 32 for all armed DrumTracks."""
    new_state = state
    for track_idx in state.armed_tracks:
        track = new_state.tracks[track_idx]
        if track is None or not isinstance(track, DrumTrack):
            continue
        loop = track.loops[new_state.selected_loop]
        if loop.step_count == 16:
            new_steps = loop.steps + tuple(False for _ in range(16))
        else:
            new_steps = loop.steps[:16]
        new_loop = dataclasses.replace(loop, steps=new_steps)
        new_loops = (
            track.loops[:new_state.selected_loop]
            + (new_loop,)
            + track.loops[new_state.selected_loop + 1:]
        )
        new_track = dataclasses.replace(track, loops=new_loops)
        new_tracks = (
            new_state.tracks[:track_idx]
            + (new_track,)
            + new_state.tracks[track_idx + 1:]
        )
        new_state = dataclasses.replace(new_state, tracks=new_tracks)
    return new_state


def _clear_armed_loops(state: AppState) -> AppState:
    """Clear all steps in selected_loop for every armed DrumTrack. Pure."""
    new_state = state
    for track_idx in state.armed_tracks:
        track = new_state.tracks[track_idx]
        if track is None or not isinstance(track, DrumTrack):
            continue
        loop = track.loops[new_state.selected_loop]
        blank = default_loop(loop.step_count)
        new_loop = dataclasses.replace(loop, steps=blank.steps)
        new_loops = (
            track.loops[:new_state.selected_loop]
            + (new_loop,)
            + track.loops[new_state.selected_loop + 1:]
        )
        new_track = dataclasses.replace(track, loops=new_loops)
        new_tracks = (
            new_state.tracks[:track_idx]
            + (new_track,)
            + new_state.tracks[track_idx + 1:]
        )
        new_state = dataclasses.replace(new_state, tracks=new_tracks)
    return new_state
