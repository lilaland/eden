"""
atomsq_probe.py — Discovery tool for the PreSonus Atom SQ.

Purpose:
    - List MIDI ports and identify the Atom SQ ones
    - Sniff every byte the controller sends (notes, CCs, SysEx, aftertouch)
    - Send experimental messages BACK to the device to test:
        * LED control via channels 2/3/4 (the R/G/B theory from KVR forum)
        * The "native mode" handshake (C-2 note-off vel 127 on ch 16)
        * Arbitrary SysEx for OLED text
    - Tag every event with elapsed time and pretty-print

Dependencies:
    pip install mido python-rtmidi

Usage:
    python atomsq_probe.py list           # show ports
    python atomsq_probe.py sniff          # log incoming MIDI forever
    python atomsq_probe.py handshake      # try native-mode handshake
    python atomsq_probe.py rgb 5 127 0 0  # light pad 5 red (note num, R, G, B)
    python atomsq_probe.py sysex 7E 7F 06 01    # send arbitrary SysEx bytes
"""

import sys
import time
import mido


# --- port discovery -----------------------------------------------------------

ATOMSQ_HINTS = ("atom sq", "atm sq", "atomsq")


def find_ports():
    """Return (input_name, output_name) for the Atom SQ note/cc port.

    The device exposes TWO ports: 'ATM SQ' (notes/CC) and 'ATM SQ Control'
    (transport/screen on natively-supported DAWs). We grab both pairs if
    available and let the caller pick.
    """
    ins = [p for p in mido.get_input_names() if any(h in p.lower() for h in ATOMSQ_HINTS)]
    outs = [p for p in mido.get_output_names() if any(h in p.lower() for h in ATOMSQ_HINTS)]
    return ins, outs


def cmd_list():
    print("All MIDI inputs:")
    for p in mido.get_input_names():
        print(f"  {p}")
    print("\nAll MIDI outputs:")
    for p in mido.get_output_names():
        print(f"  {p}")
    ins, outs = find_ports()
    print(f"\nLikely Atom SQ inputs:  {ins}")
    print(f"Likely Atom SQ outputs: {outs}")


# --- sniffing -----------------------------------------------------------------

def pretty(msg, t0):
    """Format a mido message with elapsed time and raw bytes."""
    elapsed = f"{(time.perf_counter() - t0) * 1000:8.1f}ms"
    try:
        raw = " ".join(f"{b:02X}" for b in msg.bytes())
    except Exception:
        raw = "?"
    return f"[{elapsed}]  {raw:32s}  {msg}"


def cmd_sniff():
    ins, _ = find_ports()
    if not ins:
        print("No Atom SQ input found. Run `list` to see all ports.")
        return
    print(f"Sniffing on: {ins}")
    print("Press buttons, pads, encoders. Ctrl-C to stop.\n")
    t0 = time.perf_counter()
    # Open every Atom SQ port simultaneously so we capture both 'ATM SQ' and
    # 'ATM SQ Control'.
    ports = [mido.open_input(name) for name in ins]
    try:
        while True:
            for p in ports:
                for msg in p.iter_pending():
                    src = p.name.replace("PreSonus ", "")
                    print(f"{src:20s}  {pretty(msg, t0)}")
            time.sleep(0.001)  # cheap busy-loop; fine for a probe tool
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for p in ports:
            p.close()


# --- sending experimental messages -------------------------------------------

def pick_output():
    _, outs = find_ports()
    if not outs:
        raise SystemExit("No Atom SQ output found. Run `list`.")
    # Prefer the non-'Control' port for note/cc style messages.
    primary = next((p for p in outs if "control" not in p.lower()), outs[0])
    return mido.open_output(primary), primary


