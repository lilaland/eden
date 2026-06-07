"""sessions.py — JSON serialization/deserialization for Eden sessions."""

from __future__ import annotations

import json
import os
from typing import Optional

from eden.state import (
    AppState, DrumTrack, SynthTrack, SampleTrack, ChopPoint, Scene, Loop, StepNote,
    NoteEvent, Mode, InstrumentSubmode,
    FXChain, default_loop, default_track_loops,
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


def _parse_pitches_entry(entry) -> tuple[int, ...]:
    """Convert a session pitches entry to a tuple. Handles old int and new list format."""
    if isinstance(entry, list):
        return tuple(entry) if entry else (60,)
    return (int(entry),)  # old format: single int per step


def _str_to_steps(
    s: str,
    pitches: list | None = None,
    velocities: list | None = None,
    gates: list | None = None,
    probabilities: list | None = None,
    lock_cutoffs: list | None = None,
) -> tuple[StepNote, ...]:
    result = []
    for i, c in enumerate(s):
        if pitches and i < len(pitches):
            step_pitches = _parse_pitches_entry(pitches[i])
        else:
            step_pitches = (60,)
        probability = 100
        if probabilities and i < len(probabilities) and probabilities[i] is not None:
            probability = int(probabilities[i])
        lock_cutoff = None
        if lock_cutoffs and i < len(lock_cutoffs) and lock_cutoffs[i] is not None:
            lock_cutoff = float(lock_cutoffs[i])
        result.append(StepNote(
            on=c == "1",
            pitches=step_pitches,
            velocity=velocities[i] if velocities and i < len(velocities) else 100,
            gate=gates[i] if gates and i < len(gates) else 0.5,
            probability=probability,
            lock_cutoff=lock_cutoff,
        ))
    return tuple(result)


def _fxchain_to_dict(chain: FXChain) -> dict:
    return {"page1": list(chain.page1), "page2": list(chain.page2)}


def _dict_to_fxchain(d) -> FXChain:
    if d is None:
        return FXChain()
    return FXChain(
        page1=tuple(float(v) for v in d.get("page1", (0.5, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0))),
        page2=tuple(float(v) for v in d.get("page2", (0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0))),
    )


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
    step_pitches = [list(s.pitches) for s in loop.steps]
    velocities = [s.velocity for s in loop.steps]
    gates = [s.gate for s in loop.steps]
    if any(p != [60] for p in step_pitches):
        d["pitches"] = step_pitches
    if any(v != 100 for v in velocities):
        d["velocities"] = velocities
    if any(g != 0.5 for g in gates):
        d["gates"] = gates
    # Persist per-step probability if non-default
    probs = [s.probability for s in loop.steps]
    if any(p != 100 for p in probs):
        d["probabilities"] = probs
    # Persist per-step lock_cutoff if set
    locks = [s.lock_cutoff for s in loop.steps]
    if any(lk is not None for lk in locks):
        d["lock_cutoffs"] = locks
    # Arp/chord — only emit when non-default
    if loop.arp_on:
        d["arp_on"] = loop.arp_on
        d["arp_mode"] = loop.arp_mode
        d["arp_rate"] = loop.arp_rate
        d["arp_octaves"] = loop.arp_octaves
    if loop.chord_on:
        d["chord_on"] = loop.chord_on
        d["chord_type"] = loop.chord_type
    # Free events
    if loop.free_events:
        d["free_events"] = [
            {"tick": e.tick, "pitch": e.pitch, "velocity": e.velocity,
             "gate": e.gate, "aftertouch": e.aftertouch}
            for e in loop.free_events
        ]
    return d


def _dict_to_loop(d: Optional[dict], track_arp: Optional[dict] = None) -> Loop:
    """Deserialize a loop dict. track_arp is a dict with legacy per-track arp/chord fields."""
    if d is None:
        return default_loop()
    steps = _str_to_steps(
        d["steps"],
        pitches=d.get("pitches"),
        velocities=d.get("velocities"),
        gates=d.get("gates"),
        probabilities=d.get("probabilities"),
        lock_cutoffs=d.get("lock_cutoffs"),
    )
    # Migrate legacy track-level arp/chord to loop if this loop has no override
    arp_src = d if "arp_on" in d else (track_arp or {})
    chord_src = d if "chord_on" in d else (track_arp or {})
    raw_events = d.get("free_events", [])
    free_events = tuple(
        NoteEvent(
            tick=e["tick"], pitch=e["pitch"], velocity=e["velocity"],
            gate=e["gate"], aftertouch=e.get("aftertouch", 0.0),
        )
        for e in raw_events
    )
    return Loop(
        steps=steps,
        bars=d.get("bars", 1),
        numerator=d.get("numerator", 4),
        step_size=d.get("step_size", 16),
        loop_count=d.get("loop_count", 0),
        volume=d.get("volume", 1.0),
        arp_on=bool(arp_src.get("arp_on", False)),
        arp_mode=str(arp_src.get("arp_mode", "up")),
        arp_rate=int(arp_src.get("arp_rate", 16)),
        arp_octaves=int(arp_src.get("arp_octaves", 1)),
        chord_on=bool(chord_src.get("chord_on", False)),
        chord_type=str(chord_src.get("chord_type", "major")),
        free_events=free_events,
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
            "fx": _fxchain_to_dict(track.fx),
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
            "fx": _fxchain_to_dict(track.fx),
            "loops": [_loop_to_dict(lp) for lp in track.loops],
        }
    if isinstance(track, SampleTrack):
        return {
            "type": "sample",
            "name": track.name,
            "sample_key": track.sample_key,
            "play_mode": track.play_mode,
            "trim_start": track.trim_start,
            "trim_end": track.trim_end,
            "amp_attack": track.amp_attack,
            "amp_release": track.amp_release,
            "pan": track.pan,
            "mute_group": track.mute_group,
            "volume": track.volume,
            "keep_empty": track.keep_empty,
            "stretch_mode": track.stretch_mode,
            "stretch_bars": track.stretch_bars,
            "fx": _fxchain_to_dict(track.fx),
            "chops": [
                {
                    "start_offset": c.start_offset,
                    "end_offset": c.end_offset,
                    "name": c.name,
                    "tune": c.tune,
                    "reverse": c.reverse,
                }
                for c in track.chops
            ],
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
                         volume=d.get("volume", 1.0), loops=loops[:16],
                         fx=_dict_to_fxchain(d.get("fx")))
    if t == "synth":
        # Legacy: arp/chord may have been stored at track level; migrate to loops
        legacy_arp = {k: d[k] for k in ("arp_on", "arp_mode", "arp_rate", "arp_octaves",
                                          "chord_on", "chord_type") if k in d}
        raw_loops = d.get("loops", [])
        loops = tuple(_dict_to_loop(l, track_arp=legacy_arp) for l in raw_loops)
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
            fx=_dict_to_fxchain(d.get("fx")),
        )
    if t == "sample":
        raw_loops = d.get("loops", [])
        loops = tuple(_dict_to_loop(l) for l in raw_loops)
        while len(loops) < 16:
            loops += (default_loop(),)
        chops = tuple(
            ChopPoint(
                start_offset=c["start_offset"],
                end_offset=c["end_offset"],
                name=c.get("name", ""),
                tune=float(c.get("tune", 0.0)),
                reverse=bool(c.get("reverse", False)),
            )
            for c in d.get("chops", [])
        )
        # Support legacy "one_shot" field: if play_mode not set but one_shot is,
        # infer play_mode from it.
        if "play_mode" not in d and "one_shot" in d:
            play_mode = "oneshot" if d["one_shot"] else "gate"
        else:
            play_mode = d.get("play_mode", "oneshot")
        return SampleTrack(
            name=d["name"],
            sample_key=d.get("sample_key", ""),
            loops=loops[:16],
            chops=chops,
            play_mode=play_mode,
            trim_start=float(d.get("trim_start", 0.0)),
            trim_end=float(d.get("trim_end", 1.0)),
            amp_attack=float(d.get("amp_attack", 0.0)),
            amp_release=float(d.get("amp_release", 0.05)),
            pan=float(d.get("pan", 0.0)),
            mute_group=int(d.get("mute_group", 0)),
            volume=float(d.get("volume", 1.0)),
            keep_empty=bool(d.get("keep_empty", False)),
            stretch_mode=d.get("stretch_mode", "off"),
            stretch_bars=int(d.get("stretch_bars", 1)),
            fx=_dict_to_fxchain(d.get("fx")),
        )
    return None


# ── Scene ─────────────────────────────────────────────────────────────────────

def _load_scenes(raw: list) -> tuple:
    scenes = []
    for s in raw:
        if s is None:
            scenes.append(None)
        else:
            raw_tracks = s.get("tracks", [])
            tracks = tuple(_dict_to_track(t) for t in raw_tracks)
            while len(tracks) < 16:
                tracks += (None,)
            scenes.append(Scene(
                tracks=tracks[:16],
                tempo_bpm=float(s.get("tempo_bpm", 120.0)),
                swing=float(s.get("swing", 0.0)),
            ))
    while len(scenes) < 8:
        scenes.append(None)
    return tuple(scenes[:8])


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
        "global_fx": _fxchain_to_dict(state.global_fx),
        "scenes": [
            {
                "tracks": [_track_to_dict(t) for t in sc.tracks],
                "tempo_bpm": sc.tempo_bpm,
                "swing": sc.swing,
            }
            if sc is not None else None
            for sc in state.scenes
        ],
        "active_scene": state.active_scene,
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
        "global_fx": _dict_to_fxchain(data.get("global_fx")),
        "scenes": _load_scenes(data.get("scenes", [])),
        "active_scene": int(data.get("active_scene", 0)),
    }


def load_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_file(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
