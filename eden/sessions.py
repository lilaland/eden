"""sessions.py — JSON serialization/deserialization for Eden sessions."""

from __future__ import annotations

import json
import os
from typing import Optional

from eden.state import (
    AppState, DrumTrack, SynthTrack, Loop, StepNote, Mode, InstrumentSubmode,
    default_loop, default_track_loops,
)

SESSION_VERSION = 2

_SLOT_LETTERS = "ABCDEFGH"


def slot_letter(slot: int) -> str:
    return _SLOT_LETTERS[slot] if 0 <= slot < 8 else "?"


def slot_from_letter(letter: str) -> Optional[int]:
    idx = _SLOT_LETTERS.find(letter.upper())
    return idx if idx >= 0 else None


# ── Step encoding ─────────────────────────────────────────────────────────────

def _steps_to_str(steps: tuple[StepNote, ...]) -> str:
    return "".join("1" if s.on else "0" for s in steps)


def _str_to_steps(
    s: str,
    pitches: list | None = None,
    velocities: list | None = None,
    gates: list | None = None,
) -> tuple[StepNote, ...]:
    result = []
    for i, c in enumerate(s):
        result.append(StepNote(
            on=c == "1",
            pitch=pitches[i] if pitches and i < len(pitches) else 60,
            velocity=velocities[i] if velocities and i < len(velocities) else 100,
            gate=gates[i] if gates and i < len(gates) else 0.5,
        ))
    return tuple(result)


# ── Loop ──────────────────────────────────────────────────────────────────────

def _loop_to_dict(loop: Loop) -> Optional[dict]:
    if loop.is_empty:
        return None
    d: dict = {
        "steps": _steps_to_str(loop.steps),
        "bars": loop.bars,
        "numerator": loop.numerator,
        "step_size": loop.step_size,
        "loop_count": loop.loop_count,
    }
    if loop.volume != 1.0:
        d["volume"] = loop.volume
    # Only emit per-step arrays when non-default (drums never will)
    pitches = [s.pitch for s in loop.steps]
    velocities = [s.velocity for s in loop.steps]
    gates = [s.gate for s in loop.steps]
    if any(p != 60 for p in pitches):
        d["pitches"] = pitches
    if any(v != 100 for v in velocities):
        d["velocities"] = velocities
    if any(g != 0.5 for g in gates):
        d["gates"] = gates
    return d


def _dict_to_loop(d: Optional[dict]) -> Loop:
    if d is None:
        return default_loop()
    steps = _str_to_steps(
        d["steps"],
        pitches=d.get("pitches"),
        velocities=d.get("velocities"),
        gates=d.get("gates"),
    )
    return Loop(
        steps=steps,
        bars=d.get("bars", 1),
        numerator=d.get("numerator", 4),
        step_size=d.get("step_size", 16),
        loop_count=d.get("loop_count", 0),
        volume=d.get("volume", 1.0),
    )


# ── Track ─────────────────────────────────────────────────────────────────────

def _track_to_dict(track) -> Optional[dict]:
    if track is None:
        return None
    if isinstance(track, DrumTrack):
        return {
            "type": "drum",
            "name": track.name,
            "sample_name": track.sample_name,
            "volume": track.volume,
            "loops": [_loop_to_dict(lp) for lp in track.loops],
        }
    if isinstance(track, SynthTrack):
        return {
            "type": "synth",
            "name": track.name,
            "osc_type": track.osc_type,
            "amp_attack": track.amp_attack,
            "amp_decay": track.amp_decay,
            "amp_sustain": track.amp_sustain,
            "amp_release": track.amp_release,
            "filter_cutoff": track.filter_cutoff,
            "filter_res": track.filter_res,
            "volume": track.volume,
            "max_voices": track.max_voices,
            "root_note": track.root_note,
            "scale": track.scale,
            "quantized": track.quantized,
            "aftertouch": track.aftertouch,
            "arp_on": track.arp_on,
            "arp_mode": track.arp_mode,
            "arp_rate": track.arp_rate,
            "arp_octaves": track.arp_octaves,
            "chord_on": track.chord_on,
            "chord_type": track.chord_type,
            "loops": [_loop_to_dict(lp) for lp in track.loops],
        }
    return None