def cmd_handshake():
    """Send the native-mode entry sequence derived from [JB] DisplayMode.java:122–163.

    Correct velocity for entry is 1 (not 127 — the KVR forum rumour was wrong;
    JB source uses sendMidi(143, 0, 1) which is note_off ch=15 note=0 vel=1).
    The full sequence resets encoders, sends Universal Device Inquiry ×3, then
    sends the entry byte. Partial sequences may not work — send all steps.
    """
    out, name = pick_output()
    try:
        # Step 1 (×3): reset encoder CCs + note_off vel=0
        ENCODER_CCS = [29, 15, 16, 17, 18, 19, 20, 21]
        for _ in range(3):
            for cc in ENCODER_CCS:
                out.send(mido.Message("control_change", channel=0, control=cc, value=0))
            out.send(mido.Message("note_off", channel=15, note=0, velocity=0))

        # Step 2 (×3): Universal Device Inquiry SysEx
        for _ in range(3):
            out.send(mido.Message("sysex", data=(0x7E, 0x7F, 0x06, 0x01)))

        # Step 3: enter native mode — velocity=1, NOT 127
        msg = mido.Message("note_off", channel=15, note=0, velocity=1)
        print(f"Sending to {name}: {msg}  (bytes: {' '.join(f'{b:02X}' for b in msg.bytes())})")
        out.send(msg)

        # Step 4: enable pad LEDs
        out.send(mido.Message("sysex", data=(0x00, 0x01, 0x06, 0x22, 0x13, 0x00)))
        # Step 5: activate display / take nav keys
        out.send(mido.Message("sysex", data=(0x00, 0x01, 0x06, 0x22, 0x13, 0x01)))

        print("Full init sequence sent. Now run `sniff` in another terminal and press buttons —")
        print("look for CC remapping (PLAY should now be CC 0x6D instead of 0x56).")
    finally:
        out.close()


def cmd_rgb(note: int, r: int, g: int, b: int):
    """Set pad `note` to an RGB color. VERIFIED 2026-05-18.

    Protocol: prime on ch=0, then ch=1=R, ch=2=G, ch=3=B (all 0-indexed).
    Pad note numbers: 36–51 bottom row, 52–67 top row (linear chromatic).
    Values 0–127. Works in standard MIDI mode with SONG mode active on device.

    Example: python probe.py rgb 36 0 127 0   → pad 0 green
             python probe.py rgb 36 127 0 0   → pad 0 red
             python probe.py rgb 36 0 0 127   → pad 0 blue
    """
    out, name = pick_output()
    try:
        # Prime — enables the LED
        prime = mido.Message("note_on", channel=0, note=note, velocity=127)
        out.send(prime)
        time.sleep(0.005)
        for ch, val, label in [(1, r, "R"), (2, g, "G"), (3, b, "B")]:
            msg = mido.Message("note_on", channel=ch, note=note, velocity=val)
            print(f"  {label}: {msg}  bytes={' '.join(f'{x:02X}' for x in msg.bytes())}")
            out.send(msg)
            time.sleep(0.005)
        print(f"Sent RGB({r},{g},{b}) to pad note {note} on {name}.")
    finally:
        out.close()


def cmd_sysex(*hex_bytes):
    """Send an arbitrary SysEx payload (without F0/F7 framing).

    Example:
        python probe.py sysex 7E 7F 06 01
    sends the universal "device inquiry" — useful to confirm comms.
    """
    out, name = pick_output()
    try:
        data = tuple(int(h, 16) for h in hex_bytes)
        msg = mido.Message("sysex", data=data)
        print(f"Sending to {name}: F0 {' '.join(f'{b:02X}' for b in data)} F7")
        out.send(msg)
        print("Sent. Sniff to see if the device replies.")
    finally:
        out.close()


