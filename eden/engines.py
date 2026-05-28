"""eden/engines.py — Per-track audio engines.

TrackEngine protocol + two concrete implementations:
  DrumEngine   — sample playback, one engine per drum track slot
  SynthEngine  — polyphonic subtractive synth, one engine per synth track slot

Both are called from the AudioMixer's sounddevice callback.
"""

from __future__ import annotations

import collections
import math
import sys

import numpy as np

# ── MIDI utils ────────────────────────────────────────────────────────────────

_TWO_PI = 2.0 * math.pi


def midi_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


# ── TrackEngine protocol ──────────────────────────────────────────────────────

class TrackEngine:
    """
    Interface for per-track audio engines. Structural duck-typing is fine
    in Python, but an explicit base class makes isinstance checks possible.

    All methods are called from the audio callback thread EXCEPT note_on,
    which is enqueued via a lock-free deque and drained inside fill_block.
    """

    def note_on(self, pitch: int, velocity: float, gate_samples: int, track_state) -> None:
        raise NotImplementedError

    def fill_block(self, buf: np.ndarray, n_frames: int) -> None:
        raise NotImplementedError

    def all_notes_off(self) -> None:
        raise NotImplementedError

    @property
    def is_silent(self) -> bool:
        raise NotImplementedError


# ── DrumEngine ────────────────────────────────────────────────────────────────

_MAX_DRUM_VOICES = 8


class _DrumVoice:
    __slots__ = ("data", "position", "gain")

    def __init__(self, data: np.ndarray, gain: float) -> None:
        self.data = data
        self.position = 0
        self.gain = gain

    @property
    def frames_left(self) -> int:
        return len(self.data) - self.position


class DrumEngine(TrackEngine):
    """
    Fire-and-forget sample playback. One instance per drum track slot.
    Shares a reference to the AudioMixer's sample dict so newly loaded
    samples are visible immediately without engine recreation.
    """

    def __init__(self, sample_name: str, samples: dict) -> None:
        self._sample_name = sample_name
        self._samples = samples
        self._trigger_queue: collections.deque = collections.deque(maxlen=_MAX_DRUM_VOICES * 4)
        self._voices: list[_DrumVoice] = []

    def note_on(self, pitch: int, velocity: float, gate_samples: int, track_state) -> None:
        sample = self._samples.get(self._sample_name)
        if sample is None:
            return
        self._trigger_queue.append((sample, float(np.clip(velocity, 0.0, 1.0))))

    def fill_block(self, buf: np.ndarray, n_frames: int) -> None:
        while True:
            try:
                item = self._trigger_queue.popleft()
            except IndexError:
                break
            if item is None:
                self._voices.clear()
            else:
                sample_data, gain = item
                self._voices.append(_DrumVoice(data=sample_data, gain=gain))
                while len(self._voices) > _MAX_DRUM_VOICES:
                    self._voices.pop(0)

        still_active: list[_DrumVoice] = []
        for voice in self._voices:
            if voice.frames_left <= 0:
                continue
            n = min(n_frames, voice.frames_left)
            buf[:n] += voice.data[voice.position: voice.position + n] * voice.gain
            voice.position += n
            if voice.frames_left > 0:
                still_active.append(voice)
        self._voices = still_active

    def all_notes_off(self) -> None:
        self._trigger_queue.append(None)

    @property
    def is_silent(self) -> bool:
        return len(self._voices) == 0 and len(self._trigger_queue) == 0


# ── SynthVoice ────────────────────────────────────────────────────────────────

_ENV_ATTACK  = 0
_ENV_DECAY   = 1
_ENV_SUSTAIN = 2
_ENV_RELEASE = 3
_ENV_DONE    = 4


