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
_ONSET_FADE = 8  # linear ramp-up over first 8 frames (~0.18 ms) — click protection only


class _DrumVoice:
    __slots__ = ("data", "position", "gain", "fade_remaining")

    def __init__(self, data: np.ndarray, gain: float) -> None:
        self.data = data
        self.position = 0
        self.gain = gain
        self.fade_remaining = _ONSET_FADE

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
        vol = getattr(track_state, "volume", 1.0) if track_state is not None else 1.0
        self._trigger_queue.append((sample, float(np.clip(velocity * vol, 0.0, 1.0))))

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
            chunk = voice.data[voice.position: voice.position + n] * voice.gain
            if voice.fade_remaining > 0:
                fade_n = min(n, voice.fade_remaining)
                start = _ONSET_FADE - voice.fade_remaining
                ramp = np.linspace(start / _ONSET_FADE, (start + fade_n) / _ONSET_FADE, fade_n)
                chunk = chunk.copy()
                chunk[:fade_n] *= ramp[:, np.newaxis] if chunk.ndim == 2 else ramp
                voice.fade_remaining -= fade_n
            buf[:n] += chunk
            voice.position += n
            if voice.frames_left > 0:
                still_active.append(voice)
        self._voices = still_active

    def all_notes_off(self) -> None:
        self._trigger_queue.append(None)

    @property
    def is_silent(self) -> bool:
        return len(self._voices) == 0 and len(self._trigger_queue) == 0


# ── SampleEngine ─────────────────────────────────────────────────────────────

_MAX_SAMPLE_VOICES = 16


