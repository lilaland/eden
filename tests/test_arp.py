"""tests/test_arp.py — Tests for chord expansion and arp sequence computation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eden.arp import expand_chord, compute_arp_sequence, arp_ticks_per_note, CHORD_INTERVALS


# ── expand_chord ──────────────────────────────────────────────────────────────

def test_expand_chord_major_from_c():
    result = expand_chord((60,), "major")
    assert result == (60, 64, 67)  # C E G


def test_expand_chord_minor_from_a():
    result = expand_chord((69,), "minor")
    assert result == (69, 72, 76)  # A C E


def test_expand_chord_deduplicates():
    # Two notes a third apart with major: some overlap
    result = expand_chord((60, 64), "major")
    pitches = list(result)
    assert len(pitches) == len(set(pitches))


def test_expand_chord_clamps_to_127():
    result = expand_chord((125,), "major")
    assert all(0 <= p <= 127 for p in result)


def test_expand_chord_unknown_type_falls_back_to_major():
    result = expand_chord((60,), "nonexistent")
    assert result == (60, 64, 67)


def test_expand_chord_all_known_types():
    for chord_type in CHORD_INTERVALS:
        result = expand_chord((60,), chord_type)
        assert len(result) >= 3


# ── compute_arp_sequence ──────────────────────────────────────────────────────

def test_arp_up_single_octave():
    result = compute_arp_sequence((60, 64, 67), "up", 1)
    assert result == (60, 64, 67)


def test_arp_down_single_octave():
    result = compute_arp_sequence((60, 64, 67), "down", 1)
    assert result == (67, 64, 60)


def test_arp_down_up_is_pendulum():
    result = compute_arp_sequence((60, 64, 67), "down_up", 1)
    assert result[0] == 60
    assert result[-1] != result[0]  # no repeated bottom
    assert 60 in result and 64 in result and 67 in result


def test_arp_two_octaves_expands():
    result = compute_arp_sequence((60,), "up", 2)
    assert result == (60, 72)


def test_arp_chord_mode_returns_all():
    result = compute_arp_sequence((60, 64, 67), "chord", 1)
    assert set(result) == {60, 64, 67}


def test_arp_input_mode_preserves_order():
    result = compute_arp_sequence((67, 60, 64), "input", 1)
    assert result == (67, 60, 64)


def test_arp_random_returns_same_notes():
    result = compute_arp_sequence((60, 64, 67), "random", 1)
    assert set(result) == {60, 64, 67}
    assert len(result) == 3


def test_arp_empty_pitches_returns_empty():
    result = compute_arp_sequence((), "up", 1)
    assert result == ()


# ── arp_ticks_per_note ────────────────────────────────────────────────────────

def test_arp_ticks_quarter_note():
    assert arp_ticks_per_note(4) == 8


def test_arp_ticks_eighth_note():
    assert arp_ticks_per_note(8) == 4


def test_arp_ticks_sixteenth_note():
    assert arp_ticks_per_note(16) == 2


def test_arp_ticks_thirtysecond_note():
    assert arp_ticks_per_note(32) == 1
