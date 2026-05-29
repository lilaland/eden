"""eden/scales.py — Scale definitions and pitch/degree conversion utilities."""

from __future__ import annotations

# Intervals are semitone offsets from the root within one octave (0–11).
SCALES: dict[str, tuple[int, ...]] = {
    "chromatic":    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11),
    "major":        (0, 2, 4, 5, 7, 9, 11),
    "minor":        (0, 2, 3, 5, 7, 8, 10),
    "pentatonic":   (0, 2, 4, 7, 9),
    "min_pent":     (0, 3, 5, 7, 10),
    "blues":        (0, 3, 5, 6, 7, 10),
    "dorian":       (0, 2, 3, 5, 7, 9, 10),
    "mixolydian":   (0, 2, 4, 5, 7, 9, 10),
    "phrygian":     (0, 1, 3, 5, 7, 8, 10),
    "lydian":       (0, 2, 4, 6, 7, 9, 11),
    "jazz_minor":   (0, 2, 3, 5, 7, 9, 11),
    "whole_tone":   (0, 2, 4, 6, 8, 10),
    "diminished":   (0, 2, 3, 5, 6, 8, 9, 11),
}

SCALE_NAMES: tuple[str, ...] = tuple(SCALES)

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Short display names for OLED (≤5 chars)
SCALE_SHORT: dict[str, str] = {
    "chromatic":  "CHROM",
    "major":      "MAJOR",
    "minor":      "MINOR",
    "pentatonic": "PENTA",
    "min_pent":   "MPENT",
    "blues":      "BLUES",
    "dorian":     "DORI",
    "mixolydian": "MIXO",
    "phrygian":   "PHRY",
    "lydian":     "LYDI",
    "jazz_minor": "JAZZ",
    "whole_tone": "WHOLE",
    "diminished": "DIM",
}


def degree_to_pitch(root: int, scale: str, degree: int) -> int:
    """Convert an unbounded scale degree to a MIDI pitch (clamped 0–127).

    Degree 0 = root. Negative degrees go below root.
    Example: degree_to_pitch(60, "major", 7) == 72  (one octave up)
    """
    intervals = SCALES.get(scale, SCALES["chromatic"])
    n = len(intervals)
    octave, idx = divmod(degree, n)
    return max(0, min(127, root + octave * 12 + intervals[idx]))


def pitch_to_degree(root: int, scale: str, pitch: int) -> int | None:
    """Return the scale degree of a pitch, or None if pitch is not in the scale.

    Degree 0 = root note (any octave of root returns the appropriate degree).
    """
    intervals = SCALES.get(scale, SCALES["chromatic"])
    n = len(intervals)
    semitone_in_oct = (pitch - root) % 12  # always 0-11
    octave_offset = (pitch - root) // 12
    try:
        idx = list(intervals).index(semitone_in_oct)
    except ValueError:
        return None
    return octave_offset * n + idx


def pitch_name(pitch: int) -> str:
    """Return a short display name like 'C4', 'F#3'."""
    return f"{_NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def is_root(root: int, pitch: int) -> bool:
    """True if pitch is any octave of the root note."""
    return (pitch - root) % 12 == 0


# ── Piano keyboard layout ─────────────────────────────────────────────────────

# Semitone offsets of the 7 white keys per octave: C D E F G A B
_WHITE_KEY_SEMITONES: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)
# Semitone offsets of black keys between consecutive white keys (None = no black key)
_BLACK_KEY_SEMITONES: tuple[int | None, ...] = (1, 3, None, 6, 8, 10, None)


def piano_base_note(root: int, offset: int) -> int:
    """MIDI note of the leftmost white key: C of root's octave + offset semitones."""
    return root - (root % 12) + offset


def piano_white_pitch(base: int, pad_pos: int) -> int:
    """MIDI pitch for white-key pad 0–15. base = MIDI note of leftmost white key."""
    octave = pad_pos // 7
    degree = pad_pos % 7
    return max(0, min(127, base + octave * 12 + _WHITE_KEY_SEMITONES[degree]))


def piano_black_pitch(base: int, pad_pos: int) -> int | None:
    """MIDI pitch for black-key pad 0–15, or None for the dead E#/B# positions."""
    octave = pad_pos // 7
    degree = pad_pos % 7
    semi = _BLACK_KEY_SEMITONES[degree]
    if semi is None:
        return None
    return max(0, min(127, base + octave * 12 + semi))


def note_in_scale(pitch: int, root: int, scale: str) -> bool:
    """True if pitch belongs to the given scale rooted at root."""
    intervals = SCALES.get(scale, SCALES["chromatic"])
    return (pitch - root) % 12 in intervals


def white_idx_to_midi(white_idx: int) -> int:
    """Raw MIDI pitch for white key index (0 = C-1 = MIDI 0, 35 = C4 = MIDI 60).

    May return values outside 0-127 for extreme indices; callers must range-check.
    One increment = one white key (one column) to the right on a piano.
    """
    octave, degree = divmod(white_idx, 7)
    return octave * 12 + _WHITE_KEY_SEMITONES[degree]


def black_key_at(white_idx: int) -> int | None:
    """Raw MIDI pitch of the black key to the right of white key white_idx, or None.

    None is returned for the E/F and B/C boundaries where no black key exists.
    May return values outside 0-127; callers must range-check.
    """
    octave, degree = divmod(white_idx, 7)
    semi = _BLACK_KEY_SEMITONES[degree]
    return None if semi is None else octave * 12 + semi
