"""
eden/app.py — Eden v0 main application.

Wires AtomSQ + SequencerClock + SamplePlayer together.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from eden.controller import AtomSQ
    from eden.audio import SamplePlayer
    from eden.clock import SequencerClock
    from eden.theme import PAD_ACTIVE, PAD_PLAYHEAD, PAD_INACTIVE, PAD_SELECTED, PAD_OFF
except ImportError:
    from controller import AtomSQ
    from audio import SamplePlayer
    from clock import SequencerClock
    from theme import PAD_ACTIVE, PAD_PLAYHEAD, PAD_INACTIVE, PAD_SELECTED, PAD_OFF

try:
    from controller_map import OLED_MAIN_LINE1, OLED_MAIN_LINE2
except ImportError:
    OLED_MAIN_LINE1, OLED_MAIN_LINE2 = 0x06, 0x07

# controller_map.py documents indices 0–15 as the bottom row (player-side pads).
# The sequencer lives on the bottom row.
# UNVERIFIED: physical row assignment — confirm with hardware sniff.
_BOTTOM_ROW_START = 0  # pad index of first bottom-row pad

# LED note addressing: FL source uses linear 36–67 (pad 0 → note 36).
# This matches feedback.py's _PAD_NOTE_OFFSET = 36.
# UNVERIFIED: whether native-mode LED addressing uses this same 36–67 range.
_LED_NOTE_OFFSET = 36


def _step_to_pad_index(step: int) -> int:
    """Map a sequencer step (0–15) to a physical pad index (0–15)."""
    return _BOTTOM_ROW_START + step


class EdenApp:
    """
    Eden v0 — wires AtomSQ + SequencerClock + SamplePlayer together.

    v0 goals:
    1. Enter native mode
    2. Light pads in RGB colors
    3. Write to OLED
    4. Play drum samples on pad press
    5. 16-step sequencer with playhead on pads
    """

    def __init__(
        self,
        sample_dir: str = "samples",
        bpm: float = 120.0,
    ) -> None:
        """Wire up controller, clock, and audio. Do not start clock here."""
        self._controller = AtomSQ()
        self._audio = SamplePlayer(sample_dir=sample_dir)
        self._clock = SequencerClock(bpm=bpm, steps=16, ppq=4)

        self._steps: list[bool] = [False] * 16
        self._playhead: int = 0
        self._track_sample: str = "kick"
        self._bpm: float = bpm

        self._clock.on_tick(self._on_clock_tick)
        self._controller.on_pad_press(self._on_pad_press)

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Enter native mode, paint pads, start clock and MIDI listener.

        Combined OLED + pad LED protocol confirmed 2026-05-18:
        All output (pad RGB, OLED SysEx, init) goes to ATM SQ Control port.
        Pad input arrives on the main ATM SQ port as usual.
        Instrument menu pad mode = "blocks" recommended for consistent input.
        """
        self._controller.enter_native_mode()
        self._repaint_pads()
        self._write_oled_status()
        self._clock.start()
        self._controller.start_listening()

    def stop(self) -> None:
        """Stop clock, audio, and MIDI listener. Clear pad LEDs."""
        self._clock.stop()
        self._controller.stop_listening()
        self._audio.stop_all()
        self._audio.close()
        self._controller.close()

    def set_bpm(self, bpm: float) -> None:
        """Update BPM while running."""
        self._bpm = float(bpm)
        self._clock.set_bpm(bpm)
        self._controller.write_oled(OLED_MAIN_LINE2, f"BPM {bpm:.0f}", align=0x00)

    def toggle_step(self, track: int, step: int) -> None:
        """Toggle a step on/off in the step grid."""
        # v0: single track, ignore track argument
        if 0 <= step < 16:
            self._steps[step] = not self._steps[step]

    def run_interactive(self) -> None:
        """
        Block until KeyboardInterrupt, then call stop().
        Prints a brief startup message.
        """
        print(f"Eden v0 — {self._bpm:.0f} BPM  |  Ctrl-C to quit")
        self.start()
        try:
            import time
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            print("\n  Stopping Eden...")
            self.stop()

    def _write_oled_status(self) -> None:
        self._controller.write_oled(OLED_MAIN_LINE1, "EDEN")
        self._controller.write_oled(OLED_MAIN_LINE2, f"BPM {self._bpm:.0f}")

    # ─── Clock tick handler ───────────────────────────────────────────────────

    def _on_clock_tick(self, step: int) -> None:
        self._playhead = step

        if self._steps[step]:
            self._audio.trigger(self._track_sample, 1.0)

        self._repaint_pads()
        self._print_status()

    def _print_status(self) -> None:
        chars = []
        for i, active in enumerate(self._steps):
            if i == self._playhead:
                chars.append("♦" if active else "▶")
            else:
                chars.append("█" if active else "·")
        steps_str = " ".join(chars)
        print(f"\r  Eden  {self._bpm:.0f} BPM  [{steps_str}]  ", end="", flush=True)

    # ─── Pad press handler ────────────────────────────────────────────────────

    def _on_pad_press(self, pad_index: int, velocity: int) -> None:
        # Only respond to the bottom row (indices 0–15)
        if pad_index < _BOTTOM_ROW_START or pad_index >= _BOTTOM_ROW_START + 16:
            return

        step = pad_index - _BOTTOM_ROW_START
        self._steps[step] = not self._steps[step]

        # Flash pad immediately; repaint on next clock tick will restore state.
        # UNVERIFIED: set_pad_color note addressing — pad_index vs note value.
        # PAD_NOTES[pad_index] gives the MIDI note for this physical pad.
        self._set_pad_by_index(pad_index, PAD_SELECTED)

        self._audio.trigger(self._track_sample, velocity / 127.0)

    # ─── Rendering helpers ────────────────────────────────────────────────────

    def _repaint_pads(self) -> None:
        """Set all 16 bottom-row pads to reflect the current step/playhead state."""
        for step in range(16):
            pad_index = _step_to_pad_index(step)
            if step == self._playhead:
                color = PAD_PLAYHEAD
            elif self._steps[step]:
                color = PAD_ACTIVE
            else:
                color = PAD_INACTIVE
            self._set_pad_by_index(pad_index, color)

    def _set_pad_by_index(self, pad_index: int, color: tuple[int, int, int]) -> None:
        """
        Set a pad color given its physical index (0–31).

        UNVERIFIED: uses linear chromatic LED addressing (pad 0 → note 36)
        per FL source. Consistent with feedback.py _PAD_NOTE_OFFSET=36.
        See PROTOCOL.md §4.
        """
        note = pad_index + _LED_NOTE_OFFSET
        r, g, b = color
        # UNVERIFIED: set_pad_color channel/note protocol — see PROTOCOL.md §4.
        self._controller.set_pad_color(note, r, g, b)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Eden v0 jambox")
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--samples", default="samples")
    args = parser.parse_args()

    app = EdenApp(sample_dir=args.samples, bpm=args.bpm)
    app.run_interactive()
