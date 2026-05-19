# Atom SQ Native-Mode Protocol Reference

## Sources

- **[JB]** JamesB-VS/AtomSQ_Bitwig (GPL-3.0) — Java Bitwig extension, most complete native-mode implementation
  - `AtomSQ/Atom SQ/src/main/java/com/presonus/handler/HardwareHandler.java` — all CC constants
  - `AtomSQ/Atom SQ/src/main/java/com/presonus/handler/DisplayMode.java` — init sequence, SysEx writes, mode transitions
  - `AtomSQ/Atom SQ/src/main/java/com/presonus/handler/SysexHandler.java` — OLED slot IDs, color strings, alignment constants
  - `AtomSQ/Atom SQ/src/main/java/com/presonus/AtomSQExtension.java` — encoder setup, button LED feedback, exit sequence
- **[AK]** alt-key-project/Bitwig-extension-Atom-SQ-MIDI-mode (MIT) — JS, MIDI mode only (no native/SysEx)
  - `src/main/java/com/altkeyproject/logic/AtomSqMidiMapper.java` — standard-mode CC confirmation
- **[FL]** forgery810/fl-studio-presonus-atom-sq (GPL-3.0) — Python, MCU/FL Studio mode
  - `midi_mapping.py` — standard-mode button/encoder CC map
  - `lights.py` — pad LED control via note-on channels 1/2/3 (RGB in standard mode)
- **[SNIFF]** Hardware sniff by project author, 2026-05-18
- **[KVR]** KVR forum rumor (unverified — no URL, no specific author cited)

## Confidence Legend

- **VERIFIED** — multiple independent sources agree, or hardware-confirmed
- **LIKELY** — one repo uses it consistently throughout, no contradicting evidence
- **HYPOTHESIS** — single source, forum rumor, or untested inference

---

## 1. Device Identification

### SysEx manufacturer and device IDs

| Field | Value | Source | Confidence |
|-------|-------|--------|------------|
| Manufacturer ID (3-byte) | `0x00 0x01 0x06` | [JB] SysexHandler.java:8 (`sheader = "F0 00 01 06 22 12"`) | LIKELY |
| Device/Product ID | `0x22` | [JB] SysexHandler.java:8 | LIKELY |
| Full SysEx header | `F0 00 01 06 22` | [JB] DisplayMode.java throughout | LIKELY |

### MIDI port names (macOS/Linux)

The device exposes two MIDI ports:
- `ATM SQ` — notes, CC, pads, encoders (the main port)
- `ATM SQ Control` — used by natively-supported DAWs

[SNIFF] Both ports were identified via hardware sniff. The `ATM SQ Control` port is not used by any of the three reference repos.

---

## 2. Native-Mode Entry/Exit Sequence (CRITICAL) — Updated 2026-05-18

### Studio One observed sequence (confirmed via proxy sniff)

All sent to **ATM SQ Control port**:

```
8F 00 7F   note_off ch=15 note=0 vel=127
F0 7E 7F 06 01 F7   Universal Device Inquiry (×1)
```

This is simpler than the JB 5-step sequence. No CC reset, no 3× repetition. `vel=127` works (KVR rumour was correct; JB uses vel=1 which also works — both velocities are accepted). Studio One does not send the LED enable SysEx (`13 00/01`) — those are not required.

### JB Bitwig sequence (original reference)

### Entry sequence

The JB source sends the following **exact bytes** in `DisplayMode.initHW()` [JB] DisplayMode.java:122–163:

**Step 1 — Encoder CC reset (repeated 3×)**

Each iteration sends these CCs on channel 0 (`0xB0`):

```
B0 1D 00   (CC 29 = 0)
B0 0F 00   (CC 15 = 0)
B0 10 00   (CC 16 = 0)
B0 11 00   (CC 17 = 0)
B0 12 00   (CC 18 = 0)
B0 13 00   (CC 19 = 0)
B0 14 00   (CC 20 = 0)
B0 15 00   (CC 21 = 0)
```

Then, still within each of the 3 iterations, sends:

```
8F 00 00   (note_off  channel=15  note=0  vel=0)
```

