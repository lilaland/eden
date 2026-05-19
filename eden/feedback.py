"""
feedback.py — Higher-level visual feedback layer for Eden, built on AtomSQ.

Orchestrates pad LED colors, step-sequencer playhead, mode indicators,
and OLED text output.
"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eden.controller import AtomSQ
from eden.theme import (
    PAD_ACTIVE,
    PAD_PLAYHEAD,
    PAD_INACTIVE,
    PAD_SELECTED,
    PAD_OFF,
    ACCENT_GOLD,
)
from controller_map import (
    OLED_MAIN_LINE1,
    OLED_MAIN_LINE2,
    OLED_BTN1_TITLE,
    OLED_BTN2_TITLE,
    OLED_BTN3_TITLE,
    OLED_BTN4_TITLE,
    OLED_BTN5_TITLE,
    OLED_BTN1_VALUE,
    OLED_BTN2_VALUE,
    OLED_BTN3_VALUE,
    OLED_BTN4_VALUE,
    OLED_BTN5_VALUE,
    NATIVE_LED_SONG,
    NATIVE_LED_INST,
    NATIVE_LED_EDIT,
    NATIVE_LED_USER,
)

# OLED slot pairs for soft keys SK1–SK5: (title_slot, value_slot)
_SOFT_KEY_SLOTS: list[tuple[int, int]] = [
    (OLED_BTN1_TITLE, OLED_BTN1_VALUE),
    (OLED_BTN2_TITLE, OLED_BTN2_VALUE),
    (OLED_BTN3_TITLE, OLED_BTN3_VALUE),
    (OLED_BTN4_TITLE, OLED_BTN4_VALUE),
    (OLED_BTN5_TITLE, OLED_BTN5_VALUE),
]

_MODE_LED: dict[str, int] = {
    "song": NATIVE_LED_SONG,
    "inst": NATIVE_LED_INST,
    "edit": NATIVE_LED_EDIT,
    "user": NATIVE_LED_USER,
}

_STEP_STATE_COLORS: dict[str, tuple[int, int, int]] = {
    "active":    PAD_ACTIVE,
    "playhead":  PAD_PLAYHEAD,
    "inactive":  PAD_INACTIVE,
    "selected":  PAD_SELECTED,
    "off":       PAD_OFF,
}

# UNVERIFIED: pad_index → note offset based on FL source chromatic mapping.
_PAD_NOTE_OFFSET = 36


class EdenFeedback:
    def __init__(self, controller: AtomSQ) -> None:
        """Takes a connected AtomSQ instance."""
        self._ctrl = controller
        self._pad_states: dict[int, tuple[int, int, int]] = {}

    def clear_all_pads(self) -> None:
        """Set all 32 pads to PAD_OFF."""
        for i in range(32):
            self._set_pad(i, PAD_OFF)

    def set_pad_step_state(self, pad_index: int, state: str) -> None:
        """
        Paint one pad with a named step state.
        state: "active" | "playhead" | "inactive" | "selected" | "off"
        pad_index: 0–31.
        # UNVERIFIED: pad_index → note offset based on FL source chromatic mapping.
        """
        color = _STEP_STATE_COLORS.get(state, PAD_OFF)
        self._set_pad(pad_index, color)

    def update_sequencer_row(self, steps: list[bool], playhead: int) -> None:
        """
        Paint 16 pads to show a step sequencer pattern.
        steps: list of 16 booleans (True = step active)
        playhead: current step index 0–15 (gets PLAYHEAD color regardless of active state)
        Uses first 16 pads (indices 0–15).
        """
        for i in range(16):
            if i == playhead:
                self._set_pad(i, PAD_PLAYHEAD)
            elif steps[i]:
                self._set_pad(i, PAD_ACTIVE)
            else:
                self._set_pad(i, PAD_INACTIVE)

    def flash_pad(
        self,
        pad_index: int,
        color: tuple[int, int, int],
        duration_ms: int = 80,
    ) -> None:
        """
        Flash a pad color then return to its previous state.
        Fires a background thread to restore the pad after duration_ms.
        """
        previous = self._pad_states.get(pad_index, PAD_OFF)
        self._set_pad(pad_index, color)

        def _restore() -> None:
            time.sleep(duration_ms / 1000.0)
            self._set_pad(pad_index, previous)

        threading.Thread(target=_restore, daemon=True).start()

    def write_status(self, line1: str, line2: str = "") -> None:
        """
        Write to the two main OLED lines.
        line1 → OLED_MAIN_LINE1 (slot 0x06), line2 → OLED_MAIN_LINE2 (slot 0x07).
        Uses white color and center alignment.
        """
        self._ctrl.write_oled(OLED_MAIN_LINE1, line1, 0x7F, 0x7F, 0x7F, 0x00)
        if line2:
            self._ctrl.write_oled(OLED_MAIN_LINE2, line2, 0x7F, 0x7F, 0x7F, 0x00)

    def write_soft_key(self, key_index: int, label: str, value: str = "") -> None:
        """
        Write label and optional value to a screen soft key (0–4 = SK1–SK5).
        label → title slot, value → value slot.
        Color: ACCENT_GOLD for label, white for value.
        # UNVERIFIED: OLED write requires native mode to be active.
        """
        title_slot, value_slot = _SOFT_KEY_SLOTS[key_index]
        gr, gg, gb = ACCENT_GOLD
        self._ctrl.write_oled(title_slot, label, gr, gg, gb, 0x00)
        if value:
            self._ctrl.write_oled(value_slot, value, 0x7F, 0x7F, 0x7F, 0x00)

    def set_mode_indicator(self, mode: str) -> None:
        """
        Light the appropriate mode button LED (SONG/INST/EDIT/USER) and
        write the mode name to OLED main line 1.
        mode: "song" | "inst" | "edit" | "user"
        """
        for m, cc in _MODE_LED.items():
            self._ctrl.set_button_led(cc, m == mode)
        self.write_status(mode.upper())

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _set_pad(self, pad_index: int, color: tuple[int, int, int]) -> None:
        self._pad_states[pad_index] = color
        note = pad_index + _PAD_NOTE_OFFSET
        self._ctrl.set_pad_color(note, *color)
