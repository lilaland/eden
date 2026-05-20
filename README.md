# Eden

Eden is a standalone groovebox application built around the PreSonus Atom SQ MIDI controller. It turns the controller into a self-contained instrument: step sequencer, drum sampler, synth voices, and FX — all driven from the pads and encoders, no DAW required. The name comes from Atom + Eve, and the aesthetic is straight jungle: palm greens, snakeskin patterns, sunset oranges, deep-canopy purples.

---

## The Controller is the Instrument

The Atom SQ operates in a native mode that exposes full RGB pad control and an OLED display over MIDI SysEx. Eden speaks that protocol directly. Every pad color, every screen line, every encoder response is Eden's — not PreSonus Studio One's. The controller stops being a peripheral and becomes the device.

---

## Hardware Requirements

- PreSonus Atom SQ (USB, connected before launch)
- macOS or Linux
- Python 3.11+

---

## Quick Start

```
pip install -r requirements.txt
python eden/app.py
```

**Session view** launches by default. Top row = 16 instrument tracks. Bottom row = 16 loop slots for the selected track. Press a top-row pad to select a track. Press a bottom-row pad to toggle a loop playing. Ctrl-C to quit.

Optional flags:

```
python eden/app.py --bpm 140 --samples /path/to/samples
```

**Debug window** (requires pygame):

```
pip install pygame
python eden/debug_ui.py    # standalone mirror window
```

---

## Softkey Reference (M1/M2)

### Session view

| Key | Label | Action |
|-----|-------|--------|
| SK1 | MUTE  | Toggle mute on selected track |
| SK2 | SOLO  | Toggle solo on selected track |
| SK3 | LOOPxN | Cycle loop count: inf → 1 → 2 → 4 → 8 → inf |
| SK4 | ARM1  | Arm selected track (32-step single-arm instrument view) |
| SK5 | ARM2  | Add to arm list; 2 tracks armed → dual-16 instrument view |

### Instrument view

| Key | Label | Action |
|-----|-------|--------|
| SK1 | STEPS | Step-grid mode (active) |
| SK2 | KEYS M3 | Placeholder (M3) |
| SK3 | PADS  | Placeholder (M2) |
| SK4 | < BACK | Return to session view |
| SK5 | CLEAR | Clear all steps (hold Shift to confirm) |

---

## Probing / Hardware Tests

`probe.py` is a low-level test harness for the Atom SQ protocol. Useful for diagnostics and verifying hardware behaviour without running the full app.

```
python probe.py list            # show MIDI ports
python probe.py sniff           # log all incoming MIDI
python probe.py main_daw_test   # confirm OLED + pad RGB working
```

Legacy hardware feedback test:

```
python tests/test_feedback.py   # interactive LED/OLED test (requires controller)
```

---

## v0 Status — Complete

All five goals that prove the core tech stack works, no DAW required.

- [x] Enter native mode on the Atom SQ
- [x] Light pads in arbitrary RGB colors
- [x] Write text to the OLED display
- [x] Play a drum sample on pad press with low latency
- [x] Run a 16-step sequencer with visible playhead on pads

## M1/M2 Status — Complete

Immutable-state architecture + session/instrument views.

- [x] Frozen `AppState` dataclass — 16 tracks × 16 loops × 16/32 steps
- [x] Pure event/reducer/renderer pipeline (103 tests, zero hardware required)
- [x] Session view — track select, loop play/stop, mute, solo, loop count
- [x] Instrument view — 32-step single-arm, dual-16 dual-arm, step toggle
- [x] Encoder 9 → BPM control
- [x] Shift + SK5 (CLEAR) with hold confirm
- [x] Audio step scheduler reads from AppState (lock-free, CPython atomic)
- [x] Soft key dispatch (previously missing from v0 controller)
- [x] Shift key dispatch (previously missing from v0 controller)
- [x] Pygame debug mirror window (read-only, 30fps, tropical theme)

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Naming

Atom (the controller) + Eve = Eden. The tropical snake theme follows naturally — palm greens, sunset oranges, jungle teals, deep-canopy purples. The snake is in the garden. The garden runs on MIDI.
