"""render.py — Pure rendering functions for Eden jambox.

Three functions, zero side effects. Each takes AppState and returns
a plain Python value suitable for the controller layer to consume.
"""

from __future__ import annotations

import eden.catalog as catalog
import eden.sessions as sessions
from eden.scales import (
    degree_to_pitch, pitch_to_degree, pitch_name, SCALE_SHORT, is_root,
    note_in_scale, white_idx_to_midi, black_key_at,
)
from eden.state import (
    AppState, Mode, InstrumentSubmode, Loop, DrumTrack, SynthTrack, SampleTrack, Track,
)
from eden.fx import FX_LABELS, fmt_fx_val
from eden.theme import (
    PAD_ACTIVE, PAD_PLAYHEAD, PAD_INACTIVE, PAD_SELECTED, PAD_OFF,
    ACCENT_GOLD, ACCENT_CORAL, BG_DARK,
    PAD_DRUM, PAD_SYNTH, PAD_SAMPLE, PAD_NEW_SLOT,
    PAD_PINK, PAD_ARMED, NOTE_COLORS,
)
from controller_map import (
    OLED_MAIN_LINE1, OLED_MAIN_LINE2,
    OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
    OLED_BTN4_TITLE, OLED_BTN5_TITLE, OLED_BTN6_TITLE,
    OLED_BTN1_VALUE, OLED_BTN2_VALUE, OLED_BTN3_VALUE,
    OLED_BTN4_VALUE, OLED_BTN5_VALUE, OLED_BTN6_VALUE,
    NATIVE_LED_SONG, NATIVE_LED_INST, NATIVE_LED_PLAY, NATIVE_LED_STOP,
    NATIVE_LED_REC, NATIVE_LED_METRO, NATIVE_LED_EDIT,
)

# OLED bar/label colors (7-bit, matching the MIDI data range)
_OLED_WHITE    = (0x7F, 0x7F, 0x7F)   # value-slot text and main lines
_OLED_ACTIVE   = ACCENT_GOLD           # bar lit = this control is selected
_OLED_DIM      = (0x30, 0x30, 0x30)   # bar off = inactive/unselected button
_OLED_DISABLED = (0x18, 0x18, 0x18)   # bar barely visible = function unavailable
_OLED_MUTED    = ACCENT_CORAL          # bar lit coral = track is muted
_OLED_SOLOED   = (0x70, 0x60, 0x00)   # bar lit amber = track is soloed
_OLED_ARMED    = (0x7F, 0x30, 0x00)   # bar lit orange = slot is armed


# ── Internal helpers ──────────────────────────────────────────────────────────


def _track_color(track: object) -> tuple[int, int, int]:
    """Return the canonical type color for a track."""
    if isinstance(track, DrumTrack):
        return PAD_DRUM
    if isinstance(track, SynthTrack):
        return PAD_SYNTH
    if isinstance(track, SampleTrack):
        return PAD_SAMPLE
    return PAD_INACTIVE


def _brighten(color: tuple[int, int, int], factor: float = 1.3) -> tuple[int, int, int]:
    """Multiply each channel by factor, clamp to 127 (7-bit MIDI ceiling)."""
    return tuple(min(127, int(c * factor)) for c in color)  # type: ignore[return-value]


def _dim(color: tuple[int, int, int], divisor: float = 3.0) -> tuple[int, int, int]:
    """Divide each channel by divisor, rounding down."""
    return tuple(int(c / divisor) for c in color)  # type: ignore[return-value]


def _pulse(color: tuple[int, int, int], playhead: int) -> tuple[int, int, int]:
    """Alternate between full and dim every 2 steps to create a playing-loop pulse."""
    return color if (playhead % 4) < 2 else _dim(color)


# ── Public rendering functions ────────────────────────────────────────────────


