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
        # Track i → pad i  (matches v0 step-editor row; user-confirmed layout)
        for track_idx in range(16):
            pad_idx = track_idx
            track = state.tracks[track_idx]

            if track is None:
                pads[pad_idx] = PAD_NEW_SLOT if is_selected else PAD_INACTIVE
                continue

            is_soloed   = track_idx in state.soloed_tracks
            is_armed    = track_idx in state.armed_tracks
            is_muted    = track_idx in state.muted_tracks
            is_selected = track_idx == state.selected_track

            # Priority: soloed > armed > muted > selected+type > type
            if is_soloed:
                pads[pad_idx] = (100, 100, 100)
            elif is_armed:
                pads[pad_idx] = ACCENT_GOLD
            elif is_muted:
                pads[pad_idx] = _dim(ACCENT_CORAL)
            else:
                color = _track_color(track)
                if is_selected:
                    color = _brighten(color)
                pads[pad_idx] = color

        # ── Top row (pads 16-31): loop slots of selected track ───────────────
        # Loop j → pad j+16
        sel_idx = state.selected_track
        sel_track = state.tracks[sel_idx] if sel_idx is not None else None

        if sel_track is None:
            # top row stays PAD_INACTIVE
            pass
        else:
            track_color = _track_color(sel_track)
            for loop_idx in range(16):
                pad_idx = loop_idx + 16
                loop: Loop = sel_track.loops[loop_idx]

                if loop.is_empty:
                    pads[pad_idx] = PAD_NEW_SLOT if loop_idx == state.selected_loop else PAD_INACTIVE
                    continue

                is_playing = (sel_idx, loop_idx) in state.playing_loops
                if is_playing:
                    color: tuple[int, int, int] = PAD_PLAYHEAD
                else:
                    color = track_color

                if loop_idx == state.selected_loop:
                    color = _brighten(color)

                pads[pad_idx] = color

    elif state.mode == Mode.INSTRUMENT:
        armed = state.armed_tracks

        if len(armed) == 0:
            # No-arm fallback: all PAD_INACTIVE (already default)
            pass

        elif len(armed) == 1:
            # Single-arm: 32-step pattern across both rows
            track_idx = armed[0]
            track = state.tracks[track_idx]
            if track is not None:
                loop: Loop = track.loops[state.selected_loop]
                color = _track_color(track)
                step_count = loop.step_count  # 16 or 32
                for pad_idx in range(32):
                    # bottom row = steps 0-15, top row = steps 16-31
                    step_idx = pad_idx
                    if step_idx >= step_count:
                        pads[pad_idx] = PAD_INACTIVE
                        continue
                    if step_idx == state.playhead:
                        pads[pad_idx] = PAD_PLAYHEAD
                    elif loop.steps[step_idx]:
                        pads[pad_idx] = color
                    else:
                        pads[pad_idx] = PAD_INACTIVE

        elif len(armed) >= 2:
            # Dual-arm: bottom row = armed_tracks[0] (steps 0-15),
            #            top row  = armed_tracks[1] (steps 0-15)
            for row, track_idx in enumerate(armed[:2]):
                track = state.tracks[track_idx]
                if track is None:
                    continue
                loop = track.loops[state.selected_loop]
                color = _track_color(track)
                # Clamp step count to 16 for dual-arm rows
                step_count = min(loop.step_count, 16)
                for step_idx in range(16):
                    # row 0 → pads 0-15 (bottom), row 1 → pads 16-31 (top)
                    pad_idx = step_idx + (row * 16)
                    if step_idx >= step_count:
                        pads[pad_idx] = PAD_INACTIVE
                        continue
                    if step_idx == state.playhead:
                        pads[pad_idx] = PAD_PLAYHEAD
                    elif loop.steps[step_idx]:
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
        _set(OLED_MAIN_LINE2, f"LOOP {loop_count_str}")
        _set(OLED_BTN1_TITLE, "MUTE")
        _set(OLED_BTN2_TITLE, "SOLO")
        _set(OLED_BTN3_TITLE, f"LOOP x{loop_count_str}")

        # SK4: ARM1 — shows armed track name + loop, or "ARM1" if not armed
        if state.armed_tracks:
            t0 = state.armed_tracks[0]
            t0_track = state.tracks[t0]
            t0_name = t0_track.name[:4] if t0_track is not None else f"T{t0}"
            _set(OLED_BTN4_TITLE, f"{t0_name}:{state.selected_loop}")
        else:
            _set(OLED_BTN4_TITLE, "ARM1")

        # SK5: ARM2 — shows arm2 track info, ARM PADS offer, or "ARM2"
        if state.arm_pads_offer_loop is not None:
            _set(OLED_BTN5_TITLE, "ARM PADS")
        elif len(state.armed_tracks) >= 2:
            t1 = state.armed_tracks[1]
            t1_track = state.tracks[t1]
            t1_name = t1_track.name[:4] if t1_track is not None else f"T{t1}"
            _set(OLED_BTN5_TITLE, f"{t1_name}:{state.selected_loop}")
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

        # loop_count from first armed track's selected loop
        loop_count = 0
        if armed:
            track = state.tracks[armed[0]]
            if track is not None:
                loop = track.loops[state.selected_loop]
                loop_count = loop.loop_count

        loop_count_str = "inf" if loop_count == 0 else f"{loop_count}x"
        main_line2 = f"LOOP {state.selected_loop + 1} [{loop_count_str}]"

        # SK2: EXTEND/SHRINK based on current loop's step count
        step_count = 16
        if state.armed_tracks:
            t0 = state.tracks[state.armed_tracks[0]]
            if t0 is not None:
                step_count = t0.loops[state.selected_loop].step_count
        sk2_label = "SHRINK" if step_count == 32 else "EXTEND"

        _set(OLED_MAIN_LINE1, main_line1)
        _set(OLED_MAIN_LINE2, main_line2)
        _set(OLED_BTN1_TITLE, "STEPS")
        _set(OLED_BTN2_TITLE, sk2_label)
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