def _dict_to_track(d: Optional[dict]):
    if d is None:
        return None
    t = d.get("type")
    if t == "drum":
        raw_loops = d.get("loops", [])
        loops = tuple(_dict_to_loop(l) for l in raw_loops)
        while len(loops) < 16:
            loops += (default_loop(),)
        return DrumTrack(name=d["name"], sample_name=d["sample_name"],
                         volume=d.get("volume", 1.0), loops=loops[:16])
    if t == "synth":
        raw_loops = d.get("loops", [])
        loops = tuple(_dict_to_loop(l) for l in raw_loops)
        while len(loops) < 16:
            loops += (default_loop(),)
        return SynthTrack(
            name=d["name"],
            loops=loops[:16],
            osc_type=d.get("osc_type", "saw"),
            amp_attack=d.get("amp_attack", 0.005),
            amp_decay=d.get("amp_decay", 0.1),
            amp_sustain=d.get("amp_sustain", 0.7),
            amp_release=d.get("amp_release", 0.2),
            filter_cutoff=d.get("filter_cutoff", 8000.0),
            filter_res=d.get("filter_res", 0.2),
            volume=d.get("volume", 0.8),
            max_voices=d.get("max_voices", 8),
            root_note=d.get("root_note", 60),
            scale=d.get("scale", "chromatic"),
            quantized=d.get("quantized", True),
            aftertouch=d.get("aftertouch", True),
            arp_on=d.get("arp_on", False),
            arp_mode=d.get("arp_mode", "up"),
            arp_rate=d.get("arp_rate", 16),
            arp_octaves=d.get("arp_octaves", 1),
            chord_on=d.get("chord_on", False),
            chord_type=d.get("chord_type", "major"),
        )
    return None


# ── Session ───────────────────────────────────────────────────────────────────

def state_to_session(state: AppState, name: str) -> dict:
    """Serialize the persistent parts of AppState to a session dict."""
    return {
        "version": SESSION_VERSION,
        "name": name,
        "tempo_bpm": state.tempo_bpm,
        "swing": state.swing,
        "tracks": [_track_to_dict(t) for t in state.tracks],
        "active_loops": sorted([list(pair) for pair in state.active_loops]),
        "muted_tracks": sorted(state.muted_tracks),
        "soloed_tracks": sorted(state.soloed_tracks),
    }


def session_to_state_patch(data: dict, slot: int) -> dict:
    """Return a kwargs dict for dataclasses.replace() to apply a loaded session."""
    raw_tracks = data.get("tracks", [])
    tracks = tuple(_dict_to_track(t) for t in raw_tracks)
    while len(tracks) < 16:
        tracks += (None,)
    tracks = tracks[:16]

    active_loops = frozenset(
        tuple(pair) for pair in data.get("active_loops", [])
    )
    muted = frozenset(int(i) for i in data.get("muted_tracks", []))
    soloed = frozenset(int(i) for i in data.get("soloed_tracks", []))

    return {
        "tracks": tracks,
        "tempo_bpm": float(data.get("tempo_bpm", 120.0)),
        "swing": float(data.get("swing", 0.0)),
        "active_loops": active_loops,
        "playing_loops": active_loops,
        "muted_tracks": muted,
        "soloed_tracks": soloed,
        # Reset runtime state on load
        "active_session_slot": slot,
        "playhead": 0,
        "plays_remaining": (),
        "loop_measure_offsets": (),
        "armed_tracks": (),
        "instrument_view_measure": 0,
        "instrument_active_ctrl": "",
        "new_slot_active_ctrl": "",
        "saved_armed_tracks": None,
        "is_playing": True,
    }


def load_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_file(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