def render_pads(state: AppState) -> tuple[tuple[int, int, int], ...]:
    """
    Returns a tuple of 32 RGB colors, one per pad (index 0-31).
    Bottom row = pads 0-15, top row = pads 16-31.
    All channel values 0-127 (7-bit MIDI).
    """
    pads: list[tuple[int, int, int]] = [PAD_INACTIVE] * 32

    if state.mode == Mode.SESSION:
        # ── Bottom row (pads 0-15): 16 instrument track slots ────────────────
        for track_idx in range(16):
            pad_idx = track_idx
            track = state.tracks[track_idx]
            is_selected = track_idx == state.selected_track

            if track is None:
                pads[pad_idx] = PAD_NEW_SLOT if is_selected else PAD_INACTIVE
                continue

            is_armed  = track_idx in state.armed_tracks
            is_soloed = track_idx in state.soloed_tracks
            is_muted  = track_idx in state.muted_tracks

            # Priority: armed > soloed > selected > muted > type color
            if is_armed:
                pads[pad_idx] = PAD_ARMED
            elif is_soloed:
                pads[pad_idx] = (100, 100, 100)
            elif is_selected:
                pads[pad_idx] = PAD_PINK
            elif is_muted:
                pads[pad_idx] = _dim(ACCENT_CORAL)
            else:
                pads[pad_idx] = _dim(_track_color(track))

        # ── Top row (pads 16-31): loop slots of selected track ───────────────
        sel_idx = state.selected_track
        sel_track = state.tracks[sel_idx] if sel_idx is not None else None

        if sel_track is not None:
            track_color = _track_color(sel_track)
            for loop_idx in range(16):
                pad_idx = loop_idx + 16
                loop: Loop = sel_track.loops[loop_idx]
                is_sel_loop = loop_idx == state.selected_loop

                if loop.is_empty:
                    pads[pad_idx] = PAD_NEW_SLOT if is_sel_loop else PAD_INACTIVE
                    continue

                is_loop_playing = (sel_idx, loop_idx) in state.playing_loops

                if is_sel_loop and is_loop_playing:
                    pads[pad_idx] = _pulse(PAD_PINK, state.playhead)
                elif is_sel_loop:
                    pads[pad_idx] = PAD_PINK
                elif is_loop_playing:
                    pads[pad_idx] = _pulse(track_color, state.playhead)
                else:
                    pads[pad_idx] = _dim(track_color)

    elif state.mode == Mode.INSTRUMENT:
        armed = state.armed_tracks
        if not armed:
            pass  # all PAD_INACTIVE

        elif len(armed) == 1:
            track_idx = armed[0]
            track = state.tracks[track_idx]
            if track is not None:
                color = _track_color(track)
                view_m = state.instrument_view_measure

                # ── SynthTrack: dual-row layout ───────────────────────────────
                if isinstance(track, SynthTrack):
                    if not track.quantized:
                        # FREE piano: pitch_window_offset = white key index of leftmost pad
                        woff = state.pitch_window_offset
                        # Bottom row (pads 0-15): white keys
                        for col in range(16):
                            pitch = white_idx_to_midi(woff + col)
                            if pitch < 0 or pitch > 127:
                                pads[col] = PAD_OFF
                                continue
                            root_semi = pitch % 12
                            in_scale = note_in_scale(pitch, track.root_note, track.scale)
                            if root_semi == track.root_note % 12:
                                pads[col] = ACCENT_GOLD
                            elif in_scale:
                                pads[col] = color
                            else:
                                pads[col] = _dim(PAD_INACTIVE)
                        # Top row (pads 16-31): black keys (None = dead pad, no key here)
                        for col in range(16):
                            pitch = black_key_at(woff + col)
                            if pitch is None or pitch < 0 or pitch > 127:
                                pads[col + 16] = PAD_OFF
                            else:
                                root_semi = pitch % 12
                                in_scale = note_in_scale(pitch, track.root_note, track.scale)
                                if root_semi == track.root_note % 12:
                                    pads[col + 16] = _dim(ACCENT_GOLD)
                                elif in_scale:
                                    pads[col + 16] = _dim(color)
                                else:
                                    pads[col + 16] = PAD_INACTIVE
                    elif state.instrument_submode == InstrumentSubmode.PADS:
                        # PADS mode: all 32 pads = scale degrees (keyboard)
                        for pad_idx in range(32):
                            degree = state.pitch_window_offset + pad_idx
                            pitch = degree_to_pitch(track.root_note, track.scale, degree)
                            if is_root(track.root_note, pitch):
                                pads[pad_idx] = _dim(ACCENT_GOLD)
                            else:
                                pads[pad_idx] = _dim(color)
                    else:
                        # STEPS mode: top row = steps, bottom row = pitch window
                        loop = track.loops[state.selected_loop]
                        key = (track_idx, state.selected_loop)
                        playing_measure = dict(state.loop_measure_offsets).get(key, 0)
                        is_playing_loop = key in state.playing_loops
                        spb = loop.steps_per_bar
                        step_in_bar = state.playhead * spb // 32
                        global_firing_step = step_in_bar + playing_measure * spb
                        ph_step = global_firing_step  # absolute playhead step

                        # Top row (pads 16-31): step grid for current page
                        for col in range(16):
                            pad_idx = col + 16
                            step_idx = view_m * 16 + col
                            if step_idx >= loop.step_count:
                                pads[pad_idx] = PAD_OFF
                                continue
                            is_cursor = step_idx == state.step_cursor
                            is_ph = is_playing_loop and ph_step == step_idx
                            step_on = loop.steps[step_idx].on
                            if is_ph:
                                pads[pad_idx] = PAD_PLAYHEAD
                            elif is_cursor and step_on:
                                pads[pad_idx] = _brighten(PAD_PINK)
                            elif is_cursor:
                                pads[pad_idx] = PAD_PINK
                            elif step_on:
                                pads[pad_idx] = color
                            else:
                                pads[pad_idx] = PAD_INACTIVE

                        # Bottom row (pads 0-15): pitch window
                        # Find which degrees match the cursor step's pitches (all chord tones)
                        cursor_step = loop.steps[state.step_cursor] if state.step_cursor < loop.step_count else None
                        cursor_pitches: set[int] = set()
                        if cursor_step and cursor_step.on:
                            cursor_pitches = set(cursor_step.pitches)
                        for pad_idx in range(16):
                            degree = state.pitch_window_offset + pad_idx
                            pitch = degree_to_pitch(track.root_note, track.scale, degree)
                            if pitch in cursor_pitches:
                                pads[pad_idx] = color  # highlight active pitch(es)
                            elif is_root(track.root_note, pitch):
                                pads[pad_idx] = _dim(ACCENT_GOLD)
                            else:
                                pads[pad_idx] = _dim(PAD_INACTIVE)

                else:
                    # ── DrumTrack / drum-style step grid ─────────────────────
                    loop = track.loops[state.selected_loop]
                    key = (track_idx, state.selected_loop)
                    playing_measure = dict(state.loop_measure_offsets).get(key, 0)
                    is_playing_loop = key in state.playing_loops
                    steps_per_bar = loop.steps_per_bar

                    if loop.step_size > 16:
                        page_size = steps_per_bar if steps_per_bar <= 32 else 32
                        page_offset = view_m * page_size
                        if steps_per_bar > 32:
                            step_in_bar = state.playhead
                        else:
                            step_in_bar = state.playhead * steps_per_bar // 32
                        ph_col = step_in_bar // 2
                        ph_row = step_in_bar % 2
                        for row in range(2):
                            for col in range(16):
                                pad_idx = row * 16 + col
                                step = page_offset + col * 2 + row
                                if step >= loop.step_count:
                                    pads[pad_idx] = PAD_OFF
                                    continue
                                is_playhead = (
                                    is_playing_loop
                                    and playing_measure == view_m
                                    and col == ph_col
                                    and row == ph_row
                                )
                                if is_playhead:
                                    pads[pad_idx] = PAD_PLAYHEAD
                                elif loop.steps[step].on:
                                    pads[pad_idx] = color
                                else:
                                    pads[pad_idx] = PAD_INACTIVE
                    else:
                        step_in_bar = state.playhead * steps_per_bar // 32
                        global_firing_step = step_in_bar + playing_measure * steps_per_bar
                        ph_measure = global_firing_step // 16
                        ph_col = global_firing_step % 16
                        for row in range(2):
                            measure = view_m + row
                            for col in range(16):
                                pad_idx = row * 16 + col
                                global_step = measure * 16 + col
                                if global_step >= loop.step_count:
                                    pads[pad_idx] = PAD_OFF
                                    continue
                                is_playhead = (
                                    is_playing_loop
                                    and measure == ph_measure
                                    and col == ph_col
                                )
                                if is_playhead:
                                    pads[pad_idx] = PAD_PLAYHEAD
                                elif loop.steps[global_step].on:
                                    pads[pad_idx] = color
                                else:
                                    pads[pad_idx] = PAD_INACTIVE

        else:  # dual-arm
            offsets = dict(state.loop_measure_offsets)
            view_m = state.instrument_view_measure
            for row, track_idx in enumerate(armed[:2]):
                track = state.tracks[track_idx]
                if track is None:
                    continue
                loop = track.loops[state.selected_loop]
                color = _track_color(track)
                key = (track_idx, state.selected_loop)
                playing_measure = offsets.get(key, 0)
                is_playing_loop = key in state.playing_loops
                for col in range(16):
                    pad_idx = row * 16 + col
                    global_step = view_m * 16 + col
                    if global_step >= loop.step_count:
                        pads[pad_idx] = PAD_OFF
                        continue
                    is_playhead = (
                        is_playing_loop
                        and playing_measure == view_m
                        and col == state.playhead
                    )
                    if is_playhead:
                        pads[pad_idx] = PAD_PLAYHEAD
                    elif loop.steps[global_step].on:
                        pads[pad_idx] = color
                    else:
                        pads[pad_idx] = PAD_INACTIVE

    return tuple(pads)