def cmd_probe_pad(note: int, r: int, g: int, b: int):
    """Brute-force probe for pad LED SysEx command byte.

    The JB source never sets individual pad colors — it's simply not implemented.
    OLED text uses command 0x12. Pad colors likely use a different command byte.
    This command tries every PreSonus SysEx command byte 0x00–0x1F for the given
    pad note and RGB values. Watch the pad with your eyes; note which command byte
    causes a color change.

    Run `handshake` first to enter native mode, then:
        python probe.py probe_pad 36 64 0 0   # probe pad at note 36 with red

    Format tried: F0 00 01 06 22 <cmd> <note> <r> <g> <b> F7
    """
    PRESONUS_HEADER = (0x00, 0x01, 0x06, 0x22)
    out, name = pick_output()
    try:
        print(f"Probing pad note={note} RGB=({r},{g},{b}) on {name}")
        print("Trying command bytes 0x00–0x1F (0.15s each). Watch the pad...")
        for cmd in range(0x20):
            data = (*PRESONUS_HEADER, cmd, note & 0x7F, r & 0x7F, g & 0x7F, b & 0x7F)
            msg = mido.Message("sysex", data=data)
            hex_str = " ".join(f"{b:02X}" for b in data)
            print(f"  cmd=0x{cmd:02X}: F0 {hex_str} F7", end="  ", flush=True)
            out.send(msg)
            time.sleep(0.15)
            print()
        print("Done. If a pad changed color, re-run with just that command byte using `sysex`.")
    finally:
        out.close()


def cmd_pad_off(note: int):
    """Turn off a pad LED (set all channels to 0).

    python probe.py pad_off 36
    """
    out, name = pick_output()
    try:
        out.send(mido.Message("note_on", channel=0, note=note, velocity=0))
        for ch in [1, 2, 3]:
            out.send(mido.Message("note_on", channel=ch, note=note, velocity=0))
        print(f"Cleared pad note {note} on {name}.")
    finally:
        out.close()


def _send_rgb(out, note: int, r: int, g: int, b: int):
    out.send(mido.Message("note_on", channel=0, note=note, velocity=127))
    time.sleep(0.005)
    out.send(mido.Message("note_on", channel=1, note=note, velocity=r))
    out.send(mido.Message("note_on", channel=2, note=note, velocity=g))
    out.send(mido.Message("note_on", channel=3, note=note, velocity=b))


def _send_oled_text(out, slot: int, text: str, r=0x7F, g=0x7F, b=0x7F):
    text_bytes = [c & 0x7F for c in text.encode("ascii", errors="replace")]
    out.send(mido.Message("sysex", data=(0x00, 0x01, 0x06, 0x22, 0x12, slot, r, g, b, 0x00, *text_bytes)))


def _do_native_init(out, daw_mode: bool = False):
    """Send full native-mode init to `out`.

    daw_mode=True appends `14 00` (DAW mode — host takes display + pad LED control).
    daw_mode=False leaves device in keyboard mode (device firmware draws pads).
    JB source sends `14 00` in every SongMode init before writing OLED content.
    """
    ENCODER_CCS = [29, 15, 16, 17, 18, 19, 20, 21]
    for _ in range(3):
        for cc in ENCODER_CCS:
            out.send(mido.Message("control_change", channel=0, control=cc, value=0))
        out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
    for _ in range(3):
        out.send(mido.Message("sysex", data=(0x7E, 0x7F, 0x06, 0x01)))
    out.send(mido.Message("note_off", channel=15, note=0, velocity=1))
    if daw_mode:
        # Switch device from keyboard mode (firmware draws pads) to DAW mode
        # (host controls display and pad LEDs). [JB] DisplayMode.java:174.
        out.send(mido.Message("sysex", data=(0x00, 0x01, 0x06, 0x22, 0x14, 0x00)))
    time.sleep(0.3)


