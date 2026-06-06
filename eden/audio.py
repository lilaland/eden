"""
eden/audio.py — Audio mixer and step scheduler for Eden jambox.

AudioMixer owns the sounddevice stream and per-track TrackEngine instances.
StepScheduler reads AppState on each clock tick and calls engine.note_on().
StateRef is a thread-safe atomic state container shared between main and audio threads.
"""

from __future__ import annotations

import os
import random
import sys
import time
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

from eden.engines import DrumEngine, SampleEngine, SynthEngine, TrackEngine
from eden.state import SampleTrack, SynthTrack
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
        self._sample_dir = sample_dir
        self._samples: dict[str, np.ndarray] = {}
        self._engines: dict[int, TrackEngine] = {}
        self._finishing_engines: dict[int, TrackEngine] = {}
        self._mute_group_registry: dict[int, int] = {}  # track_idx → mute_group_id

        # Pre-allocated mix buffer (float64 for internal precision)
        self._mix_buf = np.zeros((BLOCK_SIZE, 2), dtype=np.float64)
        self._track_buf = np.zeros((BLOCK_SIZE, 2), dtype=np.float64)
        self._fx_processors: dict[int, object] = {}
        self._master_fx = None

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

    @property
    def sample_dir(self) -> str:
        return self._sample_dir

    def unload(self, name: str) -> None:
        """Remove a sample from the in-memory cache (does not touch disk)."""
        self._samples.pop(name, None)

    def loaded_names(self) -> list[str]:
        """Return sorted list of all loaded sample names."""
        return sorted(self._samples.keys())

    def get_peaks(self, name: str, n_points: int = 1500) -> list[float] | None:
        """Return downsampled peak values for waveform display (0.0–1.0 each)."""
        sample = self._samples.get(name)
        if sample is None:
            return None
        mono = np.abs(sample).max(axis=1)
        n = len(mono)
        if n == 0:
            return [0.0] * n_points
        chunk = max(1, n // n_points)
        peaks = []
        for i in range(n_points):
            s = i * chunk
            e = min(s + chunk, n)
            peaks.append(float(mono[s:e].max()) if s < n else 0.0)
        peak_max = max(peaks) or 1.0
        return [p / peak_max for p in peaks]

    def normalize(self, name: str) -> bool:
        """Normalize sample peak to 1.0 in-memory. Returns True if done."""
        sample = self._samples.get(name)
        if sample is None:
            return False
        peak = np.abs(sample).max()
        if peak > 0:
            self._samples[name] = sample / peak
        return True

    def detect_onsets(self, name: str, n_target: int = 8) -> list[float]:
        """
        Simple numpy-only spectral flux onset detection.
        Returns list of normalized boundary positions (interior only, not 0.0 or 1.0)
        targeting ~n_target-1 interior boundaries (i.e. n_target segments).
        Falls back to equal divisions if fewer onsets detected.
        """
        sample = self._samples.get(name)
        if sample is None:
            return []
        mono = sample.mean(axis=1)
        hop = 512
        win = 1024
        n_frames = (len(mono) - win) // hop
        if n_frames < 2:
            return [i / n_target for i in range(1, n_target)]

        # Spectral flux
        flux = np.zeros(n_frames)
        prev = np.zeros(win // 2 + 1)
        for i in range(n_frames):
            chunk = mono[i * hop: i * hop + win]
            spec = np.abs(np.fft.rfft(chunk * np.hanning(win)))
            diff = spec - prev
            flux[i] = np.maximum(diff, 0).sum()
            prev = spec

        # Normalize flux
        if flux.max() > 0:
            flux /= flux.max()

        # Peak pick with adaptive threshold
        threshold = flux.mean() + 0.5 * flux.std()
        min_dist = max(1, n_frames // (n_target * 4))
        peaks = []
        last = -min_dist
        for i in range(1, len(flux) - 1):
            if flux[i] > threshold and flux[i] > flux[i - 1] and flux[i] > flux[i + 1]:
                if i - last >= min_dist:
                    peaks.append(i)
                    last = i

        # Pick n_target-1 strongest peaks
        if len(peaks) > n_target - 1:
            strengths = [(flux[p], p) for p in peaks]
            strengths.sort(reverse=True)
            peaks = sorted(p for _, p in strengths[:n_target - 1])

        if not peaks:
            return [i / n_target for i in range(1, n_target)]

        total = len(mono)
        return [p * hop / total for p in peaks]

    # ------------------------------------------------------------------
    # Engine management (called from main thread)
    # ------------------------------------------------------------------

    def create_engine_for(self, track) -> TrackEngine:
        from eden.state import DrumTrack, SynthTrack, SampleTrack
        if isinstance(track, DrumTrack):
            return DrumEngine(track.sample_name, self._samples)
        if isinstance(track, SynthTrack):
            return SynthEngine(self._sr)
        if isinstance(track, SampleTrack):
            return SampleEngine(track.sample_key, self._samples, sample_rate=self._sr)
        raise ValueError(f"No engine for track type {type(track).__name__!r}")

    def assign_engine(self, track_idx: int, engine: TrackEngine, mute_group: int = 0) -> None:
        self._engines[track_idx] = engine
        if mute_group > 0:
            self._mute_group_registry[track_idx] = mute_group
        else:
            self._mute_group_registry.pop(track_idx, None)

    def remove_engine(self, track_idx: int) -> None:
        self._engines.pop(track_idx, None)
        self._mute_group_registry.pop(track_idx, None)

    def get_engine(self, track_idx: int) -> Optional[TrackEngine]:
        return self._engines.get(track_idx)

    def assign_finishing_engine(self, track_idx: int, engine: TrackEngine) -> None:
        self._finishing_engines[track_idx] = engine

    def get_finishing_engine(self, track_idx: int) -> Optional[TrackEngine]:
        return self._finishing_engines.get(track_idx)

    def clear_finishing_engines(self) -> None:
        self._finishing_engines.clear()

    def silence_mute_group(self, group_id: int, except_track: int) -> None:
        """Stop all tracks in group_id except except_track."""
        if group_id <= 0:
            return
        for ti, engine in list(self._engines.items()):
            if ti == except_track:
                continue
            # We need track state to check mute_group; look up via the engines dict
            # The simplest approach: store mute_group registry updated by assign_engine
            grp = self._mute_group_registry.get(ti, 0)
            if grp == group_id:
                engine.all_notes_off()

    def assign_fx_processor(self, track_idx: int, proc) -> None:
        self._fx_processors[track_idx] = proc

    def remove_fx_processor(self, track_idx: int) -> None:
        self._fx_processors.pop(track_idx, None)

    def set_master_fx(self, proc) -> None:
        self._master_fx = proc

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
        track_buf = self._track_buf

        for track_idx, engine in list(self._engines.items()):
            track_buf[:frames] = 0.0
            engine.fill_block(track_buf[:frames], frames)
            fx = self._fx_processors.get(track_idx)
            if fx is not None:
                processed = fx.process(track_buf[:frames].astype(np.float32))
                mix[:frames] += processed.astype(np.float64)
            else:
                mix[:frames] += track_buf[:frames]

        for engine in list(self._finishing_engines.values()):
            engine.fill_block(mix[:frames], frames)

        np.clip(mix[:frames], -1.0, 1.0, out=mix[:frames])

        if self._master_fx is not None:
            out_f32 = mix[:frames].astype(np.float32)
            processed = self._master_fx.process(out_f32)
            outdata[:] = np.clip(processed if processed.shape[0] == frames else out_f32, -1.0, 1.0)
        else:
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

    def __init__(self, mixer: AudioMixer, state_ref: StateRef, record_fn=None) -> None:
        self._mixer = mixer
        self._state_ref = state_ref
        self._arp_tracks: dict[int, dict] = {}       # step-sequencer arp contexts
        self._live_arp_tracks: dict[int, dict] = {}  # live pad-held arp contexts
        self._record_fn = record_fn  # optional(track_idx, pitch, velocity, tpn) called when arp fires during recording

    def on_tick(self) -> None:
        state = self._state_ref.get()
        if not state.is_playing:
            self._arp_tracks.clear()
            # Live arps keep running even without transport
            if self._live_arp_tracks:
                self._advance_arp()
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

        # Advance ongoing arp sequences first so each interval is uniform
        self._advance_arp()

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

                # Per-step probability: skip if random roll exceeds threshold
                if step.probability < 100:
                    if random.randint(1, 100) > step.probability:
                        break

                engine = get_engine(track_idx)
                if engine is None:
                    continue

                step_secs = (4.0 / loop.step_size) * (60.0 / bpm)
                gate_samples = max(1, int(step.gate * step_secs * sr))
                amplitude = (step.velocity / 127.0) * loop.volume
                pitches = step.pitches

                # SampleTrack: use chop index from pitch; fire single note
                if isinstance(track, SampleTrack):
                    chop_idx = pitches[0] if pitches else 0
                    engine.note_on(chop_idx, amplitude, gate_samples, track)
                    break

                if apply_effects and isinstance(track, SynthTrack):
                    # Chord expansion: add chord tones to each pitch
                    if loop.chord_on:
                        pitches = expand_chord(pitches, loop.chord_type)

                    # Arp: sequence pitches over time instead of playing all at once
                    if loop.arp_on and loop.arp_mode != "chord":
                        seq = compute_arp_sequence(pitches, loop.arp_mode, loop.arp_octaves)
                        if seq:
                            tpn = arp_ticks_per_note(loop.arp_rate)
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
                    elif loop.arp_on and loop.arp_mode == "chord":
                        # Chord arp mode = all notes at once (same as chord_on)
                        pitches = compute_arp_sequence(pitches, "chord", loop.arp_octaves)

                for p in pitches:
                    engine.note_on(p, amplitude, gate_samples, track)
                break

    def start_live_arp(
        self,
        track_idx: int,
        seq: tuple,
        engine,
        amplitude: float,
        tpn: int,
        gate_samples: int,
        track,
    ) -> None:
        """Start a live (pad-held) arp sequence, firing the first note immediately."""
        if not seq:
            return
        engine.note_on(seq[0], amplitude, gate_samples, track)
        if len(seq) > 1:
            self._live_arp_tracks[track_idx] = {
                "sequence": seq,
                "idx": 1,
                "ticks_until_next": tpn,
                "ticks_per_note": tpn,
                "amplitude": amplitude,
                "gate_samples": gate_samples,
                "engine": engine,
                "track": track,
            }

    def merge_live_arp(
        self,
        track_idx: int,
        seq: tuple,
        engine,
        amplitude: float,
        tpn: int,
        gate_samples: int,
        track,
    ) -> None:
        """Update or start a live arp sequence without restarting the phase.

        If an arp is already running for this track, the sequence is swapped
        in-place and the current index is clamped to the new length so the
        rhythm continues uninterrupted.  If no arp is running, starts one
        immediately (same as start_live_arp).
        """
        if not seq:
            return
        ctx = self._live_arp_tracks.get(track_idx)
        if ctx is not None:
            ctx["sequence"] = seq
            ctx["idx"] = ctx["idx"] % len(seq)
            ctx["amplitude"] = amplitude
            ctx["gate_samples"] = gate_samples
            ctx["engine"] = engine
            ctx["track"] = track
        else:
            self.start_live_arp(track_idx, seq, engine, amplitude, tpn, gate_samples, track)

    def stop_live_arp(self, track_idx: int) -> None:
        """Stop a live arp; the last-fired note decays naturally."""
        self._live_arp_tracks.pop(track_idx, None)

    def _advance_arp(self) -> None:
        """Fire the next note for each active arp sequence (step and live)."""
        state = self._state_ref.get() if self._record_fn else None
        for ctx_dict in (self._arp_tracks, self._live_arp_tracks):
            is_live = ctx_dict is self._live_arp_tracks
            for track_idx, ctx in list(ctx_dict.items()):
                ctx["ticks_until_next"] -= 1
                if ctx["ticks_until_next"] > 0:
                    continue
                seq = ctx["sequence"]
                idx = ctx["idx"]
                pitch = seq[idx]
                ctx["engine"].note_on(pitch, ctx["amplitude"], ctx["gate_samples"], ctx["track"])
                ctx["idx"] = (idx + 1) % len(seq)
                ctx["ticks_until_next"] = ctx["ticks_per_note"]
                # Record each arp note to the loop when free_recording is active
                if is_live and self._record_fn and state is not None and state.free_recording:
                    velocity = int(ctx["amplitude"] * 127)
                    self._record_fn(track_idx, pitch, velocity, ctx["ticks_per_note"])


# ---------------------------------------------------------------------------
# SampleRecorder — captures audio from default input device
# ---------------------------------------------------------------------------


class SampleRecorder:
    """Captures audio from the default input device. Thread-safe."""

    def __init__(self, sr: int = 44100):
        self._sr = sr
        self._chunks: list = []
        self._recording = False
        self._stream = None
        self._lock = threading.Lock()

    def start(self):
        self._chunks = []
        self._recording = True
        self._stream = sd.InputStream(
            samplerate=self._sr, channels=2, dtype='float32',
            callback=self._cb, blocksize=512,
        )
        self._stream.start()

    def _cb(self, indata, frames, time_info, status):
        if self._recording:
            self._chunks.append(indata.copy())

    def stop(self) -> np.ndarray:
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._chunks:
            return np.concatenate(self._chunks, axis=0).astype(np.float64)
        return np.zeros((0, 2), dtype=np.float64)


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