class _SampleVoice:
    __slots__ = ('data', 'pos', 'gain', 'pan_l', 'pan_r', 'pitch_rate',
                 'attack_inc', 'release_dec', 'env', 'attacking',
                 'gate_remaining', 'releasing', 'release_from',
                 'play_mode', 'done', 'abs_start', 'abs_end')

    def __init__(self, data, gain, pan_l, pan_r, pitch_rate,
                 attack_samples, release_samples, gate_samples, play_mode,
                 abs_start=0.0, abs_end=1.0):
        self.data = data
        self.pos = 0.0
        self.gain = gain
        self.pan_l = pan_l
        self.pan_r = pan_r
        self.pitch_rate = pitch_rate
        self.attack_inc = 1.0 / max(1, attack_samples)
        self.release_dec = 1.0 / max(1, release_samples)
        self.env = 0.0
        self.attacking = attack_samples > 0
        self.gate_remaining = gate_samples if play_mode != "oneshot" else 0
        self.releasing = False
        self.release_from = 1.0
        self.play_mode = play_mode
        self.done = False
        self.abs_start = abs_start
        self.abs_end = abs_end

    def note_off(self):
        if not self.releasing:
            self.releasing = True
            self.release_from = self.env

    def fill(self, buf, n_frames):
        """Render n_frames of this voice into buf (additive).

        Fast paths (numpy-vectorized) cover the two states that dominate a
        voice's lifetime — flat sustain (env == 1) and a linear release ramp —
        where there are no per-sample feedback transitions. Attack ramps and the
        gate→release boundary fall through to the per-sample loop (_fill_slow),
        which remains the reference implementation for those blocks.
        """
        if self.done:
            return
        # Flat sustain: not attacking, not releasing, and the gate won't expire
        # within this block (so env stays a constant 1.0 the whole time).
        if (not self.attacking and not self.releasing
                and (self.gate_remaining == 0 or self.gate_remaining > n_frames)):
            self._fill_vec(buf, n_frames, env_release=False)
            return
        # Linear release ramp: already releasing and past the attack phase.
        if self.releasing and not self.attacking:
            self._fill_vec(buf, n_frames, env_release=True)
            return
        self._fill_slow(buf, n_frames)

    def _fill_vec(self, buf, n_frames, env_release):
        """Vectorized render for constant-sustain or linear-release blocks."""
        data = self.data
        data_len = len(data)
        rate = self.pitch_rate
        pos0 = self.pos
        i = np.arange(n_frames)
        positions = pos0 + i * rate
        idx = positions.astype(np.int64)
        # idx is non-decreasing (rate > 0); first index needing data[idx+1] OOB.
        k_src = int(np.searchsorted(idx, data_len - 1, side="left"))

        if env_release:
            step = self.release_from * self.release_dec
            env_used = self.env - (i + 1) * step  # post-update env per sample
            below = env_used <= 0.0
            k_env = int(np.argmax(below)) if below.any() else n_frames
            k = min(k_src, k_env)
        else:
            env_used = None
            k_env = n_frames
            k = k_src

        if k > 0:
            si = idx[:k]
            fr = (positions[:k] - si)[:, np.newaxis]
            seg = data[si] * (1.0 - fr) + data[si + 1] * fr
            if env_release:
                g = self.gain * env_used[:k]
                buf[:k, 0] += seg[:, 0] * g * self.pan_l
                buf[:k, 1] += seg[:, 1] * g * self.pan_r
            else:
                buf[:k, 0] += seg[:, 0] * (self.gain * self.pan_l)
                buf[:k, 1] += seg[:, 1] * (self.gain * self.pan_r)

        # Envelope reaching zero is checked before source exhaustion in the
        # per-sample loop, so it wins ties here too.
        if env_release and k_env <= k_src and k_env < n_frames:
            self.env = 0.0
            self.done = True
            self.pos = pos0 + k * rate
            return
        if k_src < n_frames:
            self.done = True
            self.pos = pos0 + k * rate
            return

        # Whole block consumed.
        self.pos = pos0 + n_frames * rate
        if env_release:
            self.env = self.env - n_frames * (self.release_from * self.release_dec)
        else:
            self.env = 1.0
        if self.gate_remaining > 0:
            self.gate_remaining = max(0, self.gate_remaining - n_frames)

    def _fill_slow(self, buf, n_frames):
        """Sample-by-sample: advance pos by pitch_rate, interpolate, apply envelope and pan."""
        i = 0
        data = self.data
        data_len = len(data)
        while i < n_frames and not self.done:
            # Gate countdown
            if self.gate_remaining > 0:
                self.gate_remaining -= 1
                if self.gate_remaining == 0 and not self.releasing:
                    self.releasing = True
                    self.release_from = self.env
            # Envelope
            if self.attacking:
                self.env += self.attack_inc
                if self.env >= 1.0:
                    self.env = 1.0
                    self.attacking = False
            elif self.releasing:
                self.env -= self.release_from * self.release_dec
                if self.env <= 0.0:
                    self.env = 0.0
                    self.done = True
                    break
            else:
                self.env = 1.0
            # Linear interpolation at float position
            idx = int(self.pos)
            if idx >= data_len - 1:
                self.done = True
                break
            frac = self.pos - idx
            s0 = data[idx]
            s1 = data[idx + 1]
            s_l = s0[0] * (1.0 - frac) + s1[0] * frac
            s_r = s0[1] * (1.0 - frac) + s1[1] * frac
            env_gain = self.gain * self.env
            buf[i, 0] += s_l * env_gain * self.pan_l
            buf[i, 1] += s_r * env_gain * self.pan_r
            self.pos += self.pitch_rate
            i += 1