def cmd_rgb_daw():
    """Test: native mode + DAW mode (14 00) + note-on RGB + OLED simultaneously.

    Hypothesis: `F0 00 01 06 22 14 00 F7` switches device from keyboard mode
    (firmware draws pads) to DAW mode (host controls LEDs). After that, the
    standard note-on ch=0-3 RGB protocol should work while OLED is also active.

    Watch for:
      - OLED shows 'DAW MODE TEST'
      - Pad 0 = RED, pad 1 = GREEN, pad 2 = BLUE
      - Instrument/pad mode button no longer changes pad colors while this runs

    python probe.py rgb_daw
    """
    _, outs = find_ports()
    if not outs:
        raise SystemExit("No Atom SQ output found.")
    primary = next((p for p in outs if "control" not in p.lower()), outs[0])
    out = mido.open_output(primary)
    print(f"Using: {primary}")

    try:
        _do_native_init(out, daw_mode=True)
        print("Native + DAW mode active (14 00 sent).")

        _send_oled_text(out, 0x06, "DAW MODE TEST")
        _send_oled_text(out, 0x07, "pad LED test")
        print("OLED written.")

        _send_rgb(out, 36, 127, 0, 0)   # pad 0 = red
        _send_rgb(out, 37, 0, 127, 0)   # pad 1 = green
        _send_rgb(out, 38, 0, 0, 127)   # pad 2 = blue
        print("Pad RGB sent: 0=RED 1=GREEN 2=BLUE")
        print()
        print("OBSERVE:")
        print("  Pads 0-2 show R/G/B  AND  OLED shows text?  → combined protocol works!")
        print("  Pads still show instrument mode colors?       → 14 00 didn't help")
        print("  Pad mode button no longer changes LEDs?       → DAW mode confirmed")
        print()
        print("Holding 15 seconds... Ctrl-C to stop early.")
        try:
            time.sleep(15)
        except KeyboardInterrupt:
            pass
    finally:
        out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        out.close()
        print("\nExited native mode.")


def cmd_oled_ctrl_std():
    """Test: OLED SysEx on ATM SQ Control port WITHOUT entering native mode.

    Hypothesis: Studio One uses ATM SQ Control for SysEx and ATM SQ for MIDI.
    If OLED SysEx works on the Control port in standard mode (no native init),
    then pad LEDs (ch=0-3 note-on) still work on the main port simultaneously.
    That would be the combined protocol — no native mode needed at all.

    Watch the OLED. If it shows 'CTRL PORT TEST', OLED works without native mode.

    python probe.py oled_ctrl_std
    """
    _, outs = find_ports()
    if not outs:
        raise SystemExit("No Atom SQ output found.")
    control_name = next((p for p in outs if "control" in p.lower()), None)
    primary_name = next((p for p in outs if "control" not in p.lower()), outs[0])
    if not control_name:
        raise SystemExit("ATM SQ Control output not found.")
    print(f"Sending OLED SysEx to: {control_name}  (no native mode)")
    ctrl = mido.open_output(control_name)
    prim = mido.open_output(primary_name)
    try:
        # No native init — stay in standard mode.
        _send_oled_text(ctrl, 0x06, "CTRL PORT TEST")
        _send_oled_text(ctrl, 0x07, "no native mode")
        print("OLED SysEx sent to Control port.")
        print()
        print("OBSERVE:")
        print("  OLED shows 'CTRL PORT TEST'?  → OLED works in standard mode via Control port!")
        print("  OLED unchanged?               → native mode IS required for OLED")
        print()
        # Also paint pads with the standard protocol to confirm that still works.
        _send_rgb(prim, 36, 127, 0, 0)
        _send_rgb(prim, 37, 0, 127, 0)
        _send_rgb(prim, 38, 0, 0, 127)
        print("Pad RGB sent to primary port (standard mode): 0=RED 1=GREEN 2=BLUE")
        print("Holding 10 seconds... Ctrl-C to stop.")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            pass
    finally:
        ctrl.close()
        prim.close()


def cmd_probe_channels_native():
    """Test note-on ch=0-15 for pad LEDs in native mode.

    We confirmed ch=0-3 don't work in native mode. Try all 16 channels.
    Enters native mode + DAW mode, then sends note=36 (pad 0) on each channel
    with vel=127, 0.3s apart. Watch pad 0 for any color change.

    python probe.py probe_channels_native
    """
    _, outs = find_ports()
    if not outs:
        raise SystemExit("No Atom SQ output found.")
    primary = next((p for p in outs if "control" not in p.lower()), outs[0])
    out = mido.open_output(primary)
    try:
        _do_native_init(out, daw_mode=True)
        print("Native + DAW mode. Trying note-on ch=0-15 on note 36 (pad 0)...")
        print("Watch pad 0 for any color change.\n")
        for ch in range(16):
            print(f"  ch={ch:2d}: note_on ch={ch} note=36 vel=127", flush=True)
            out.send(mido.Message("note_on", channel=ch, note=36, velocity=127))
            time.sleep(0.3)
        print("\nDone. Any channel light up pad 0?")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        out.close()


