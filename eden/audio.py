"""
eden/audio.py — Sample playback engine for Eden jambox.

Expected sample names in the samples/ directory:
    kick            — kick drum (kick.wav)
    snare           — snare drum (snare.wav)
    hihat_closed    — closed hi-hat (hihat_closed.wav)
    hihat_open      — open hi-hat (hihat_open.wav)

Drop corresponding .wav files into the samples/ directory and they will be
loaded automatically by SamplePlayer.
"""

from __future__ import annotations

import os
import sys
import time
import collections
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_VOICES = 8
DEFAULT_SAMPLE_RATE = 44100
BLOCK_SIZE = 256  # frames per callback — keeps latency low (~5.8 ms @ 44100)


# ---------------------------------------------------------------------------
# Internal voice state
# ---------------------------------------------------------------------------

@dataclass
class _Voice:
    """Represents one playing instance of a sample."""
    data: np.ndarray        # float32, shape (frames, channels)
    position: int = 0
    gain: float = 1.0
    active: bool = True

    @property
    def frames_left(self) -> int:
        return len(self.data) - self.position


# ---------------------------------------------------------------------------
# SamplePlayer
# ---------------------------------------------------------------------------

class SamplePlayer:
    """
    Low-latency sample player backed by sounddevice in callback mode.

    Samples are pre-loaded into float32 numpy arrays at startup.
    Voice triggering is lock-free: a collections.deque is used as a
    single-producer / single-consumer queue between trigger() (any thread)
    and the audio callback (sounddevice thread).
    """

    def __init__(self, sample_dir: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._samples: Dict[str, np.ndarray] = {}

        # Lock-free trigger queue: trigger() appends, callback consumes.
        # Bounding at MAX_VOICES * 4 prevents unbounded growth if nobody
        # is consuming (e.g. stream not started yet).
        self._trigger_queue: collections.deque = collections.deque(maxlen=MAX_VOICES * 4)

        # Active voices — only touched inside the audio callback.
        self._voices: list[_Voice] = []

        # Pre-allocated mix buffer — reused every callback, never heap-allocated
        # inside the hot path.
        self._mix_buf = np.zeros((BLOCK_SIZE, 2), dtype=np.float32)

        # Load all .wav files found in sample_dir.
        if os.path.isdir(sample_dir):
            for fname in os.listdir(sample_dir):
                if fname.lower().endswith(".wav"):
                    name = os.path.splitext(fname)[0]
                    try:
                        self.load(name, os.path.join(sample_dir, fname))
                    except Exception as exc:
                        print(f"[audio] warning: could not load {fname}: {exc}", file=sys.stderr)

        # Open the output stream.
        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=2,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
        )
        self._stream.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, name: str, path: str) -> None:
        """Load (or reload) a single sample by name from a WAV file."""
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        if sr != self._sample_rate:
            # Simple nearest-neighbour resample — good enough for drums;
            # replace with resampy/librosa if quality matters later.
            ratio = self._sample_rate / sr
            new_len = int(len(data) * ratio)
            indices = (np.arange(new_len) / ratio).astype(np.int32)
            indices = np.clip(indices, 0, len(data) - 1)
            data = data[indices]

        # Normalise to stereo
        if data.shape[1] == 1:
            data = np.hstack([data, data])
        elif data.shape[1] > 2:
            data = data[:, :2]

        self._samples[name] = data

    def trigger(self, name: str, velocity: float = 1.0) -> None:
        """
        Trigger a sample by name.

        Thread-safe and lock-free: appends a (name, gain) tuple to a deque.
        The audio callback drains this deque and spawns voices.
        """
        sample = self._samples.get(name)
        if sample is None:
            print(f"[audio] unknown sample: {name!r}", file=sys.stderr)
            return
        gain = float(np.clip(velocity, 0.0, 1.0))
        self._trigger_queue.append((sample, gain))

    def stop_all(self) -> None:
        """Silence all currently playing voices on the next callback."""
        # Append a sentinel; callback checks for it.
        self._trigger_queue.append(None)

    def close(self) -> None:
        """Stop the audio stream and release resources."""
        self._stream.stop()
        self._stream.close()

    # ------------------------------------------------------------------
    # Audio callback (runs on the sounddevice audio thread)
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

        # Drain pending triggers / stop-all sentinels.
        while True:
            try:
                item = self._trigger_queue.popleft()
            except IndexError:
                break
            if item is None:
                # stop_all sentinel
                self._voices.clear()
            else:
                sample_data, gain = item
                voice = _Voice(data=sample_data, gain=gain)
                self._voices.append(voice)
                # Drop oldest voice if we exceed MAX_VOICES.
                while len(self._voices) > MAX_VOICES:
                    self._voices.pop(0)

        # Mix active voices into pre-allocated buffer (reuse self._mix_buf).
        mix = self._mix_buf
        mix[:frames] = 0.0

        still_active: list[_Voice] = []
        for voice in self._voices:
            if not voice.active or voice.frames_left <= 0:
                continue
            n = min(frames, voice.frames_left)
            mix[:n] += voice.data[voice.position: voice.position + n] * voice.gain
            voice.position += n
            if voice.frames_left > 0:
                still_active.append(voice)
            # else: voice exhausted, drop it

        self._voices = still_active

        # Soft clip to prevent digital distortion when many voices overlap.
        np.clip(mix[:frames], -1.0, 1.0, out=mix[:frames])
        outdata[:] = mix[:frames]


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
    player = SamplePlayer(sample_dir=sample_dir)

    # Also ensure it's registered under a predictable name.
    name = os.path.splitext(os.path.basename(wav_path))[0]
    player.load(name, wav_path)

    print(f"Triggering sample '{name}' ...")
    player.trigger(name, velocity=1.0)

    # Wait long enough for the longest typical drum sample (~3 s).
    time.sleep(3.0)
    player.close()
    print("Done.")