class SampleEngine(TrackEngine):
    """
    Chop-based sample playback engine with A/R envelope, pan, pitch-rate, and
    play_mode support (oneshot / gate / legato).

    Each note_on call uses pitch as a chop index. In SAMPLE_KEYS mode, the
    caller (app.py) passes a modified track_state with an adjusted ChopPoint.tune
    for the desired semitone transposition.

    Shares the AudioMixer._samples dict so newly loaded samples are visible
    without engine recreation.
    """

    def __init__(self, sample_key: str, samples: dict, sample_rate: int = 44100) -> None:
        self._sample_key = sample_key
        self._samples = samples
        self._sr = sample_rate
        self._trigger_queue: collections.deque = collections.deque(maxlen=_MAX_SAMPLE_VOICES * 4)
        self._voices: list[_SampleVoice] = []
        self._active: dict[int, _SampleVoice] = {}  # chop_idx → voice (for gate/legato)

    def note_on(self, pitch: int, velocity: float, gate_samples: int, track_state) -> None:
        sample = self._samples.get(self._sample_key)
        if sample is None:
            return

        vol = getattr(track_state, 'volume', 1.0) or 1.0
        pan = getattr(track_state, 'pan', 0.0)
        pan_l = min(1.0, 1.0 - pan) * vol
        pan_r = min(1.0, 1.0 + pan) * vol

        gain = float(np.clip(velocity, 0.0, 1.0))
        play_mode = getattr(track_state, 'play_mode', 'oneshot')
        attack = getattr(track_state, 'amp_attack', 0.0)
        release = getattr(track_state, 'amp_release', 0.05)
        trim_start = getattr(track_state, 'trim_start', 0.0)
        trim_end = getattr(track_state, 'trim_end', 1.0)

        chops = getattr(track_state, 'chops', ())
        n = len(sample)
        t_start = int(trim_start * n)
        t_end = int(trim_end * n)
        effective = sample[t_start:t_end]

        sample_mode = getattr(track_state, 'sample_mode', 'chopped')
        if sample_mode == 'oneshot':
            slice_data = effective
            is_pitched = getattr(track_state, 'pitched', False)
            root_note = getattr(track_state, 'root_note', 60)
            tune = float(pitch - root_note) if is_pitched else 0.0
            reverse = False
            abs_start = trim_start
            abs_end = trim_end
        elif chops and 0 <= pitch < len(chops):
            chop = chops[pitch]
            m = len(effective)
            c_start = int(chop.start_offset * m)
            c_end = int(chop.end_offset * m)
            slice_data = effective[c_start:c_end]
            tune = getattr(chop, 'tune', 0.0)
            reverse = getattr(chop, 'reverse', False)
            trim_span = trim_end - trim_start
            abs_start = trim_start + chop.start_offset * trim_span
            abs_end   = trim_start + chop.end_offset   * trim_span
        else:
            slice_data = effective
            tune = 0.0
            reverse = False
            abs_start = trim_start
            abs_end = trim_end

        if reverse:
            slice_data = slice_data[::-1]
        if len(slice_data) == 0:
            return

        pitch_rate = 2.0 ** (tune / 12.0)
        attack_samps = int(attack * self._sr)
        release_samps = max(1, int(release * self._sr))

        voice = _SampleVoice(
            slice_data, gain, pan_l, pan_r, pitch_rate,
            attack_samps, release_samps, gate_samples, play_mode,
            abs_start=abs_start, abs_end=abs_end,
        )
        self._trigger_queue.append(('on', pitch, voice, play_mode))

    def note_off(self, chop_idx: int) -> None:
        """Trigger release for the active voice at chop_idx (gate/legato modes)."""
        self._trigger_queue.append(('off', chop_idx))

    def fill_block(self, buf: np.ndarray, n_frames: int) -> None:
        # Drain trigger queue
        while True:
            try:
                item = self._trigger_queue.popleft()
            except IndexError:
                break
            if item is None:
                # all_notes_off sentinel
                for v in self._voices:
                    v.note_off()
                self._active.clear()
                continue
            if not isinstance(item, tuple):
                continue
            kind = item[0]
            if kind == 'on':
                _, chop_idx, voice, pm = item
                if pm == 'legato':
                    # Mono: release all existing voices
                    for v in self._voices:
                        v.note_off()
                    self._active.clear()
                    self._voices.append(voice)
                    self._active[chop_idx] = voice
                elif pm == 'gate':
                    self._voices.append(voice)
                    self._active[chop_idx] = voice
                else:  # oneshot
                    self._voices.append(voice)
                    if len(self._voices) > _MAX_SAMPLE_VOICES:
                        self._voices.pop(0)
            elif kind == 'off':
                chop_idx = item[1]
                v = self._active.get(chop_idx)
                if v is not None:
                    v.note_off()
                    self._active.pop(chop_idx, None)

        still_active: list[_SampleVoice] = []
        for voice in self._voices:
            if voice.done:
                # Remove from active dict if it's this voice
                for k, av in list(self._active.items()):
                    if av is voice:
                        del self._active[k]
                continue
            voice.fill(buf, n_frames)
            if not voice.done:
                still_active.append(voice)
            else:
                for k, av in list(self._active.items()):
                    if av is voice:
                        del self._active[k]
        self._voices = still_active

    def all_notes_off(self) -> None:
        self._trigger_queue.append(None)

    @property
    def is_silent(self) -> bool:
        return len(self._voices) == 0 and len(self._trigger_queue) == 0

    @property
    def playback_cursor(self) -> float:
        """0.0–1.0 position in full sample of newest active voice, or -1.0 if silent."""
        for v in reversed(self._voices):
            if not v.done:
                ratio = v.pos / max(1, len(v.data) - 1)
                return v.abs_start + ratio * (v.abs_end - v.abs_start)
        return -1.0


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
        "_vel_floor", "_aftertouch",  # _vel_floor = initial amplitude; _aftertouch = smoothed gain
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

        self._osc_type  = getattr(track_state, "osc_type", "saw")
        vel_gain        = float(np.clip(velocity, 0.0, 1.0))
        self._volume    = getattr(track_state, "volume", 0.8)
        self._vel_floor = vel_gain   # D0 can only raise amplitude above this
        self._aftertouch = vel_gain  # current smoothed amplitude (starts at vel)

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
        at_gain    = self._aftertouch  # snapshot for this block; engine updates between blocks

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

            s = x * env * volume * at_gain
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

