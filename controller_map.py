"""
controller_map.py — PreSonus ATOM SQ protocol constants.

Sources:
  - Baseline MIDI sniff, hardware-verified 2026-05-18  [SNIFF]
  - JamesB-VS/AtomSQ_Bitwig Java source (native-mode protocol) [JB]
  - alt-key-project/Bitwig-extension-Atom-SQ-MIDI-mode source  [AK]

Channel numbers are 0-indexed throughout (MIDI ch 1 = 0, ch 10 = 9, ch 16 = 15).
Lines marked UNVERIFIED have not been confirmed on hardware.
Lines marked NATIVE-ONLY apply only after the full native-mode init sequence.
"""

# ─── Pad grid ──────────────────────────────────────────────────────────────────
# 32 pads in staggered 16×2 layout. Default mode: keyboard scale.            [SNIFF]
# Channel 10 (index 9), velocity-sensitive, plus channel-pressure aftertouch.
# Scale pitch classes per octave: {0,2,5,7,8,9} = C,D,F,G,Ab,A.
# Pad indices 0–31 correspond to physical left→right order.

PAD_CHANNEL = 9

PAD_NOTES = [
     2,  5,  7,  8,  9, 12, 14, 17, 19, 20, 21, 24, 26, 29, 31, 32,
    33, 36, 38, 41, 43, 44, 45, 48, 50, 53, 55, 56, 57, 60, 62, 65,
]

PAD_NOTE_TO_INDEX = {n: i for i, n in enumerate(PAD_NOTES)}

# ─── Encoders (standard MIDI mode) ────────────────────────────────────────────
# Encoders 1–8 are touch-sensitive endless rotaries.                          [SNIFF]
# Encoder 9 is the large center encoder.
# In standard MIDI mode all encoders send ABSOLUTE values (0–127).
# After native-mode init, encoders 1–8 switch to relative signed-bit.        [JB UNVERIFIED]

ENC_CHANNEL = 0

ENC_CC = {1: 14, 2: 15, 3: 16, 4: 17, 5: 18, 6: 19, 7: 20, 8: 21}  # encoder# → CC

ENC9_TURN_CC    = 1    # CC 1 (mod-wheel slot) in standard MIDI mode     [SNIFF]
ENC9_PUSH_NOTE  = 96   # note on PAD_CHANNEL in standard MIDI mode        [SNIFF]

# Native mode encoder 9 CC (turn only; push may also change):               [JB UNVERIFIED]
ENC9_NATIVE_CC  = 29   # CC 0x1D

# ─── Transport / global buttons (standard MIDI mode) ──────────────────────────
# Channel 0. Value 0x7F = pressed, 0x00 = released.                          [SNIFF]

BTN_CHANNEL = 0

BTN_PLAY  = 86   # CC 0x56
BTN_STOP  = 85   # CC 0x55
BTN_REC   = 87   # CC 0x57
BTN_METRO = 89   # CC 0x59
BTN_A     = 64   # CC 0x40

BTN_LEFT  = 102  # CC 0x66
BTN_UP    = 103  # CC 0x67
BTN_DOWN  = 104  # CC 0x68
BTN_RIGHT = 105  # CC 0x69

BTN_SHIFT = 31   # CC 0x1F                                                   [SNIFF+JB]

# Mode buttons — native-mode CC values from [JB] HardwareHandler.java.        [JB LIKELY]
# These are the values the device sends in native mode AND what the host
# sends to control the button LEDs (same CC number, same channel).
# Standard-mode CCs for these buttons have not been sniffed yet.
BTN_SONG    = 32   # CC 0x20
BTN_INST    = 33   # CC 0x21
BTN_EDIT    = 34   # CC 0x22
BTN_USER    = 35   # CC 0x23
BTN_BACK    = 42   # CC 0x2A
BTN_FORWARD = 43   # CC 0x2B