def cmd_proxy():
    """Proxy both ATM SQ ports and log every byte Studio One sends to the device.

    Creates two virtual MIDI ports:
      'ATM SQ Spy'      — proxy for the main ATM SQ port
      'ATM SQ Ctrl Spy' — proxy for ATM SQ Control port

    Setup (do this ONCE, leave probe.py running):
      1. Run this command — virtual ports are now live
      2. Open Studio One → Preferences → External Devices
      3. Find the Atom SQ surface controller entry
      4. Change its MIDI output from 'ATM SQ Control' → 'ATM SQ Ctrl Spy'
         (and if there is a second output for the main port, change that too)
      5. Click OK / Apply and let Studio One reinitialize the controller
      6. All bytes Studio One sends will log below, forwarded to the real device

    Output format:  [elapsed ms]  PORT  DIRECTION  HEX_BYTES
    S1→DEV = Studio One sending to device (what we need)

    python probe.py proxy
    """
    _, outs = find_ports()
    ins, _  = find_ports()

    primary_out_name = next((p for p in outs if "control" not in p.lower()), None)
    control_out_name = next((p for p in outs if "control"     in p.lower()), None)
    primary_in_name  = next((p for p in ins  if "control" not in p.lower()), None)

    if not primary_out_name:
        raise SystemExit("ATM SQ main output not found. Run 'list'.")

    real_primary_out = mido.open_output(primary_out_name)
    real_control_out = mido.open_output(control_out_name) if control_out_name else None
    real_primary_in  = mido.open_input(primary_in_name)   if primary_in_name  else None

    # Virtual input ports — Studio One sends to these; we receive and forward.
    spy_main = mido.open_input("ATM SQ Spy",      virtual=True)
    spy_ctrl = mido.open_input("ATM SQ Ctrl Spy", virtual=True)

    print("=" * 60)
    print("Virtual ports created:")
    print("  'ATM SQ Spy'       → forwards to:", primary_out_name)
    print("  'ATM SQ Ctrl Spy'  → forwards to:", control_out_name or "(not found)")
    print()
    print("In Studio One → Preferences → External Devices → Atom SQ:")
    print("  Change MIDI output to 'ATM SQ Ctrl Spy'")
    print("  (or 'ATM SQ Spy' if it asks for a separate main port)")
    print("  Apply, then reinitialize the controller.")
    print()
    print("Logging all traffic. Ctrl-C to stop.")
    print("=" * 60)
    print()

    t0 = time.perf_counter()

    def ts():
        return f"[{(time.perf_counter() - t0)*1000:9.1f}ms]"

    try:
        while True:
            # Studio One → ATM SQ (via spy_main)
            for msg in spy_main.iter_pending():
                raw = " ".join(f"{b:02X}" for b in msg.bytes())
                print(f"{ts()}  MAIN   S1→DEV  {raw}")
                real_primary_out.send(msg)

            # Studio One → ATM SQ Control (via spy_ctrl)
            for msg in spy_ctrl.iter_pending():
                raw = " ".join(f"{b:02X}" for b in msg.bytes())
                print(f"{ts()}  CTRL   S1→DEV  {raw}")
                if real_control_out:
                    real_control_out.send(msg)

            # ATM SQ → host (pass-through log only — Studio One still reads direct)
            if real_primary_in:
                for msg in real_primary_in.iter_pending():
                    raw = " ".join(f"{b:02X}" for b in msg.bytes())
                    print(f"{ts()}  MAIN   DEV→S1  {raw}")

            time.sleep(0.001)
    except KeyboardInterrupt:
        print("\nProxy stopped.")
    finally:
        spy_main.close()
        spy_ctrl.close()
        real_primary_out.close()
        if real_control_out:
            real_control_out.close()
        if real_primary_in:
            real_primary_in.close()


