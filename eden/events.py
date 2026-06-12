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
    hold_seconds: float = 0.0  # filled by app layer for FREE piano mode


@dataclass(frozen=True)
class EncoderTurned(Event):
    encoder: int  # 1-9
    delta: int


@dataclass(frozen=True)
class TransportPressed(Event):
    button: str   # "PLAY" | "STOP" | "REC" | "METRO"
    pressed: bool


@dataclass(frozen=True)
class InstrumentUndo(Event):
    pass  # Undo last recording action in INSTRUMENT mode


@dataclass(frozen=True)
class InstrumentReset(Event):
    pass  # Reset selected loop to empty 1-bar default


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


@dataclass(frozen=True)
class AftertouchChanged(Event):
    value: int  # 0-127 channel pressure from hardware


@dataclass(frozen=True)
class SetChops(Event):
    """Set chop points on a SampleTrack from the web UI."""
    track_idx: int
    chops: tuple  # tuple[ChopPoint, ...]


@dataclass(frozen=True)
class WebSelectCell(Event):
    """Select a track+loop cell from the web session view."""
    track: int  # 0-15
    loop: int   # 0-15


@dataclass(frozen=True)
class SampleRecordStart(Event):
    track_idx: int   # SampleTrack to record into


@dataclass(frozen=True)
class SampleRecordStop(Event):
    track_idx: int
    new_key: str     # key under which the recorded audio was saved


@dataclass(frozen=True)
class AutoChop(Event):
    track_idx: int
    n_slices: int    # target slice count (4, 8, 16)
    boundaries: tuple  # tuple[float, ...] — already-computed onset boundaries


@dataclass(frozen=True)
class SetTrim(Event):
    track_idx: int
    trim_start: float
    trim_end: float


@dataclass(frozen=True)
class NormalizeAction(Event):
    track_idx: int


@dataclass(frozen=True)
class LoadSample(Event):
    """Assign a sample (by key) to a track's sample slot.

    track_type is used only when the target slot is empty:
      "drum"   → create a DrumTrack
      "sample" → create a SampleTrack (default)
    sample_mode / pitched are forwarded to the new SampleTrack when slot is empty.
    """
    track_idx: int
    sample_key: str
    track_type: str = "sample"
    sample_mode: str = "chopped"   # "oneshot" | "chopped"
    pitched: bool = False


@dataclass(frozen=True)
class SetAvailableSamples(Event):
    """Update the available sample pool (from web Sample Manager)."""
    keys: tuple  # tuple[str, ...]


@dataclass(frozen=True)
class WebDemoSample(Event):
    """Trigger a short audio preview for a catalog entry from the web library."""
    sample_key: str
    track_type: str = "sample"  # "drum" | "sample"


@dataclass(frozen=True)
class RemoveTrack(Event):
    """Remove a track from the session (set slot to None)."""
    track_idx: int


@dataclass(frozen=True)
class TapChopMark(Event):
    """One tap during SAMPLE_TAP_CHOP mode; app.py intercepts PadPressed to inject timestamp."""
    timestamp: float
    pad_index: int


@dataclass(frozen=True)
class CopyChop(Event):
    """Copy a chop to the track's clipboard for later paste."""
    track_idx: int
    chop_idx: int


@dataclass(frozen=True)
class PasteChop(Event):
    """Paste the clipboard chop over the target slot (replaces or appends)."""
    track_idx: int
    chop_idx: int


@dataclass(frozen=True)
class EnterSampleRecordFlow(Event):
    """Begin a new-sample recording flow for the given track slot."""
    track_idx: int