`sendMidi(143, 0, 0)` — decimal 143 = `0x8F` = note_off on channel 15 (0-indexed).

**Step 2 — Universal Device Inquiry SysEx (3×)**

```
F0 7E 7F 06 01 F7
```

Sent three times [JB] DisplayMode.java:153–155.

**Step 3 — Enter native mode (the critical byte)**

```
8F 00 01   (note_off  channel=15  note=0  vel=1)
```

`sendMidi(143, 0, 1)` — [JB] DisplayMode.java:157. **Velocity = 1, not 127.**

**Step 4 — Enable pad LEDs**

```
F0 00 01 06 22 13 00 F7
```

[JB] DisplayMode.java:159. This is `SYSEX_CMD_LED_ENABLE (0x13)` with argument `0x00` (pad LEDs on). The comment in the source reads: "this line alone turns on the lights."

**Step 5 — Activate display**

```
F0 00 01 06 22 13 01 F7
```

[JB] DisplayMode.java:163. `SYSEX_CMD_LED_ENABLE (0x13)` with argument `0x01`. The comment reads: "this line alone makes the Inst menu at least come back to life!" and notes that this also takes command of the nav keys on the right — if set to `0x00`, the display still shows and navigates but the keys also send MIDI messages.

### Full init sequence in order

```
# Three identical blocks (block repeated 3 times):
B0 1D 00 ; B0 0F 00 ; B0 10 00 ; B0 11 00
B0 12 00 ; B0 13 00 ; B0 14 00 ; B0 15 00
8F 00 00   ← note_off ch15 note0 vel=0 (not the entry byte — this is the reset)

# Three Universal Device Inquiry SysEx:
F0 7E 7F 06 01 F7   (×3)

# Enter native mode:
8F 00 01   ← note_off ch15 note0 vel=1

# Enable pad LEDs:
F0 00 01 06 22 13 00 F7

# Activate display / take command of nav keys:
F0 00 01 06 22 13 01 F7
```

### Exit sequence

**[JB]** AtomSQExtension.java:1167:

```
8F 00 00   (note_off  channel=15  note=0  vel=0)
```

`sendMidi(143, 0, 0)` on `exit()`. This is the same byte that is sent during the reset loop in `initHW()`.

### Discrepancy: velocity=1 vs velocity=127

`controller_map.py` has `NATIVE_ENTER = (15, 0, 1)` (velocity=1) which **matches the JB source** (`sendMidi(143,00,01)`). The `probe.py` handshake uses `velocity=127`, which is the **KVR rumour** value and is **not confirmed** by any reference implementation. The JB source consistently uses velocity=1. **controller_map.py is correct; probe.py is wrong.**

The exit byte `8F 00 00` (vel=0) is also confirmed by both `controller_map.py` (`NATIVE_EXIT = (15, 0, 0)`) and the JB source.

---

## 3. Pad Grid Layout (Physical → Note Number Mapping)

### Standard MIDI mode (default)

Pads send note-on/note-off on **channel 10 (0-indexed: 9)**, velocity-sensitive, with poly aftertouch also on channel 9.

The device has 32 pads arranged in a staggered 16×2 layout (16 bottom row, 16 top row). In the default keyboard-scale mode, pad note numbers reflect scale pitch classes:

```python
PAD_NOTES = [
     2,  5,  7,  8,  9, 12, 14, 17, 19, 20, 21, 24, 26, 29, 31, 32,  # bottom row
    33, 36, 38, 41, 43, 44, 45, 48, 50, 53, 55, 56, 57, 60, 62, 65,  # top row
]
```

[SNIFF] Hardware-verified. These are scale-mode note numbers (C,D,F,G,Ab,A pitch classes).

### FL Studio standard mode pad mapping

The FL Studio script [FL] midi_mapping.py:8–9 uses:
- Bottom row: notes 36–51 (continuous chromatic)
- Top row: notes 52–67 (continuous chromatic)

This is a different mapping — it reflects what the device sends when **not** in the default keyboard-scale mode, or when the FL script overrides the scale. The FL lights.py initialises LEDs at note numbers 36–67 [FL] lights.py:46.