def _render_fx_edit(state: AppState, _set) -> None:
    """Render the 4×2 FX edit overlay onto the OLED."""
    page = state.fx_edit_page
    labels = FX_LABELS[page]
    if state.mode == Mode.INSTRUMENT and state.armed_tracks:
        track = state.tracks[state.armed_tracks[0]]
        chain = getattr(track, "fx", state.global_fx) if track is not None else state.global_fx
    else:
        chain = state.global_fx
    vals = chain.page1 if page == 0 else chain.page2
    active = state.fx_active_knob
    page_ind = f"{'FX1' if page == 0 else 'FX2'}"

    def _fc(idx: int) -> tuple:
        return _OLED_ACTIVE if idx == active else _OLED_DIM

    _set(OLED_BTN1_TITLE, labels[0], _fc(0))
    _set(OLED_BTN1_VALUE, fmt_fx_val(page, 0, vals[0]))
    _set(OLED_BTN2_TITLE, labels[1], _fc(1))
    _set(OLED_BTN2_VALUE, fmt_fx_val(page, 1, vals[1]))
    _set(OLED_BTN3_TITLE, labels[2], _fc(2))
    _set(OLED_BTN3_VALUE, fmt_fx_val(page, 2, vals[2]))
    _set(OLED_MAIN_LINE1, f"{labels[3]}  {fmt_fx_val(page, 3, vals[3])}", _fc(3))
    _set(OLED_BTN4_TITLE, labels[4], _fc(4))
    _set(OLED_BTN4_VALUE, fmt_fx_val(page, 4, vals[4]))
    _set(OLED_BTN5_TITLE, labels[5], _fc(5))
    _set(OLED_BTN5_VALUE, fmt_fx_val(page, 5, vals[5]))
    _set(OLED_BTN6_TITLE, labels[6], _fc(6))
    _set(OLED_BTN6_VALUE, fmt_fx_val(page, 6, vals[6]))
    _set(OLED_MAIN_LINE2, f"{labels[7]}  {fmt_fx_val(page, 7, vals[7])}", _fc(7))


