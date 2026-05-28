"""reduce.py — Pure reducer for Eden AppState transitions."""

from __future__ import annotations

import dataclasses
from typing import Callable

import eden.catalog as catalog
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
    ArrowPressed,
    ClockTicked,
    EncoderTurned,
    Event,
    MetronomePressed,
    ModeButtonPressed,
    PadPressed,
    PadReleased,
    SessionLoaded,
    ShiftChanged,
    SoftkeyPressed,
    SongSlotPressed,
    TapTempoPressed,
    TouchbarMoved,
    TransportPressed,
)




# ── Top-level dispatch ────────────────────────────────────────────────────────


def reduce(state: AppState, event: Event) -> AppState:
    if isinstance(event, ShiftChanged):
        return dataclasses.replace(state, shift_held=event.held)
    if isinstance(event, ClockTicked):
        return _on_clock_ticked(state)
    if isinstance(event, ModeButtonPressed):
        return _on_mode_button(state, event)
    if isinstance(event, MetronomePressed):
        return _on_metronome(state, event)
    if isinstance(event, TapTempoPressed):
        return _on_tap_tempo(state, event)
    if isinstance(event, SessionLoaded):
        return _on_session_loaded(state, event)
    if isinstance(event, SongSlotPressed):
        return state  # handled entirely by app layer (requires file I/O)
    # Metronome+jog intercepts encoder before mode dispatch.
    if isinstance(event, EncoderTurned) and state.metronome_held and event.encoder == 9:
        new_bpm = max(20.0, min(300.0, state.tempo_bpm + event.delta))
        return dataclasses.replace(state, tempo_bpm=float(new_bpm))
    if state.mode == Mode.SESSION:
        return _reduce_session(state, event)
    if state.mode == Mode.INSTRUMENT:
        return _reduce_instrument(state, event)
    return state


# ── Global handlers ───────────────────────────────────────────────────────────


def _on_clock_ticked(state: AppState) -> AppState:
    if not state.is_playing:
        return state
    new_playhead = (state.playhead + 1) % 32
    state = dataclasses.replace(state, playhead=new_playhead)
    if new_playhead == 0:
        state = _handle_loop_wrap(state)
    return state