# Aftertouch slew rates (per audio block ≈ 256/44100 s ≈ 5.8 ms)
# Attack ~40 ms (follow pressure rises quickly), release ~250 ms (prevent sudden drops)
_AT_ATTACK  = 0.15
_AT_RELEASE = 0.025


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
        self._aftertouch_target: float = 0.0  # 0.0 = no pressure yet (inactive)

    def note_on(self, pitch: int, velocity: float, gate_samples: int, track_state) -> None:
        max_v = getattr(track_state, "max_voices", _MAX_SYNTH_VOICES)
        self._trigger_queue.append((pitch, velocity, gate_samples, track_state, max_v))

    def note_off(self, pitch: int) -> None:
        """Trigger release for all voices at the given pitch."""
        self._trigger_queue.append(("off", pitch))

    def release_all(self) -> None:
        """Send every currently-sounding voice into its release phase.

        Used by retrigger mode: queued before a new note/chord so prior
        voices fade out while the incoming notes layer in together.
        """
        self._trigger_queue.append(("rel", None))

    def set_aftertouch(self, value: float) -> None:
        """Update channel pressure gain (0.0-1.0) for all active voices."""
        self._trigger_queue.append(("at", value))

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
            if isinstance(item, tuple) and len(item) == 2:
                kind, payload = item
                if kind == "off":
                    for v in self._voices:
                        if v._freq == midi_to_hz(payload) and v._gate_remaining > 1:
                            v._gate_remaining = 1
                elif kind == "rel":
                    for v in self._voices:
                        if v._gate_remaining > 1:
                            v._gate_remaining = 1
                elif kind == "at":
                    self._aftertouch_target = float(payload)
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

        # Smooth aftertouch toward target per-voice (each voice has its own vel_floor)
        at_target = self._aftertouch_target
        for v in self._voices:
            effective = max(v._vel_floor, at_target)  # never drops below initial velocity
            curr = v._aftertouch
            coeff = _AT_ATTACK if effective > curr else _AT_RELEASE
            v._aftertouch = curr + coeff * (effective - curr)

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
