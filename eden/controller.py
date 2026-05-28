"""
controller.py — Python wrapper for the PreSonus Atom SQ MIDI controller.

All protocol constants sourced from controller_map.py and PROTOCOL.md.
Channel numbers are 0-indexed throughout (matching controller_map.py convention).

PORT ARCHITECTURE (confirmed 2026-05-18 via Studio One proxy sniff):
  ATM SQ         — pad/encoder/button INPUT (standard MIDI, always active)
  ATM SQ Control — ALL OUTPUT in native mode: pad LEDs, OLED SysEx, button LEDs, init
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from typing import Callable

_DEBUG_MIDI = os.environ.get("DEBUG_MIDI", "").lower() in ("1", "true", "yes")

import mido

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from controller_map import (
    PAD_CHANNEL,
    PAD_NOTE_TO_INDEX,
    ENC_CHANNEL,
    ENC_CC,
    ENC9_TURN_CC,
    ENC9_NATIVE_CC,
    BTN_CHANNEL,
    BTN_PLAY,
    BTN_STOP,
    BTN_REC,
    BTN_METRO,
    BTN_SONG,
    BTN_INST,
    BTN_EDIT,
    BTN_USER,
    BTN_BACK,
    BTN_FORWARD,
    NATIVE_LED_PLAY,
    NATIVE_LED_STOP,
    NATIVE_LED_REC,
    NATIVE_LED_METRO,
    SYSEX_HEADER,
    SYSEX_CMD_DISPLAY_TEXT,
    SOFT_KEY_CHANNEL,
    SOFT_KEY_CC,
    BTN_SHIFT,
    TOUCHBAR_PITCHWHEEL_CHANNEL,
)
from eden.events import (
    PadPressed,
    PadReleased,
    EncoderTurned,
    MetronomePressed,
    PlusMinusPressed,
    SongSlotPressed,
    TransportPressed,
    ModeButtonPressed,
    ShiftChanged,
    SoftkeyPressed,
    TouchbarMoved,
    ArrowPressed,
)

# ─── Native-mode transport CC table (PROTOCOL.md §8) ─────────────────────────
_NATIVE_TRANSPORT_CC: dict[int, str] = {
    NATIVE_LED_PLAY:  "PLAY",
    NATIVE_LED_STOP:  "STOP",
    NATIVE_LED_REC:   "REC",
    NATIVE_LED_METRO: "METRO",
}

_STD_TRANSPORT_CC: dict[int, str] = {
    BTN_PLAY:  "PLAY",
    BTN_STOP:  "STOP",
    BTN_REC:   "REC",
    BTN_METRO: "METRO",
}

_MODE_BTN_CC: dict[int, str] = {
    BTN_SONG:    "SONG",
    BTN_INST:    "INST",
    BTN_EDIT:    "EDIT",
    BTN_USER:    "USER",
    BTN_BACK:    "BACK",
    BTN_FORWARD: "FORWARD",
}

_ENC_CC_TO_NUM: dict[int, int] = {v: k for k, v in ENC_CC.items()}


class AtomSQ:
    def __init__(self, port_hint: str = "atm sq", event_queue: queue.SimpleQueue | None = None) -> None:
        """
        Open MIDI I/O for the Atom SQ.

        Opens two separate output ports:
          self._out      — ATM SQ main port (standard MIDI output, rarely used)
          self._ctrl_out — ATM SQ Control port (ALL native-mode output: LEDs, OLED, init)
        Input comes from ATM SQ main port only.

        event_queue: optional queue.SimpleQueue to receive Event dataclass instances
                     alongside the existing callback system. Both dispatch paths are
                     active simultaneously when provided.
        """
        hint = port_hint.lower()
        all_outs = [p for p in mido.get_output_names() if hint in p.lower()]
        all_ins  = [p for p in mido.get_input_names()  if hint in p.lower()]

        primary_outs = [p for p in all_outs if "control" not in p.lower()]
        control_outs = [p for p in all_outs if "control"     in p.lower()]
        primary_ins  = [p for p in all_ins  if "control" not in p.lower()]

        if not primary_outs:
            print(f"[AtomSQ] WARNING: no primary output matching '{port_hint}'")
        if not control_outs:
            print(f"[AtomSQ] WARNING: ATM SQ Control port not found — native mode disabled")
        if not primary_ins:
            print(f"[AtomSQ] WARNING: no input matching '{port_hint}'")

        self._out      = mido.open_output(primary_outs[0]) if primary_outs else None
        self._ctrl_out = mido.open_output(control_outs[0]) if control_outs else None
        self._in       = mido.open_input(primary_ins[0])   if primary_ins  else None

        self._native_mode: bool = False
        self._enc_last: dict[int, int | None] = {n: None for n in range(1, 10)}

        self._event_queue: queue.SimpleQueue | None = event_queue

        self._cb_pad_press:   Callable[[int, int], None] | None = None
        self._cb_pad_release: Callable[[int], None] | None = None
        self._cb_enc_delta:   Callable[[int, int], None] | None = None
        self._cb_mode_btn:    Callable[[str, bool], None] | None = None
        self._cb_transport:   Callable[[str, bool], None] | None = None
        self._cb_shift:       Callable[[bool], None] | None = None
        self._cb_softkey:     Callable[[int], None] | None = None

        self._listener_thread: threading.Thread | None = None
        self._listening: bool = False

    # ─── MIDI send helpers ────────────────────────────────────────────────────

    def _send(self, msg: mido.Message) -> None:
        """Send to the main ATM SQ port (standard MIDI)."""
        if self._out:
            self._out.send(msg)

    def _ctrl_send(self, msg: mido.Message) -> None:
        """Send to ATM SQ Control port (native-mode LEDs, OLED, init)."""
        if self._ctrl_out:
            self._ctrl_out.send(msg)

    def _send_cc(self, channel: int, control: int, value: int) -> None:
        self._send(mido.Message("control_change", channel=channel, control=control, value=value))

    def _ctrl_send_cc(self, channel: int, control: int, value: int) -> None:
        self._ctrl_send(mido.Message("control_change", channel=channel, control=control, value=value))

    def _send_note_off(self, channel: int, note: int, velocity: int) -> None:
        self._send(mido.Message("note_off", channel=channel, note=note, velocity=velocity))

    def _ctrl_send_note_off(self, channel: int, note: int, velocity: int) -> None:
        self._ctrl_send(mido.Message("note_off", channel=channel, note=note, velocity=velocity))

    def _send_note_on(self, channel: int, note: int, velocity: int) -> None:
        self._send(mido.Message("note_on", channel=channel, note=note, velocity=velocity))

    def _ctrl_send_note_on(self, channel: int, note: int, velocity: int) -> None:
        self._ctrl_send(mido.Message("note_on", channel=channel, note=note, velocity=velocity))

    def _send_sysex(self, data: tuple[int, ...] | list[int]) -> None:
        self._send(mido.Message("sysex", data=tuple(data)))

    def _ctrl_send_sysex(self, data: tuple[int, ...] | list[int]) -> None:
        self._ctrl_send(mido.Message("sysex", data=tuple(data)))

    # ─── Native-mode entry / exit ─────────────────────────────────────────────

    def enter_native_mode(self) -> None:
        """
        Enter native mode + DAW mode via ATM SQ main port.

        Confirmed working 2026-05-18:
          1. JB 5-step init via main port (cold-safe)
          2. DAW mode SysEx (0x14 00) — hands pad LED control to host

        All output (init, OLED, pad RGB) goes to ATM SQ main port.
        Pad input arrives on ATM SQ main port (unchanged).
        ATM SQ Control port is not used (Studio One uses it but main port works too).
        """
        _ENC_CCS = [29, 15, 16, 17, 18, 19, 20, 21]
        for _ in range(3):
            for cc in _ENC_CCS:
                self._send_cc(0, cc, 0)
            self._send_note_off(15, 0, 0)
        for _ in range(3):
            self._send_sysex((0x7E, 0x7F, 0x06, 0x01))
        self._send_note_off(15, 0, 1)
        self._send_sysex((0x00, 0x01, 0x06, 0x22, 0x14, 0x00))
        self._native_mode = True

    def exit_native_mode(self) -> None:
        """Restore standard mode."""
        self._send_note_off(15, 0, 0)
        self._native_mode = False

    # ─── Output: LEDs and display ─────────────────────────────────────────────

    def set_pad_color(self, pad_note: int, r: int, g: int, b: int) -> None:
        """
        Set an individual pad's RGB color via ATM SQ main port.
        pad_note: 36–67 (bottom row 36–51, top row 52–67)
        r, g, b: 0–127 (7-bit intensity)

        Requires DAW mode active (enter_native_mode sends 0x14 00).
          note_on ch=0 note=pad_note vel=127  — prime
          note_on ch=1 note=pad_note vel=r
          note_on ch=2 note=pad_note vel=g
          note_on ch=3 note=pad_note vel=b
        """
        self._send_note_on(0, pad_note, 127)
        self._send_note_on(1, pad_note, r & 0x7F)
        self._send_note_on(2, pad_note, g & 0x7F)
        self._send_note_on(3, pad_note, b & 0x7F)

    def set_button_led(self, cc: int, on: bool) -> None:
        """
        Set a button LED on/off.
        cc: native-mode CC number (NATIVE_LED_* from controller_map.py)
        """
        self._send_cc(BTN_CHANNEL, cc, 127 if on else 0)

    def write_oled(
        self,
        slot: int,
        text: str,
        r: int = 0x7F,
        g: int = 0x7F,
        b: int = 0x7F,
        align: int = 0x00,
    ) -> None:
        """
        Write text to an OLED display slot via ATM SQ Control port.
        slot: 0x00–0x0D (see OLED_* constants in controller_map.py)
        r, g, b: 0–0x7F (7-bit, default white)
        align: 0x00=center, 0x01=left, 0x02=right
        """
        text_bytes = [b & 0x7F for b in text.encode("ascii", errors="replace")]
        payload = (
            *SYSEX_HEADER,
            SYSEX_CMD_DISPLAY_TEXT,
            slot & 0x7F,
            r & 0x7F,
            g & 0x7F,
            b & 0x7F,
            align & 0x7F,
            *text_bytes,
        )
        self._send_sysex(payload)

    # ─── Input: callback registration ─────────────────────────────────────────

    def on_pad_press(self, callback: Callable[[int, int], None]) -> None:
        """callback(pad_index: int, velocity: int) — pad_index 0–31"""
        self._cb_pad_press = callback

    def on_pad_release(self, callback: Callable[[int], None]) -> None:
        """callback(pad_index: int)"""
        self._cb_pad_release = callback

    def on_encoder_delta(self, callback: Callable[[int, int], None]) -> None:
        """callback(encoder_num: int, delta: int) — encoder_num 1–9"""
        self._cb_enc_delta = callback

    def on_mode_button(self, callback: Callable[[str, bool], None]) -> None:
        """callback(button_name: str, pressed: bool)"""
        self._cb_mode_btn = callback

    def on_transport_button(self, callback: Callable[[str, bool], None]) -> None:
        """callback(button_name: str, pressed: bool)"""
        self._cb_transport = callback

    def on_shift(self, callback: Callable[[bool], None]) -> None:
        """callback(held: bool) — True on press, False on release"""
        self._cb_shift = callback

    def on_softkey(self, callback: Callable[[int], None]) -> None:
        """callback(key_index: int) — key_index 0-4 (SK1-SK5)"""
        self._cb_softkey = callback

    # ─── Listener thread ──────────────────────────────────────────────────────

    def start_listening(self) -> None:
        if self._listening or self._in is None:
            return
        self._listening = True
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._listener_thread.start()

    def stop_listening(self) -> None:
        self._listening = False
        if self._listener_thread:
            self._listener_thread.join(timeout=1.0)
            self._listener_thread = None

    def _listen_loop(self) -> None:
        while self._listening and self._in:
            for msg in self._in.iter_pending():
                self._dispatch_midi(msg)
            time.sleep(0.001)

    # ─── MIDI dispatch ────────────────────────────────────────────────────────

    def _dispatch_midi(self, msg: mido.Message) -> None:
        if not hasattr(msg, "channel"):
            return  # sysex, clock, active-sense — no channel attribute

        if msg.type == "pitchwheel" and msg.channel == TOUCHBAR_PITCHWHEEL_CHANNEL:
            position = (msg.pitch + 8192) / 16383.0
            if self._event_queue:
                self._event_queue.put(TouchbarMoved(position=position))
            return

        if _DEBUG_MIDI and msg.type == "control_change":
            print(f"[MIDI] cc ch={msg.channel} ctrl={msg.control} val={msg.value}")

        # +/- buttons: channel 0, notes 0-1.  [SNIFF: note=0 → "-", note=1 → "+"]
        if msg.channel == 0 and msg.type in ("note_on", "note_off") and msg.note in (0, 1):
            button = "-" if msg.note == 0 else "+"
            pressed = msg.type == "note_on" and msg.velocity > 0
            if self._event_queue:
                self._event_queue.put(PlusMinusPressed(button=button, pressed=pressed))
            return

        # Blocks-mode pad presses: channel 0, notes 36-67 (linear chromatic).
        # Confirmed in both standard mode and native mode via hardware sniff.
        if msg.channel == 0 and msg.type in ("note_on", "note_off") and 36 <= msg.note <= 67:
            pad_idx = msg.note - 36
            if msg.type == "note_on" and msg.velocity > 0:
                if self._event_queue:
                    self._event_queue.put(PadPressed(pad_index=pad_idx, velocity=msg.velocity))
                if self._cb_pad_press:
                    self._cb_pad_press(pad_idx, msg.velocity)
            else:
                if self._event_queue:
                    self._event_queue.put(PadReleased(pad_index=pad_idx))
                if self._cb_pad_release:
                    self._cb_pad_release(pad_idx)
            return

        # Keys/scale-mode pad presses: channel 9, scale-mode note numbers.
        if msg.type == "note_on" and msg.channel == PAD_CHANNEL:
            pad_idx = PAD_NOTE_TO_INDEX.get(msg.note)
            if pad_idx is None:
                return
            if msg.velocity > 0:
                if self._event_queue:
                    self._event_queue.put(PadPressed(pad_index=pad_idx, velocity=msg.velocity))
                if self._cb_pad_press:
                    self._cb_pad_press(pad_idx, msg.velocity)
            else:
                if self._event_queue:
                    self._event_queue.put(PadReleased(pad_index=pad_idx))
                if self._cb_pad_release:
                    self._cb_pad_release(pad_idx)
            return

        if msg.type == "note_off" and msg.channel == PAD_CHANNEL:
            pad_idx = PAD_NOTE_TO_INDEX.get(msg.note)
            if pad_idx is not None:
                if self._event_queue:
                    self._event_queue.put(PadReleased(pad_index=pad_idx))
                if self._cb_pad_release:
                    self._cb_pad_release(pad_idx)
            return

        if msg.type == "control_change" and msg.channel == ENC_CHANNEL:
            cc, value = msg.control, msg.value

            if cc in _ENC_CC_TO_NUM:
                enc_num = _ENC_CC_TO_NUM[cc]
                delta = self._decode_encoder_delta(enc_num, value)
                if delta != 0:
                    if self._event_queue:
                        self._event_queue.put(EncoderTurned(encoder=enc_num, delta=delta))
                    if self._cb_enc_delta:
                        self._cb_enc_delta(enc_num, delta)
                return

            if cc == ENC9_TURN_CC and not self._native_mode:
                delta = self._decode_encoder_delta(9, value)
                if delta != 0:
                    if self._event_queue:
                        self._event_queue.put(EncoderTurned(encoder=9, delta=delta))
                    if self._cb_enc_delta:
                        self._cb_enc_delta(9, delta)
                return

            if cc == ENC9_NATIVE_CC and self._native_mode:
                delta = value if value < 64 else -(value - 64)  # signed-magnitude [SNIFF: CCW=0x41]
                if delta != 0:
                    if self._event_queue:
                        self._event_queue.put(EncoderTurned(encoder=9, delta=delta))
                    if self._cb_enc_delta:
                        self._cb_enc_delta(9, delta)
                return

            transport_table = _NATIVE_TRANSPORT_CC if self._native_mode else _STD_TRANSPORT_CC
            if cc in transport_table:
                name = transport_table[cc]
                pressed = (value == 127)
                if name == "METRO":
                    if self._event_queue:
                        self._event_queue.put(MetronomePressed(pressed=pressed))
                    return
                if self._event_queue:
                    self._event_queue.put(TransportPressed(button=name, pressed=pressed))
                if self._cb_transport:
                    self._cb_transport(name, pressed)
                return

            # SHIFT button: CC 31, channel 0 (BTN_CHANNEL == ENC_CHANNEL == 0).  [SNIFF+JB]
            if cc == BTN_SHIFT:
                held = (value == 127)
                if self._event_queue:
                    self._event_queue.put(ShiftChanged(held=held))
                if self._cb_shift:
                    self._cb_shift(held)
                return

            # Song slot buttons A-H: CC 0-7, channel 0, native mode only.  [SNIFF]
            if 0 <= cc <= 7 and self._native_mode:
                pressed = (value == 127)
                if self._event_queue:
                    self._event_queue.put(SongSlotPressed(slot=cc, pressed=pressed))
                return

            # Arrow keys: CC 90 = left, CC 102 = right, channel 0.  [SNIFF]
            if cc == 90 or cc == 102:
                direction = "LEFT" if cc == 90 else "RIGHT"
                pressed = (value == 127)
                if self._event_queue:
                    self._event_queue.put(ArrowPressed(direction=direction, pressed=pressed))
                return

            if cc in _MODE_BTN_CC:
                name = _MODE_BTN_CC[cc]
                pressed = (value == 127)
                if self._event_queue:
                    self._event_queue.put(ModeButtonPressed(button=name, pressed=pressed))
                if self._cb_mode_btn:
                    self._cb_mode_btn(name, pressed)
                return

        # Screen soft keys: channel 2, CC 24-28, left→right (SK1-SK5).  [SNIFF x2]
        # Value 127 = pressed; these keys do not send a separate release message.  # UNVERIFIED: no separate release confirmed on hardware
        if msg.type == "control_change" and msg.channel == SOFT_KEY_CHANNEL:
            if msg.control in SOFT_KEY_CC:
                key_idx = SOFT_KEY_CC.index(msg.control)
                if msg.value == 127:  # pressed only (soft keys don't have separate release)
                    if self._event_queue:
                        self._event_queue.put(SoftkeyPressed(key=key_idx))
                    if self._cb_softkey:
                        self._cb_softkey(key_idx)
                return

    def _decode_encoder_delta(self, enc_num: int, value: int) -> int:
        if self._native_mode and enc_num != 9:
            return value if value < 64 else -(value - 64)  # signed-magnitude
        last = self._enc_last.get(enc_num)
        self._enc_last[enc_num] = value
        if last is None:
            return 0
        delta = value - last
        if delta > 64:
            delta -= 128
        elif delta < -64:
            delta += 128
        return delta

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Exit native mode (if active) and close all MIDI ports."""
        self.stop_listening()
        if self._native_mode:
            self.exit_native_mode()
        if self._ctrl_out:
            self._ctrl_out.close()
        if self._out:
            self._out.close()
        if self._in:
            self._in.close()