def render_oled(state: AppState) -> dict[int, tuple[str, int, int, int]]:
    """
    Returns a dict of {slot_id: (text, r, g, b)} for every OLED slot to update.
    Only slots with non-empty text are included.
    Slot IDs are from controller_map.py. Colors drive the hardware bar indicator.

    UNVERIFIED: The OLED write_oled interface in controller.py enforces 7-bit ASCII.
    Unicode characters (e.g. the infinity symbol '∞') may not render correctly on
    hardware. We use the ASCII string "inf" as a safe stand-in.
    """
    out: dict[int, tuple[str, int, int, int]] = {}

    def _set(slot: int, text: str, color: tuple[int, int, int] = _OLED_WHITE) -> None:
        if text:
            out[slot] = (text, *color)

    if state.edit_mode:
        _render_fx_edit(state, _set)
        return out

    # Metronome held — BPM display overrides all other content.
    if state.metronome_held:
        bpm = state.tempo_bpm
        bpm_str = f"{bpm:.1f}" if bpm != int(bpm) else f"{int(bpm)}"
        _set(OLED_MAIN_LINE1, "TEMPO")
        _set(OLED_MAIN_LINE2, f"{bpm_str} BPM")
        _set(OLED_BTN3_TITLE, "JOG", _OLED_DIM)
        _set(OLED_BTN3_VALUE, "BPM")
        tap_count = len(state.tap_times)
        if tap_count >= 1:
            _set(OLED_BTN4_TITLE, "TAP", _OLED_ACTIVE)
            _set(OLED_BTN4_VALUE, f"{tap_count} tap{'s' if tap_count != 1 else ''}")
        else:
            _set(OLED_BTN4_TITLE, "SHIFT+TAP", _OLED_DIM)
        return out

    if state.mode == Mode.SESSION:
        # ── New-instrument picker (empty slot selected) ───────────────────────
        if state.tracks[state.selected_track] is None:
            types = catalog.INSTRUMENT_TYPES
            type_name = types[state.new_slot_type_idx] if state.new_slot_type_idx < len(types) else "?"
            cats = catalog.get_categories(state.new_slot_type_idx)
            cat_name = cats[state.new_slot_cat_idx] if cats else "-"
            vars_ = catalog.get_variations(state.new_slot_type_idx, state.new_slot_cat_idx)
            var_name = vars_[state.new_slot_var_idx] if vars_ else "-"
            trk_name, _ = catalog.get_track_params(
                state.new_slot_type_idx, state.new_slot_cat_idx, state.new_slot_var_idx
            )
            ctrl = state.new_slot_active_ctrl
            is_keys = state.new_slot_type_idx == 1
            type_color = _OLED_ACTIVE if ctrl == "TYPE" else _OLED_DIM
            cat_color  = _OLED_ACTIVE if ctrl == "CAT"  else _OLED_DIM
            var_color  = _OLED_ACTIVE if ctrl == "VAR"  else _OLED_DIM
            _set(OLED_MAIN_LINE1, f"T{state.selected_track + 1}: {trk_name}")
            _set(OLED_MAIN_LINE2, f"{cat_name} / {var_name}")
            _set(OLED_BTN1_TITLE, "TYPE", type_color)
            _set(OLED_BTN1_VALUE, type_name)
            if is_keys:
                _set(OLED_BTN2_TITLE, "FOLDER", cat_color)
                _set(OLED_BTN2_VALUE, cat_name)
                _set(OLED_BTN3_TITLE, "PRESET", var_color)
                _set(OLED_BTN3_VALUE, var_name)
            else:
                _set(OLED_BTN2_TITLE, "CATEG", cat_color)
                _set(OLED_BTN2_VALUE, cat_name)
                _set(OLED_BTN3_TITLE, "STYLE", var_color)
                _set(OLED_BTN3_VALUE, var_name)
            _set(OLED_BTN4_TITLE, "BACK", _OLED_DIM)
            _set(OLED_BTN5_TITLE, "CREATE", _OLED_DIM)
            return out

        sel_track = state.tracks[state.selected_track]
        track_name = sel_track.name if sel_track is not None else "EMPTY"

        loop_count = 0
        if sel_track is not None:
            loop = sel_track.loops[state.selected_loop]
            loop_count = loop.loop_count
        loop_count_str = "inf" if loop_count == 0 else f"{loop_count}x"

        slot_letter = sessions.slot_letter(state.active_session_slot)
        _set(OLED_MAIN_LINE1, f"[{slot_letter}] {track_name}")

        if state.finishing_loops:
            seen: list[str] = []
            for track_idx, _ in sorted(state.finishing_loops):
                if track_idx < len(state.finishing_tracks):
                    ft = state.finishing_tracks[track_idx]
                    nm = ft.name if ft is not None else f"T{track_idx + 1}"
                    if nm not in seen:
                        seen.append(nm)
            _set(OLED_MAIN_LINE2, "+".join(seen[:3]) + " out")
        elif state.armed_tracks:
            names = []
            for idx in state.armed_tracks[:2]:
                t = state.tracks[idx]
                names.append(t.name if t is not None else f"T{idx + 1}")
            _set(OLED_MAIN_LINE2, "ARM: " + "+".join(names))
        else:
            _set(OLED_MAIN_LINE2, f"LOOP {loop_count_str}")

        # SK1: MUTE — bar lit coral when track is muted
        is_muted = state.selected_track in state.muted_tracks
        _set(OLED_BTN1_TITLE, "UNMUTE" if is_muted else "MUTE",
             _OLED_MUTED if is_muted else _OLED_DIM)

        # SK2: SOLO — bar lit amber when track is soloed
        is_soloed = state.selected_track in state.soloed_tracks
        _set(OLED_BTN2_TITLE, "UNSOLO" if is_soloed else "SOLO",
             _OLED_SOLOED if is_soloed else _OLED_DIM)

        # SK3: VOL (normal) | LOOPxN (shift)
        if state.shift_held:
            _set(OLED_BTN3_TITLE, f"LOOPx{loop_count_str}", _OLED_DIM)
        else:
            vol_active = state.session_active_ctrl == "VOL"
            vol_color = _OLED_ACTIVE if vol_active else _OLED_DIM
            _set(OLED_BTN3_TITLE, "VOL", vol_color)
            if vol_active and sel_track is not None:
                if state.session_selected_row == 1:
                    lv = sel_track.loops[state.selected_loop].volume
                    _set(OLED_BTN3_VALUE, f"L{state.selected_loop + 1} {lv:.0%}")
                else:
                    tv = getattr(sel_track, "volume", 1.0)
                    _set(OLED_BTN3_VALUE, f"Trk {tv:.0%}")

        # SK4: ARM1 — bar lit orange when armed, dim when not; "REC ALL" when shift held
        if state.armed_tracks:
            t0 = state.armed_tracks[0]
            t0_track = state.tracks[t0]
            t0_name = t0_track.name if t0_track is not None else f"T{t0 + 1}"
            _set(OLED_BTN4_TITLE, t0_name, _OLED_ARMED)
            _set(OLED_BTN4_VALUE, f"S{t0 + 1} L{state.selected_loop + 1}")
        elif state.shift_held:
            _set(OLED_BTN4_TITLE, "REC ALL", _OLED_DIM)
        else:
            _set(OLED_BTN4_TITLE, "ARM1", _OLED_DIM)

        # SK5: ARM2 — bar lit orange when armed, dim when not
        if state.arm_pads_offer_loop is not None:
            _set(OLED_BTN5_TITLE, "ARM PADS", _OLED_DIM)
        elif len(state.armed_tracks) >= 2:
            t1 = state.armed_tracks[1]
            t1_track = state.tracks[t1]
            t1_name = t1_track.name if t1_track is not None else f"T{t1 + 1}"
            _set(OLED_BTN5_TITLE, t1_name, _OLED_ARMED)
            _set(OLED_BTN5_VALUE, f"S{t1 + 1} L{state.selected_loop + 1}")
        else:
            _set(OLED_BTN5_TITLE, "ARM2", _OLED_DIM)

    elif state.mode == Mode.INSTRUMENT:
        armed = state.armed_tracks

        if len(armed) == 0:
            main_line1 = "EMPTY"
        elif len(armed) == 1:
            t = state.tracks[armed[0]]
            if isinstance(t, SynthTrack):
                scale_short = SCALE_SHORT.get(t.scale, t.scale[:5].upper())
                page = state.instrument_oled_page
                dots = ["○", "○", "○", "○"]
                dots[min(page, 3)] = "●"
                page_ind = "".join(dots)
                rec_prefix = "● " if state.free_recording else ""
                main_line1 = f"{rec_prefix}{t.name} {scale_short}/{pitch_name(t.root_note)} {page_ind}"
            else:
                main_line1 = t.name if t is not None else "EMPTY"
        else:
            t0 = state.tracks[armed[0]]
            t1 = state.tracks[armed[1]]
            n0 = t0.name if t0 is not None else "EMPTY"
            n1 = t1.name if t1 is not None else "EMPTY"
            main_line1 = f"{n0}+{n1}"

        # Get first armed loop's params for VALUE display and view-mode detection
        first_bars, first_numer, first_size = 1, 4, 16
        is_interleaved = False
        if armed:
            tr0 = state.tracks[armed[0]]
            if tr0 is not None:
                lp = tr0.loops[state.selected_loop]
                first_bars, first_numer, first_size = lp.bars, lp.numerator, lp.step_size
                is_interleaved = lp.step_size > 16

        # Max pages: bar-based for interleaved view, 16-step pages for normal view
        max_pages = 1
        if armed:
            for idx in armed:
                tr = state.tracks[idx]
                if tr is not None:
                    lp = tr.loops[state.selected_loop]
                    if lp.step_size > 16:
                        if lp.steps_per_bar > 32:
                            max_pages = max(max_pages, max(1, (lp.step_count + 31) // 32))
                        else:
                            max_pages = max(max_pages, lp.bars)
                    else:
                        max_pages = max(max_pages, max(1, (lp.step_count + 15) // 16))

        view_m = state.instrument_view_measure
        first_spb = first_numer * (first_size // 4)
        page_label = "P" if (is_interleaved and first_spb > 32) else ("B" if is_interleaved else "P")

        # OLED line2: FREE synth/drum → recording status; QUANT synth/drum → page progress
        first_track_for_line2 = state.tracks[armed[0]] if armed else None
        is_free_mode = (
            (isinstance(first_track_for_line2, SynthTrack)
             and not is_interleaved
             and not first_track_for_line2.quantized)
            or (isinstance(first_track_for_line2, DrumTrack)
                and state.instrument_submode in (InstrumentSubmode.PADS, InstrumentSubmode.DRUM_FREE))
        )
        if is_free_mode:
            loop_num = state.selected_loop + 1
            # BBT position display (bar.beat.sub)
            if armed and state.tracks[armed[0]] is not None:
                _lp = state.tracks[armed[0]].loops[state.selected_loop]
                _spb = _lp.steps_per_bar
                _offsets = dict(state.loop_measure_offsets)
                _bar_off = _offsets.get((armed[0], state.selected_loop), 0)
                _step_in_bar = state.playhead * _spb // 32
                _spbeat = max(1, _spb // _lp.numerator)
                _bar = _bar_off + 1
                _beat = _step_in_bar // _spbeat + 1
                _sub = _step_in_bar % _spbeat + 1
                pos = f"{_bar}.{_beat}.{_sub}"
            else:
                pos = "1.1.1"
            if state.free_recording:
                main_line2 = f"● {pos} L{loop_num}"
            elif state.free_record_pending:
                main_line2 = f"ARM {pos} L{loop_num}"
            else:
                main_line2 = f"    {pos} L{loop_num}"
        else:
            # QUANT step mode and drums: show which page/measure you're on
            main_line2 = f"{page_label}{view_m + 1}/{max_pages} L{state.selected_loop + 1}"

        ctrl = state.instrument_active_ctrl
        _set(OLED_MAIN_LINE1, main_line1)
        _set(OLED_MAIN_LINE2, main_line2)

        # SK controls depend on primary armed track type
        first_track = state.tracks[armed[0]] if armed else None
        if isinstance(first_track, SynthTrack):
            shift = state.shift_held
            scale_short = SCALE_SHORT.get(first_track.scale, first_track.scale[:5].upper())
            root_color_val = NOTE_COLORS.get(first_track.root_note % 12, _OLED_DIM)
            page = state.instrument_oled_page
            if page == 0:
                if shift:
                    # Page 0 shift: OSC / CUTOFF / ATTACK / SUSTAIN / RELEASE
                    osc_color    = _OLED_ACTIVE if ctrl == "OSC"     else _OLED_DIM
                    cutoff_color = _OLED_ACTIVE if ctrl == "CUTOFF"  else _OLED_DIM
                    attack_color = _OLED_ACTIVE if ctrl == "ATTACK"  else _OLED_DIM
                    sust_color   = _OLED_ACTIVE if ctrl == "SUSTAIN" else _OLED_DIM
                    rel_color    = _OLED_ACTIVE if ctrl == "RELEASE" else _OLED_DIM
                    cutoff_hz = first_track.filter_cutoff
                    cutoff_str = f"{int(cutoff_hz)}Hz" if cutoff_hz < 1000 else f"{cutoff_hz/1000:.1f}k"
                    atk = first_track.amp_attack
                    atk_str = f"{round(atk*1000)}ms" if atk < 1.0 else f"{atk:.1f}s"
                    rel = first_track.amp_release
                    rel_str = f"{round(rel*1000)}ms" if rel < 1.0 else f"{rel:.1f}s"
                    _set(OLED_BTN1_TITLE, "OSC", osc_color)
                    _set(OLED_BTN1_VALUE, first_track.osc_type.upper()[:4])
                    _set(OLED_BTN2_TITLE, "CUTOFF", cutoff_color)
                    _set(OLED_BTN2_VALUE, cutoff_str)
                    _set(OLED_BTN3_TITLE, "ATTACK", attack_color)
                    _set(OLED_BTN3_VALUE, atk_str)
                    _set(OLED_BTN4_TITLE, "SUSTAIN", sust_color)
                    _set(OLED_BTN4_VALUE, f"{first_track.amp_sustain:.0%}")
                    _set(OLED_BTN5_TITLE, "RELEASE", rel_color)
                    _set(OLED_BTN5_VALUE, rel_str)
                else:
                    # Page 0 normal: SCALE / ROOT / LEN / AFTRCH(or QUANT) / OCTAVE
                    scale_color  = _OLED_ACTIVE if ctrl == "SCALE"  else _OLED_DIM
                    root_color   = _OLED_ACTIVE if ctrl == "ROOT"   else root_color_val
                    len_color    = _OLED_ACTIVE if ctrl == "BARS"   else _OLED_DIM
                    octave_color = _OLED_ACTIVE if ctrl == "OCTAVE" else _OLED_DIM
                    _set(OLED_BTN1_TITLE, "SCALE", scale_color)
                    _set(OLED_BTN1_VALUE, scale_short)
                    _set(OLED_BTN2_TITLE, "ROOT", root_color)
                    _set(OLED_BTN2_VALUE, pitch_name(first_track.root_note))
                    _set(OLED_BTN3_TITLE, "LEN", len_color)
                    _set(OLED_BTN3_VALUE, f"{first_bars}bar" + ("s" if first_bars != 1 else ""))
                    aftrch_color = _OLED_ACTIVE if first_track.aftertouch else _OLED_DIM
                    if shift:
                        _set(OLED_BTN4_TITLE, "AFTRCH", aftrch_color)
                        _set(OLED_BTN4_VALUE, "ON" if first_track.aftertouch else "OFF")
                    elif not first_track.quantized:
                        _set(OLED_BTN4_TITLE, "QUANT", _OLED_DIM)
                    else:
                        _set(OLED_BTN4_TITLE, "FREE", _OLED_DIM)
                    oct_val = state.octave_offset
                    oct_str = f"+{oct_val}" if oct_val >= 0 else str(oct_val)
                    _set(OLED_BTN5_TITLE, "OCTAVE", octave_color)
                    _set(OLED_BTN5_VALUE, oct_str)
            elif page == 1:
                # Page 1: ARP — settings live on the selected loop
                sel_loop = first_track.loops[state.selected_loop]
                arp_on_color   = _OLED_ACTIVE if sel_loop.arp_on   else _OLED_DIM
                mode_color     = _OLED_ACTIVE if ctrl == "ARP_MODE" else _OLED_DIM
                rate_color     = _OLED_ACTIVE if ctrl == "ARP_RATE" else _OLED_DIM
                oct_color      = _OLED_ACTIVE if ctrl == "ARP_OCT"  else _OLED_DIM
                _set(OLED_BTN1_TITLE, "ARP", arp_on_color)
                _set(OLED_BTN1_VALUE, "ON" if sel_loop.arp_on else "OFF")
                _set(OLED_BTN2_TITLE, "MODE", mode_color)
                _set(OLED_BTN2_VALUE, sel_loop.arp_mode.upper()[:5])
                _set(OLED_BTN3_TITLE, "CLEAR", _OLED_DIM)
                _set(OLED_BTN4_TITLE, "RATE", rate_color)
                _set(OLED_BTN4_VALUE, f"1/{sel_loop.arp_rate}")
                _set(OLED_BTN5_TITLE, "OCTAVES", oct_color)
                _set(OLED_BTN5_VALUE, str(sel_loop.arp_octaves))
            elif page == 2:
                # Page 2: CHORD — settings live on the selected loop
                sel_loop = first_track.loops[state.selected_loop]
                chord_on_color = _OLED_ACTIVE if sel_loop.chord_on  else _OLED_DIM
                ctype_color    = _OLED_ACTIVE if ctrl == "CHORD_TYPE" else _OLED_DIM
                voices_color   = _OLED_ACTIVE if ctrl == "VOICES"     else _OLED_DIM
                _set(OLED_BTN1_TITLE, "CHORD", chord_on_color)
                _set(OLED_BTN1_VALUE, "ON" if sel_loop.chord_on else "OFF")
                _set(OLED_BTN2_TITLE, "TYPE", ctype_color)
                _set(OLED_BTN2_VALUE, sel_loop.chord_type.upper()[:5])
                _set(OLED_BTN3_TITLE, "VOICES", voices_color)
                _set(OLED_BTN3_VALUE, str(first_track.max_voices))
                vel_color = _OLED_ACTIVE if state.vel_sensitive else _OLED_DIM
                _set(OLED_BTN5_TITLE, "VEL" if state.vel_sensitive else "MONO", vel_color)
            elif page == 3:
                # Page 3: QUANTIZE
                grid_color = _OLED_ACTIVE if ctrl == "Q_GRID" else _OLED_DIM
                str_color  = _OLED_ACTIVE if ctrl == "Q_STR"  else _OLED_DIM
                _set(OLED_BTN1_TITLE, "GRID", grid_color)
                _set(OLED_BTN1_VALUE, f"1/{state.quantize_grid}")
                _set(OLED_BTN2_TITLE, "", _OLED_DIM)
                _set(OLED_BTN3_TITLE, "AMOUNT", str_color)
                _set(OLED_BTN3_VALUE, f"{int(state.quantize_strength * 100)}%")
                _set(OLED_BTN4_TITLE, "", _OLED_DIM)
                _set(OLED_BTN5_TITLE, "QUANT", _OLED_DIM)
            elif page == 4:
                keep = getattr(first_track, 'keep_empty', False)
                keep_color = _OLED_ACTIVE if keep else _OLED_DIM
                _set(OLED_BTN1_TITLE, "KEEP", keep_color)
                _set(OLED_BTN1_VALUE, "YES" if keep else "NO")
                _set(OLED_BTN5_TITLE, "DELETE", _OLED_DISABLED)
        elif state.instrument_submode in (InstrumentSubmode.PADS, InstrumentSubmode.DRUM_FREE):
            # Drum free recording submode: QUANT / Q.GRID / Q.AMT / BACK / VEL
            grid_color = _OLED_ACTIVE if ctrl == "Q_GRID" else _OLED_DIM
            str_color  = _OLED_ACTIVE if ctrl == "Q_STR"  else _OLED_DIM
            vel_color  = _OLED_ACTIVE if state.vel_sensitive else _OLED_DIM
            _set(OLED_BTN1_TITLE, "QUANT", _OLED_DIM)
            _set(OLED_BTN2_TITLE, "Q.GRID", grid_color)
            _set(OLED_BTN2_VALUE, f"1/{state.quantize_grid}")
            _set(OLED_BTN3_TITLE, "Q.AMT", str_color)
            _set(OLED_BTN3_VALUE, f"{int(state.quantize_strength * 100)}%")
            _set(OLED_BTN4_TITLE, "< BACK", _OLED_DIM)
            _set(OLED_BTN5_TITLE, "VEL" if state.vel_sensitive else "MONO", vel_color)
        else:
            if state.instrument_oled_page == 0:
                bars_color  = _OLED_ACTIVE if ctrl == "BARS"  else _OLED_DIM
                numer_color = _OLED_ACTIVE if ctrl == "NUMER" else _OLED_DIM
                size_color  = _OLED_ACTIVE if ctrl == "SIZE"  else _OLED_DIM
                _set(OLED_BTN1_TITLE, "BARS", bars_color)
                _set(OLED_BTN1_VALUE, str(first_bars))
                _set(OLED_BTN2_TITLE, "NUMER", numer_color)
                _set(OLED_BTN2_VALUE, str(first_numer))
                _set(OLED_BTN3_TITLE, "SIZE", size_color)
                _set(OLED_BTN3_VALUE, f"1/{first_size}")
                _set(OLED_BTN4_TITLE, "< BACK", _OLED_DIM)
                if state.shift_held:
                    _set(OLED_BTN5_TITLE, "CLEAR", _OLED_DIM)
                    _set(OLED_BTN5_VALUE, "SHIFT+")
                else:
                    _set(OLED_BTN5_TITLE, "FREE", _OLED_DIM)
            elif state.instrument_oled_page == 1:
                keep = getattr(first_track, 'keep_empty', False)
                keep_color = _OLED_ACTIVE if keep else _OLED_DIM
                _set(OLED_BTN1_TITLE, "KEEP", keep_color)
                _set(OLED_BTN1_VALUE, "YES" if keep else "NO")
                _set(OLED_BTN5_TITLE, "DELETE", _OLED_DISABLED)

    return out


def render_button_leds(state: AppState) -> dict[int, bool]:
    """
    Returns {cc: on} for button LEDs that should be set.
    Uses native-mode CC constants from controller_map.py.

    UNVERIFIED: LED CC values are from [JB] source, not hardware-verified.
    """
    return {
        NATIVE_LED_PLAY: state.is_playing,
        NATIVE_LED_STOP: not state.is_playing,
        NATIVE_LED_INST: state.mode == Mode.INSTRUMENT,
        NATIVE_LED_SONG: state.mode == Mode.SESSION,
        NATIVE_LED_EDIT: state.edit_mode,
    }