class SynthVoice:
    """
    Single synthesizer voice:
      - Direct-formula oscillator (saw/square/sine/triangle)
      - State Variable Filter, LP mode (Simper/Cytomic TPT formulation)
      - ADSR amplitude envelope with gate countdown

    Oscillator phase is generated with numpy (vectorized); filter and envelope
    advance sample-by-sample (sequential state prevents vectorization there).

    Parameters are read from track_state at construction; uses getattr with
    defaults so voices work even while SynthTrack fields are still minimal.
    """

    __slots__ = (
        "_freq", "_sr", "_phase",
        "_gate_remaining",
        "_env_level", "_env_stage", "_env_release_from",
        "_attack_inc", "_decay_inc", "_sustain_level", "_release_samples",
        "_osc_type", "_volume",
        "_filt_a1", "_filt_a2", "_filt_a3",
        "_filt_ic1eq", "_filt_ic2eq",
    )

    def __init__(
        self,
        pitch: int,
        velocity: float,
        gate_samples: int,
        track_state,
        sample_rate: int,
    ) -> None:
        sr = sample_rate
        self._freq = midi_to_hz(pitch)
        self._sr = sr
        self._phase = 0.0

        self._gate_remaining = gate_samples

        # Envelope — read params with safe defaults for incomplete SynthTrack
        attack  = getattr(track_state, "amp_attack",  0.005)
        decay   = getattr(track_state, "amp_decay",   0.1)
        sustain = getattr(track_state, "amp_sustain",  0.7)
        release = getattr(track_state, "amp_release",  0.2)

        self._env_level        = 0.0
        self._env_stage        = _ENV_ATTACK
        self._env_release_from = 0.0
        self._attack_inc       = 1.0 / max(1, int(attack  * sr))
        self._decay_inc        = (1.0 - sustain) / max(1, int(decay * sr))
        self._sustain_level    = sustain
        self._release_samples  = max(1, int(release * sr))

        self._osc_type = getattr(track_state, "osc_type", "saw")
        volume         = getattr(track_state, "volume",   0.8)
        self._volume   = volume * float(np.clip(velocity, 0.0, 1.0))

        # SVF LP filter coefficients (Simper TPT)
        cutoff = getattr(track_state, "filter_cutoff", 8000.0)
        res    = getattr(track_state, "filter_res",    0.2)
        g  = math.tan(math.pi * min(cutoff, sr * 0.49) / sr)
        k  = 2.0 * (1.0 - min(float(res), 0.999))
        a1 = 1.0 / (1.0 + g * (g + k))
        self._filt_a1   = a1
        self._filt_a2   = g * a1
        self._filt_a3   = g * g * a1
        self._filt_ic1eq = 0.0
        self._filt_ic2eq = 0.0

    @property
    def is_done(self) -> bool:
        return self._env_stage == _ENV_DONE

    def fill_block(self, buf: np.ndarray, n_frames: int) -> None:
        # ── Oscillator (numpy-vectorized) ─────────────────────────────────────
        phase_inc = self._freq / self._sr
        raw = self._phase + np.arange(n_frames, dtype=np.float64) * phase_inc
        phases = raw % 1.0
        self._phase = float((self._phase + n_frames * phase_inc) % 1.0)

        osc_type = self._osc_type
        if osc_type == "saw":
            osc = 2.0 * phases - 1.0
        elif osc_type == "square":
            osc = np.where(phases < 0.5, 1.0, -1.0)
        elif osc_type == "sine":
            osc = np.sin(_TWO_PI * phases)
        else:  # triangle
            osc = 2.0 * np.abs(2.0 * phases - 1.0) - 1.0

        # ── Filter + envelope (sequential) ───────────────────────────────────
        a1, a2, a3 = self._filt_a1, self._filt_a2, self._filt_a3
        ic1, ic2   = self._filt_ic1eq, self._filt_ic2eq

        env        = self._env_level
        env_stage  = self._env_stage
        env_rf     = self._env_release_from
        gate       = self._gate_remaining

        attack_inc = self._attack_inc
        decay_inc  = self._decay_inc
        sustain    = self._sustain_level
        rel_samp   = self._release_samples
        volume     = self._volume

        for i in range(n_frames):
            # Gate countdown → trigger release
            if gate > 0:
                gate -= 1
                if gate == 0 and env_stage < _ENV_RELEASE:
                    env_rf    = env
                    env_stage = _ENV_RELEASE

            # SVF low-pass (Simper TPT)
            x  = osc[i]
            v3 = x  - ic2
            v1 = a1 * ic1 + a2 * v3
            v2 = ic2 + a2 * ic1 + a3 * v3
            ic1 = 2.0 * v1 - ic1
            ic2 = 2.0 * v2 - ic2
            x  = v2

            # ADSR
            if env_stage == _ENV_ATTACK:
                env += attack_inc
                if env >= 1.0:
                    env       = 1.0
                    env_stage = _ENV_DECAY
            elif env_stage == _ENV_DECAY:
                env -= decay_inc
                if env <= sustain:
                    env       = sustain
                    env_stage = _ENV_SUSTAIN
            elif env_stage == _ENV_RELEASE:
                env -= env_rf / rel_samp
                if env <= 0.0:
                    env       = 0.0
                    env_stage = _ENV_DONE
            # _ENV_SUSTAIN: held, no change

            s = x * env * volume
            buf[i, 0] += s
            buf[i, 1] += s

        # Write back sequential state
        self._filt_ic1eq       = ic1
        self._filt_ic2eq       = ic2
        self._env_level        = env
        self._env_stage        = env_stage
        self._env_release_from = env_rf
        self._gate_remaining   = gate


# ── SynthEngine ───────────────────────────────────────────────────────────────

_MAX_SYNTH_VOICES = 8


class SynthEngine(TrackEngine):
    """
    Polyphonic synthesizer engine. One instance per synth track slot.
    Voice count is capped by track_state.max_voices (default 8).
    Stealing policy: prefer voices already in release; fallback to oldest.
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        self._sr = sample_rate
        self._voices: list[SynthVoice] = []
        self._trigger_queue: collections.deque = collections.deque(
            maxlen=_MAX_SYNTH_VOICES * 4
        )

    def note_on(self, pitch: int, velocity: float, gate_samples: int, track_state) -> None:
        max_v = getattr(track_state, "max_voices", _MAX_SYNTH_VOICES)
        self._trigger_queue.append((pitch, velocity, gate_samples, track_state, max_v))

    def fill_block(self, buf: np.ndarray, n_frames: int) -> None:
        # Drain trigger queue
        while True:
            try:
                item = self._trigger_queue.popleft()
            except IndexError:
                break
            if item is None:
                self._voices.clear()
                continue
            pitch, velocity, gate_samples, track_state, max_v = item
            # Steal if at cap: prefer releasing voices, then oldest
            while len(self._voices) >= max_v:
                releasing = next(
                    (j for j, v in enumerate(self._voices) if v._env_stage >= _ENV_RELEASE),
                    None,
                )
                if releasing is not None:
                    self._voices.pop(releasing)
                else:
                    self._voices.pop(0)
            self._voices.append(
                SynthVoice(pitch, velocity, gate_samples, track_state, self._sr)
            )

        # Mix active voices
        alive: list[SynthVoice] = []
        for voice in self._voices:
            if voice.is_done:
                continue
            voice.fill_block(buf, n_frames)
            alive.append(voice)
        self._voices = alive

    def all_notes_off(self) -> None:
        self._trigger_queue.append(None)

    @property
    def is_silent(self) -> bool:
        return len(self._voices) == 0 and len(self._trigger_queue) == 0