**Note on pad LEDs:** The FL source treats pad note numbers as 36–67 for LED addressing (always linear/chromatic). The JB source never writes pad RGB LEDs directly — it only enables them via the SysEx LED enable command. See Section 4.

### Encoder 9 push note (standard mode)

CC 1167: `ENC9_PUSH_NOTE = 96` on channel 9 (PAD_CHANNEL). [SNIFF]

---

## 4. Pad RGB LED Control (Exact Protocol) — **VERIFIED 2026-05-18**

### Protocol

**Hardware-confirmed** via probe.py sniff + Ableton cross-reference. The FL source color labels were wrong; the actual mapping is clean additive RGB.

```
note_on  ch=0  note=<pad_note>  vel=127   — prime: enable the LED
note_on  ch=1  note=<pad_note>  vel=<R>   — red intensity   0–127
note_on  ch=2  note=<pad_note>  vel=<G>   — green intensity 0–127
note_on  ch=3  note=<pad_note>  vel=<B>   — blue intensity  0–127
```

All channels are 0-indexed (mido convention). In MIDI status bytes: 0x90, 0x91, 0x92, 0x93.

- **Prime (ch=0)** must be sent before the color channels. Velocity on prime appears to be ignored beyond enabling the LED; always use 127.
- **To turn off**: send prime ch=0 vel=0, or send all color channels at vel=0.
- **Values**: 0–127 (7-bit MIDI velocity). 0 = off for that component, 127 = full intensity.
- **Pad note numbers**: bottom row 36–51 (pad indices 0–15), top row 52–67 (pad indices 16–31). Linear chromatic addressing.

### Mode requirement — **VERIFIED 2026-05-18 (Studio One proxy sniff)**

The pad LED protocol is the same ch=0–3 note-on format in both standard and native mode. The critical difference is **which port receives the commands**:

| Mode | LED commands sent to |
|------|---------------------|
| Standard MIDI (SONG mode) | ATM SQ (main port) |
| Native mode | **ATM SQ Control port** |

This was the root cause of all failed native-mode LED experiments — we were sending to the wrong port.

**Combined OLED + pad LED protocol** (confirmed via Studio One proxy):
1. Enter native mode → ATM SQ Control port
2. Send pad colors → ATM SQ Control port (same ch=0–3 note-on format)
3. Send OLED SysEx → ATM SQ Control port
4. Pad INPUT continues to arrive on the main ATM SQ port

**Pad mode:** blocks mode (ch=0 notes 36–67) recommended so pad input note numbers match LED addressing. Keys/continuous modes use ch=9 with different note numbers and will not work with Eden's dispatcher.

### Verification sources

- [SNIFF] probe.py hardware test, 2026-05-18: ch=2+vel=127 → green pad confirmed
- [ABLETON] Ableton Live controller script uses ch=1 low velocity for "empty clip" red state; ch=1 vel=127 → bright red confirmed; ch=3 vel=127 → blue confirmed
- [FL] lights.py: same 4-channel structure confirmed, but color labels ("blue", "purple", "yellow") were wrong for this firmware

### Previous hypothesis (superseded)

FL source labelled channels 1/2/3 as blue/purple/yellow. This was incorrect. The actual mapping is R/G/B at channels 1/2/3 respectively.

### RGB value range

Max value is 0x7F = 127 (7-bit MIDI data byte constraint). Consistent with [JB] SysexHandler.java color strings (`"7F0000"` = full red, `"007F00"` = full green, `"00007F"` = full blue).

---

## 5. OLED Display Commands (SysEx Byte Layout)

### Command: SYSEX_CMD_DISPLAY_TEXT (0x12)  — **VERIFIED 2026-05-18**

Full SysEx frame format, derived from [JB] DisplayMode.java lines 67–115 and SysexHandler.java.
**Hardware-confirmed**: text writes, slot addressing, and colored text all work as documented.

```
F0  00 01 06 22  12  <slot_id>  <color_r> <color_g> <color_b>  <align>  <text_bytes...>  F7
```

