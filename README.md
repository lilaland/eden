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

The OLED shows **EDEN / BPM 120**. The 16 bottom-row pads are the step sequencer. Press any pad to toggle a step. The playhead advances in real time. Ctrl-C to quit.

Optional flags:

```
python eden/app.py --bpm 140 --samples /path/to/samples
```

---

## Probing / Hardware Tests

`probe.py` is a low-level test harness for the Atom SQ protocol. Useful for diagnostics and verifying hardware behaviour without running the full app.

```
python probe.py list            # show MIDI ports
python probe.py sniff           # log all incoming MIDI
python probe.py main_daw_test   # confirm OLED + pad RGB working
```

---

## v0 Status — Complete

All five goals that prove the core tech stack works, no DAW required.

- [x] Enter native mode on the Atom SQ
- [x] Light pads in arbitrary RGB colors
- [x] Write text to the OLED display
- [x] Play a drum sample on pad press with low latency
- [x] Run a 16-step sequencer with visible playhead on pads

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Naming

Atom (the controller) + Eve = Eden. The tropical snake theme follows naturally — palm greens, sunset oranges, jungle teals, deep-canopy purples. The snake is in the garden. The garden runs on MIDI.
