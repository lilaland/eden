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