def cmd_probe_pad_native(note: int, r: int, g: int, b: int):
    """Brute-force native-mode pad LED SysEx command byte.

    Enters native mode, then tries every PreSonus SysEx command byte 0x00–0x2F
    on BOTH the main port AND the Control port with two payload formats:
      Format A: F0 00 01 06 22 <cmd> <note>  <r> <g> <b> F7  (note = MIDI note 36–67)
      Format B: F0 00 01 06 22 <cmd> <index> <r> <g> <b> F7  (index = pad 0–31)

    Watch pad 0 (bottom-left). Note which cmd+port+format causes a color change.
    Run with r=127 g=0 b=0 (bright red) for easy visibility.

    python probe.py probe_pad_native 36 127 0 0
    """
    _, outs = find_ports()
    if not outs:
        raise SystemExit("No Atom SQ output found.")

    primary_name  = next((p for p in outs if "control" not in p.lower()), outs[0])
    control_name  = next((p for p in outs if "control"     in p.lower()), None)

    primary = mido.open_output(primary_name)
    control = mido.open_output(control_name) if control_name else None

    HEADER = (0x00, 0x01, 0x06, 0x22)

    try:
        print("Entering native mode...")
        _do_native_init(primary)
        print(f"Native mode active. Probing pad note={note} (index={note-36}) RGB=({r},{g},{b})")
        print("Watching pad 0 (bottom-left). Ctrl-C to stop.\n")

        for cmd in range(0x30):
            for fmt_label, payload_id in [("note", note), ("index", note - 36)]:
                for port_label, port in [("PRIMARY", primary), ("CONTROL", control)]:
                    if port is None:
                        continue
                    data = (*HEADER, cmd, payload_id & 0x7F, r & 0x7F, g & 0x7F, b & 0x7F)
                    hex_str = " ".join(f"{x:02X}" for x in data)
                    print(f"  cmd=0x{cmd:02X} fmt={fmt_label:5s} port={port_label}: F0 {hex_str} F7", flush=True)
                    port.send(mido.Message("sysex", data=data))
                    time.sleep(0.15)

        print("\nDone. If a pad changed color, note the cmd+fmt+port above it.")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        primary.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        primary.close()
        if control:
            control.close()
        print("Exited native mode.")


def cmd_rgb_native():
    """Test combined native-mode OLED + pad RGB in one shot.

    Enters native mode, writes 'EDEN TEST' to the OLED main line, then paints
    three bottom-row pads: pad 0 = RED, pad 1 = GREEN, pad 2 = BLUE.
    Holds for 10 seconds so you can observe both the OLED and pad LEDs.

    python probe.py rgb_native
    """
    _, outs = find_ports()
    if not outs:
        raise SystemExit("No Atom SQ output found.")

    primary = next((p for p in outs if "control" not in p.lower()), outs[0])
    out = mido.open_output(primary)
    print(f"Using output: {primary}")

    try:
        _do_native_init(out)
        print("Native mode active.")

        _send_oled_text(out, 0x06, "EDEN TEST")
        _send_oled_text(out, 0x07, "rgb_native")
        print("OLED text sent.")

        _send_rgb(out, 36, 127, 0, 0)
        _send_rgb(out, 37, 0, 127, 0)
        _send_rgb(out, 38, 0, 0, 127)
        print("Pad RGB sent: pad 0=RED, pad 1=GREEN, pad 2=BLUE")
        print("Holding 10 seconds... Ctrl-C to exit early.")

        try:
            time.sleep(10)
        except KeyboardInterrupt:
            pass

    finally:
        out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        out.close()
        print("\nExited native mode.")