def _handle_loop_wrap(state: AppState) -> AppState:
    """Advance offsets on each 16-step wrap; decrement plays_remaining only on full loop completion.

    For interleaved loops (step_size > 16), offsets track bar index — one bar per 16-tick cycle.
    For normal loops, offsets track 16-step page index.
    """
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

        if loop.step_size > 16:
            if loop.steps_per_bar > 32:
                cycle_count = max(1, (loop.step_count + 31) // 32)
            else:
                cycle_count = loop.bars
        else:
            cycle_count = loop.bars

        if cycle_count > 1:
            current = offsets.get(key, 0)
            nxt = (current + 1) % cycle_count
            offsets[key] = nxt
            if nxt != 0:
                continue  # mid-loop, don't count a play yet

        # 1-cycle loop OR just completed all cycles → count one play
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

    # Advance finishing loops (old session, playing out in background).
    fin_remaining = dict(state.finishing_plays_remaining)
    fin_offsets = dict(state.finishing_loop_measure_offsets)
    fin_to_stop: set[tuple[int, int]] = set()

    for key in state.finishing_loops:
        track_idx, loop_idx = key
        if not state.finishing_tracks or track_idx >= len(state.finishing_tracks):
            fin_to_stop.add(key)
            continue
        track = state.finishing_tracks[track_idx]
        if track is None:
            fin_to_stop.add(key)
            continue
        loop = track.loops[loop_idx]

        if loop.step_size > 16:
            cycle_count = max(1, (loop.step_count + 31) // 32) if loop.steps_per_bar > 32 else loop.bars
        else:
            cycle_count = loop.bars

        if cycle_count > 1:
            current = fin_offsets.get(key, 0)
            nxt = (current + 1) % cycle_count
            fin_offsets[key] = nxt
            if nxt != 0:
                continue  # mid-loop, not done yet

        if key not in fin_remaining:
            fin_to_stop.add(key)
            continue
        count = fin_remaining[key] - 1
        if count <= 0:
            fin_to_stop.add(key)
            del fin_remaining[key]
            fin_offsets.pop(key, None)
        else:
            fin_remaining[key] = count

    new_fin_loops = state.finishing_loops - fin_to_stop
    return dataclasses.replace(
        state,
        playing_loops=state.playing_loops - loops_to_stop,
        plays_remaining=tuple(remaining.items()),
        loop_measure_offsets=tuple(offsets.items()),
        finishing_loops=new_fin_loops,
        finishing_tracks=state.finishing_tracks if new_fin_loops else (),
        finishing_plays_remaining=tuple(fin_remaining.items()),
        finishing_loop_measure_offsets=tuple(fin_offsets.items()),
    )


_TAP_MAX_TAPS = 8
_TAP_TIMEOUT = 2.0  # seconds — gap larger than this resets tap history


def _on_session_loaded(state: AppState, event: SessionLoaded) -> AppState:
    """Apply a newly loaded session, optionally preserving old loops as finishing."""
    base = dict(
        tracks=event.tracks,
        tempo_bpm=event.tempo_bpm,
        swing=event.swing,
        active_loops=event.active_loops,
        playing_loops=event.active_loops,
        muted_tracks=event.muted_tracks,
        soloed_tracks=event.soloed_tracks,
        active_session_slot=event.slot,
        plays_remaining=(),
        loop_measure_offsets=(),
        armed_tracks=(),
        instrument_view_measure=0,
        instrument_active_ctrl="",
        new_slot_active_ctrl="",
        saved_armed_tracks=None,
    )
    if event.immediate or not state.playing_loops:
        return dataclasses.replace(
            state,
            **base,
            finishing_loops=frozenset(),
            finishing_tracks=(),
            finishing_plays_remaining=(),
            finishing_loop_measure_offsets=(),
        )
    # Graceful: keep old loops finishing in background.
    old_remaining = dict(state.plays_remaining)
    for key in state.playing_loops:
        if key not in old_remaining:  # infinite loop — give one more cycle
            old_remaining[key] = 1
    return dataclasses.replace(
        state,
        **base,
        finishing_loops=state.playing_loops,
        finishing_tracks=state.tracks,
        finishing_plays_remaining=tuple(old_remaining.items()),
        finishing_loop_measure_offsets=state.loop_measure_offsets,
    )


def _on_metronome(state: AppState, event: MetronomePressed) -> AppState:
    if not event.pressed:
        return dataclasses.replace(state, metronome_held=False)
    return dataclasses.replace(state, metronome_held=True)


def _on_tap_tempo(state: AppState, event: TapTempoPressed) -> AppState:
    times = state.tap_times
    if times and (event.timestamp - times[-1]) > _TAP_TIMEOUT:
        times = ()
    times = (times + (event.timestamp,))[-_TAP_MAX_TAPS:]
    new_state = dataclasses.replace(state, tap_times=times, playhead=0)
    if len(times) >= 2:
        intervals = [times[i] - times[i - 1] for i in range(1, len(times))]
        avg = sum(intervals) / len(intervals)
        new_bpm = max(20.0, min(300.0, 60.0 / avg))
        return dataclasses.replace(new_state, tempo_bpm=float(new_bpm))
    return new_state


def _on_mode_button(state: AppState, event: ModeButtonPressed) -> AppState:
    if not event.pressed:
        return state
    if event.button == "INST":
        if state.tracks[state.selected_track] is None:
            # Empty slot — create track from picker and enter INSTRUMENT,
            # saving current arm state to restore when returning to SESSION.
            state = _create_new_slot_track(state)
            return dataclasses.replace(
                state,
                armed_tracks=(state.selected_track,),
                saved_armed_tracks=state.armed_tracks,
                mode=Mode.INSTRUMENT,
                instrument_submode=InstrumentSubmode.STEPS,
            )
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
        armed = state.saved_armed_tracks if state.saved_armed_tracks is not None else state.armed_tracks
        return dataclasses.replace(state, mode=Mode.SESSION, armed_tracks=armed, saved_armed_tracks=None)
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
        # Bottom row: select track; auto-select loop 0.
        # Empty slots show the new-instrument picker — track is created only on SK5 CREATE.
        if pad != state.selected_track:
            state = _drop_fully_empty_tracks(state, (state.selected_track,))
        track = state.tracks[pad]
        if track is None:
            # Select empty slot and reset the new-instrument picker indices.
            return dataclasses.replace(
                state,
                selected_track=pad,
                selected_loop=0,
                arm_pads_offer_loop=None,
                new_slot_type_idx=0,
                new_slot_cat_idx=0,
                new_slot_var_idx=0,
                new_slot_active_ctrl="",
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
    if event.button == "REC" and state.shift_held:
        # Shift+REC: set active_loops = currently playing loops (session startup config).
        return dataclasses.replace(state, active_loops=state.playing_loops)
    return state


def _session_softkey(state: AppState, event: SoftkeyPressed) -> AppState:
    t = state.selected_track
    # New-instrument picker: empty slot selected → repurpose SK1-SK5.
    if state.tracks[t] is None:
        return _new_slot_softkey(state, event)
    # ARM PADS offer: SK5 accepts
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


def _new_slot_softkey(state: AppState, event: SoftkeyPressed) -> AppState:
    """Handle softkeys while the new-instrument picker is open."""
    if event.key == 0:  # SK1: activate/deactivate TYPE ctrl
        new_ctrl = "" if state.new_slot_active_ctrl == "TYPE" else "TYPE"
        return dataclasses.replace(state, new_slot_active_ctrl=new_ctrl)
    if event.key == 1:  # SK2: activate/deactivate CAT ctrl
        new_ctrl = "" if state.new_slot_active_ctrl == "CAT" else "CAT"
        return dataclasses.replace(state, new_slot_active_ctrl=new_ctrl)
    if event.key == 2:  # SK3: activate/deactivate VAR ctrl
        new_ctrl = "" if state.new_slot_active_ctrl == "VAR" else "VAR"
        return dataclasses.replace(state, new_slot_active_ctrl=new_ctrl)
    if event.key == 3:  # SK4: BACK — deactivate any active ctrl
        return dataclasses.replace(state, new_slot_active_ctrl="")
    if event.key == 4:  # SK5: CREATE — instantiate the track
        return _create_new_slot_track(state)
    return state


def _create_new_slot_track(state: AppState) -> AppState:
    """Create a DrumTrack at the selected empty slot using the current picker values."""
    pad = state.selected_track
    name, sample = catalog.get_track_params(
        state.new_slot_type_idx, state.new_slot_cat_idx, state.new_slot_var_idx
    )
    new_track = DrumTrack(name=name, sample_name=sample, loops=default_track_loops())
    new_tracks = state.tracks[:pad] + (new_track,) + state.tracks[pad + 1:]
    return dataclasses.replace(
        state,
        tracks=new_tracks,
        new_slot_active_ctrl="",
    )


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
        # New-instrument picker active: jog changes the selected control.
        if state.tracks[state.selected_track] is None and state.new_slot_active_ctrl:
            return _new_slot_encoder(state, event)
        new_bpm = max(60.0, min(200.0, state.tempo_bpm + event.delta))
        return dataclasses.replace(state, tempo_bpm=float(new_bpm))
    return state


def _new_slot_encoder(state: AppState, event: EncoderTurned) -> AppState:
    """Jog the active new-slot picker control."""
    delta = 1 if event.delta > 0 else -1
    ctrl = state.new_slot_active_ctrl
    if ctrl == "TYPE":
        types = catalog.INSTRUMENT_TYPES
        new_idx = (state.new_slot_type_idx + delta) % len(types)
        # Reset downstream indices when type changes.
        return dataclasses.replace(
            state,
            new_slot_type_idx=new_idx,
            new_slot_cat_idx=0,
            new_slot_var_idx=0,
        )
    if ctrl == "CAT":
        cats = catalog.get_categories(state.new_slot_type_idx)
        if cats:
            new_idx = (state.new_slot_cat_idx + delta) % len(cats)
            return dataclasses.replace(
                state,
                new_slot_cat_idx=new_idx,
                new_slot_var_idx=0,
            )
    if ctrl == "VAR":
        vars_ = catalog.get_variations(state.new_slot_type_idx, state.new_slot_cat_idx)
        if vars_:
            new_idx = (state.new_slot_var_idx + delta) % len(vars_)
            return dataclasses.replace(state, new_slot_var_idx=new_idx)
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
    if isinstance(event, ArrowPressed):
        return _instrument_arrow(state, event)
    return state


_STEP_SIZES: tuple[int, ...] = (4, 8, 16, 32)


def _resize_loop_to(loop: Loop, bars: int, numer: int, size: int) -> Loop:
    """Resize a loop to bars*numer*(size//4) steps.

    When step_size changes, existing steps are remapped to the new resolution:
    old step i → new step i * (new_spu / old_spu), where spu = steps-per-beat.
    This preserves musical position (e.g. 16→32 spreads each step to its even slot,
    leaving odd slots empty for new subdivisions; 32→16 quantizes to nearest).
    When only bars/numer change, steps are extended or truncated unchanged.
    """
    new_count = bars * numer * (size // 4)
    if size != loop.step_size:
        old_spu = loop.step_size // 4
        new_spu = size // 4
        new_steps: list[bool] = [False] * new_count
        for i, active in enumerate(loop.steps):
            if active:
                new_i = i * new_spu // old_spu
                if 0 <= new_i < new_count:
                    new_steps[new_i] = True
        return dataclasses.replace(loop, steps=tuple(new_steps), bars=bars, numerator=numer, step_size=size)
    current = loop.steps
    if new_count > len(current):
        new_steps_t = current + (False,) * (new_count - len(current))
    else:
        new_steps_t = current[:new_count]
    return dataclasses.replace(loop, steps=new_steps_t, bars=bars, numerator=numer, step_size=size)


def _apply_to_armed_loops(
    state: AppState, transform: Callable[[Loop], Loop]
) -> AppState:
    """Apply transform to selected_loop of every armed DrumTrack. Returns new state."""
    new_state = state
    loop_idx = state.selected_loop
    for track_idx in state.armed_tracks:
        track = new_state.tracks[track_idx]
        if track is None or not isinstance(track, DrumTrack):
            continue
        loop = track.loops[loop_idx]
        new_loop = transform(loop)
        if new_loop is loop:
            continue
        new_loops = track.loops[:loop_idx] + (new_loop,) + track.loops[loop_idx + 1:]
        new_track = dataclasses.replace(track, loops=new_loops)
        new_tracks = (
            new_state.tracks[:track_idx]
            + (new_track,)
            + new_state.tracks[track_idx + 1:]
        )
        new_state = dataclasses.replace(new_state, tracks=new_tracks)
    return new_state


def _max_view_pages(state: AppState) -> int:
    """Max display pages across all armed loops.
    Interleaved view (step_size > 16): one page per bar.
    Normal view: one page per 16 steps (ceiling division).
    """
    m = 1
    for idx in state.armed_tracks:
        track = state.tracks[idx]
        if track is not None:
            lp = track.loops[state.selected_loop]
            if lp.step_size > 16:
                if lp.steps_per_bar > 32:
                    m = max(m, max(1, (lp.step_count + 31) // 32))
                else:
                    m = max(m, lp.bars)
            else:
                m = max(m, max(1, (lp.step_count + 15) // 16))
    return m


def _clamp_all_armed_playback(state: AppState) -> AppState:
    """Clamp playback offsets for all armed loops after a potential shrink."""
    for track_idx in state.armed_tracks:
        track = state.tracks[track_idx]
        if track is None:
            continue
        loop_idx = state.selected_loop
        loop = track.loops[loop_idx]
        state = _clamp_playback_after_shrink(state, track_idx, loop_idx, loop.step_count)
    return state


def _adjust_bars(state: AppState, delta: int) -> AppState:
    """Add or remove one bar from all armed loops."""
    step = 1 if delta > 0 else -1

    def transform(loop: Loop) -> Loop:
        new_bars = max(1, min(8, loop.bars + step))
        if new_bars == loop.bars:
            return loop
        return _resize_loop_to(loop, new_bars, loop.numerator, loop.step_size)

    new_state = _apply_to_armed_loops(state, transform)
    new_state = _clamp_all_armed_playback(new_state)
    max_pages = _max_view_pages(new_state)
    view = min(new_state.instrument_view_measure, max(0, max_pages - 1))
    return dataclasses.replace(new_state, instrument_view_measure=view)


def _adjust_numer(state: AppState, delta: int) -> AppState:
    """Change numerator (beats per bar) on all armed loops."""
    step = 1 if delta > 0 else -1

    def transform(loop: Loop) -> Loop:
        new_numer = max(1, min(16, loop.numerator + step))
        if new_numer == loop.numerator:
            return loop
        return _resize_loop_to(loop, loop.bars, new_numer, loop.step_size)

    new_state = _apply_to_armed_loops(state, transform)
    new_state = _clamp_all_armed_playback(new_state)
    max_pages = _max_view_pages(new_state)
    view = min(new_state.instrument_view_measure, max(0, max_pages - 1))
    return dataclasses.replace(new_state, instrument_view_measure=view)


def _adjust_size(state: AppState, delta: int) -> AppState:
    """Change step_size on all armed loops."""
    def transform(loop: Loop) -> Loop:
        try:
            idx = _STEP_SIZES.index(loop.step_size)
        except ValueError:
            idx = 2  # default to 16
        new_idx = max(0, min(len(_STEP_SIZES) - 1, idx + (1 if delta > 0 else -1)))
        new_size = _STEP_SIZES[new_idx]
        if new_size == loop.step_size:
            return loop
        return _resize_loop_to(loop, loop.bars, loop.numerator, new_size)

    new_state = _apply_to_armed_loops(state, transform)
    new_state = _clamp_all_armed_playback(new_state)
    max_pages = _max_view_pages(new_state)
    view = min(new_state.instrument_view_measure, max(0, max_pages - 1))
    return dataclasses.replace(new_state, instrument_view_measure=view)


def _ensure_loop_length(state: AppState, track_idx: int, loop_idx: int, min_steps: int) -> AppState:
    """Extend a DrumTrack loop to at least min_steps, growing bars as needed."""
    track = state.tracks[track_idx]
    if track is None or not isinstance(track, DrumTrack):
        return state
    loop = track.loops[loop_idx]
    if loop.step_count >= min_steps:
        return state
    steps_per_bar = loop.numerator * (loop.step_size // 4)
    if steps_per_bar == 0:
        return state
    new_bars = max(loop.bars, (min_steps + steps_per_bar - 1) // steps_per_bar)
    new_bars = min(new_bars, 8)
    if new_bars == loop.bars:
        return state
    new_loop = _resize_loop_to(loop, new_bars, loop.numerator, loop.step_size)
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
        track = state.tracks[affected_track]
        loop = track.loops[loop_idx] if track is not None else None
        if loop is not None and loop.step_size > 16:
            # Interleaved: row 0 = even steps, row 1 = odd steps within page
            col = pad % 16
            row = pad // 16
            page_size = 32 if loop.steps_per_bar > 32 else loop.steps_per_bar
            step_idx = view_m * page_size + col * 2 + row
        else:
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
        offsets = dict(new_state.loop_measure_offsets)
        for track_idx in new_state.armed_tracks:
            key = (track_idx, loop_idx)
            if key in new_playing and key not in offsets:
                offsets[key] = 0
        new_state = dataclasses.replace(
            new_state,
            playing_loops=frozenset(new_playing),
            loop_measure_offsets=tuple(offsets.items()),
        )

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
    if event.button == "REC" and state.shift_held:
        return dataclasses.replace(state, active_loops=state.playing_loops)
    return state


def _instrument_softkey(state: AppState, event: SoftkeyPressed) -> AppState:
    if event.key == 0:  # SK1: BARS — toggle active ctrl
        new_ctrl = "" if state.instrument_active_ctrl == "BARS" else "BARS"
        return dataclasses.replace(state, instrument_active_ctrl=new_ctrl)
    if event.key == 1:  # SK2: NUMER — toggle active ctrl
        new_ctrl = "" if state.instrument_active_ctrl == "NUMER" else "NUMER"
        return dataclasses.replace(state, instrument_active_ctrl=new_ctrl)
    if event.key == 2:  # SK3: SIZE — toggle active ctrl
        new_ctrl = "" if state.instrument_active_ctrl == "SIZE" else "SIZE"
        return dataclasses.replace(state, instrument_active_ctrl=new_ctrl)
    if event.key == 3:  # SK4: BACK — GC empty armed tracks, return to SESSION
        state = _drop_fully_empty_tracks(state, state.armed_tracks, skip_armed=False)
        armed = state.saved_armed_tracks if state.saved_armed_tracks is not None else state.armed_tracks
        return dataclasses.replace(state, mode=Mode.SESSION, instrument_active_ctrl="",
                                   armed_tracks=armed, saved_armed_tracks=None)
    if event.key == 4:  # SK5: CLEAR — shift only
        if state.shift_held:
            return _clear_armed_loops(state)
        return state
    return state


def _clamp_playback_after_shrink(
    state: AppState, track_idx: int, loop_idx: int, new_step_count: int
) -> AppState:
    """If a playing loop's current offset is past the new end, reset to 0."""
    key = (track_idx, loop_idx)
    if key not in state.playing_loops:
        return state
    offsets = dict(state.loop_measure_offsets)
    current = offsets.get(key, 0)
    track = state.tracks[track_idx]
    loop = track.loops[loop_idx] if track is not None else None
    if loop is not None and loop.step_size > 16:
        if loop.steps_per_bar > 32:
            new_max = max(0, (new_step_count + 31) // 32 - 1)
        else:
            new_max = max(0, loop.bars - 1)
    else:
        new_max = max(0, loop.bars - 1) if loop is not None else 0
    if current > new_max:
        offsets[key] = 0
        return dataclasses.replace(state, loop_measure_offsets=tuple(offsets.items()))
    return state


def _instrument_encoder(state: AppState, event: EncoderTurned) -> AppState:
    if event.encoder != 9:
        return state
    if state.instrument_active_ctrl == "BARS":
        return _adjust_bars(state, event.delta)
    if state.instrument_active_ctrl == "NUMER":
        return _adjust_numer(state, event.delta)
    if state.instrument_active_ctrl == "SIZE":
        return _adjust_size(state, event.delta)
    return state


def _instrument_touchbar(state: AppState, event: TouchbarMoved) -> AppState:
    max_m = _max_view_pages(state)
    view = max(0, min(max_m - 1, int(event.position * max_m)))
    return dataclasses.replace(state, instrument_view_measure=view)


def _instrument_arrow(state: AppState, event: ArrowPressed) -> AppState:
    if not event.pressed:
        return state
    max_pages = _max_view_pages(state)
    delta = 1 if event.direction == "RIGHT" else -1
    view = max(0, min(max_pages - 1, state.instrument_view_measure + delta))
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
        blank_steps = tuple(False for _ in range(loop.step_count))
        new_loop = dataclasses.replace(loop, steps=blank_steps)
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
