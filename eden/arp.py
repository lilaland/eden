"""eden/arp.py — Arp sequence computation and chord expansion."""

from __future__ import annotations

import random as _random

# ── Chord intervals ───────────────────────────────────────────────────────────

CHORD_INTERVALS: dict[str, tuple[int, ...]] = {
    "major":  (0, 4, 7),
    "minor":  (0, 3, 7),
    "dom7":   (0, 4, 7, 10),
    "maj7":   (0, 4, 7, 11),
    "min7":   (0, 3, 7, 10),
    "sus2":   (0, 2, 7),
    "sus4":   (0, 5, 7),
    "aug":    (0, 4, 8),
    "dim":    (0, 3, 6),
}


def expand_chord(pitches: tuple[int, ...], chord_type: str) -> tuple[int, ...]:
    """Expand each pitch by chord intervals. Deduplicates and clamps to 0-127."""
    intervals = CHORD_INTERVALS.get(chord_type, (0, 4, 7))
    result: list[int] = []
    seen: set[int] = set()
    for p in pitches:
        for i in intervals:
            note = max(0, min(127, p + i))
            if note not in seen:
                result.append(note)
                seen.add(note)
    return tuple(result)


# ── Arp sequence ──────────────────────────────────────────────────────────────

def compute_arp_sequence(pitches: tuple[int, ...], mode: str, octaves: int) -> tuple[int, ...]:
    """Build the arp note sequence from pitches, mode, and octave span.

    Returns an empty tuple if pitches is empty.
    """
    if not pitches:
        return ()
    base = sorted(set(pitches))
    n_oct = max(1, octaves)

    expanded: list[int] = []
    for oct_i in range(n_oct):
        for p in base:
            expanded.append(min(127, p + oct_i * 12))

    if mode == "up":
        return tuple(expanded)

    if mode == "down":
        return tuple(reversed(expanded))

    if mode == "down_up":
        down = list(reversed(expanded))
        # Remove repeated top note; if seq wraps, also remove repeated bottom
        pendulum = expanded + down[1:]
        if len(pendulum) > 1 and pendulum[-1] == pendulum[0]:
            pendulum = pendulum[:-1]
        return tuple(pendulum)

    if mode == "chord":
        return tuple(expanded)  # all-at-once is handled at call site

    if mode == "random":
        shuffled = list(expanded)
        _random.shuffle(shuffled)
        return tuple(shuffled)

    # "input": preserve input order, expand over octaves
    input_order = list(pitches)
    result: list[int] = []
    for oct_i in range(n_oct):
        for p in input_order:
            result.append(min(127, p + oct_i * 12))
    return tuple(result)


def arp_ticks_per_note(arp_rate: int) -> int:
    """Return the clock-tick interval for one arp note at the given note-value rate.

    Clock runs at 32 ticks/bar (4/4 @ 16th grid). arp_rate is the denominator:
      4  = quarter note → 8 ticks
      8  = eighth note  → 4 ticks
      16 = 16th note    → 2 ticks
      32 = 32nd note    → 1 tick
    """
    return max(1, 32 // max(1, arp_rate))
