"""events.py — All Eden event types as frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


class Event:
    """Base marker class for all Eden events."""


@dataclass(frozen=True)
class PadPressed(Event):
    pad_index: int  # 0-31
    velocity: int


@dataclass(frozen=True)
class PadReleased(Event):
    pad_index: int


@dataclass(frozen=True)
class EncoderTurned(Event):
    encoder: int  # 1-9
    delta: int


@dataclass(frozen=True)
class TransportPressed(Event):
    button: str   # "PLAY" | "STOP" | "REC" | "METRO"
    pressed: bool


@dataclass(frozen=True)
class ClockTicked(Event):
    pass  # No step arg — reducer owns playhead advancement


@dataclass(frozen=True)
class ModeButtonPressed(Event):
    button: str   # "SONG" | "INST" | "EDIT" | "USER" | "BACK" | "FORWARD"
    pressed: bool


@dataclass(frozen=True)
class ShiftChanged(Event):
    held: bool


@dataclass(frozen=True)
class SoftkeyPressed(Event):
    key: int  # 0-4 (SK1=0 through SK5=4)


@dataclass(frozen=True)
class TouchbarMoved(Event):
    position: float  # 0.0 = left end, 1.0 = right end (pitchwheel -8192 → +8191)


@dataclass(frozen=True)
class ArrowPressed(Event):
    direction: str   # "LEFT" | "RIGHT"
    pressed: bool


@dataclass(frozen=True)
class MetronomePressed(Event):
    pressed: bool


@dataclass(frozen=True)
class SongSlotPressed(Event):
    slot: int    # 0-7 (A=0 … H=7)
    pressed: bool


@dataclass(frozen=True)
class SessionLoaded(Event):
    """Emitted by app layer after reading a session file; reducer applies the switch."""
    slot: int
    tracks: tuple         # tuple[Optional[Track], ...] — new session
    tempo_bpm: float
    swing: float
    active_loops: frozenset   # frozenset[tuple[int, int]]
    muted_tracks: frozenset   # frozenset[int]
    soloed_tracks: frozenset  # frozenset[int]
    immediate: bool           # True = shift (cut now), False = graceful (finish loops)


@dataclass(frozen=True)
class TapTempoPressed(Event):
    timestamp: float  # time.time() at moment of tap


@dataclass(frozen=True)
class PlusMinusPressed(Event):
    button: str   # "+" | "-"
    pressed: bool