# ─── Screen soft keys (native mode, hardware-verified 2026-05-27) ────────────
# 6 soft keys on channel 0 (MIDI ch 1), CC 36–41, left→right order.         [SNIFF]
# Physical order: SK1=CC36, SK2=CC37, SK3=CC38, SK4=CC39, SK5=CC40, SK6=CC41.
# Press = value 127, release = value 0 (both sent; only press is dispatched).
# Previous values (ch 2, CC 24–28) were wrong — not verified against hardware.

SOFT_KEY_CHANNEL = 0
SOFT_KEY_CC = [36, 37, 38, 39, 40, 41]

# ─── Native-mode protocol ─────────────────────────────────────────────────────

PRESONUS_SYSEX_ID = (0x00, 0x01, 0x06)   # 3-byte manufacturer ID           [JB]
ATOMSQ_DEVICE_ID  = 0x22                  # product byte                     [JB]

SYSEX_CMD_DISPLAY_TEXT  = 0x12           # write text to OLED slot           [JB]
SYSEX_CMD_LED_ENABLE    = 0x13           # 0x00=off 0x01=on                  [JB]
SYSEX_CMD_DISPLAY_MODE  = 0x14           # 0x00=DAW 0x01=keyboard            [JB]

SYSEX_HEADER = bytes([0x00, 0x01, 0x06, 0x22])  # manufacturer + device

# OLED display slot IDs (argument to SYSEX_CMD_DISPLAY_TEXT)                 [JB]
OLED_BTN1_TITLE  = 0x00
OLED_BTN2_TITLE  = 0x01
OLED_BTN3_TITLE  = 0x02
OLED_BTN1_VALUE  = 0x03
OLED_BTN2_VALUE  = 0x04
OLED_BTN3_VALUE  = 0x05
OLED_MAIN_LINE1  = 0x06
OLED_MAIN_LINE2  = 0x07
OLED_BTN4_TITLE  = 0x08
OLED_BTN5_TITLE  = 0x09
OLED_BTN6_TITLE  = 0x0A
OLED_BTN4_VALUE  = 0x0B
OLED_BTN5_VALUE  = 0x0C
OLED_BTN6_VALUE  = 0x0D

OLED_ALIGN_CENTER = 0x00
OLED_ALIGN_LEFT   = 0x01
OLED_ALIGN_RIGHT  = 0x02

# RGB range is 0–0x7F (7-bit MIDI data bytes).                               [JB]
# Button LED control (host→device): CC on channel 0, 0x7F=on 0x00=off.      [JB UNVERIFIED]
# Native-mode LED CC values differ from standard-mode values above.
NATIVE_LED_PLAY  = 0x6D
NATIVE_LED_STOP  = 0x6F
NATIVE_LED_REC   = 0x6B
NATIVE_LED_METRO = 0x69
NATIVE_LED_SONG  = 0x20
NATIVE_LED_INST  = 0x21
NATIVE_LED_EDIT  = 0x22
NATIVE_LED_USER  = 0x23
NATIVE_LED_SHIFT = 0x1F

# Native-mode init sequence — from [JB] DisplayMode.java:122–163.             [JB LIKELY]
# NOTE: Steps 1–2 are each sent THREE times; steps 3–5 are sent once.
#   Step 1 (×3): CC reset on ch 0 — CC 29,15,16,17,18,19,20,21 = 0
#   Step 1 (×3): note_off ch=15 note=0 vel=0   (within each reset block)
#   Step 2 (×3): SysEx F0 7E 7F 06 01 F7       (Universal Device Inquiry)
#   Step 3:      note_off ch=15 note=0 vel=1   (enter native mode — vel=1, NOT 127)
#   Step 4:      SysEx F0 00 01 06 22 13 00 F7 (enable pad LEDs)
#   Step 5:      SysEx F0 00 01 06 22 13 01 F7 (activate display + take nav keys)
# Exit:          note_off ch=15 note=0 vel=0
# NOTE: probe.py previously sent vel=127 for entry — that was wrong (KVR rumour).

NATIVE_ENTER = (15, 0, 1)   # (channel, note, velocity) for note_off
NATIVE_EXIT  = (15, 0, 0)
