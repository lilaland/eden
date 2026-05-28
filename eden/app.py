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
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eden.controller import AtomSQ
from eden.audio import SamplePlayer, StateRef, StepScheduler
from eden.clock import SequencerClock
from eden.reduce import reduce
from eden.render import render_pads, render_oled, render_button_leds
from eden.state import default_state, AppState
from eden.events import ClockTicked, SoftkeyPressed, SongSlotPressed, TapTempoPressed, TransportPressed, TouchbarMoved
import eden.sessions as sessions

# UNVERIFIED: pad LED addressing — pad_index → note offset confirmed in v0 probe.py
# UNVERIFIED: ATM SQ Control port requirement — all LED/OLED output must go to Control port
_PAD_NOTE_OFFSET = 36
_DEFAULT_SESSIONS_DIR = "sessions"


class EdenApp:
    def __init__(
        self,
        sample_dir: str = "samples",
        bpm: float = 120.0,
        session_paths: list[str | None] | None = None,
        sessions_dir: str = _DEFAULT_SESSIONS_DIR,
    ) -> None:
        self._eq: queue.Queue = queue.Queue()
        self._sessions_dir = sessions_dir
        self._session_paths: list[str | None] = list(session_paths) if session_paths else [None] * 8
        while len(self._session_paths) < 8:
            self._session_paths.append(None)

        # Load initial state: slot 0 if it has a file, otherwise default.
        self._state = default_state()
        self._state = dataclasses.replace(self._state, tempo_bpm=bpm)
        self._try_load_slot(0, initial=True)

        self._state_ref = StateRef(self._state)

        self._controller = AtomSQ(event_queue=self._eq)
        self._audio = SamplePlayer(sample_dir=sample_dir)
        self._clock = SequencerClock(
            bpm=self._state.tempo_bpm, steps=32, ppq=8, event_queue=self._eq
        )
        self._scheduler = StepScheduler(player=self._audio, state_ref=self._state_ref)

        # Render delta state: compare against previous render to send only diffs.
        self._last_pad_colors: tuple[tuple[int, int, int], ...] = tuple(
            (0, 0, 0) for _ in range(32)
        )
        self._last_oled: dict[int, tuple[str, int, int, int]] = {}
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
        print(f"Eden M2 — {self._state.tempo_bpm:.0f} BPM  slot {sessions.slot_letter(self._state.active_session_slot)}  |  Ctrl-C to quit")
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

            # SK4 while metronome held → tap tempo (needs wall-clock timestamp).
            if isinstance(event, SoftkeyPressed) and event.key == 3 and self._state.metronome_held:
                event = TapTempoPressed(timestamp=time.time())

            new_state = reduce(self._state, event)

            if new_state is not self._state:
                old_bpm = self._state.tempo_bpm
                self._state = new_state
                self._state_ref.set(new_state)
                self._flush_render()
                if new_state.tempo_bpm != old_bpm:
                    self._clock.set_bpm(new_state.tempo_bpm)

            # REC press → save current session to active slot.
            if isinstance(event, TransportPressed) and event.button == "REC" and event.pressed:
                self._save_session(self._state.active_session_slot)

            # Pending session: load when playing_loops drains to empty.
            if self._state.pending_session_slot is not None and not self._state.playing_loops:
                self._load_session(self._state.pending_session_slot)

            # Schedule audio AFTER state swap so scheduler sees updated playhead.
            if isinstance(event, ClockTicked):
                self._scheduler.on_tick()

    # ─── Session I/O ─────────────────────────────────────────────────────────

    def _slot_path(self, slot: int) -> str:
        """Resolve or auto-generate a file path for the given slot."""
        if self._session_paths[slot]:
            return self._session_paths[slot]
        letter = sessions.slot_letter(slot).lower()
        path = os.path.join(self._sessions_dir, f"session_{letter}.json")
        self._session_paths[slot] = path
        return path

    def _save_session(self, slot: int) -> None:
        path = self._slot_path(slot)
        name = os.path.splitext(os.path.basename(path))[0]
        data = sessions.state_to_session(self._state, name)
        try:
            sessions.save_file(path, data)
        except OSError as e:
            print(f"[session] save failed: {e}", file=sys.stderr)

    def _load_session(self, slot: int) -> None:
        path = self._session_paths[slot]
        if not path or not os.path.exists(path):
            # Empty slot — just switch the active slot index.
            self._state = dataclasses.replace(
                self._state, active_session_slot=slot, pending_session_slot=None
            )
            self._state_ref.set(self._state)
            self._flush_render()
            return
        try:
            data = sessions.load_file(path)
        except (OSError, ValueError) as e:
            print(f"[session] load failed: {e}", file=sys.stderr)
            self._state = dataclasses.replace(self._state, pending_session_slot=None)
            return
        patch = sessions.session_to_state_patch(data, slot)
        self._state = dataclasses.replace(self._state, **patch)
        self._state_ref.set(self._state)
        self._clock.set_bpm(self._state.tempo_bpm)
        self._flush_render()

    def _try_load_slot(self, slot: int, initial: bool = False) -> None:
        """Load a session file into state if the path exists. No-op if missing."""
        path = self._session_paths[slot]
        if not path or not os.path.exists(path):
            if initial:
                self._state = dataclasses.replace(self._state, active_session_slot=slot)
            return
        try:
            data = sessions.load_file(path)
            patch = sessions.session_to_state_patch(data, slot)
            self._state = dataclasses.replace(self._state, **patch)
        except (OSError, ValueError) as e:
            print(f"[session] initial load failed for slot {sessions.slot_letter(slot)}: {e}", file=sys.stderr)

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
        for slot, entry in new_oled.items():
            if self._last_oled.get(slot) != entry:
                text, r, g, b = entry
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
    parser = argparse.ArgumentParser(description="Eden M2 jambox")
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--samples", default="samples")
    parser.add_argument(
        "--session", action="append", metavar="SLOT:FILE",
        help="Pre-load session file into A-H slot. Example: --session A:kick.json"
    )
    parser.add_argument("--sessions-dir", default=_DEFAULT_SESSIONS_DIR,
                        help="Directory for auto-named session files (default: sessions/)")
    args = parser.parse_args()

    session_paths: list[str | None] = [None] * 8
    for spec in (args.session or []):
        letter, _, path = spec.partition(":")
        idx = sessions.slot_from_letter(letter)
        if idx is not None:
            session_paths[idx] = path
        else:
            print(f"[warn] unknown slot '{letter}' in --session {spec}", file=sys.stderr)

    app = EdenApp(
        sample_dir=args.samples,
        bpm=args.bpm,
        session_paths=session_paths,
        sessions_dir=args.sessions_dir,
    )
    app.run()