Field breakdown:
| Offset | Byte(s) | Meaning |
|--------|---------|---------|
| 0 | `F0` | SysEx start |
| 1–3 | `00 01 06` | PreSonus manufacturer ID |
| 4 | `22` | Atom SQ device ID |
| 5 | `12` | Command: DISPLAY_TEXT |
| 6 | `<slot_id>` | OLED slot (0x00–0x0D, see table below) |
| 7–9 | `<RR GG BB>` | Color in 7-bit RGB (each 0x00–0x7F) |
| 10 | `<align>` | `0x00`=center, `0x01`=left, `0x02`=right |
| 11+ | `<text>` | ASCII text bytes (not null-terminated in practice) |
| last | `F7` | SysEx end |

**Example from JB source** [JB] DisplayMode.java:108:
```
SysexBuilder.fromHex("F0 00 01 06 22 12")
  .addByte(sH.MainL1)          // slot = 0x06
  .addHex(sH.yellow)           // "7F7F00" = R=0x7F G=0x7F B=0x00
  .addByte(sH.spc)             // align = 0x00 (center)
  .addString("Track: ", 7)
  .addString(trackName, len)
  .terminate()                 // appends F7
```

Resulting bytes: `F0 00 01 06 22 12 06 7F 7F 00 00 54 72 61 63 6B 3A 20 ... F7`

**Hardcoded example from EditMode** [JB] DisplayMode.java:313:
```
F0 00 01 06 22 12 06 00 5B 5B 00 F7
```
Slot=0x06 (MainL1), color=00 5B 5B (R=0, G=91, B=91 = teal), align=0x00, text=empty (just terminates). This clears/blanks main line 1 with a teal color and no text.

### OLED slot IDs

[JB] SysexHandler.java:10–36:

```
Slot 0x00 = B1L1  (Button 1, line 1 = top label)
Slot 0x01 = B2L1  (Button 2, line 1 = top label)
Slot 0x02 = B3L1  (Button 3, line 1 = top label)
Slot 0x03 = B1L2  (Button 1, line 2 = value/subtitle)
Slot 0x04 = B2L2  (Button 2, line 2 = value/subtitle)
Slot 0x05 = B3L2  (Button 3, line 2 = value/subtitle)
Slot 0x06 = MainL1 (Main display line 1)
Slot 0x07 = MainL2 (Main display line 2)
Slot 0x08 = B4L1  (Button 4, line 1)
Slot 0x09 = B5L1  (Button 5, line 1)
Slot 0x0A = B6L1  (Button 6, line 1)
Slot 0x0B = B4L2  (Button 4, line 2)
Slot 0x0C = B5L2  (Button 5, line 2)
Slot 0x0D = B6L2  (Button 6, line 2)
```

These correspond to the 6 soft keys (3 above the display, 3 below) plus 2 main lines. The physical device has 5 soft keys; JB defines 6 slots. **Confidence: LIKELY** — used consistently in all JB display code.

Note: The `sButtonsTitle[]` array in SysexHandler.java:39 maps button index 0–5 to slots `{0x00, 0x01, 0x02, 0x0D, 0x0C, 0x0B}` — meaning buttons 4/5/6 use the L2 (value) row for their title, not L1. This is an asymmetric arrangement.

### Command: SYSEX_CMD_LED_ENABLE (0x13)

```
F0 00 01 06 22 13 <arg> F7
```

| arg | Effect |
|-----|--------|
| `0x00` | Enable pad LEDs (turns on LED system) |
| `0x01` | Activate display / take control of nav keys |

[JB] DisplayMode.java:159,163. Both are sent during init (step 4 and step 5). They are also sent at the beginning of each mode-switch to re-enable the LED system before writing display text.

### Command: SYSEX_CMD_DISPLAY_MODE (0x14)

```
F0 00 01 06 22 14 <arg> F7
```

| arg | Effect |
|-----|--------|
| `0x00` | DAW mode (show DAW-controlled content) |
| `0x01` | Keyboard mode (show keyboard UI) |

[JB] DisplayMode.java:174–175 (SongMode sends `1400F7` then writes button titles), DisplayMode.java:322 (UserMode sends `1401F7`). **Confidence: LIKELY.**

---

## 6. Button LED Control (Native Mode)

### Mechanism