def cmd_main_daw_test():
    """All output via ATM SQ main port; DAW mode (0x14 00) before pad RGB.

    Theory: OLED works on main port (confirmed). Pad RGB on main port
    previously showed old firmware colours because DAW mode wasn't active.
    0x14 00 tells the firmware to hand pad LED control to the host.

    python probe.py main_daw_test
    """
    _, outs = find_ports()
    main = next((p for p in outs if "control" not in p.lower()), None)
    if not main:
        raise SystemExit(f"Main ATM SQ port not found. Ports: {outs}")
    print(f"Using: {main}")
    out = mido.open_output(main)
    try:
        _do_native_init(out)
        print("Native init done.")
        time.sleep(0.1)

        # DAW mode: hand pad LED control to host
        out.send(mido.Message("sysex", data=(0x00, 0x01, 0x06, 0x22, 0x14, 0x00)))
        print("DAW mode sent (0x14 00).")
        time.sleep(0.1)

        # OLED (all via main port — previously confirmed working)
        def oled(slot, text):
            tb = [b & 0x7F for b in text.encode("ascii", errors="replace")]
            out.send(mido.Message("sysex", data=(
                0x00, 0x01, 0x06, 0x22, 0x12,
                slot & 0x7F, 0x7F, 0x7F, 0x7F, 0x00, *tb
            )))
        oled(0x06, "DAW TEST")
        oled(0x07, "main port")
        print("OLED sent.")
        time.sleep(0.05)

        # Pad RGB via main port
        def rgb(note, r, g, b):
            out.send(mido.Message("note_on", channel=0, note=note, velocity=127))
            out.send(mido.Message("note_on", channel=1, note=note, velocity=r))
            out.send(mido.Message("note_on", channel=2, note=note, velocity=g))
            out.send(mido.Message("note_on", channel=3, note=note, velocity=b))
        rgb(36, 127, 0,   0)
        rgb(37, 0,   127, 0)
        rgb(38, 0,   0,   127)
        print("Pad RGB sent via main: note36=RED note37=GREEN note38=BLUE")
        print("Holding 10s...")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            pass
    finally:
        out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        out.close()
        print("Done.")


def cmd_split_test():
    """Split-port test: init via ATM SQ (main), OLED+LEDs via ATM SQ Control.

    Rationale: OLED was confirmed working when init went to the main port.
    Studio One proxy showed LEDs require the Control port.
    This hybrid tests whether init needs the main port but LEDs need Control.

    python probe.py split_test
    """
    _, outs = find_ports()
    main = next((p for p in outs if "control" not in p.lower()), None)
    ctrl = next((p for p in outs if "control"     in p.lower()), None)
    if not main or not ctrl:
        raise SystemExit(f"Need both ports. Found: {outs}")
    print(f"Main port:    {main}")
    print(f"Control port: {ctrl}")

    out_main = mido.open_output(main)
    out_ctrl = mido.open_output(ctrl)
    try:
        # Init via main port (empirically confirmed cold-safe from probe.py testing)
        _do_native_init(out_main)
        print("Native init sent via main port.")
        time.sleep(0.1)

        # OLED via Control port
        def oled(slot, text):
            tb = [b & 0x7F for b in text.encode("ascii", errors="replace")]
            out_ctrl.send(mido.Message("sysex", data=(
                0x00, 0x01, 0x06, 0x22, 0x12,
                slot & 0x7F, 0x7F, 0x7F, 0x7F, 0x00, *tb
            )))
        oled(0x06, "SPLIT TEST")
        oled(0x07, "main+ctrl")
        print("OLED sent via Control port.")
        time.sleep(0.05)

        # Pad RGB via Control port
        def rgb(note, r, g, b):
            out_ctrl.send(mido.Message("note_on", channel=0, note=note, velocity=127))
            out_ctrl.send(mido.Message("note_on", channel=1, note=note, velocity=r))
            out_ctrl.send(mido.Message("note_on", channel=2, note=note, velocity=g))
            out_ctrl.send(mido.Message("note_on", channel=3, note=note, velocity=b))
        rgb(36, 127, 0,   0)
        rgb(37, 0,   127, 0)
        rgb(38, 0,   0,   127)
        print("Pad RGB sent via Control port: note36=RED note37=GREEN note38=BLUE")
        print("Holding 10s...")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            pass
    finally:
        out_main.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        out_main.close()
        out_ctrl.close()
        print("Done.")


