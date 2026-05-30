"""
eden/audio.py — Audio mixer and step scheduler for Eden jambox.

AudioMixer owns the sounddevice stream and per-track TrackEngine instances.
StepScheduler reads AppState on each clock tick and calls engine.note_on().
StateRef is a thread-safe atomic state container shared between main and audio threads.
"""

from __future__ import annotations

import os
import sys
import time
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from eden.engines import DrumEngine, SynthEngine, TrackEngine
from eden.state import SynthTrack
from eden.arp import expand_chord, compute_arp_sequence, arp_ticks_per_note

# ---------------------------------------------------------------------------
# StateRef — atomic state reference
# ---------------------------------------------------------------------------


class StateRef:
    """
    Thread-safe atomic reference to the current AppState.

    Writes are serialized by a lock; reads are lock-free in Python
    because object reference assignment is atomic in CPython.
    The audio callback reads self._state directly (no lock) — safe under CPython's GIL.
    """

    def __init__(self, initial_state) -> None:
        self._state = initial_state
        self._lock = threading.Lock()

    def get(self):
        return self._state

    def set(self, new_state) -> None:
        with self._lock:
            self._state = new_state


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SAMPLE_RATE = 44100
BLOCK_SIZE = 256  # frames per callback — ~5.8 ms @ 44100


# ---------------------------------------------------------------------------
# AudioMixer
# ---------------------------------------------------------------------------


