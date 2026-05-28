"""state.py — All Eden state types as frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Union


class Mode(Enum):
    SESSION = auto()
    INSTRUMENT = auto()


@dataclass(frozen=True)
class StepNote:
    """A single step in a loop. Drums use on/velocity; synths use all fields."""
    on: bool
    pitch: int = 60      # MIDI note 0-127; ignored by DrumTrack
    velocity: int = 100  # 0-127; used by both drums and synths
    gate: float = 0.5    # fraction of step duration held; ignored by DrumTrack

    @classmethod
    def off(cls) -> "StepNote":
        return cls(on=False)


class InstrumentSubmode(Enum):
    STEPS = auto()  # default step-grid editing
    PADS = auto()   # M2: live pad recording into a loop slot


@dataclass(frozen=True)
class Loop:
    """A single loop slot: variable-length step sequence plus play-count config."""

    steps: tuple[StepNote, ...]  # 16 or 32 StepNotes
    loop_count: int = 0          # 0=∞, 1/2/4/8=plays per cycle (configured)
    bars: int = 1
    numerator: int = 4
    step_size: int = 16          # note value denominator: 4/8/16/32

    @property
    def is_empty(self) -> bool:
        return not any(s.on for s in self.steps)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def steps_per_bar(self) -> int:
        return self.numerator * (self.step_size // 4)


@dataclass(frozen=True)
class DrumTrack:
    """A drum/sample track backed by a single sample file."""

    name: str
    sample_name: str
    loops: tuple[Loop, ...]  # always 16 loops


@dataclass(frozen=True)
class SynthTrack:
    """Polyphonic subtractive synth track."""

    name: str
    loops: tuple[Loop, ...]
    osc_type: str = "saw"          # saw / square / sine / triangle
    amp_attack: float = 0.005
    amp_decay: float = 0.1
    amp_sustain: float = 0.7
    amp_release: float = 0.2
    filter_cutoff: float = 8000.0  # Hz
    filter_res: float = 0.2        # 0.0–0.99
    volume: float = 0.8
    max_voices: int = 8


@dataclass(frozen=True)
class SampleTrack:
    """M3 scaffold — reducers raise NotImplementedError."""

    name: str
    loops: tuple[Loop, ...]


Track = Union[DrumTrack, SynthTrack, SampleTrack]


@dataclass(frozen=True)
class AppState:
    """Complete, immutable snapshot of Eden application state."""

    mode: Mode
    tracks: tuple[Optional[Track], ...]      # length 16; None = empty slot
    selected_track: int                       # 0-15
    selected_loop: int                        # 0-15
    armed_tracks: tuple[int, ...]             # 0, 1, or 2 track indices
    playing_loops: frozenset[tuple[int, int]] # (track_idx, loop_idx) pairs
    playhead: int                             # 0-31
    is_playing: bool
    tempo_bpm: float
    swing: float                              # 0.0-1.0
    shift_held: bool
    soloed_tracks: frozenset[int]
    muted_tracks: frozenset[int]
    instrument_submode: InstrumentSubmode     # only meaningful when mode == INSTRUMENT
    # Fields with defaults must come last in frozen dataclass
    plays_remaining: tuple[tuple[tuple[int, int], int], ...] = ()
    # ((track_idx, loop_idx), remaining) — only set for loops with loop_count > 0
    arm_pads_offer_loop: Optional[int] = None  # set by Shift+empty-loop in session view
    loop_measure_offsets: tuple[tuple[tuple[int, int], int], ...] = ()
    # ((track_idx, loop_idx), current_measure_index) — only for playing multi-measure loops
    instrument_view_measure: int = 0   # which measure page the pad grid shows
    instrument_active_ctrl: str = ""   # "" | "BARS" | "NUMER" | "SIZE"
    # New-slot selection state (SESSION mode, empty track selected)
    new_slot_type_idx: int = 0         # index into catalog.INSTRUMENT_TYPES
    new_slot_cat_idx: int = 0          # index into categories for current type
    new_slot_var_idx: int = 0          # index into variations for current category
    new_slot_active_ctrl: str = ""     # "" | "TYPE" | "CAT" | "VAR"
    saved_armed_tracks: Optional[tuple[int, ...]] = None  # restored on exit from new-slot INSTRUMENT
    metronome_held: bool = False
    tap_times: tuple[float, ...] = ()  # recent Shift+Metronome tap timestamps
    # Session management (M2)
    active_session_slot: int = 0            # 0-7 → A-H, which slot is currently loaded
    active_loops: frozenset[tuple[int, int]] = frozenset()  # loops that auto-start on session load
    # Graceful session transition: old loops finish while new session is already displayed
    finishing_loops: frozenset[tuple[int, int]] = frozenset()
    finishing_tracks: tuple = ()            # tuple[Optional[Track], ...] snapshot of prev session
    finishing_plays_remaining: tuple[tuple[tuple[int, int], int], ...] = ()
    finishing_loop_measure_offsets: tuple[tuple[tuple[int, int], int], ...] = ()


# ── Factory functions ─────────────────────────────────────────────────────────


def default_loop(step_count: int = 16) -> Loop:
    """Create an empty loop with all steps off."""
    return Loop(steps=tuple(StepNote.off() for _ in range(step_count)))


def default_track_loops(step_count: int = 16) -> tuple[Loop, ...]:
    """Create 16 empty loops for a new track."""
    return tuple(default_loop(step_count) for _ in range(16))


def _kick_loop() -> Loop:
    steps = tuple(StepNote(on=i in (0, 4, 8, 12)) for i in range(16))
    return Loop(steps=steps)


def _snare_loop() -> Loop:
    steps = tuple(StepNote(on=i in (4, 12)) for i in range(16))
    return Loop(steps=steps)


def default_state() -> AppState:
    """
    Default startup state:
      Track 0: DrumTrack("KICK")  — 4-on-the-floor pattern in loop 0, playing
      Track 1: DrumTrack("SNARE") — backbeat pattern in loop 0, playing
      Tracks 2-15: None (empty)
      Mode: SESSION, BPM: 120, Selected track: 0
    """
    kick_loops = (_kick_loop(),) + tuple(default_loop() for _ in range(15))
    snare_loops = (_snare_loop(),) + tuple(default_loop() for _ in range(15))
    tracks: list[Optional[Track]] = [None] * 16
    tracks[0] = DrumTrack("KICK", "kick", loops=kick_loops)
    tracks[1] = DrumTrack("SNARE", "snare", loops=snare_loops)
    return AppState(
        mode=Mode.SESSION,
        tracks=tuple(tracks),
        selected_track=0,
        selected_loop=0,
        armed_tracks=(),
        playing_loops=frozenset({(0, 0), (1, 0)}),  # loop 0 playing on both tracks
        playhead=0,
        is_playing=True,
        tempo_bpm=120.0,
        swing=0.0,
        shift_held=False,
        soloed_tracks=frozenset(),
        muted_tracks=frozenset(),
        instrument_submode=InstrumentSubmode.STEPS,
        active_loops=frozenset({(0, 0), (1, 0)}),  # matches playing_loops for default
    )
