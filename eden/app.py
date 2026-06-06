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
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eden.controller import AtomSQ
from eden.audio import AudioMixer, StateRef, StepScheduler
from eden.clock import SequencerClock
from eden.reduce import reduce
from eden.render import render_pads, render_oled, render_button_leds
from eden.scales import degree_to_pitch, white_idx_to_midi, black_key_at
from eden.arp import expand_chord, compute_arp_sequence, arp_ticks_per_note
from eden.state import default_state, AppState, DrumTrack, SynthTrack, InstrumentSubmode, Mode
from eden.fx import FXProcessor
from eden.events import AftertouchChanged, ClockTicked, InstrumentReset, InstrumentUndo, PadPressed, PadReleased, PlusMinusPressed, SessionLoaded, SoftkeyPressed, SongSlotPressed, TapTempoPressed, TransportPressed, TouchbarMoved
from eden.state import Mode
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
        self._mixer = AudioMixer(sample_dir=sample_dir)
        self._clock = SequencerClock(
            bpm=self._state.tempo_bpm, steps=32, ppq=8, event_queue=self._eq
        )
        self._scheduler = StepScheduler(mixer=self._mixer, state_ref=self._state_ref)
        self._init_engines(self._state)

        # Render delta state: compare against previous render to send only diffs.
        self._last_pad_colors: tuple[tuple[int, int, int], ...] = tuple(
            (0, 0, 0) for _ in range(32)
        )
        self._last_oled: dict[int, tuple[str, int, int, int]] = {}
        self._last_leds: dict[int, bool] = {}

        # FREE piano mode: track pad-down timestamps for hold-duration recording
        self._free_pad_down_times: dict[int, float] = {}
        # FREE arp mode: held pads per track so multi-pad arps cycle all pitches
        self._held_arp_pitches: dict[int, dict[int, int]] = {}  # track_idx → {pad_idx → pitch}
        self._fx_processors: dict[int, FXProcessor] = {}
        self._master_fx: FXProcessor = FXProcessor(sample_rate=44100)
        self._mixer.set_master_fx(self._master_fx)
        self._init_fx(self._state)

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._controller.enter_native_mode()
        self._clock.start()
        self._controller.start_listening()
        self._flush_render()  # paint initial state

    def stop(self) -> None:
        self._clock.stop()
        self._controller.stop_listening()
        self._mixer.stop_all()
        self._mixer.close()
        self._controller.close()

    def run(self, ui=None) -> None:
        print(f"Eden M2 — {self._state.tempo_bpm:.0f} BPM  slot {sessions.slot_letter(self._state.active_session_slot)}  |  Ctrl-C to quit")
        self.start()
        try:
            if ui is not None:
                # Run the Eden event loop on a background thread so the UI
                # can own the main thread (required on macOS for SDL/pygame).
                bg = threading.Thread(target=self._event_loop, daemon=True)
                bg.start()
                ui.run_blocking()  # blocks until window closed or Ctrl-C
            else:
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

            # FREE piano mode: record pad-down timestamp; enrich PadReleased with hold time.
            if isinstance(event, PadPressed) and self._is_free_piano_mode():
                self._free_pad_down_times[event.pad_index] = time.time()
            if isinstance(event, PadReleased) and self._is_free_piano_mode():
                down_time = self._free_pad_down_times.pop(event.pad_index, time.time())
                event = PadReleased(pad_index=event.pad_index,
                                    hold_seconds=time.time() - down_time)

            # Shift+STOP in INSTRUMENT: undo.
            if (isinstance(event, TransportPressed) and event.button == "STOP"
                    and self._state.shift_held
                    and self._state.mode == Mode.INSTRUMENT):
                if not event.pressed:
                    event = InstrumentUndo()  # type: ignore[assignment]
                else:
                    continue  # consume press, act on release

            # A-H slot press: SESSION mode only → immediate display switch.
            if isinstance(event, SongSlotPressed) and event.pressed:
                if (self._state.mode == Mode.SESSION and
                        event.slot != self._state.active_session_slot):
                    self._switch_session(event.slot, immediate=self._state.shift_held)
                continue  # don't dispatch to reducer

            new_state = reduce(self._state, event)

            if new_state is not self._state:
                old_bpm = self._state.tempo_bpm
                self._sync_engines(self._state, new_state)
                self._sync_fx(self._state, new_state)
                self._state = new_state
                self._state_ref.set(new_state)
                self._flush_render()
                if new_state.tempo_bpm != old_bpm:
                    self._clock.set_bpm(new_state.tempo_bpm)

            # REC press → save current session to active slot (SESSION mode only).
            if (isinstance(event, TransportPressed) and event.button == "REC" and event.pressed
                    and self._state.mode == Mode.SESSION):
                self._save_session(self._state.active_session_slot)

            # Schedule audio AFTER state swap so scheduler sees updated playhead.
            if isinstance(event, ClockTicked):
                self._scheduler.on_tick()

            # Immediate note-on for synth PADS/STEPS pitch entry (audio feedback).
            if isinstance(event, PadPressed) and self._state.mode == Mode.INSTRUMENT:
                self._maybe_trigger_synth_preview(event)

            # Aftertouch note-off: release held preview note when pad is lifted.
            if isinstance(event, PadReleased) and self._state.mode == Mode.INSTRUMENT:
                self._maybe_release_synth_preview(event)

            # Channel pressure → update gain on active synth voices.
            if isinstance(event, AftertouchChanged):
                self._apply_aftertouch(event.value)

    def _is_free_piano_mode(self) -> bool:
        """True when INSTRUMENT mode is active with an unquantized SynthTrack armed."""
        if self._state.mode != Mode.INSTRUMENT or not self._state.armed_tracks:
            return False
        track = self._state.tracks[self._state.armed_tracks[0]]
        return isinstance(track, SynthTrack) and not track.quantized

    def _maybe_trigger_synth_preview(self, event: PadPressed) -> None:
        """Fire a short preview note when recording a pitch in synth pad modes."""
        if not self._state.armed_tracks:
            return
        track_idx = self._state.armed_tracks[0]
        track = self._state.tracks[track_idx]
        if not isinstance(track, SynthTrack):
            return
        pad = event.pad_index
        if not track.quantized:
            # FREE piano keyboard mode — same index arithmetic as reduce/_piano_pad_pressed
            offset = self._state.pitch_window_offset
            if pad < 16:
                pitch = white_idx_to_midi(offset + pad)
                if pitch < 0 or pitch > 127:
                    return
            else:
                pitch = black_key_at(offset + (pad - 16))
                if pitch is None or pitch < 0 or pitch > 127:
                    return  # dead key or out of range
        else:
            submode = self._state.instrument_submode
            if submode == InstrumentSubmode.PADS:
                degree = self._state.pitch_window_offset + pad
            elif submode == InstrumentSubmode.STEPS and pad < 16:
                degree = self._state.pitch_window_offset + pad
            else:
                return
            pitch = degree_to_pitch(track.root_note, track.scale, degree)
        pitch = max(0, min(127, pitch + self._state.octave_offset * 12))
        engine = self._mixer.get_engine(track_idx)
        if engine is None:
            return
        # FREE mode: gate is effectively ∞ — pad release triggers note_off regardless of aftertouch
        # STEPS/PADS mode: short preview so the note doesn't linger
        if not track.quantized:
            gate = max(1, int(30.0 * self._mixer._sr))
            amplitude = event.velocity / 127.0 if self._state.vel_sensitive else 1.0
        else:
            gate = max(1, int(0.25 * self._mixer._sr))
            amplitude = event.velocity / 127.0

        # Chord/arp settings come from the selected loop (per-loop, not per-track)
        sel_loop = track.loops[self._state.selected_loop]

        # Chord expansion (applies in both FREE and STEPS/PADS modes)
        pitches: tuple[int, ...] = (pitch,)
        if sel_loop.chord_on:
            pitches = expand_chord(pitches, sel_loop.chord_type)

        # In FREE mode with arp on: drive the arp via the clock tick scheduler.
        # Accumulate all held pads so holding multiple keys arpeggios through all of them.
        if sel_loop.arp_on and not track.quantized:
            held = self._held_arp_pitches.setdefault(track_idx, {})
            held[pad] = pitch
            all_pitches: tuple[int, ...] = tuple(sorted(set(held.values())))
            if sel_loop.chord_on:
                all_pitches = expand_chord(all_pitches, sel_loop.chord_type)
            seq = compute_arp_sequence(all_pitches, sel_loop.arp_mode, sel_loop.arp_octaves)
            if seq:
                tpn = arp_ticks_per_note(sel_loop.arp_rate)
                bpm = self._state.tempo_bpm
                arp_gate = max(1, int(0.8 * tpn * 60.0 / bpm / 8.0 * self._mixer._sr))
                self._scheduler.merge_live_arp(
                    track_idx, seq, engine, amplitude, tpn, arp_gate, track
                )
            return

        for p in pitches:
            engine.note_on(p, amplitude, gate, track)

    def _apply_aftertouch(self, value: int) -> None:
        """Forward channel pressure to all armed synth engines that have aftertouch enabled."""
        if not self._state.armed_tracks:
            return
        from eden.engines import SynthEngine
        gain = value / 127.0
        for track_idx in self._state.armed_tracks:
            track = self._state.tracks[track_idx]
            if not isinstance(track, SynthTrack) or not track.aftertouch:
                continue
            engine = self._mixer.get_engine(track_idx)
            if isinstance(engine, SynthEngine):
                engine.set_aftertouch(gain)

    def _maybe_release_synth_preview(self, event: PadReleased) -> None:
        """Release a held aftertouch preview note on pad up."""
        if not self._state.armed_tracks:
            return
        track_idx = self._state.armed_tracks[0]
        track = self._state.tracks[track_idx]
        if not isinstance(track, SynthTrack) or track.quantized:
            return  # quantized modes use short gate, no note_off needed
        from eden.engines import SynthEngine
        engine = self._mixer.get_engine(track_idx)
        if not isinstance(engine, SynthEngine):
            return
        pad = event.pad_index
        if not track.quantized:
            offset = self._state.pitch_window_offset
            if pad < 16:
                pitch = white_idx_to_midi(offset + pad)
                if pitch < 0 or pitch > 127:
                    return
            else:
                pitch = black_key_at(offset + (pad - 16))
                if pitch is None:
                    return
        else:
            submode = self._state.instrument_submode
            if submode == InstrumentSubmode.PADS:
                degree = self._state.pitch_window_offset + pad
            elif submode == InstrumentSubmode.STEPS and pad < 16:
                degree = self._state.pitch_window_offset + pad
            else:
                return
            pitch = degree_to_pitch(track.root_note, track.scale, degree)
        pitch = max(0, min(127, pitch + self._state.octave_offset * 12))

        # Chord/arp from selected loop
        sel_loop = track.loops[self._state.selected_loop]

        # Live arp: remove this pad from held set; if others still down, update
        # sequence; if none remain, stop the arp entirely.
        if sel_loop.arp_on:
            held = self._held_arp_pitches.get(track_idx, {})
            held.pop(pad, None)
            if held:
                all_pitches: tuple[int, ...] = tuple(sorted(set(held.values())))
                if sel_loop.chord_on:
                    all_pitches = expand_chord(all_pitches, sel_loop.chord_type)
                seq = compute_arp_sequence(all_pitches, sel_loop.arp_mode, sel_loop.arp_octaves)
                tpn = arp_ticks_per_note(sel_loop.arp_rate)
                bpm = self._state.tempo_bpm
                arp_gate = max(1, int(0.8 * tpn * 60.0 / bpm / 8.0 * self._mixer._sr))
                # Keep existing amplitude from running context; it was set on press
                existing = self._scheduler._live_arp_tracks.get(track_idx)
                cur_amplitude = existing["amplitude"] if existing else 1.0
                if seq:
                    self._scheduler.merge_live_arp(
                        track_idx, seq, engine, cur_amplitude, tpn, arp_gate, track
                    )
            else:
                self._held_arp_pitches.pop(track_idx, None)
                self._scheduler.stop_live_arp(track_idx)
            return

        pitches: tuple[int, ...] = (pitch,)
        if sel_loop.chord_on:
            pitches = expand_chord(pitches, sel_loop.chord_type)
        for p in pitches:
            engine.note_off(p)

    # ─── Engine lifecycle ─────────────────────────────────────────────────────

    def _init_engines(self, state: AppState) -> None:
        """Create engines for all non-None tracks in state."""
        for i, track in enumerate(state.tracks):
            if track is not None:
                self._mixer.assign_engine(i, self._mixer.create_engine_for(track))

    def _init_fx(self, state: AppState) -> None:
        """Create FX processors for all non-None tracks with fx attribute."""
        self._master_fx.update_async(state.global_fx)
        for i, track in enumerate(state.tracks):
            if track is not None and hasattr(track, "fx"):
                proc = FXProcessor(sample_rate=self._mixer._sr)
                self._fx_processors[i] = proc
                self._mixer.assign_fx_processor(i, proc)
                proc.update_async(track.fx)

    def _sync_fx(self, old_state: AppState, new_state: AppState) -> None:
        """Sync FX processors after a state transition."""
        if old_state.global_fx is not new_state.global_fx:
            self._master_fx.update_async(new_state.global_fx)

        for i, (old_t, new_t) in enumerate(zip(old_state.tracks, new_state.tracks)):
            if new_t is None:
                if i in self._fx_processors:
                    self._mixer.remove_fx_processor(i)
                    del self._fx_processors[i]
            elif not hasattr(new_t, "fx"):
                pass
            elif old_t is None or not hasattr(old_t, "fx"):
                proc = FXProcessor(sample_rate=self._mixer._sr)
                self._fx_processors[i] = proc
                self._mixer.assign_fx_processor(i, proc)
                proc.update_async(new_t.fx)
            elif old_t.fx is not new_t.fx:
                proc = self._fx_processors.get(i)
                if proc is None:
                    proc = FXProcessor(sample_rate=self._mixer._sr)
                    self._fx_processors[i] = proc
                    self._mixer.assign_fx_processor(i, proc)
                proc.update_async(new_t.fx)

    def _sync_engines(self, old_state: AppState, new_state: AppState) -> None:
        """
        Diff-based engine management called after every state transition.

        Tracks that changed get their engines replaced. When a graceful session
        transition is in progress (finishing_loops is non-empty), old engines
        for finishing tracks are moved to _finishing_engines so they keep playing.
        When finishing_loops drains to empty, finishing engines are released.
        """
        old_tracks = old_state.tracks
        new_tracks = new_state.tracks

        for i, (old_t, new_t) in enumerate(zip(old_tracks, new_tracks)):
            if old_t is new_t:
                continue

            # Reuse the existing engine when the track type hasn't changed and
            # no audio-critical parameters changed.  SynthEngine has no init
            # deps on track data at all; DrumEngine only needs replacement when
            # the sample name changes.  Replacing engines during FREE recording
            # (which creates a new track object on every pad press) would kill
            # active voices and break live arp sequences.
            if (old_t is not None and new_t is not None
                    and type(old_t) is type(new_t)):
                if isinstance(new_t, SynthTrack):
                    continue  # SynthEngine is stateless w.r.t. track data
                if isinstance(new_t, DrumTrack) and old_t.sample_name == new_t.sample_name:
                    continue  # DrumEngine only depends on sample_name

            # Preserve old engine if this track has finishing loops
            if new_state.finishing_loops and old_t is not None:
                if any(tid == i for tid, _ in new_state.finishing_loops):
                    old_engine = self._mixer.get_engine(i)
                    if old_engine is not None:
                        self._mixer.assign_finishing_engine(i, old_engine)

            self._mixer.remove_engine(i)
            if new_t is not None:
                self._mixer.assign_engine(i, self._mixer.create_engine_for(new_t))

        # Release finishing engines once all finishing loops have played out
        if old_state.finishing_loops and not new_state.finishing_loops:
            self._mixer.clear_finishing_engines()

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

    def _switch_session(self, slot: int, immediate: bool) -> None:
        """Dispatch a SessionLoaded event to transition to a new session slot."""
        path = self._session_paths[slot]
        if path and os.path.exists(path):
            try:
                data = sessions.load_file(path)
            except (OSError, ValueError) as e:
                print(f"[session] load failed: {e}", file=sys.stderr)
                return
            patch = sessions.session_to_state_patch(data, slot)
            ev = SessionLoaded(
                slot=slot,
                tracks=patch["tracks"],
                tempo_bpm=patch["tempo_bpm"],
                swing=patch["swing"],
                active_loops=patch["active_loops"],
                muted_tracks=patch["muted_tracks"],
                soloed_tracks=patch["soloed_tracks"],
                immediate=immediate,
            )
        else:
            # Empty slot — switch display, keep no tracks.
            ev = SessionLoaded(
                slot=slot,
                tracks=tuple(None for _ in range(16)),
                tempo_bpm=self._state.tempo_bpm,
                swing=self._state.swing,
                active_loops=frozenset(),
                muted_tracks=frozenset(),
                soloed_tracks=frozenset(),
                immediate=True,
            )
        new_state = reduce(self._state, ev)
        if new_state is not self._state:
            old_bpm = self._state.tempo_bpm
            self._sync_engines(self._state, new_state)
            self._sync_fx(self._state, new_state)
            self._state = new_state
            self._state_ref.set(new_state)
            self._flush_render()
            if new_state.tempo_bpm != old_bpm:
                self._clock.set_bpm(new_state.tempo_bpm)

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
    parser.add_argument("--ui", action="store_true",
                        help="Open the pygame debug window (requires pygame)")
    parser.add_argument("--web", action="store_true",
                        help="Open browser controller mirror on http://localhost:8765")
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

    ui = None
    if args.web:
        from eden.web_ui import WebUI
        ui = WebUI(
            app._state_ref,
            dispatch_fn=app._eq.put,
            sessions_dir=app._sessions_dir,
            mixer=app._mixer,
        )
    elif args.ui:
        from eden.debug_ui import DebugUI
        ui = DebugUI(app._state_ref)

    app.run(ui=ui)
