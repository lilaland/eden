"""state.py — All Eden state types as frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Union


class Mode(Enum):
    SESSION = auto()
    INSTRUMENT = auto()


@dataclass(frozen=True)
class StepNote:
    """A single step in a loop. Drums use on/velocity; synths use all fields."""
    on: bool
    pitches: tuple[int, ...] = (60,)     # MIDI notes 0-127; multi-voice chord; ignored by DrumTrack
    velocity: int = 100                  # 0-127; used by both drums and synths
    gate: float = 0.5                    # fraction of step duration held; ignored by DrumTrack
    aftertouch: float = 0.0             # channel pressure at time of recording [0,1]; playback-ignored
    probability: int = 100              # 1-100; steps below 100 fire stochastically
    lock_cutoff: Optional[float] = None # overrides SynthTrack.filter_cutoff for this step only

    @classmethod
    def off(cls) -> "StepNote":
        return cls(on=False)


@dataclass(frozen=True)
class NoteEvent:
    """A single note event captured during free recording, before quantize."""
    tick: int           # absolute playhead tick within loop (bar * 32 + playhead, 0-based)
    pitch: int          # MIDI note 0-127
    velocity: int       # 0-127
    gate: float         # duration as fraction of one step (same units as StepNote.gate)
    aftertouch: float = 0.0  # channel pressure at release time [0,1]


class InstrumentSubmode(Enum):
    STEPS = auto()        # default step-grid editing
    PADS = auto()         # live pad recording into a loop slot
    DRUM_FREE = auto()    # free multi-track drum recording (pads 0-15 = tracks 0-15)
    SAMPLE_CHOPS = auto() # chop-to-step assignment grid
    SAMPLE_RECORD = auto() # input → trim → chop-detect (scaffold for now)
    SAMPLE_KEYS = auto()  # all pads = chromatic keyboard for selected chop
    SAMPLE_EDIT = auto()  # top row = chop selector, bottom row = waveform scrub/trim
    SAMPLE_TAP_CHOP = auto()  # tap pads during playback to mark chop boundaries


@dataclass(frozen=True)
class ChopPoint:
    """One slice of a sample, expressed as normalized offsets into the file."""
    start_offset: float   # 0.0–1.0
    end_offset: float     # 0.0–1.0
    name: str = ""
    tune: float = 0.0     # semitones offset, applied at playback
    reverse: bool = False


@dataclass(frozen=True)
class Loop:
    """A single loop slot: variable-length step sequence plus play-count config."""

    steps: tuple[StepNote, ...]  # 16 or 32 StepNotes
    loop_count: int = 0          # 0=∞, 1/2/4/8=plays per cycle (configured)
    bars: int = 1
    numerator: int = 4
    step_size: int = 16          # note value denominator: 4/8/16/32
    volume: float = 1.0          # per-loop mix volume 0.0–1.0
    # Chord/arp settings (per-loop; applied during step-sequencer playback)
    arp_on: bool = False
    arp_mode: str = "up"         # up / down / down_up / chord / random / input
    arp_rate: int = 16           # note value denominator (4/8/16/32)
    arp_octaves: int = 1         # 1–4
    chord_on: bool = False
    chord_type: str = "major"
    # Raw free-recording events; preserved for re-quantize
    free_events: tuple = ()      # tuple[NoteEvent, ...]

    @property
    def is_empty(self) -> bool:
        return not any(s.on for s in self.steps) and not self.free_events

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def steps_per_bar(self) -> int:
        return self.numerator * (self.step_size // 4)


@dataclass(frozen=True)
class FXChain:
    """8-slot FX values per page, normalized 0.0–1.0."""
    # Page 1: LOW EQ, MID EQ, HI EQ, DELAY, CHORUS, REVERB, DIST, PHASE
    page1: tuple[float, ...] = (0.5, 0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0)
    # Page 2: HPF, LPF, CRUSH, PITCH, COMP, TAPE, GATE, RSAMP
    page2: tuple[float, ...] = (0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class DrumTrack:
    """A drum/sample track backed by a single sample file."""

    name: str
    sample_name: str
    loops: tuple[Loop, ...]  # always 16 loops
    volume: float = 1.0      # track mix volume 0.0–1.0
    keep_empty: bool = False
    fx: FXChain = field(default_factory=FXChain)


@dataclass(frozen=True)
class SynthTrack:
    """Polyphonic subtractive synth track."""

    name: str
    loops: tuple[Loop, ...]
    osc_type: str = "saw"          # saw / square / sine / triangle
    amp_attack: float = 0.005
    amp_decay: float = 0.1
    amp_sustain: float = 0.85
    amp_release: float = 0.4
    filter_cutoff: float = 8000.0  # Hz
    filter_res: float = 0.2        # 0.0–0.99
    volume: float = 0.8
    max_voices: int = 8
    root_note: int = 60            # MIDI root pitch (default C4)
    scale: str = "chromatic"       # key in scales.SCALES
    quantized: bool = True         # True = scale-degree step editor; False = piano keyboard
    aftertouch: bool = True        # channel pressure enabled
    retrigger: bool = False        # True = new notes cut prior voices (still allows chords)
    keep_empty: bool = False
    fx: FXChain = field(default_factory=FXChain)


@dataclass(frozen=True)
class SampleTrack:
    """Sample-based track with optional KO II-style chop sequencing."""
    name: str
    sample_key: str              # key into AudioMixer._samples (e.g. "kick_techno")
    loops: tuple[Loop, ...]      # always 16 loops
    chops: tuple[ChopPoint, ...] = ()   # empty = whole-sample (one-shot mode)
    play_mode: str = "oneshot"   # "oneshot" | "gate" | "legato"
    trim_start: float = 0.0      # normalized 0.0-1.0
    trim_end: float = 1.0
    amp_attack: float = 0.0      # seconds (0 = instant)
    amp_release: float = 0.05    # seconds
    pan: float = 0.0             # -1.0 to +1.0
    mute_group: int = 0          # 0 = none; 1-8 = exclusive mute group
    volume: float = 1.0
    keep_empty: bool = False
    stretch_mode: str = "off"    # "off" | "repitch" | "stretch"
    stretch_bars: int = 1        # target loop length in bars (used when stretch_mode != "off")
    sample_mode: str = "chopped"  # "oneshot" | "chopped" — structural playback mode
    pitched: bool = False         # oneshot only: pitch by MIDI note relative to root_note
    root_note: int = 60           # MIDI root for pitched 1-shot pitch_rate computation
    scale: str = "chromatic"      # scale for 1-shot pitched step recording
    quantized: bool = True         # True=scale-degree pads, False=piano free mode
    chop_clipboard: object = None  # ephemeral copy/paste buffer (not serialized)
    fx: FXChain = field(default_factory=FXChain)


Track = Union[DrumTrack, SynthTrack, SampleTrack]


@dataclass(frozen=True)
class Scene:
    """Snapshot of all 16 track slots for instant recall."""
    tracks: tuple[Optional[Track], ...]  # length 16
    tempo_bpm: float = 120.0
    swing: float = 0.0


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
    new_slot_mode_idx: int = 0         # KEYS only: 0=QUANT, 1=FREE
    new_slot_active_ctrl: str = ""     # "" | "TYPE" | "CAT" | "VAR" | "MODE"
    saved_armed_tracks: Optional[tuple[int, ...]] = None  # restored on exit from new-slot INSTRUMENT
    metronome_held: bool = False
    tap_times: tuple[float, ...] = ()  # recent Shift+Metronome tap timestamps
    # Velocity mode: False = mono (always 100), True = use actual pad velocity
    vel_sensitive: bool = True
    # SESSION volume control
    session_active_ctrl: str = ""    # "" | "VOL"
    session_selected_row: int = 0    # 0 = track row (pads 0-15), 1 = loop row (pads 16-31)
    # Synth step/keyboard editor state (ephemeral, not persisted)
    step_cursor: int = 0            # absolute step index of the highlighted step
    pitch_window_offset: int = 0    # scale-degree offset (quantized) or semitone offset (free)
    octave_offset: int = 0          # additional ±N octave transpose (applied on top of window)
    # Single-level undo for INSTRUMENT mode recording actions
    undo_snapshot: Optional[tuple] = None  # tracks tuple before last edit
    undo_cursor: int = 0                   # step_cursor at time of snapshot
    sample_edit_snapshot: Optional[tuple] = None  # tracks snapshot taken when entering SAMPLE_EDIT for 1-shot
    # Session management (M2)
    active_session_slot: int = 0            # 0-7 → A-H, which slot is currently loaded
    active_loops: frozenset[tuple[int, int]] = frozenset()  # loops that auto-start on session load
    # Graceful session transition: old loops finish while new session is already displayed
    finishing_loops: frozenset[tuple[int, int]] = frozenset()
    finishing_tracks: tuple = ()            # tuple[Optional[Track], ...] snapshot of prev session
    finishing_plays_remaining: tuple[tuple[tuple[int, int], int], ...] = ()
    finishing_loop_measure_offsets: tuple[tuple[tuple[int, int], int], ...] = ()
    # OLED page for Instrument view (SynthTrack: 0=params, 1=arp, 2=chord)
    instrument_oled_page: int = 0
    # FREE recording state
    free_recording: bool = False
    free_record_pending: bool = False
    free_loop_length: int = 0  # 0 = first pass (growing); >0 = overdub (fixed wrap length)
    rec_held_shift: bool = False          # True while shift+REC is physically held
    rec_held_ticks: int = 0               # clock ticks since shift+REC was pressed
    free_undo_loops: tuple = ()           # ((track_idx, loop_idx, Loop), ...) snapshot before last REC
    # Last-used scale/root — shared by FREE and QUANT; applied to newly created SynthTracks
    last_synth_scale: str = "chromatic"
    last_synth_root: int = 60
    global_fx: FXChain = field(default_factory=FXChain)
    edit_mode: bool = False
    fx_edit_page: int = 0
    fx_active_knob: int = -1
    # Quantize settings (applied to free_events → steps)
    quantize_grid: int = 16          # grid resolution (same denominator as step_size)
    quantize_strength: float = 1.0   # 0.0–1.0; pull-toward-grid fraction
    # In-flight free-recording presses: (pad, tick, pitch, velocity) tuples
    free_pending_ticks: tuple = ()
    # Current channel pressure [0,1]; captured into NoteEvents on release
    current_aftertouch: float = 0.0
    # Scene management (M5)
    scenes: tuple[Optional[Scene], ...] = field(default_factory=lambda: tuple([None] * 8))
    active_scene: int = 0
    # SampleTrack ephemeral state
    sample_chop_cursor: int = 0      # selected chop index in SAMPLE_CHOPS / SAMPLE_KEYS
    sample_recording: bool = False   # True while audio input is being recorded
    tap_chop_times: tuple = ()       # wall-clock timestamps collected during SAMPLE_TAP_CHOP
    # Available sample pool (populated from web Sample Manager or default set on startup)
    available_samples: tuple[str, ...] = ()


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
