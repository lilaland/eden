# Eden 🌴

Eden is a standalone groovebox application built around the PreSonus Atom SQ MIDI controller. It turns the controller into a self-contained instrument: step sequencer, drum sampler, synth voices, and FX — all driven from the pads and encoders, no DAW required. The name comes from Atom + Eve, and the aesthetic is straight jungle: palm greens, snakeskin patterns, sunset oranges, deep-canopy purples.

---

## The Controller is the Instrument

The Atom SQ operates in a native mode that exposes full RGB pad control and an OLED display over MIDI SysEx. Eden speaks that protocol directly. Every pad color, every screen line, every encoder response is Eden's — not PreSonus Studio One's. The controller stops being a peripheral and becomes the device.

---

## Hardware Requirements

- PreSonus Atom SQ (USB, connected before launch)
- Mac or Linux
- Python 3.11+

---

## Dependencies

| Package | Purpose |
|---|---|
| `mido` | MIDI I/O abstraction |
| `python-rtmidi` | Low-level MIDI backend for mido |
| `sounddevice` | Low-latency audio output |
| `numpy` | Sample buffer manipulation |

Install everything at once:

```
pip install mido python-rtmidi sounddevice numpy
```

---

## Quick Start

**1. Verify hardware**

Before running anything else, confirm Eden can see your controller:

```
python probe.py
```

`probe.py` lists all available MIDI ports. You should see a port with "Atom SQ" in the name. If you don't, check the USB connection and try again.

**2. Run Eden** _(once v0 is complete)_

```
python -m eden
```

---

## v0 Status

The five goals that prove the core tech stack works. None of these require a DAW.

- [ ] Enter native mode on the Atom SQ
- [ ] Light a pad in an arbitrary RGB color
- [ ] Write static text to the OLED screen
- [ ] Play a drum sample on pad press with low latency
- [ ] Run a 16-step sequencer with visible playhead on pads

---

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Naming

Atom (the controller) + Eve = Eden. The tropical snake theme follows naturally — palm greens, sunset oranges, jungle teals, deep-canopy purples. The snake is in the garden. The garden runs on MIDI.
