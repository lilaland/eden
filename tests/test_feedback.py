"""
test_feedback.py — Interactive hardware test for Eden LED/screen feedback.

Run with: python tests/test_feedback.py
Requires: PreSonus Atom SQ connected via USB, native mode capable firmware.
Each test prints instructions, sends MIDI, then waits for user to press Enter.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from eden.controller import AtomSQ
from eden.feedback import EdenFeedback
from eden.theme import PAD_ACTIVE, PAD_PLAYHEAD, PAD_SELECTED, PAD_INACTIVE


# ─── Test functions ───────────────────────────────────────────────────────────


def test_01_native_entry(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Enter native mode."""
    print("  Action: entering native mode via controller.enter_native_mode()")
    controller.enter_native_mode()


def test_02_pad_colors(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Light pads 0–15 in sequence with 4 cycling colors."""
    colors = [PAD_ACTIVE, PAD_PLAYHEAD, PAD_SELECTED, PAD_INACTIVE]
    color_names = ["active (palm green)", "playhead (orange)", "selected (teal)", "inactive (purple)"]
    print(f"  Action: lighting pads 0–15 in sequence with colors: {', '.join(color_names)}")
    for i in range(16):
        color = colors[i % 4]
        feedback._set_pad(i, color)
        time.sleep(0.1)


def test_03_all_pads_off(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Clear all pads."""
    print("  Action: calling feedback.clear_all_pads()")
    feedback.clear_all_pads()


def test_04_sequencer_row(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Show a 16-step pattern with even steps active, playhead at step 4."""
    steps = [i % 2 == 0 for i in range(16)]
    playhead = 4
    print(f"  Action: update_sequencer_row(steps=even indices active, playhead={playhead})")
    feedback.update_sequencer_row(steps, playhead)


def test_05_playhead_walk(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Walk the playhead across all 16 steps at 120 BPM (0.5s per step)."""
    steps = [False] * 16
    print("  Action: walking playhead across steps 0–15 at 0.5s intervals (120 BPM)")
    for playhead in range(16):
        feedback.update_sequencer_row(steps, playhead)
        time.sleep(0.5)


def test_06_oled_main(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Write 'Eden v0' to main line 1, 'Ready' to line 2."""
    print("  Action: feedback.write_status('Eden v0', 'Ready')")
    feedback.write_status("Eden v0", "Ready")


def test_07_soft_keys(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Write 'BPM' / '120' to SK1, 'STEPS' / '16' to SK2."""
    print("  Action: writing BPM:120 to SK1, STEPS:16 to SK2")
    feedback.write_soft_key(0, "BPM", "120")
    feedback.write_soft_key(1, "STEPS", "16")


def test_08_mode_buttons(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Cycle through SONG/INST/EDIT/USER mode indicators with 1s each."""
    modes = ["song", "inst", "edit", "user"]
    print(f"  Action: cycling mode indicators {modes} at 1s each")
    for mode in modes:
        feedback.set_mode_indicator(mode)
        time.sleep(1.0)


def test_09_native_exit(feedback: EdenFeedback, controller: AtomSQ) -> None:
    """Exit native mode."""
    print("  Action: calling controller.exit_native_mode()")
    controller.exit_native_mode()


# ─── Runner ───────────────────────────────────────────────────────────────────

_TESTS = [
    (test_01_native_entry, "Did the pad LEDs illuminate?"),
    (test_02_pad_colors,   "Did 16 pads light in 4 different colors?"),
    (test_03_all_pads_off, "Did all pads turn off?"),
    (test_04_sequencer_row, "Do you see 8 green pads, one orange (step 4), rest purple?"),
    (test_05_playhead_walk, "Did the orange dot walk left to right?"),
    (test_06_oled_main,    "Does the OLED show Eden v0 / Ready?"),
    (test_07_soft_keys,    "Do soft keys show BPM:120 and STEPS:16?"),
    (test_08_mode_buttons, "Did the mode buttons light in sequence?"),
    (test_09_native_exit,  "Did the device return to standard behavior?"),
]


def run_all() -> None:
    controller = AtomSQ()
    feedback = EdenFeedback(controller)

    passed = failed = skipped = 0

    for fn, prompt in _TESTS:
        name = fn.__name__
        print(f"\n[{name}] {fn.__doc__}")
        try:
            fn(feedback, controller)
        except Exception as exc:
            print(f"  ERROR during execution: {exc}")
            failed += 1
            continue

        while True:
            raw = input(f"  {prompt} (y/n/s to skip): ").strip().lower()
            if raw in ("y", "n", "s"):
                break
            print("  Please enter y, n, or s.")

        if raw == "y":
            passed += 1
            print("  PASS")
        elif raw == "s":
            skipped += 1
            print("  SKIP")
        else:
            failed += 1
            print("  FAIL")

    print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    controller.close()


if __name__ == "__main__":
    run_all()