def cmd_ctrl_test():
    """Minimal test: ALL output via ATM SQ Control port only.

    This is the confirmed correct architecture (2026-05-18 proxy sniff):
    - Native init → ATM SQ Control
    - OLED SysEx → ATM SQ Control
    - Pad RGB note-ons → ATM SQ Control

    If OLED shows text and pad 0/1/2 light up red/green/blue, the protocol is correct.

    python probe.py ctrl_test
    """
    _, outs = find_ports()
    ctrl = next((p for p in outs if "control" in p.lower()), None)
    if not ctrl:
        raise SystemExit("ATM SQ Control output not found. Check USB connection.")
    print(f"Using control port: {ctrl}")

    out = mido.open_output(ctrl)
    try:
        # JB 5-step init via Control port (cold-safe)
        _ENC_CCS = [29, 15, 16, 17, 18, 19, 20, 21]
        for _ in range(3):
            for cc in _ENC_CCS:
                out.send(mido.Message("control_change", channel=0, control=cc, value=0))
            out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        for _ in range(3):
            out.send(mido.Message("sysex", data=(0x7E, 0x7F, 0x06, 0x01)))
        out.send(mido.Message("note_off", channel=15, note=0, velocity=1))
        print("Native init sent (JB 5-step via Control port).")

        time.sleep(0.1)

        # OLED text
        def oled(slot, text):
            tb = [b & 0x7F for b in text.encode("ascii", errors="replace")]
            out.send(mido.Message("sysex", data=(
                0x00, 0x01, 0x06, 0x22, 0x12,
                slot & 0x7F, 0x7F, 0x7F, 0x7F, 0x00, *tb
            )))
        oled(0x06, "CTRL TEST")
        oled(0x07, "R G B pads")
        print("OLED text sent.")

        time.sleep(0.05)

        # Pad 0=RED, 1=GREEN, 2=BLUE (notes 36, 37, 38)
        def rgb(note, r, g, b):
            out.send(mido.Message("note_on", channel=0, note=note, velocity=127))
            out.send(mido.Message("note_on", channel=1, note=note, velocity=r))
            out.send(mido.Message("note_on", channel=2, note=note, velocity=g))
            out.send(mido.Message("note_on", channel=3, note=note, velocity=b))
        rgb(36, 127, 0,   0)
        rgb(37, 0,   127, 0)
        rgb(38, 0,   0,   127)
        print("Pad RGB sent: note36=RED  note37=GREEN  note38=BLUE")
        print("Holding 10s... Ctrl-C to exit.")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            pass
    finally:
        out.send(mido.Message("note_off", channel=15, note=0, velocity=0))
        out.close()
        print("\nDone.")


# --- entry point --------------------------------------------------------------

COMMANDS = {
    "list":                    (cmd_list, 0),
    "sniff":                   (cmd_sniff, 0),
    "handshake":               (cmd_handshake, 0),
    "rgb":                     (cmd_rgb, 4),
    "rgb_native":              (cmd_rgb_native, 0),
    "rgb_daw":                 (cmd_rgb_daw, 0),
    "oled_ctrl_std":           (cmd_oled_ctrl_std, 0),
    "probe_channels_native":   (cmd_probe_channels_native, 0),
    "ctrl_test":               (cmd_ctrl_test, 0),
    "split_test":              (cmd_split_test, 0),
    "main_daw_test":           (cmd_main_daw_test, 0),
    "proxy":                   (cmd_proxy, 0),
    "pad_off":                 (cmd_pad_off, 1),
    "probe_pad":               (cmd_probe_pad, 4),
    "probe_pad_native":        (cmd_probe_pad_native, 4),
    "sysex":                   (cmd_sysex, None),  # variadic
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    fn, argc = COMMANDS[cmd]
    args = sys.argv[2:]
    if argc is None:
        fn(*args)
    elif argc == 0:
        fn()
    else:
        if len(args) != argc:
            print(f"`{cmd}` expects {argc} args, got {len(args)}")
            sys.exit(1)
        fn(*(int(a) for a in args))


if __name__ == "__main__":
    main()