In native mode, button LEDs are controlled by sending **CC on channel 0** (`0xB0`). Value `0x7F` (127) = LED on, `0x00` = LED off. [JB] AtomSQExtension.java:408:

```java
mMidiOut.sendMidi(0xB0, controlNumber, value ? 127 : 0);
```

The `controlNumber` used here is the **same CC number** the button sends when pressed. In native mode, these CC numbers differ from standard mode (see Section 8).

### Native-mode button LED CC values

Taken from HardwareHandler.java and used as both input (button press) and output (LED control) in native mode:

| Button | Native CC | Hex | Notes |
|--------|-----------|-----|-------|
| SONG | 32 | 0x20 | [JB] HH.java:17 |
| INST | 33 | 0x21 | [JB] HH.java:18 |
| EDIT | 34 | 0x22 | [JB] HH.java:19 |
| USER | 35 | 0x23 | [JB] HH.java:20 |
| SHIFT | 31 | 0x1F | [JB] HH.java:27 |
| BTN_A | 64 | 0x40 | [JB] HH.java:29 |
| PLAY | 109 | 0x6D | [JB] HH.java:12 |
| STOP | 111 | 0x6F | [JB] HH.java:13 |
| REC | 107 | 0x6B | [JB] HH.java:14 |
| METRO | 105 | 0x69 | [JB] HH.java:15 |
| UP | 87 | 0x57 | [JB] HH.java:22 |
| DOWN | 89 | 0x59 | [JB] HH.java:23 |
| LEFT | 90 | 0x5A | [JB] HH.java:24 |
| RIGHT | 102 | 0x66 | [JB] HH.java:25 |
| BACK | 42 | 0x2A | [JB] HH.java:43 |
| FORWARD | 43 | 0x2B | [JB] HH.java:44 |
| Screen BTN 1 | 36 | 0x24 | [JB] HH.java:36 |
| Screen BTN 2 | 37 | 0x25 | [JB] HH.java:37 |
| Screen BTN 3 | 38 | 0x26 | [JB] HH.java:38 |
| Screen BTN 4 | 39 | 0x27 | [JB] HH.java:39 |
| Screen BTN 5 | 40 | 0x28 | [JB] HH.java:40 |
| Screen BTN 6 | 41 | 0x29 | [JB] HH.java:41 |

**Confidence: LIKELY** — these are the values used consistently throughout JB's implementation for both reading button presses and writing LED states.

---

## 7. Encoder Protocol

### Standard MIDI mode

All encoders send **absolute values 0–127** on channel 0. [SNIFF]

| Encoder | CC | Notes |
|---------|----|-------|
| 1 | 14 | [JB] HH.java:66, [SNIFF] |
| 2 | 15 | [JB] (iterated from CC_ENCODER_1 + index) |
| 3 | 16 | [JB] |
| 4 | 17 | [JB] |
| 5 | 18 | [JB] |
| 6 | 19 | [JB] |
| 7 | 20 | [JB] |
| 8 | 21 | [JB] |
| 9 (center) | 1 | CC 1 (mod-wheel slot) in standard mode [SNIFF] |

Encoder 9 push = note 96 on PAD_CHANNEL (ch 9). [SNIFF]

### Native mode encoder protocol

After native-mode init, encoders 1–8 switch to **relative signed-bit** format. [JB] AtomSQExtension.java:438:

```java
encoder.setAdjustValueMatcher(
    mMidiIn.createRelativeSignedBitCCValueMatcher(0, hH.CC_ENCODER_1 + index, 100)
);
```

- Channel: 0
- CC: 14–21 (same as standard mode)
- Format: **signed-bit** — values 1–63 = clockwise, values 65–127 = counterclockwise (bit 6 is the sign bit)
- Sensitivity parameter: 100 (Bitwig-specific scaling)

**Confidence: LIKELY** — `createRelativeSignedBitCCValueMatcher` is a Bitwig API call that definitively sets the expected format. The hardware must be emitting signed-bit relative values in native mode.

### Encoder 9 in native mode

[JB] AtomSQExtension.java:442–443:

```java
encoder.setAdjustValueMatcher(
    mMidiIn.createRelativeSignedBitCCValueMatcher(0, hH.CC_ENCODER_9, 127)
);
```

- CC: 29 (0x1D) — different from standard mode CC 1
- Format: signed-bit relative
- Sensitivity: 127

**Confidence: LIKELY.** The FL source [FL] midi_mapping.py:81 also lists `60: "jog_wheel"` at channel 0 for the jog wheel in standard mode, suggesting the encoder 9 CC may differ between modes. The JB value of CC 29 for native mode is used consistently.

---

## 8. Button/CC Map — Complete Table

### Standard MIDI mode (device → host)

All CCs on channel 0, value 127 = pressed, 0 = released. Confirmed by two or more sources.

| Button | CC | Hex | Source | Confidence |
|--------|----|-----|--------|------------|
| PLAY | 86 | 0x56 | [SNIFF][AK]:136 | VERIFIED |
| STOP | 85 | 0x55 | [SNIFF][AK]:129 | VERIFIED |
| REC | 87 | 0x57 | [SNIFF][AK]:143 | VERIFIED |
| METRO | 89 | 0x59 | [SNIFF][AK]:150 | VERIFIED |
| LEFT arrow | 102 | 0x66 | [SNIFF][AK]:157 | VERIFIED |
| RIGHT arrow | 105 | 0x69 | [SNIFF][AK]:164 | VERIFIED |
| UP arrow | 103 | 0x67 | [SNIFF][AK]:171 | VERIFIED |
| DOWN arrow | 104 | 0x68 | [SNIFF][AK]:178 | VERIFIED |
| SHIFT | 31 | 0x1F | [SNIFF][JB]HH:27 | VERIFIED |
| BTN_A | 64 | 0x40 | [SNIFF][JB]HH:29 | VERIFIED |

Note: The AK source confirms PLAY=0x56, STOP=0x55, REC=0x57, METRO=0x59, LEFT=0x66, RIGHT=0x69, UP=0x67, DOWN=0x68 in standard mode.

### Standard MIDI mode — soft keys (screen buttons)

Channel 2 (0-indexed), CC 24–28, left→right. [SNIFF x2]

| Button | CC | Channel (0-idx) |
|--------|----|-----------------|
| SK1 | 24 | 2 |
| SK2 | 25 | 2 |
| SK3 | 26 | 2 |
| SK4 | 27 | 2 |
| SK5 | 28 | 2 |

The FL source [FL] midi_mapping.py:69–75 confirms channel 2, CC 24–29 (it lists 6 buttons; physical device has 5).

### Native mode (device → host, also host → device for LED)

All CCs on channel 0. [JB] HardwareHandler.java:

| Button | Native CC | Hex |
|--------|-----------|-----|
| SONG | 32 | 0x20 |
| INST | 33 | 0x21 |
| EDIT | 34 | 0x22 |
| USER | 35 | 0x23 |
| BACK | 42 | 0x2A |
| FORWARD | 43 | 0x2B |
| Screen BTN 1 | 36 | 0x24 |
| Screen BTN 2 | 37 | 0x25 |
| Screen BTN 3 | 38 | 0x26 |
| Screen BTN 4 | 39 | 0x27 |
| Screen BTN 5 | 40 | 0x28 |
| Screen BTN 6 | 41 | 0x29 |
| SHIFT | 31 | 0x1F |
| BTN_A | 64 | 0x40 |
| PLAY | 109 | 0x6D |
| STOP | 111 | 0x6F |
| REC | 107 | 0x6B |
| METRO | 105 | 0x69 |
| UP | 87 | 0x57 |
| DOWN | 89 | 0x59 |
| LEFT | 90 | 0x5A |
| RIGHT | 102 | 0x66 |

**Confidence: LIKELY** for all native-mode CCs — they are used consistently in JB's button creation and LED feedback code.

### controller_map.py gap-fill

The following were `None` in `controller_map.py` and are now filled from [JB] HardwareHandler.java:

```python
BTN_SONG    = 32   # CC 0x20  [JB]
BTN_INST    = 33   # CC 0x21  [JB]
BTN_EDIT    = 34   # CC 0x22  [JB]
BTN_USER    = 35   # CC 0x23  [JB]
BTN_BACK    = 42   # CC 0x2A  [JB]
BTN_FORWARD = 43   # CC 0x2B  [JB]
```

**Confidence: LIKELY** for all six — they are the values used in the only working native-mode implementation.

### Discrepancies between standard and native mode CC values

Several buttons send different CC numbers in standard vs native mode:

| Button | Standard mode CC | Native mode CC | Notes |
|--------|-----------------|----------------|-------|
| PLAY | 86 (0x56) | 109 (0x6D) | Both confirmed in respective contexts |
| STOP | 85 (0x55) | 111 (0x6F) | Both confirmed |
| REC | 87 (0x57) | 107 (0x6B) | Both confirmed |
| METRO | 89 (0x59) | 105 (0x69) | Both confirmed |
| LEFT | 102 (0x66) | 90 (0x5A) | Both confirmed |
| RIGHT | 105 (0x69) | 102 (0x66) | Note: LEFT and RIGHT swap in native mode |
| UP | 103 (0x67) | 87 (0x57) | Both confirmed |
| DOWN | 104 (0x68) | 89 (0x59) | Both confirmed |

The remapping is handled internally by the device upon entering native mode. After the `8F 00 01` entry byte, the device begins reporting buttons on their native CCs.

---

## 9. Open Questions (Hardware Testing Required)

### HIGH PRIORITY

1. ~~**Pad RGB in native mode**~~ — **RESOLVED 2026-05-18**. Protocol confirmed: prime ch=0, then ch=1=R, ch=2=G, ch=3=B, all velocity 0–127. Works in standard MIDI mode (SONG mode active). See Section 4.

2. **Button CC values after native-mode entry**: The table in Section 8 shows remapping. Needs hardware sniff to confirm the device actually outputs the native CCs after `8F 00 01`. Specific test: press PLAY before and after native-mode entry; confirm CC changes from 0x56 to 0x6D.

3. **Encoder relative format in native mode**: Are encoders 1–8 already in relative mode before native entry? The JB source uses `createRelativeSignedBitCCValueMatcher` without any mode-switch command to change encoder behavior. The JB init sequence does not include a "switch encoders to relative" SysEx. This may mean the encoders are always relative in the default firmware, or it may mean this is a standard-mode behavior not yet probed. Sniff CC 14–21 while turning encoders before and after native-mode entry.

### MEDIUM PRIORITY

4. **Velocity=1 vs velocity=127 for native entry**: The JB source uses velocity=1 (`8F 00 01`). The probe.py uses velocity=127. Hardware test: try both and observe which one triggers the LED/display change.

5. **SYSEX_CMD_LED_ENABLE 0x13 arg semantics**: JB sends `13 00` (pad LEDs) before `13 01` (display). Is `13 00` necessary, or does `13 01` alone activate both? Does `13 00` only affect pads? The comment says `13 00` "turns on the lights" and `13 01` makes the display and nav keys respond. Test by skipping `13 00`.

6. **SYSEX_CMD_DISPLAY_MODE 0x14 semantics**: JB sends `14 00 F7` (DAW mode) before most mode-switches, then `14 01 F7` (keyboard mode) only for UserMode. Test: does `14 00` clear the display to a blank state? Does `14 01` overlay a keyboard graphic?

7. **Screen button BTN 6 vs physical layout**: JB defines 6 screen button slots (CC 36–41, slots 0x00–0x0D) but the physical device has 5 soft keys. Which slot/CC is absent on the hardware?

8. **SysEx 0x13 0x01 nav key capture**: JB comment says this byte "takes command of the nav keys on the right." Verify: after `13 01`, do LEFT/RIGHT/UP/DOWN arrows stop sending standard CCs (0x66/0x69/0x67/0x68) and only respond to host LED commands?

### LOW PRIORITY

9. **SysEx response from device**: The three Universal Device Inquiry SysEx (`F0 7E 7F 06 01 F7`) messages in the init sequence typically elicit a response (`F0 7E <id> 06 02 ...`). What does the Atom SQ respond with? The AK source logs unhandled SysEx (`"UNHANDLED Sysex " + data`) but never processes incoming SysEx.