class AudioMixer:
    """
    Low-latency audio mixer backed by sounddevice in callback mode.

    Owns:
      - Sample loading (_samples dict shared with DrumEngine instances)
      - Active track engines (_engines: track_idx → TrackEngine)
      - Finishing engines (_finishing_engines: track_idx → TrackEngine) for
        graceful session transitions — old engines continue playing until
        their loops finish, then are discarded.

    The audio callback snapshots both engine dicts at the start to avoid
    iteration-during-modification issues (main thread may reassign engines).
    """

    def __init__(self, sample_dir: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self._sr = sample_rate
        self._samples: dict[str, np.ndarray] = {}
        self._engines: dict[int, TrackEngine] = {}
        self._finishing_engines: dict[int, TrackEngine] = {}

        # Pre-allocated mix buffer (float64 for internal precision)
        self._mix_buf = np.zeros((BLOCK_SIZE, 2), dtype=np.float64)

        if os.path.isdir(sample_dir):
            for fname in os.listdir(sample_dir):
                if fname.lower().endswith(".wav"):
                    name = os.path.splitext(fname)[0]
                    try:
                        self.load(name, os.path.join(sample_dir, fname))
                    except Exception as exc:
                        print(f"[audio] warning: could not load {fname}: {exc}", file=sys.stderr)

        self._stream = sd.OutputStream(
            samplerate=self._sr,
            channels=2,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
        )
        self._stream.start()

    # ------------------------------------------------------------------
    # Sample loading
    # ------------------------------------------------------------------

    def load(self, name: str, path: str) -> None:
        """Load (or reload) a single sample by name from a WAV file."""
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        if sr != self._sr:
            ratio = self._sr / sr
            new_len = int(len(data) * ratio)
            indices = (np.arange(new_len) / ratio).astype(np.int32)
            indices = np.clip(indices, 0, len(data) - 1)
            data = data[indices]
        if data.shape[1] == 1:
            data = np.hstack([data, data])
        elif data.shape[1] > 2:
            data = data[:, :2]
        # Convert to float64 so DrumEngine mixes into float64 buf without casting
        self._samples[name] = data.astype(np.float64)

    # ------------------------------------------------------------------
    # Engine management (called from main thread)
    # ------------------------------------------------------------------

    def create_engine_for(self, track) -> TrackEngine:
        from eden.state import DrumTrack, SynthTrack
        if isinstance(track, DrumTrack):
            return DrumEngine(track.sample_name, self._samples)
        if isinstance(track, SynthTrack):
            return SynthEngine(self._sr)
        raise ValueError(f"No engine for track type {type(track).__name__!r}")

    def assign_engine(self, track_idx: int, engine: TrackEngine) -> None:
        self._engines[track_idx] = engine

    def remove_engine(self, track_idx: int) -> None:
        self._engines.pop(track_idx, None)

    def get_engine(self, track_idx: int) -> Optional[TrackEngine]:
        return self._engines.get(track_idx)

    def assign_finishing_engine(self, track_idx: int, engine: TrackEngine) -> None:
        self._finishing_engines[track_idx] = engine

    def get_finishing_engine(self, track_idx: int) -> Optional[TrackEngine]:
        return self._finishing_engines.get(track_idx)

    def clear_finishing_engines(self) -> None:
        self._finishing_engines.clear()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop_all(self) -> None:
        """Silence all active voices (enqueued as lock-free sentinel per engine)."""
        for engine in list(self._engines.values()):
            engine.all_notes_off()
        for engine in list(self._finishing_engines.values()):
            engine.all_notes_off()

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()

    # ------------------------------------------------------------------
    # Audio callback (sounddevice audio thread)
    # ------------------------------------------------------------------

    def _audio_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(f"[audio] stream status: {status}", file=sys.stderr)

        mix = self._mix_buf
        mix[:frames] = 0.0

        for engine in list(self._engines.values()):
            engine.fill_block(mix[:frames], frames)

        for engine in list(self._finishing_engines.values()):
            engine.fill_block(mix[:frames], frames)

        np.clip(mix[:frames], -1.0, 1.0, out=mix[:frames])
        outdata[:] = mix[:frames].astype(np.float32)


# ---------------------------------------------------------------------------
# StepScheduler — reads state, dispatches note_on to engines
# ---------------------------------------------------------------------------


class StepScheduler:
    """
    On each clock tick, reads AppState and calls engine.note_on() for every
    active step at the current playhead. Runs on the main (event-loop) thread.

    Arp state (_arp_tracks) keeps a per-track context for ongoing arp sequences.
    Each context is a dict with keys: sequence, idx, ticks_until_next,
    ticks_per_note, amplitude, gate_samples, engine, track.
    """

    def __init__(self, mixer: AudioMixer, state_ref: StateRef) -> None:
        self._mixer = mixer
        self._state_ref = state_ref
        self._arp_tracks: dict[int, dict] = {}  # track_idx → arp context

    def on_tick(self) -> None:
        state = self._state_ref.get()
        if not state.is_playing:
            self._arp_tracks.clear()
            return

        playhead = state.playhead
        offsets = dict(state.loop_measure_offsets)
        muted = state.muted_tracks
        soloed = state.soloed_tracks

        effective_muted = muted
        if soloed:
            effective_muted = frozenset(
                i for i in range(len(state.tracks)) if i not in soloed
            )

        self._trigger_loops(
            state.playing_loops, state.tracks, offsets, playhead,
            effective_muted, state.tempo_bpm, self._mixer.get_engine,
            apply_effects=True,
        )

        if state.finishing_loops and state.finishing_tracks:
            fin_offsets = dict(state.finishing_loop_measure_offsets)
            self._trigger_loops(
                state.finishing_loops, state.finishing_tracks, fin_offsets, playhead,
                effective_muted, state.tempo_bpm, self._mixer.get_finishing_engine,
                apply_effects=False,
            )

        # Advance ongoing arp sequences
        self._advance_arp()

    def _trigger_loops(
        self,
        loops,
        tracks,
        offsets,
        playhead,
        muted,
        bpm: float,
        get_engine: Callable[[int], Optional[TrackEngine]],
        *,
        apply_effects: bool = False,
    ) -> None:
        sr = self._mixer._sr
        for track_idx, track in enumerate(tracks):
            if track is None or track_idx in muted:
                continue

            for loop_idx, loop in enumerate(track.loops):
                key = (track_idx, loop_idx)
                if key not in loops:
                    continue

                spb = loop.steps_per_bar
                if spb > 32:
                    step_in_bar = playhead
                    stride = 32
                else:
                    step_in_bar = playhead * spb // 32
                    if step_in_bar == (playhead - 1) * spb // 32:
                        continue
                    stride = spb

                offset = offsets.get(key, 0)
                effective_step = step_in_bar + offset * stride
                if effective_step >= loop.step_count:
                    continue

                step = loop.steps[effective_step]
                if not step.on:
                    continue

                engine = get_engine(track_idx)
                if engine is None:
                    continue

                step_secs = (4.0 / loop.step_size) * (60.0 / bpm)
                gate_samples = max(1, int(step.gate * step_secs * sr))
                amplitude = (step.velocity / 127.0) * loop.volume
                pitches = step.pitches

                if apply_effects and isinstance(track, SynthTrack):
                    # Chord expansion: add chord tones to each pitch
                    if track.chord_on:
                        pitches = expand_chord(pitches, track.chord_type)

                    # Arp: sequence pitches over time instead of playing all at once
                    if track.arp_on and track.arp_mode != "chord":
                        seq = compute_arp_sequence(pitches, track.arp_mode, track.arp_octaves)
                        if seq:
                            tpn = arp_ticks_per_note(track.arp_rate)
                            arp_gate = max(1, int(0.8 * tpn * 60.0 / bpm / 8.0 * sr))
                            # Fire first note immediately; register context for subsequent
                            engine.note_on(seq[0], amplitude, arp_gate, track)
                            if len(seq) > 1:
                                self._arp_tracks[track_idx] = {
                                    "sequence": seq,
                                    "idx": 1,
                                    "ticks_until_next": tpn,
                                    "ticks_per_note": tpn,
                                    "amplitude": amplitude,
                                    "gate_samples": arp_gate,
                                    "engine": engine,
                                    "track": track,
                                }
                            else:
                                self._arp_tracks.pop(track_idx, None)
                        break
                    elif track.arp_on and track.arp_mode == "chord":
                        # Chord arp mode = all notes at once (same as chord_on)
                        pitches = compute_arp_sequence(pitches, "chord", track.arp_octaves)

                for p in pitches:
                    engine.note_on(p, amplitude, gate_samples, track)
                break

    def _advance_arp(self) -> None:
        """Fire the next note for each active arp sequence."""
        finished: list[int] = []
        for track_idx, ctx in self._arp_tracks.items():
            ctx["ticks_until_next"] -= 1
            if ctx["ticks_until_next"] > 0:
                continue
            # Fire next note
            seq = ctx["sequence"]
            idx = ctx["idx"]
            ctx["engine"].note_on(
                seq[idx], ctx["amplitude"], ctx["gate_samples"], ctx["track"]
            )
            idx = (idx + 1) % len(seq)
            ctx["idx"] = idx
            ctx["ticks_until_next"] = ctx["ticks_per_note"]
        # No cleanup needed — arp loops indefinitely until a new step fires


# ---------------------------------------------------------------------------
# CLI test entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m eden.audio <path/to/sample.wav>")
        sys.exit(1)

    wav_path = sys.argv[1]
    if not os.path.isfile(wav_path):
        print(f"File not found: {wav_path}")
        sys.exit(1)

    sample_dir = os.path.dirname(wav_path) or "."
    mixer = AudioMixer(sample_dir=sample_dir)

    name = os.path.splitext(os.path.basename(wav_path))[0]
    mixer.load(name, wav_path)

    from eden.state import DrumTrack
    from eden.engines import DrumEngine
    engine = DrumEngine(name, mixer._samples)
    mixer.assign_engine(0, engine)

    print(f"Triggering sample '{name}' ...")
    from eden.state import StepNote
    engine.note_on(60, 1.0, 44100, None)

    time.sleep(3.0)
    mixer.close()
    print("Done.")
