# Eden Roadmap

---

## v0 — POC Complete ✓

**What we built:**

The full native-mode protocol for the Atom SQ was reverse-engineered from scratch — no official documentation exists. Key findings live in `PROTOCOL.md`.

- **Protocol layer** (`eden/controller.py`, `controller_map.py`): full MIDI abstraction for the Atom SQ. JB 5-step native-mode init + DAW mode handshake (SysEx `0x14 00`) hands pad LED control to the host. All output goes to the ATM SQ main port. Pad input (blocks mode, ch=0, notes 36–67) dispatched to typed callbacks.
- **OLED display**: SysEx text protocol confirmed and working. Writes to 14 named slots; supports RGB color and alignment.
- **Pad RGB LEDs**: ch=0 prime + ch=1/2/3 R/G/B note-ons in DAW mode. Full 7-bit color depth per pad.
- **Clock** (`eden/clock.py`): drift-free `perf_counter`-based sequencer clock. 80/20 sleep/busywait for sub-millisecond timing accuracy.
- **Sample player** (`eden/audio.py`): `sounddevice` callback-mode engine. Pre-loaded float32 buffers, lock-free deque trigger queue, 8-voice polyphony, soft clip.
- **Step sequencer** (`eden/app.py`): 16-step single-track sequencer. Pad press toggles steps; playhead paints pads live; OLED shows BPM.
- **Test harness** (`probe.py`): MIDI port discovery, live sniffing, and hardware-confirmed test commands for every protocol feature.

**What we learned the hard way:**

- The `0x13` SysEx command silently shuts everything off — never send it.
- The ATM SQ Control port (which Studio One uses) is not required; the main ATM SQ port works for all output once DAW mode is active.
- The listener thread crashes on SysEx messages (no `.channel` attribute) unless guarded — the device sends a Device Identity Reply on startup that kills the input loop.

---

## v1 — Playable Groovebox

A real instrument you can jam with.

- **8-track sequencer**: each track has its own sample, 16 steps, per-step velocity
- **Track select**: top pad row selects the active track; bottom row edits its steps
- **Mute / solo**: hold a modifier button + tap track pad
- **Swing**: global swing amount on an encoder
- **Pattern slots**: 8 storable patterns, switchable without stopping playback
- **Real-time record**: play pads to write steps live while the clock runs
- **BPM encoder**: main encoder adjusts BPM; OLED updates live

---

## v2 — Instrument Layer

Move beyond samples into synthesis.

- **Synth voices**: minimal FM and wavetable engine, one per track
- **Chord / bass mode**: pads play scale degrees; encoder scrolls root note
- **Encoder parameter control**: encoders map to filter, env, fx; OLED shows name + value

---

## v3 — Sampler

Capture and reshape audio.

- **Record from input**: capture a loop and assign slices to pads
- **Timestretch / pitch**: independent tempo and pitch control per slice
- **Kit loading**: drop a folder of WAVs and auto-map to pads

---

## v4 — Session and Arrangement

Turn jams into tracks.

- **Song mode**: chain patterns into a linear arrangement
- **Export**: render to audio file or MIDI
- **Undo / redo**: full history across the session

---

## Future / Wishlist

- Networked jam over OSC — multiple controllers, shared sequence
- Plug-in hosting (LV2 or CLAP) for external synth and FX
- CV/gate output via USB-MIDI adapter
