"""
eden/app.py — Eden M1/M2 main application.

Architecture
------------
main thread:
  event_queue.get(timeout=0.01) → reduce(state, event) → state_ref.set(new_state)
  → render+diff+send to controller

clock thread (daemon):
  SequencerClock → pushes ClockTicked() to event_queue

MIDI input thread (daemon):
  AtomSQ listener → pushes Pad/Encoder/Transport/Mode/Shift/Softkey events
  to event_queue

audio thread (sounddevice daemon):
  SamplePlayer callback → reads trigger_queue (deque), mixes, outputs

StepScheduler:
  Called by main thread AFTER processing ClockTicked.
  Reads state_ref.get() → calls player.trigger() for active steps.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import queue
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eden.controller import AtomSQ
from eden.audio import SamplePlayer, StateRef, StepScheduler
from eden.clock import SequencerClock
from eden.reduce import reduce
from eden.render import render_pads, render_oled, render_button_leds
from eden.state import default_state, AppState
from eden.events import ClockTicked, SoftkeyPressed, TouchbarMoved
from eden.theme import ACCENT_GOLD

try:
    from controller_map import (
        OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
        OLED_BTN4_TITLE, OLED_BTN5_TITLE, OLED_BTN6_TITLE,
    )
except ImportError:
    # Fallback slot IDs from PROTOCOL.md §5
    OLED_BTN1_TITLE = 0x00; OLED_BTN2_TITLE = 0x01; OLED_BTN3_TITLE = 0x02
    OLED_BTN4_TITLE = 0x08; OLED_BTN5_TITLE = 0x09; OLED_BTN6_TITLE = 0x0A

# UNVERIFIED: pad LED addressing — pad_index → note offset confirmed in v0 probe.py
# UNVERIFIED: ATM SQ Control port requirement — all LED/OLED output must go to Control port
_PAD_NOTE_OFFSET = 36

_OLED_SOFTKEY_TITLE_SLOTS = {
    OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
    OLED_BTN4_TITLE, OLED_BTN5_TITLE, OLED_BTN6_TITLE,
}


class EdenApp:
    def __init__(self, sample_dir: str = "samples", bpm: float = 120.0) -> None:
        self._eq: queue.Queue = queue.Queue()
        self._state = default_state()
        self._state = dataclasses.replace(self._state, tempo_bpm=bpm)
        self._state_ref = StateRef(self._state)

        self._controller = AtomSQ(event_queue=self._eq)
        self._audio = SamplePlayer(sample_dir=sample_dir)
        self._clock = SequencerClock(bpm=bpm, steps=16, ppq=4, event_queue=self._eq)
        self._scheduler = StepScheduler(player=self._audio, state_ref=self._state_ref)

        # Render delta state: compare against previous render to send only diffs.
        self._last_pad_colors: tuple[tuple[int, int, int], ...] = tuple(
            (0, 0, 0) for _ in range(32)
        )
        self._last_oled: dict[int, str] = {}
        self._last_leds: dict[int, bool] = {}

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._controller.enter_native_mode()
        self._clock.start()
        self._controller.start_listening()
        self._flush_render()  # paint initial state

    def stop(self) -> None:
        self._clock.stop()
        self._controller.stop_listening()
        self._audio.stop_all()
        self._audio.close()
        self._controller.close()

    def run(self) -> None:
        print(f"Eden M1/M2 — {self._state.tempo_bpm:.0f} BPM  |  Ctrl-C to quit")
        self.start()
        try:
            self._event_loop()
        except KeyboardInterrupt:
            pass
        finally:
            print("\n  Stopping Eden...")
            self.stop()

    # ─── Event loop ───────────────────────────────────────────────────────────

    def _event_loop(self) -> None:
        while True:
            try:
                event = self._eq.get(timeout=0.01)
            except queue.Empty:
                continue

            new_state = reduce(self._state, event)

            if isinstance(event, SoftkeyPressed):
                print(f"[EVENT] SoftkeyPressed key={event.key}  armed={new_state.armed_tracks}  mode={new_state.mode.name}")

            if new_state is not self._state:
                self._state = new_state
                self._state_ref.set(new_state)
                self._flush_render()

            # Schedule audio AFTER state swap so scheduler sees updated playhead.
            if isinstance(event, ClockTicked):
                self._scheduler.on_tick()

    # ─── Render / diff / send ─────────────────────────────────────────────────

    def _flush_render(self) -> None:
        """Compute render outputs and send only the deltas to the controller."""
        self._send_pad_diffs()
        self._send_oled_diffs()
        self._send_led_diffs()

    def _send_pad_diffs(self) -> None:
        new_colors = render_pads(self._state)
        for i, (color, last) in enumerate(zip(new_colors, self._last_pad_colors)):
            if color != last:
                note = i + _PAD_NOTE_OFFSET
                self._controller.set_pad_color(note, *color)
        self._last_pad_colors = new_colors

    def _send_oled_diffs(self) -> None:
        new_oled = render_oled(self._state)
        for slot, text in new_oled.items():
            if self._last_oled.get(slot) != text:
                if slot in _OLED_SOFTKEY_TITLE_SLOTS:
                    r, g, b = ACCENT_GOLD
                else:
                    r = g = b = 0x7F
                self._controller.write_oled(slot, text, r, g, b)
        # Clear any slots that were in last render but not in new render.
        for slot in self._last_oled:
            if slot not in new_oled:
                self._controller.write_oled(slot, "", 0, 0, 0)
        self._last_oled = new_oled

    def _send_led_diffs(self) -> None:
        new_leds = render_button_leds(self._state)
        for cc, on in new_leds.items():
            if self._last_leds.get(cc) != on:
                self._controller.set_button_led(cc, on)
        self._last_leds = new_leds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eden M1/M2 jambox")
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--samples", default="samples")
    args = parser.parse_args()

    app = EdenApp(sample_dir=args.samples, bpm=args.bpm)
    app.run()
