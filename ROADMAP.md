# Eden Roadmap

This document is the vision; see README.md for what works today.

## Known protocol gap: OLED + pad LEDs simultaneously

Pad RGB (ch=0–3 note-on) works in SONG mode. OLED SysEx works in native mode.
Neither works in the other's mode. The combined protocol is what PreSonus Studio One
uses but has not been reverse-engineered. To unblock this: sniff Studio One with
`probe.py sniff` while the ATOM SQ is connected — the bytes Studio One sends to the
device will reveal the native-mode pad LED protocol. Until then, Eden v0 runs in
SONG mode (pad LEDs only).

---

## v0.1 — Hardware Verified

The foundation. Proves the protocol layer is solid before anything musical is built.

- Enter native mode, light pads with full RGB control over SysEx
- Write text to the OLED display
- Play a drum sample on pad press; run a 16-step sequencer with playhead

---

## v1 — Playable Groovebox

A real instrument you can jam with.

- 8-track step sequencer with per-step velocity and probability; track mute/solo and swing
- Song mode: chain patterns into a linear arrangement
- Real-time recording: play pads to write steps live

---

## v2 — Instrument Layer

Move beyond samples into synthesis.

- Synth voices: minimal FM and wavetable, one per track
- Chord voicing on pads; bass pattern mode
- Encoders control parameters live; OLED displays parameter name and value

---

## v3 — Sampler

Capture and reshape audio.

- Record samples from audio input, assign slices to pads
- Timestretch, pitch-shift, and sample chaining
- Import from disk; drag-and-drop kit loading

---

## v4 — Session and Arrangement

Turn jams into tracks.

- Song structure editor: patterns chain into a full song
- Export to MIDI file or rendered audio
- Undo/redo history across the full session

---

## Future / Wishlist

Ideas that need more thought or hardware.

- Networked jam over OSC — multiple controllers, one shared sequence
- Plug-in hosting (LV2 or CLAP) for external synth/FX
- Hardware expansion: additional controllers, CV/gate output
