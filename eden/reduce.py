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
    TouchbarMoved,
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
    new_playhead = (state.playhead + 1) % 16
    state = dataclasses.replace(state, playhead=new_playhead)
    if new_playhead == 0:
        state = _handle_loop_wrap(state)
    return state


def _handle_loop_wrap(state: AppState) -> AppState:
    """Advance measure offsets on each 16-step wrap; decrement plays_remaining only on full loop completion."""
    remaining = dict(state.plays_remaining)
    offsets = dict(state.loop_measure_offsets)
    loops_to_stop: set[tuple[int, int]] = set()

    for key in state.playing_loops:
        track_idx, loop_idx = key
        track = state.tracks[track_idx]
        if track is None:
            loops_to_stop.add(key)
            continue

        loop = track.loops[loop_idx]
        measure_count = loop.step_count // 16

        if measure_count > 1:
            current = offsets.get(key, 0)
            nxt = (current + 1) % measure_count
            offsets[key] = nxt
            if nxt != 0:
                continue  # mid-loop, don't count a play yet

        # 1-measure loop OR just completed all measures → count one play
        if key not in remaining:
            continue  # infinite loop
        count = remaining[key] - 1
        if count <= 0:
            loops_to_stop.add(key)
            del remaining[key]
            offsets.pop(key, None)
        else:
            remaining[key] = count

    for key in loops_to_stop:
        offsets.pop(key, None)

    return dataclasses.replace(
        state,
        playing_loops=state.playing_loops - loops_to_stop,
        plays_remaining=tuple(remaining.items()),
        loop_measure_offsets=tuple(offsets.items()),
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
        state = _drop_fully_empty_tracks(state, state.armed_tracks, skip_armed=False)
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
        # Bottom row: select track; auto-select loop 0; create DrumTrack if slot is empty.
        # GC the previously selected track if it has no content and we're moving away from it.
        if pad != state.selected_track:
            state = _drop_fully_empty_tracks(state, (state.selected_track,))
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
        offsets = dict(state.loop_measure_offsets)
        if pair in state.playing_loops:
            new_playing = state.playing_loops - {pair}
            new_remaining = tuple(e for e in state.plays_remaining if e[0] != pair)
            offsets.pop(pair, None)
        else:
            new_playing = state.playing_loops | {pair}
            lc = track.loops[loop_idx].loop_count
            new_remaining = (
                state.plays_remaining + ((pair, lc),) if lc > 0 else state.plays_remaining
            )
            offsets[pair] = 0  # initialize measure offset
        return dataclasses.replace(
            base,
            playing_loops=new_playing,
            plays_remaining=new_remaining,
            loop_measure_offsets=tuple(offsets.items()),
        )


def _session_transport(state: AppState, event: TransportPressed) -> AppState:
    if not event.pressed:
        return state
    if event.button == "PLAY":
        return dataclasses.replace(state, is_playing=True)
    if event.button == "STOP":
        return dataclasses.replace(state, is_playing=False, playhead=0, loop_measure_offsets=())
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
    """Set arm1 to selected track and stay in SESSION.

    - Same track as current arm1 → disarm both slots.
    - Different track → replace arm1; keep arm2 only if it differs from new arm1.
    """
    t = state.selected_track
    if state.armed_tracks and state.armed_tracks[0] == t:
        return dataclasses.replace(state, armed_tracks=())
    arm2 = state.armed_tracks[1] if len(state.armed_tracks) >= 2 else None
    new_armed = (t, arm2) if (arm2 is not None and arm2 != t) else (t,)
    return dataclasses.replace(state, armed_tracks=new_armed)


def _arm_dual(state: AppState) -> AppState:
    """Set arm2 to selected track and stay in SESSION.

    - No arm1 set → no-op (arm1 must come first).
    - Selected track == arm1 → no-op (can't arm same track twice).
    - Selected track == current arm2 → disarm arm2 only.
    - Otherwise → set/replace arm2.
    """
    t = state.selected_track
    if not state.armed_tracks:
        return state  # arm1 must be set first
    arm1 = state.armed_tracks[0]
    if t == arm1:
        return state  # can't be both arm1 and arm2
    if len(state.armed_tracks) >= 2 and state.armed_tracks[1] == t:
        return dataclasses.replace(state, armed_tracks=(arm1,))
    return dataclasses.replace(state, armed_tracks=(arm1, t))


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
    if isinstance(event, EncoderTurned):
        return _instrument_encoder(state, event)
    if isinstance(event, TouchbarMoved):
        return _instrument_touchbar(state, event)
    return state


def _ensure_loop_length(state: AppState, track_idx: int, loop_idx: int, min_steps: int) -> AppState:
    """Extend a DrumTrack loop to at least min_steps (in 16-step increments)."""
    track = state.tracks[track_idx]
    if track is None or not isinstance(track, DrumTrack):
        return state
    loop = track.loops[loop_idx]
    if loop.step_count >= min_steps:
        return state
    new_length = ((min_steps - 1) // 16 + 1) * 16
    extra = tuple(False for _ in range(new_length - loop.step_count))
    new_steps = loop.steps + extra
    new_loop = dataclasses.replace(loop, steps=new_steps)
    new_loops = track.loops[:loop_idx] + (new_loop,) + track.loops[loop_idx + 1:]
    new_track = dataclasses.replace(track, loops=new_loops)
    new_tracks = state.tracks[:track_idx] + (new_track,) + state.tracks[track_idx + 1:]
    return dataclasses.replace(state, tracks=new_tracks)


def _instrument_pad_pressed(state: AppState, event: PadPressed) -> AppState:
    pad = event.pad_index
    loop_idx = state.selected_loop
    view_m = state.instrument_view_measure

    if len(state.armed_tracks) == 1:
        affected_track = state.armed_tracks[0]
        # step = view_measure*16 + pad (pad 0-15 = bottom row, 16-31 = top row)
        step_idx = view_m * 16 + pad
        state = _ensure_loop_length(state, affected_track, loop_idx, step_idx + 1)
        new_state = _toggle_step(state, affected_track, loop_idx, step_idx)
    else:
        # dual-arm: bottom row → arm1, top row → arm2; both at view_measure
        row = pad // 16
        step_in_row = pad % 16
        affected_track = state.armed_tracks[row] if row < len(state.armed_tracks) else state.armed_tracks[0]
        step_idx = view_m * 16 + step_in_row
        state = _ensure_loop_length(state, affected_track, loop_idx, step_idx + 1)
        new_state = _toggle_step(state, affected_track, loop_idx, step_idx)

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

    return _drop_fully_empty_tracks(new_state, (affected_track,))


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
        return dataclasses.replace(state, is_playing=False, playhead=0, loop_measure_offsets=())
    return state


def _instrument_softkey(state: AppState, event: SoftkeyPressed) -> AppState:
    if event.key == 0:  # SK1: STEPS — activate jogwheel (single-arm only)
        if len(state.armed_tracks) > 1:
            return state  # disabled in dual-arm
        new_ctrl = "" if state.instrument_active_ctrl == "STEPS" else "STEPS"
        return dataclasses.replace(state, instrument_active_ctrl=new_ctrl)
    if event.key == 1:  # SK2: MEASURES — activate jogwheel for measure count
        new_ctrl = "" if state.instrument_active_ctrl == "MEASURES" else "MEASURES"
        return dataclasses.replace(state, instrument_active_ctrl=new_ctrl)
    if event.key == 2:  # SK3: PADS — placeholder
        return state
    if event.key == 3:  # SK4: BACK — GC empty armed tracks, return to SESSION
        state = _drop_fully_empty_tracks(state, state.armed_tracks, skip_armed=False)
        return dataclasses.replace(state, mode=Mode.SESSION, instrument_active_ctrl="")
    if event.key == 4:  # SK5: CLEAR — shift only
        if state.shift_held:
            return _clear_armed_loops(state)
        return state
    return state


def _max_arm_measures(state: AppState) -> int:
    """Return the highest measure count across all armed loops."""
    m = 1
    for idx in state.armed_tracks:
        track = state.tracks[idx]
        if track is not None:
            m = max(m, track.loops[state.selected_loop].step_count // 16)
    return m


def _adjust_measures(state: AppState, delta: int) -> AppState:
    """Add or remove one measure (16 steps) from all armed DrumTrack loops. delta sign only matters."""
    step = 1 if delta > 0 else -1
    new_state = state
    for track_idx in state.armed_tracks:
        track = new_state.tracks[track_idx]
        if track is None or not isinstance(track, DrumTrack):
            continue
        loop = track.loops[new_state.selected_loop]
        current_measures = loop.step_count // 16
        new_measures = max(1, min(8, current_measures + step))
        if new_measures == current_measures:
            continue
        if new_measures > current_measures:
            added = tuple(False for _ in range((new_measures - current_measures) * 16))
            new_steps = loop.steps + added
        else:
            new_steps = loop.steps[:new_measures * 16]
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
    # Clamp view_measure to new max
    max_m = _max_arm_measures(new_state)
    view = min(new_state.instrument_view_measure, max(0, max_m - 1))
    return dataclasses.replace(new_state, instrument_view_measure=view)


def _instrument_encoder(state: AppState, event: EncoderTurned) -> AppState:
    if event.encoder != 9:
        return state
    if state.instrument_active_ctrl == "MEASURES":
        return _adjust_measures(state, event.delta)
    # "STEPS" active: scaffold only, no resize for M1/M2
    return state


def _instrument_touchbar(state: AppState, event: TouchbarMoved) -> AppState:
    max_m = _max_arm_measures(state)
    view = max(0, min(max_m - 1, int(event.position * max_m)))
    return dataclasses.replace(state, instrument_view_measure=view)


def _drop_fully_empty_tracks(
    state: AppState, track_indices: tuple[int, ...], *, skip_armed: bool = True
) -> AppState:
    """Remove tracks whose every loop is empty: clears the slot, armed/muted/soloed sets, playing loops.
    Returns to SESSION if no armed tracks remain.

    skip_armed=True (default): armed tracks are never GC'd — they persist until the caller
    explicitly sets skip_armed=False (used only at mode-switch-to-SESSION boundaries).
    """
    protected = set(state.armed_tracks) if skip_armed else set()
    tracks = list(state.tracks)
    new_armed = list(state.armed_tracks)
    new_playing = set(state.playing_loops)
    dropped: set[int] = set()
    for idx in track_indices:
        if idx in protected:
            continue
        track = tracks[idx]
        if track is not None and all(loop.is_empty for loop in track.loops):
            tracks[idx] = None
            if idx in new_armed:
                new_armed.remove(idx)
            new_playing = {p for p in new_playing if p[0] != idx}
            dropped.add(idx)
    if not dropped:
        return state
    new_mode = Mode.SESSION if not new_armed else state.mode
    new_offsets = tuple(
        (k, v) for k, v in state.loop_measure_offsets if k[0] not in dropped
    )
    return dataclasses.replace(
        state,
        tracks=tuple(tracks),
        armed_tracks=tuple(new_armed),
        playing_loops=frozenset(new_playing),
        muted_tracks=state.muted_tracks - dropped,
        soloed_tracks=state.soloed_tracks - dropped,
        mode=new_mode,
        loop_measure_offsets=new_offsets,
    )


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
    return _drop_fully_empty_tracks(new_state, state.armed_tracks)
