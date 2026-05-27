"""render.py — Pure rendering functions for Eden jambox.

Three functions, zero side effects. Each takes AppState and returns
a plain Python value suitable for the controller layer to consume.
"""

from __future__ import annotations

from eden.state import (
    AppState, Mode, InstrumentSubmode, Loop, DrumTrack, SynthTrack, SampleTrack, Track,
)
from eden.theme import (
    PAD_ACTIVE, PAD_PLAYHEAD, PAD_INACTIVE, PAD_SELECTED, PAD_OFF,
    ACCENT_GOLD, ACCENT_CORAL, BG_DARK,
    PAD_DRUM, PAD_SYNTH, PAD_SAMPLE, PAD_NEW_SLOT,
    PAD_PINK, PAD_ARMED,
)
from controller_map import (
    OLED_MAIN_LINE1, OLED_MAIN_LINE2,
    OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
    OLED_BTN4_TITLE, OLED_BTN5_TITLE,
    OLED_BTN1_VALUE, OLED_BTN2_VALUE, OLED_BTN3_VALUE,
    OLED_BTN4_VALUE, OLED_BTN5_VALUE,
    NATIVE_LED_SONG, NATIVE_LED_INST, NATIVE_LED_PLAY, NATIVE_LED_STOP,
    NATIVE_LED_REC, NATIVE_LED_METRO,
)


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
                loop = track.loops[state.selected_loop]
                color = _track_color(track)
                view_m = state.instrument_view_measure
                # Check if this loop is playing and get its current measure
                key = (track_idx, state.selected_loop)
                playing_measure = dict(state.loop_measure_offsets).get(key, 0)
                is_playing_loop = key in state.playing_loops

                for row in range(2):
                    measure = view_m + row
                    for col in range(16):
                        pad_idx = row * 16 + col
                        global_step = measure * 16 + col
                        if global_step >= loop.step_count:
                            pads[pad_idx] = PAD_INACTIVE
                            continue
                        is_playhead = (
                            is_playing_loop
                            and playing_measure == measure
                            and col == state.playhead
                        )
                        if is_playhead:
                            pads[pad_idx] = PAD_PLAYHEAD
                        elif loop.steps[global_step]:
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
                        pads[pad_idx] = PAD_INACTIVE
                        continue
                    is_playhead = (
                        is_playing_loop
                        and playing_measure == view_m
                        and col == state.playhead
                    )
                    if is_playhead:
                        pads[pad_idx] = PAD_PLAYHEAD
                    elif loop.steps[global_step]:
                        pads[pad_idx] = color
                    else:
                        pads[pad_idx] = PAD_INACTIVE

    return tuple(pads)


def render_oled(state: AppState) -> dict[int, str]:
    """
    Returns a dict of {slot_id: text} for every OLED slot that should be updated.
    Only slots with non-empty content are included.
    Slot IDs are from controller_map.py.

    UNVERIFIED: The OLED write_oled interface in controller.py enforces 7-bit ASCII.
    Unicode characters (e.g. the infinity symbol '∞') may not render correctly on
    hardware. We use the ASCII string "inf" as a safe stand-in.
    """
    out: dict[int, str] = {}

    def _set(slot: int, text: str) -> None:
        if text:
            out[slot] = text

    if state.mode == Mode.SESSION:
        sel_track = state.tracks[state.selected_track]
        track_name = sel_track.name if sel_track is not None else "EMPTY"

        # Determine loop_count from selected track's selected loop
        loop_count = 0
        if sel_track is not None:
            loop = sel_track.loops[state.selected_loop]
            loop_count = loop.loop_count

        loop_count_str = "inf" if loop_count == 0 else f"{loop_count}x"

        _set(OLED_MAIN_LINE1, track_name)

        if state.armed_tracks:
            names = []
            for idx in state.armed_tracks[:2]:
                t = state.tracks[idx]
                names.append(t.name if t is not None else f"T{idx + 1}")
            _set(OLED_MAIN_LINE2, "ARM: " + "+".join(names))
        else:
            _set(OLED_MAIN_LINE2, f"LOOP {loop_count_str}")

        _set(OLED_BTN1_TITLE, "UNMUTE" if state.selected_track in state.muted_tracks else "MUTE")
        _set(OLED_BTN2_TITLE, "UNSOLO" if state.selected_track in state.soloed_tracks else "SOLO")
        _set(OLED_BTN3_TITLE, f"LOOP x{loop_count_str}")

        # SK4: ARM1 — name + slot/loop when armed, else label
        if state.armed_tracks:
            t0 = state.armed_tracks[0]
            t0_track = state.tracks[t0]
            t0_name = t0_track.name if t0_track is not None else f"T{t0 + 1}"
            _set(OLED_BTN4_TITLE, t0_name)
            _set(OLED_BTN4_VALUE, f"S{t0 + 1} L{state.selected_loop + 1}")
        else:
            _set(OLED_BTN4_TITLE, "ARM1")

        # SK5: ARM2 — name + slot/loop when armed, ARM PADS offer, or label
        if state.arm_pads_offer_loop is not None:
            _set(OLED_BTN5_TITLE, "ARM PADS")
        elif len(state.armed_tracks) >= 2:
            t1 = state.armed_tracks[1]
            t1_track = state.tracks[t1]
            t1_name = t1_track.name if t1_track is not None else f"T{t1 + 1}"
            _set(OLED_BTN5_TITLE, t1_name)
            _set(OLED_BTN5_VALUE, f"S{t1 + 1} L{state.selected_loop + 1}")
        else:
            _set(OLED_BTN5_TITLE, "ARM2")

    elif state.mode == Mode.INSTRUMENT:
        armed = state.armed_tracks

        if len(armed) == 0:
            main_line1 = "EMPTY"
        elif len(armed) == 1:
            t = state.tracks[armed[0]]
            main_line1 = t.name if t is not None else "EMPTY"
        else:
            t0 = state.tracks[armed[0]]
            t1 = state.tracks[armed[1]]
            n0 = t0.name if t0 is not None else "EMPTY"
            n1 = t1.name if t1 is not None else "EMPTY"
            main_line1 = f"{n0}+{n1}"

        # Current view position and total measures
        max_measures = 1
        if armed:
            for idx in armed:
                tr = state.tracks[idx]
                if tr is not None:
                    max_measures = max(max_measures, tr.loops[state.selected_loop].step_count // 16)
        view_m = state.instrument_view_measure
        main_line2 = f"M{view_m + 1}/{max_measures} L{state.selected_loop + 1}"

        # SK1: STEPS
        steps_label = "STEPS*" if state.instrument_active_ctrl == "STEPS" else "STEPS"
        # SK2: MEASURES
        meas_label = "MEAS*" if state.instrument_active_ctrl == "MEASURES" else f"MEAS {max_measures}"

        _set(OLED_MAIN_LINE1, main_line1)
        _set(OLED_MAIN_LINE2, main_line2)
        _set(OLED_BTN1_TITLE, steps_label)
        _set(OLED_BTN2_TITLE, meas_label)
        _set(OLED_BTN3_TITLE, "PADS")
        _set(OLED_BTN4_TITLE, "< BACK")
        _set(OLED_BTN5_TITLE, "CLEAR")

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
    }
