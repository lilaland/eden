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