10. **OLED color space**: JB uses 7-bit hex triples like `"7F7F00"`. Are these linear 7-bit values, or is there gamma correction? Test by sending a red/green/blue primary at `7F 00 00` and observing actual display color.

11. **Encoder 9 in standard mode**: The FL source [FL] midi_mapping.py:81 shows `60: "jog_wheel"` at channel 0, suggesting Encoder 9 uses CC 60 in the FL mapping. But [SNIFF] says CC 1. These could be two different encoders or a mode difference. Needs targeted sniff.

---

## Appendix: Source Correlation Table

| Constant in controller_map.py | JB value | AK value | FL value | Verdict |
|-------------------------------|----------|----------|----------|---------|
| `BTN_PLAY = 86` | 109 (native) | 0x56=86 (std) | 94 (FL-specific) | Standard=86 ✓ Native=109 — both correct |
| `BTN_STOP = 85` | 111 (native) | 0x55=85 (std) | 93 (FL-specific) | Standard=85 ✓ Native=111 |
| `BTN_REC = 87` | 107 (native) | 0x57=87 (std) | 95 (FL-specific) | Standard=87 ✓ Native=107 |
| `BTN_METRO = 89` | 105 (native) | 0x59=89 (std) | 89 (std, matches!) | Standard=89 ✓ |
| `BTN_LEFT = 102` | 90 (native) | 0x66=102 (std) | 98 (FL-specific) | Standard=102 ✓ |
| `BTN_RIGHT = 105` | 102 (native) | 0x69=105 (std) | 99 (FL-specific) | Standard=105 ✓ |
| `BTN_UP = 103` | 87 (native) | 0x67=103 (std) | — | Standard=103 ✓ |
| `BTN_DOWN = 104` | 89 (native) | 0x68=104 (std) | — | Standard=104 ✓ |
| `NATIVE_ENTER = (15, 0, 1)` | `sendMidi(143,0,1)` | N/A | N/A | **CORRECT — vel=1** |
| `NATIVE_EXIT = (15, 0, 0)` | `sendMidi(143,0,0)` | N/A | N/A | **CORRECT** |
| `ENC_CC = {1:14...8:21}` | CC_ENCODER_1=14, iterated | — | 14–21 [FL] midi_map | VERIFIED |
| `ENC9_NATIVE_CC = 29` | CC_ENCODER_9=29 | — | — | LIKELY |
| `BTN_SONG = None` | CC_SONG=32 | — | — | → 32 (LIKELY) |
| `BTN_INST = None` | CC_INST=33 | — | — | → 33 (LIKELY) |
| `BTN_EDIT = None` | CC_EDIT=34 | — | — | → 34 (LIKELY) |
| `BTN_USER = None` | CC_USER=35 | — | — | → 35 (LIKELY) |
| `BTN_BACK = None` | CC_BACK=42 | — | — | → 42 (LIKELY) |
| `BTN_FORWARD = None` | CC_FORWARD=43 | — | — | → 43 (LIKELY) |

### controller_map.py errors found

1. **`NATIVE_LED_PLAY = 0x6D` (109)** and **`NATIVE_LED_STOP = 0x6F` (111)**: These are correct for native mode. However, `BTN_PLAY = 86` and `BTN_STOP = 85` are standard-mode values. The `NATIVE_LED_*` constants correctly differ from the standard `BTN_*` constants. No error here — the separation is correct.

2. **`BTN_LEFT = 102` vs `NATIVE_LED_LEFT` (absent)**: There is no `NATIVE_LED_LEFT` in `controller_map.py`. In native mode, LEFT uses CC 90 (`0x5A`). This should be added.

3. **`BTN_RIGHT = 105` but RIGHT is CC 102 in native mode**: The native-mode RIGHT CC is 102 (same as standard-mode LEFT). This cross-mapping could cause a bug if code uses `BTN_RIGHT` for LED control in native mode.

4. **probe.py uses velocity=127** for the native-mode handshake: This is **wrong** per the JB source. The correct velocity is 1. The probe should be updated to send `velocity=1`.
