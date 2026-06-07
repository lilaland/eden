"""eden/web_ui.py — Browser-based real-time controller mirror for Eden.

Serves on http://localhost:8765, zero extra deps (stdlib http.server + SSE).
Streams state at ~30 fps via Server-Sent Events.

Panels (top → bottom):
  • Session view  — Ableton-style 16×16 clip grid (SESSION mode only)
  • Waveform editor — sample + chop editor (INSTRUMENT + SampleTrack only)
  • Controller mirror — always visible
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from eden.audio import StateRef
from eden.render import render_pads, render_oled, render_button_leds
from controller_map import (
    NATIVE_LED_PLAY, NATIVE_LED_STOP, NATIVE_LED_REC,
    NATIVE_LED_SONG, NATIVE_LED_INST,
)

PORT = 8765
_SLOT_LETTERS = "ABCDEFGH"


# ── State serializer ──────────────────────────────────────────────────────────

def _to_json(state, sessions_dir: str = "") -> str:
    from eden.state import DrumTrack, SynthTrack, SampleTrack, Mode
    from eden.fx import FX_LABELS, fmt_fx_val

    pads = render_pads(state)
    oled = render_oled(state)
    leds = render_button_leds(state)

    pad_data = [[c[0] * 2, c[1] * 2, c[2] * 2] for c in pads]
    oled_data = {
        str(k): [t, r * 2, g * 2, b * 2]
        for k, (t, r, g, b) in oled.items()
    }

    # Session grid: 16 tracks × 16 loops
    track_data = []
    loop_matrix = []
    for ti, track in enumerate(state.tracks):
        if track is None:
            track_data.append(None)
            loop_matrix.append(None)
        else:
            if isinstance(track, DrumTrack):
                ttype = "drum"
            elif isinstance(track, SynthTrack):
                ttype = "synth"
            else:
                ttype = "sample"
            track_data.append({
                "name": track.name,
                "type": ttype,
                "muted": ti in state.muted_tracks,
                "soloed": ti in state.soloed_tracks,
            })
            loops = []
            for li, loop in enumerate(track.loops):
                key = (ti, li)
                loops.append({
                    "filled": not loop.is_empty,
                    "playing": key in state.playing_loops,
                    "active": key in state.active_loops,
                    "finishing": key in state.finishing_loops,
                })
            loop_matrix.append(loops)

    # Current SampleTrack data
    sample_key = None
    chops = []
    trim_start = 0.0
    trim_end = 1.0
    play_mode = "oneshot"
    amp_attack = 0.0
    amp_release = 0.05
    pan = 0.0
    stretch_mode = "off"
    stretch_bars = 1
    sample_chop_cursor = state.sample_chop_cursor
    sel_track = state.tracks[state.selected_track] if state.selected_track < len(state.tracks) else None
    if isinstance(sel_track, SampleTrack):
        sample_key = sel_track.sample_key
        chops = [[c.start_offset, c.end_offset, c.name, c.tune, c.reverse]
                 for c in sel_track.chops]
        trim_start = sel_track.trim_start
        trim_end = sel_track.trim_end
        play_mode = sel_track.play_mode
        amp_attack = sel_track.amp_attack
        amp_release = sel_track.amp_release
        pan = sel_track.pan
        stretch_mode = sel_track.stretch_mode
        stretch_bars = sel_track.stretch_bars

    # Which AppState scene slots are occupied
    scenes_saved = [s is not None for s in state.scenes]

    # Which session slots have files on disk
    disk_slots = [False] * 8
    if sessions_dir:
        for i, letter in enumerate(_SLOT_LETTERS):
            path = os.path.join(sessions_dir, f"session_{letter.lower()}.json")
            disk_slots[i] = os.path.isfile(path)

    # FX knob labels + values for selected track (page 0 = enc1-8)
    fx_knobs = []
    sel_track_obj = state.tracks[state.selected_track] if state.selected_track < len(state.tracks) else None
    _fx_chain = getattr(sel_track_obj, "fx", state.global_fx) if sel_track_obj is not None else state.global_fx
    _fx_page = state.fx_edit_page if state.edit_mode else 0
    _fx_vals = _fx_chain.page1 if _fx_page == 0 else _fx_chain.page2
    _fx_labels_page = FX_LABELS[_fx_page]
    fx_knobs_raw = list(_fx_vals[:8])
    for _i in range(8):
        _lbl = _fx_labels_page[_i]
        _abbr = _lbl.split()[0][:4]  # "LOW EQ" → "LOW", "CHORUS" → "CHOR", etc.
        fx_knobs.append({"label": _abbr, "value": fmt_fx_val(_fx_page, _i, _fx_vals[_i])})

    # Step data for selected track + loop (for timeline view)
    step_data = None
    if sel_track_obj is not None and not isinstance(sel_track_obj, SampleTrack):
        sel_loop = sel_track_obj.loops[state.selected_loop] if state.selected_loop < len(sel_track_obj.loops) else None
        if sel_loop is not None:
            steps_out = []
            for st in sel_loop.steps:
                steps_out.append({
                    "on": st.on,
                    "pitches": list(st.pitches),
                    "velocity": st.velocity,
                })
            step_data = {
                "steps": steps_out,
                "bars": sel_loop.bars,
                "step_count": sel_loop.step_count,
            }

    return json.dumps({
        "pads":           pad_data,
        "oled":           oled_data,
        "play":           leds.get(NATIVE_LED_PLAY, False),
        "stop":           leds.get(NATIVE_LED_STOP, False),
        "rec":            leds.get(NATIVE_LED_REC, False),
        "song":           leds.get(NATIVE_LED_SONG, False),
        "inst":           leds.get(NATIVE_LED_INST, False),
        "mode":           state.mode.name,
        "bpm":            state.tempo_bpm,
        "playhead":       state.playhead,
        "shift":          state.shift_held,
        "metro":          state.metronome_held,
        "track":          state.selected_track,
        "loop":           state.selected_loop,
        "slot":           state.active_session_slot,
        "armed":          list(state.armed_tracks),
        "playing":        state.is_playing,
        "finishing":      len(state.finishing_loops) > 0,
        "track_data":     track_data,
        "loop_matrix":    loop_matrix,
        "sample_key":          sample_key,
        "chops":               chops,
        "trim_start":          trim_start,
        "trim_end":            trim_end,
        "play_mode":           play_mode,
        "amp_attack":          amp_attack,
        "amp_release":         amp_release,
        "pan":                 pan,
        "sample_chop_cursor":  sample_chop_cursor,
        "scenes_saved":        scenes_saved,
        "disk_slots":          disk_slots,
        "selected_track":      state.selected_track,
        "selected_loop":       state.selected_loop,
        "fx_knobs":            fx_knobs,
        "fx_knobs_raw":        fx_knobs_raw,
        "step_data":           step_data,
        "fx_edit_page":        state.fx_edit_page,
        "edit_mode":           state.edit_mode,
        "stretch_mode":        stretch_mode,
        "stretch_bars":        stretch_bars,
        "available_samples":   list(state.available_samples),
    })


# ── Action dispatcher ─────────────────────────────────────────────────────────

def _handle_action(action: dict, state_ref, dispatch_fn, mixer=None) -> None:
    from eden.events import (
        SongSlotPressed, SetChops, WebSelectCell,
        SetTrim, AutoChop, NormalizeAction, LoadSample,
    )
    from eden.state import ChopPoint

    atype = action.get("type")

    if atype == "song_slot":
        slot = int(action["slot"])
        dispatch_fn(SongSlotPressed(slot=slot, pressed=True))
        dispatch_fn(SongSlotPressed(slot=slot, pressed=False))

    elif atype == "select_cell":
        dispatch_fn(WebSelectCell(track=int(action["track"]), loop=int(action["loop"])))

    elif atype == "set_chops":
        raw = action.get("chops", [])
        chops = tuple(
            ChopPoint(
                start_offset=float(c[0]),
                end_offset=float(c[1]),
                name=c[2] if len(c) > 2 else "",
                tune=float(c[3]) if len(c) > 3 else 0.0,
                reverse=bool(c[4]) if len(c) > 4 else False,
            )
            for c in raw
        )
        dispatch_fn(SetChops(track_idx=int(action["track_idx"]), chops=chops))

    elif atype == "set_trim":
        dispatch_fn(SetTrim(
            track_idx=int(action["track_idx"]),
            trim_start=float(action["trim_start"]),
            trim_end=float(action["trim_end"]),
        ))

    elif atype == "normalize":
        track_idx = int(action["track_idx"])
        if mixer is not None:
            state = state_ref.get()
            track = state.tracks[track_idx] if track_idx < len(state.tracks) else None
            key = getattr(track, "sample_key", None)
            if key:
                mixer.normalize(key)
        dispatch_fn(NormalizeAction(track_idx=track_idx))

    elif atype == "auto_chop":
        track_idx = int(action["track_idx"])
        n_slices = int(action.get("n_slices", 8))
        boundaries = []
        if mixer is not None:
            state = state_ref.get()
            track = state.tracks[track_idx] if track_idx < len(state.tracks) else None
            key = getattr(track, "sample_key", None)
            if key:
                boundaries = mixer.detect_onsets(key, n_slices)
        dispatch_fn(AutoChop(
            track_idx=track_idx,
            n_slices=n_slices,
            boundaries=tuple(boundaries),
        ))

    elif atype == "cycle_play_mode":
        from eden.events import SoftkeyPressed
        # SK1 (key=0) in SAMPLE_CHOPS page 1 cycles play_mode
        dispatch_fn(SoftkeyPressed(key=0))

    elif atype == "load_sample":
        track_idx = int(action["track_idx"])
        sample_key = str(action["sample_key"])
        track_type = str(action.get("track_type", "sample"))
        if mixer is not None and sample_key not in mixer.loaded_names():
            import os
            path = os.path.join(mixer.sample_dir, sample_key + ".wav")
            if os.path.isfile(path):
                mixer.load(sample_key, path)
        dispatch_fn(LoadSample(
            track_idx=track_idx,
            sample_key=sample_key,
            track_type=track_type,
        ))

    elif atype == "delete_sample":
        sample_key = str(action["sample_key"])
        if mixer is not None:
            import os
            path = os.path.join(mixer.sample_dir, sample_key + ".wav")
            if os.path.isfile(path):
                os.remove(path)
            mixer.unload(sample_key)


# ── HTTP handler ──────────────────────────────────────────────────────────────

def _make_handler(state_ref: StateRef, dispatch_fn, sessions_dir: str, get_peaks_fn, mixer=None):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path == "/":
                body = _HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)

            elif parsed.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        data = _to_json(state_ref.get(), sessions_dir)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(1 / 30)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            elif parsed.path == "/waveform":
                qs = parse_qs(parsed.query)
                key = (qs.get("key") or [None])[0]
                peaks = get_peaks_fn(key) if key and get_peaks_fn else None
                if peaks is not None:
                    body = json.dumps({"peaks": peaks}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", len(body))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            elif parsed.path == "/samples":
                names = mixer.loaded_names() if mixer else []
                body = json.dumps({"samples": names}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)

            elif parsed.path == "/catalog":
                from eden.catalog import (
                    DRUM_CATEGORIES, DRUM_VARIATIONS,
                    _DRUM_SAMPLE_KEYS, _VARIATION_KEYS,
                    SAMPLE_CATEGORIES, _SAMPLE_CATALOG,
                )
                drum_sets = []
                for cat in DRUM_CATEGORIES:
                    cat_key = _DRUM_SAMPLE_KEYS[cat]
                    variations = [
                        {"var": var, "key": f"{cat_key}_{_VARIATION_KEYS[var]}"}
                        for var in DRUM_VARIATIONS
                    ]
                    drum_sets.append({"cat": cat, "variations": variations})
                sample_catalog = []
                for cat in SAMPLE_CATEGORIES:
                    entries = [
                        {"name": e[0], "key": e[2]}
                        for e in _SAMPLE_CATALOG.get(cat, ())
                    ]
                    sample_catalog.append({"cat": cat, "entries": entries})
                body = json.dumps({
                    "drum_sets": drum_sets,
                    "sample_catalog": sample_catalog,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)

            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/action" and dispatch_fn is not None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    _handle_action(json.loads(body), state_ref, dispatch_fn, mixer)
                    self.send_response(204)
                    self.end_headers()
                except Exception:
                    self.send_response(400)
                    self.end_headers()

            elif self.path == "/upload_sample" and mixer is not None:
                import email.parser, email.policy, os
                ct = self.headers.get("Content-Type", "")
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                # Parse multipart/form-data manually via email module
                msg_bytes = (f"Content-Type: {ct}\r\n\r\n").encode() + raw
                msg = email.parser.BytesParser(policy=email.policy.compat32).parsebytes(msg_bytes)
                saved = []
                if msg.is_multipart():
                    for part in msg.walk():
                        disp = part.get_content_disposition()
                        if disp != "attachment" and disp != "form-data":
                            continue
                        fname = part.get_filename()
                        if not fname or not fname.lower().endswith(".wav"):
                            continue
                        name = os.path.splitext(fname)[0]
                        dest = os.path.join(mixer.sample_dir, fname)
                        with open(dest, "wb") as f:
                            f.write(part.get_payload(decode=True))
                        try:
                            mixer.load(name, dest)
                            saved.append(name)
                        except Exception as exc:
                            print(f"[UI] upload error: {exc}", file=sys.stderr)
                resp = json.dumps({"saved": saved}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", len(resp))
                self.end_headers()
                self.wfile.write(resp)

            else:
                self.send_response(404)
                self.end_headers()

    return _Handler


# ── Public class ──────────────────────────────────────────────────────────────

class WebUI:
    def __init__(
        self,
        state_ref: StateRef,
        port: int = PORT,
        dispatch_fn=None,
        sessions_dir: str = "",
        mixer=None,
    ) -> None:
        self._state_ref = state_ref
        self._port = port
        self._dispatch_fn = dispatch_fn
        self._sessions_dir = sessions_dir
        self._mixer = mixer

    def _get_peaks(self, key: str):
        return self._mixer.get_peaks(key) if self._mixer is not None else None

    def run_blocking(self) -> None:
        handler_cls = _make_handler(
            self._state_ref,
            self._dispatch_fn,
            self._sessions_dir,
            self._get_peaks,
            self._mixer,
        )
        server = ThreadingHTTPServer(("127.0.0.1", self._port), handler_cls)
        url = f"http://localhost:{self._port}"
        print(f"[UI] Controller mirror -> {url}")
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


# ── HTML (embedded) ───────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Eden</title>
<style>
/* ── Reset ─────────────────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}

/* ── Tropical starburst backdrop ────────────────────────────────────── */
body{
  background:
    radial-gradient(ellipse 80% 60% at 20% 10%,rgba(176,64,255,.18) 0%,transparent 60%),
    radial-gradient(ellipse 60% 50% at 85% 80%,rgba(0,229,255,.13) 0%,transparent 55%),
    radial-gradient(ellipse 90% 70% at 50% 50%,#0d0618 0%,#070010 100%);
  min-height:100vh;
  display:flex;flex-direction:column;align-items:center;
  font-family:'Courier New',Consolas,monospace;color:#d8c8f8;
  padding:20px 16px 32px;gap:10px;
  position:relative;overflow-x:hidden;
}
body::before{
  content:'';pointer-events:none;position:fixed;inset:0;z-index:0;
  background:repeating-conic-gradient(
    from 0deg at 50% 50%,
    rgba(255,62,160,.03) 0deg 10deg,
    transparent 10deg 20deg
  );
  opacity:.55;
}
body>*{position:relative;z-index:1}
h1{font-size:10px;color:#5a3878;letter-spacing:3px;text-transform:uppercase}

/* ── Session view ─────────────────────────────────────────────────── */
#session-panel{
  width:1110px;
  background:linear-gradient(160deg,#120824 0%,#0c0518 100%);
  border-radius:10px;padding:10px 12px 12px;
  box-shadow:0 0 0 1px rgba(255,62,160,.12),0 8px 32px rgba(0,0,0,.8);
}
#session-panel.hidden{display:none}
#sess-top{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#sess-title{font-size:9px;color:#7040a0;letter-spacing:2px;text-transform:uppercase;flex:1}
.sess-slots{display:flex;gap:3px}
.sess-slot{
  width:34px;height:22px;border-radius:3px;
  background:#1a0a30;border:1px solid #3a1860;
  color:#6040a0;font-size:8px;text-align:center;line-height:22px;
  cursor:pointer;transition:all .08s;user-select:none;
}
.sess-slot:hover{border-color:#8040c0;color:#c080ff}
.sess-slot.active{
  background:#ff3ea0;border-color:#ff3ea0;color:#1a0030;
  box-shadow:0 0 8px rgba(255,62,160,.6),0 0 18px rgba(255,62,160,.25);
  font-weight:bold;
}
.sess-slot.on-disk{border-color:#5030a0;color:#a060e0}
.sess-slot.on-disk:hover{border-color:#9050e0;color:#d090ff}
.sess-slot.active.on-disk{background:#ff3ea0;border-color:#ff3ea0;color:#1a0030}
#bpm-badge{font-size:9px;color:#6040a0;letter-spacing:1px}

/* session grid */
#session-grid{
  display:grid;
  grid-template-columns:24px repeat(16,1fr);
  gap:1px;background:#1a0830;border-radius:4px;overflow:hidden;
}
.sg-corner{background:#0e0520}
.sg-track-hdr{
  background:#150628;padding:3px 2px 3px;cursor:pointer;
  min-width:0;overflow:hidden;text-align:center;
}
.sg-track-hdr:hover{background:#200a38}
.sg-track-hdr.selected-col{background:#2a0d48}
.sg-track-name{
  font-size:7px;color:#9070c0;text-transform:uppercase;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  letter-spacing:.3px;
}
.sg-track-type{font-size:6px;color:#4a2880;text-transform:uppercase;margin-top:1px}
.sg-track-hdr.t-drum .sg-track-type{color:#a04060}
.sg-track-hdr.t-synth .sg-track-type{color:#3090b0}
.sg-track-hdr.t-sample .sg-track-type{color:#4070a0}
.sg-track-hdr.muted .sg-track-name{opacity:.3}
.sg-track-hdr.soloed .sg-track-name{color:#ffcc00;text-shadow:0 0 6px rgba(255,204,0,.5)}
.sg-loop-num{
  background:#0c041a;font-size:7px;color:#3a1860;
  text-align:right;padding-right:3px;line-height:20px;
}
.sg-cell{
  height:20px;background:#100428;cursor:pointer;
  position:relative;transition:background .06s;border:1px solid transparent;
}
.sg-cell.empty-track{background:#080214;cursor:default}
.sg-cell.has-content{background:#1e0a38}
.sg-cell.is-playing{background:#072818}
.sg-cell.is-active{background:#08142e}
.sg-cell.is-finishing{background:#281808}
.sg-cell.selected{border-color:#ff3ea0!important;z-index:1;
  box-shadow:inset 0 0 0 1px rgba(255,62,160,.4)}
.sg-cell:not(.empty-track):hover{filter:brightness(1.6)}

/* play dot inside cells */
.sg-cell.is-playing::after{
  content:'';position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);
  width:5px;height:5px;border-radius:50%;
  background:#00ff9d;box-shadow:0 0 6px rgba(0,255,157,.85);
}
.sg-cell.is-finishing::after{
  background:#ffcc00;box-shadow:0 0 5px rgba(255,204,0,.8);
}
.sg-cell.is-active:not(.is-playing)::after{
  background:#00e5ff;box-shadow:0 0 5px rgba(0,229,255,.6);
}

/* ── Waveform editor ──────────────────────────────────────────────── */
#waveform-panel{
  width:1110px;
  background:linear-gradient(160deg,#100620 0%,#080312 100%);
  border-radius:10px;
  box-shadow:0 0 0 1px rgba(255,62,160,.1),0 8px 32px rgba(0,0,0,.8);
  overflow:hidden;
}
#waveform-panel.hidden{display:none}
#wform-top{
  display:flex;align-items:center;gap:8px;
  padding:7px 12px 5px;border-bottom:1px solid rgba(176,64,255,.15);
}
#wform-title{font-size:9px;color:#7040a0;letter-spacing:2px;text-transform:uppercase}
#wform-sample-name{font-size:10px;color:#c080ff;letter-spacing:.5px;flex:1}
#wform-chop-count{font-size:9px;color:#5090a0}
.wform-btn{
  padding:2px 8px;border-radius:3px;
  border:1px solid rgba(176,64,255,.35);
  background:rgba(80,20,120,.4);color:#d080ff;font-size:8px;font-family:inherit;
  cursor:pointer;text-transform:uppercase;letter-spacing:.5px;
  transition:all .08s;
}
.wform-btn:hover{
  border-color:#ff3ea0;color:#ff3ea0;
  background:rgba(255,62,160,.12);
  box-shadow:0 0 8px rgba(255,62,160,.3);
}
#wform-canvas-wrap{
  position:relative;height:120px;cursor:crosshair;
  background:#060112;
}
#wform-canvas{display:block;width:100%;height:120px}
.chop-handle{
  position:absolute;top:0;bottom:0;width:2px;
  background:#ff3ea0;cursor:col-resize;z-index:10;
}
.chop-handle::before{
  content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);
  width:10px;height:10px;border-radius:50%;
  background:#ff3ea0;border:1px solid #ff80c8;
  box-shadow:0 0 6px rgba(255,62,160,.7);
}
.chop-handle:hover{background:#ff80c8}
.chop-label{
  position:absolute;bottom:3px;left:3px;
  font-size:7px;color:#ff3ea0;pointer-events:none;
  text-shadow:0 0 4px rgba(255,62,160,.6);
}
/* Trim handle (cyan, bracket-style) */
.trim-handle{
  position:absolute;top:0;bottom:0;width:3px;
  background:#00b8d4;cursor:col-resize;z-index:12;
}
.trim-handle::before{
  content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);
  width:12px;height:12px;
  background:#00e5ff;border:1px solid #80f4ff;border-radius:2px;
  box-shadow:0 0 8px rgba(0,229,255,.6);
}
.trim-handle:hover{background:#00e5ff}
.trim-handle.trim-start::after{
  content:'◀';position:absolute;top:14px;left:2px;
  font-size:7px;color:#00e5ff;text-shadow:0 0 4px rgba(0,229,255,.8);
}
.trim-handle.trim-end::after{
  content:'▶';position:absolute;top:14px;right:2px;
  font-size:7px;color:#00e5ff;text-shadow:0 0 4px rgba(0,229,255,.8);
}

/* ── Instrument timeline ────────────────────────────────────────────── */
#inst-timeline{
  width:1110px;
  background:linear-gradient(160deg,#100620 0%,#080312 100%);
  border-radius:10px;
  box-shadow:0 0 0 1px rgba(0,229,255,.1),0 8px 32px rgba(0,0,0,.8);
  overflow:hidden;
  padding:10px 12px 12px;
}
#inst-timeline.hidden{display:none}
#tl-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#tl-title{font-size:9px;color:#4090b0;letter-spacing:2px;text-transform:uppercase;flex:1}
#tl-info{font-size:9px;color:#306080;letter-spacing:.5px}
#tl-canvas-wrap{position:relative;height:60px;background:#060112;border-radius:4px;overflow:hidden}
#tl-canvas{display:block;width:100%;height:60px}
/* FX meters strip */
#fx-strip{
  display:flex;gap:6px;margin-top:8px;
  padding-top:8px;border-top:1px solid rgba(0,229,255,.1);
}
.fx-meter{
  flex:1;display:flex;flex-direction:column;align-items:center;gap:3px;
}
.fx-meter-label{font-size:7px;color:#4090a0;text-transform:uppercase;letter-spacing:.4px}
.fx-meter-bar-wrap{
  width:100%;height:40px;background:#060112;border-radius:3px;
  border:1px solid rgba(0,229,255,.12);position:relative;overflow:hidden;
}
.fx-meter-bar{
  position:absolute;bottom:0;left:0;right:0;
  background:linear-gradient(0deg,#ff3ea0,#00e5ff);
  transition:height .1s;
}
.fx-meter-val{font-size:7px;color:#80c0d0;letter-spacing:.3px}

/* Light mode */
body.light #inst-timeline{
  background:#fff;
  box-shadow:0 0 0 1px rgba(0,160,200,.15),0 4px 20px rgba(0,100,160,.1);
}
body.light #tl-title{color:#0070a0}
body.light #tl-info{color:#0060a0}
body.light #tl-canvas-wrap{background:#f0f8ff}
body.light #fx-strip{border-top-color:rgba(0,160,200,.15)}
body.light .fx-meter-label{color:#0070a0}
body.light .fx-meter-bar-wrap{background:#e8f4ff;border-color:rgba(0,160,200,.2)}
body.light .fx-meter-val{color:#006090}

/* ── Controller chassis ─────────────────────────────────────────────── */
#ctrl{
  background:linear-gradient(175deg,#1e0a35 0%,#160828 60%,#0f0520 100%);
  border-radius:14px;padding:14px;width:1110px;
  box-shadow:
    0 0 0 1px rgba(255,62,160,.14),
    0 0 0 2px rgba(176,64,255,.06),
    0 16px 48px rgba(0,0,0,.9),
    inset 0 1px 0 rgba(255,62,160,.08);
}
#top{display:flex;align-items:flex-start;gap:10px;margin-bottom:8px}
#mid{display:flex;align-items:center;gap:8px;margin-bottom:8px}
#pads{
  background:#0a0318;border-radius:8px;padding:10px 10px 8px;overflow:visible;
  box-shadow:inset 0 0 20px rgba(0,0,0,.5);
}
#logo{min-width:60px;padding-top:6px;font-size:11px;font-weight:bold;
  letter-spacing:2px;text-transform:uppercase;color:#7040a0;line-height:1.6}
#logo .o{color:#ff3ea0;text-shadow:0 0 8px rgba(255,62,160,.7)}
#logo small{display:block;font-size:7px;letter-spacing:1px;color:#4a2870;margin-top:1px}
#encs{display:flex;flex-direction:column;gap:6px;padding-top:2px}
.enc-row{display:flex;gap:14px;align-items:center}
.enc-spacer{width:63px;flex-shrink:0}
.enc{
  width:44px;height:44px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#2a1045,#0e0520);
  border:1px solid #3a1860;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:1px;
  box-shadow:0 3px 7px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,62,160,.08);
}
.enc-label{font-size:6px;color:#6040a0;text-transform:uppercase;letter-spacing:.3px;line-height:1.1}
.enc-val{font-size:7px;color:#a070d0;font-weight:bold;line-height:1.1}
.pm-pair{display:flex;gap:3px;flex-shrink:0}
.pm-btn{
  width:30px;height:28px;border-radius:3px;
  background:#180830;border:1px solid #2e1050;
  color:#6040a0;font-size:12px;text-align:center;line-height:28px;cursor:default;
}
#rpanel{display:flex;align-items:flex-start;gap:8px;margin-left:auto}
#mode-col{display:flex;flex-direction:column;gap:4px;padding-top:2px}
.mode-btn{
  width:62px;height:30px;border-radius:4px;
  background:#1a0830;border:1px solid #3a1260;
  color:#7040a0;font-size:8px;font-family:inherit;
  text-transform:uppercase;letter-spacing:.4px;cursor:default;transition:all .06s;
}
.mode-btn.lit{
  background:#ff3ea0;border-color:#ff3ea0;color:#1a0030;
  box-shadow:0 0 10px rgba(255,62,160,.7),0 0 20px rgba(255,62,160,.25);
  font-weight:bold;
}
#oled-block{display:flex;flex-direction:column;gap:3px}
.sk-btn-row{display:flex;gap:3px}
.sk-btn{
  flex:1;min-width:0;height:42px;border-radius:3px;
  background:#120628;border:1px solid #2a0e50;border-top:4px solid #2a0e50;
  padding:2px 5px;cursor:default;transition:border-top-color .08s;
}
.sk-btn-title{
  font-size:8px;color:#5030a0;text-transform:uppercase;letter-spacing:.4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .08s;
}
.sk-btn-val{font-size:9px;color:#9060c0;white-space:nowrap;overflow:hidden}
#oled-screen{
  background:#01000c;border-radius:5px;border:1px solid #2a0e50;
  padding:5px 8px;width:216px;
  box-shadow:inset 0 0 18px rgba(0,0,30,.95),0 0 0 1px rgba(176,64,255,.08);
}
.main-line{
  font-size:11px;color:#e8d8ff;
  text-shadow:0 0 8px rgba(216,200,255,.35);
  white-space:nowrap;overflow:hidden;line-height:1.5;
}
#nav-col{display:flex;flex-direction:column;align-items:center;gap:5px}
#enc9{
  width:56px;height:56px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#2a1045,#0e0520);
  border:2px solid #3a1860;
  display:flex;align-items:center;justify-content:center;
  font-size:7px;color:#6040a0;
  box-shadow:0 4px 12px rgba(0,0,0,.65),0 0 0 1px rgba(255,62,160,.06);
}
.nav-pair{display:flex;gap:3px}
.nav-sm{
  width:28px;height:22px;border-radius:3px;
  background:#180830;border:1px solid #2e1050;
  color:#6040a0;font-size:10px;text-align:center;line-height:22px;cursor:default;
}
#mid-left{display:flex;flex-direction:column;gap:0}
.slots{display:flex;gap:3px;margin-bottom:3px;flex-wrap:wrap}
.slot-btn{
  width:32px;height:28px;border-radius:3px;
  background:#180830;border:1px solid #2e1050;
  color:#6040a0;font-size:8px;text-align:center;line-height:28px;
  cursor:default;transition:all .06s;
}
.slot-btn.active{
  background:#ff3ea0;border-color:#ff3ea0;color:#1a0030;
  box-shadow:0 0 8px rgba(255,62,160,.65);font-weight:bold;
}
.tr-row{display:flex;gap:4px;margin-top:4px}
.tr-btn{
  width:42px;height:36px;border-radius:4px;
  background:#180830;border:1px solid #2e1050;
  color:#7040a0;font-size:13px;text-align:center;line-height:36px;
  cursor:default;transition:all .06s;
}
.tr-btn.play.lit{
  background:#00ff9d;border-color:#00ff9d;color:#003020;
  box-shadow:0 0 10px rgba(0,255,157,.7),0 0 20px rgba(0,255,157,.2);
}
.tr-btn.stop.lit{background:#3a1860;border-color:#6030a0;color:#d8c8f8}
.tr-btn.rec.lit{
  background:#ff2060;border-color:#ff2060;color:#fff;
  box-shadow:0 0 10px rgba(255,32,96,.7),0 0 20px rgba(255,32,96,.25);
}
.tr-btn.metro.lit{background:#00d4ff;border-color:#00d4ff;color:#001828;
  box-shadow:0 0 8px rgba(0,212,255,.6)}
#ts-wrap{
  flex:1;height:18px;background:#0a0320;border-radius:8px;
  border:1px solid #2a0e50;position:relative;overflow:hidden;
}
#ts-pos{
  position:absolute;width:22px;height:100%;
  background:linear-gradient(90deg,#ff3ea0,#b040ff);
  border-radius:7px;left:50%;transform:translateX(-50%);
  opacity:0;transition:left .04s,opacity .1s;
  box-shadow:0 0 8px rgba(255,62,160,.6);
}
#nav-cross{
  display:grid;
  grid-template-columns:repeat(3,28px);
  grid-template-rows:repeat(3,28px);
  gap:3px;
}
.nav-btn{
  width:28px;height:28px;border-radius:4px;
  background:#180830;border:1px solid #2e1050;
  color:#7040a0;font-size:11px;text-align:center;line-height:28px;cursor:default;
}
#btn-shift{
  width:64px;height:28px;border-radius:4px;
  background:#ff3ea0;border:1px solid #cc1070;
  color:#1a0030;font-size:8px;font-family:inherit;
  text-transform:uppercase;font-weight:bold;letter-spacing:.5px;
  cursor:default;transition:all .06s;margin-top:5px;
  box-shadow:0 0 8px rgba(255,62,160,.45);
}
#btn-shift.held{
  background:#ffcc00;border-color:#c89000;color:#1a1000;
  box-shadow:0 0 12px rgba(255,204,0,.75),0 0 24px rgba(255,204,0,.25);
}
.pad-row{display:flex;gap:3px;margin-bottom:4px}
.pad-row:last-child{margin-bottom:0}
#pr-top{padding-left:30px}
.pad{
  width:58px;height:46px;border-radius:5px;
  background:#0e0424;border:1px solid #2a0a45;
  position:relative;transition:background-color .04s;flex-shrink:0;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.03);
}
.pad-lbl{
  position:absolute;bottom:3px;left:4px;font-size:7px;
  color:rgba(176,128,255,.2);
}
#status{
  text-align:center;font-size:9px;color:#4a2870;padding-top:4px;letter-spacing:.5px;
}

/* ── Sample library panel ───────────────────────────────────────────── */
#sample-lib{
  width:1110px;
  background:linear-gradient(160deg,#120824 0%,#0c0518 100%);
  border-radius:10px;
  box-shadow:0 0 0 1px rgba(255,62,160,.12),0 8px 32px rgba(0,0,0,.8);
}
#sample-lib-top{
  display:flex;align-items:center;gap:8px;padding:8px 12px;
  cursor:pointer;user-select:none;
}
#sample-lib-title{font-size:9px;color:#7040a0;letter-spacing:2px;text-transform:uppercase;flex:1}
#sample-lib-toggle{font-size:9px;color:#5030a0;transition:transform .15s}
#sample-count{font-size:8px;color:#5030a0}
#sample-lib-body{padding:0 12px 12px;display:none}
#sample-lib-body.open{display:block}
/* Tab bar */
#sl-tabs{
  display:flex;align-items:center;gap:6px;
  border-top:1px solid rgba(176,64,255,.12);padding-top:8px;margin-bottom:8px;
}
.sl-tab{
  padding:2px 12px;border-radius:3px;font-size:8px;font-family:inherit;
  border:1px solid rgba(176,64,255,.25);background:transparent;
  color:#6040a0;cursor:pointer;text-transform:uppercase;letter-spacing:.5px;transition:all .08s;
}
.sl-tab.active{
  background:#3a1860;border-color:#9060d0;color:#d0a0ff;
  box-shadow:0 0 6px rgba(176,64,255,.25);
}
.sl-tab:hover:not(.active){border-color:#6030a0;color:#a070c0}
#sample-upload-btn{
  margin-left:auto;
  padding:3px 10px;border-radius:3px;font-size:8px;font-family:inherit;
  border:1px solid rgba(0,229,255,.35);background:rgba(0,80,100,.4);
  color:#00e5ff;cursor:pointer;text-transform:uppercase;letter-spacing:.5px;transition:all .1s;
}
#sample-upload-btn:hover{border-color:#00e5ff;box-shadow:0 0 8px rgba(0,229,255,.3)}
#sample-upload-input{display:none}
/* Panes */
.sl-pane{display:none}
.sl-pane.active{display:block}
/* ── Drums tab ── */
#drum-filter-row{display:flex;align-items:center;gap:6px;margin-bottom:6px}
#drum-search{
  flex:1;background:#0e0424;border:1px solid #3a1860;border-radius:4px;
  color:#d8c8f8;font-size:9px;font-family:inherit;padding:3px 8px;outline:none;
}
#drum-search::placeholder{color:#4a2870}
#drum-search:focus{border-color:#ff3ea0}
#drum-list{max-height:280px;overflow-y:auto}
#drum-list::-webkit-scrollbar{width:4px}
#drum-list::-webkit-scrollbar-track{background:#0a0318}
#drum-list::-webkit-scrollbar-thumb{background:#3a1860;border-radius:2px}
.drum-cat-section{margin-bottom:5px}
.drum-cat-label{font-size:7px;color:#5030a0;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}
.drum-var-row{display:flex;flex-wrap:wrap;gap:2px}
.drum-var-btn{
  padding:2px 8px;border-radius:2px;font-size:7px;font-family:inherit;
  border:1px solid #2a0e50;background:#0e0424;color:#6040a0;
  cursor:pointer;text-transform:uppercase;letter-spacing:.2px;transition:all .07s;
}
.drum-var-btn:hover{border-color:#6030a0;color:#c080ff;background:#1a0838}
.drum-var-btn.loaded{border-color:#ff3ea0;color:#ff90c0;background:#1e0838}
/* ── Samples tab ── */
#samples-filter-row{margin-bottom:6px}
#samples-search{
  width:100%;background:#0e0424;border:1px solid #3a1860;border-radius:4px;
  color:#d8c8f8;font-size:9px;font-family:inherit;padding:3px 8px;outline:none;
  box-sizing:border-box;
}
#samples-search::placeholder{color:#4a2870}
#samples-search:focus{border-color:#ff3ea0}
#sample-catalog-list{max-height:200px;overflow-y:auto;margin-bottom:8px}
#sample-catalog-list::-webkit-scrollbar{width:4px}
#sample-catalog-list::-webkit-scrollbar-track{background:#0a0318}
#sample-catalog-list::-webkit-scrollbar-thumb{background:#3a1860;border-radius:2px}
.scat-section{margin-bottom:3px;border:1px solid #2a0e50;border-radius:4px;overflow:hidden}
.scat-header{
  display:flex;align-items:center;gap:6px;padding:4px 8px;
  background:#150628;cursor:pointer;user-select:none;
}
.scat-header:hover{background:#1e0838}
.scat-name{flex:1;font-size:8px;color:#9060c0;text-transform:uppercase;letter-spacing:.5px}
.scat-toggle{font-size:9px;color:#5030a0}
.scat-body{display:none;padding:4px 6px}
.scat-body.open{display:block}
.sc-item{
  display:flex;align-items:center;gap:4px;padding:2px 4px;border-radius:2px;
  transition:background .06s;
}
.sc-item:hover{background:#1e0838}
.sc-item.sc-active{background:#180830}
.sc-name{
  flex:1;font-size:8px;color:#a080c0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.sc-item.sc-active .sc-name{color:#ff3ea0}
.sc-item.sc-unavail .sc-name{color:#3a2050;font-style:italic}
.sc-load{
  padding:1px 6px;border-radius:2px;font-size:7px;font-family:inherit;
  border:1px solid rgba(255,62,160,.3);background:transparent;
  color:#c060a0;cursor:pointer;text-transform:uppercase;letter-spacing:.3px;transition:all .08s;
  flex-shrink:0;
}
.sc-load:hover{background:rgba(255,62,160,.15);border-color:#ff3ea0;color:#ff3ea0}
/* Settings panel */
#sl-settings{
  padding:8px 10px;border-radius:4px;
  border:1px solid rgba(176,64,255,.18);background:#0e0424;
}
#sl-settings.hidden{display:none}
.sl-settings-hdr{
  font-size:8px;color:#7040a0;text-transform:uppercase;letter-spacing:.5px;
  margin-bottom:6px;
}
.sl-settings-key{color:#d080ff;letter-spacing:.3px;text-transform:none}
.sl-settings-grid{
  display:grid;grid-template-columns:60px 1fr 60px 1fr;gap:3px 12px;
}
.sl-sg-label{font-size:7px;color:#5030a0;text-transform:uppercase;letter-spacing:.3px;line-height:16px}
.sl-sg-value{font-size:8px;color:#c090e0;line-height:16px}

/* Light mode overrides for sample lib */
body.light #sample-lib{
  background:#fff;
  box-shadow:0 0 0 1px rgba(176,64,255,.15),0 4px 20px rgba(120,60,200,.12);
}
body.light #sample-lib-title{color:#8040b0}
body.light #sample-lib-top{cursor:pointer}
body.light #sample-lib-toggle{color:#8040b0}
body.light #sl-tabs{border-top-color:rgba(176,64,255,.15)}
body.light .sl-tab{border-color:rgba(130,60,200,.25);color:#7050a0}
body.light .sl-tab.active{background:#e0d0f8;border-color:#9060d0;color:#5030a0}
body.light #sample-upload-btn{background:rgba(200,240,255,.6);border-color:#0090c0;color:#0060a0}
body.light #sample-count{color:#8060b0}
body.light #drum-search,body.light #samples-search{
  background:#f4f0fc;border-color:#c0a8e0;color:#2a1050;
}
body.light #drum-search::placeholder,body.light #samples-search::placeholder{color:#a090c0}
body.light #drum-list::-webkit-scrollbar-track,
body.light #sample-catalog-list::-webkit-scrollbar-track{background:#f5f0ff}
body.light #drum-list::-webkit-scrollbar-thumb,
body.light #sample-catalog-list::-webkit-scrollbar-thumb{background:#c0a8e0}
body.light .drum-cat-label{color:#8050b0}
body.light .drum-var-btn{background:#f0e8ff;border-color:#c0a8e0;color:#7050a0}
body.light .drum-var-btn:hover{background:#e4d4ff;border-color:#9060c0;color:#4020a0}
body.light .drum-var-btn.loaded{background:#fff0f8;border-color:#ff3ea0;color:#d0005a}
body.light .scat-header{background:#f5f0ff}
body.light .scat-header:hover{background:#ede4ff}
body.light .scat-name{color:#7040b0}
body.light .scat-toggle{color:#9060c0}
body.light .scat-section{border-color:#d0c0ec}
body.light .sc-item:hover{background:#ece4ff}
body.light .sc-item.sc-active{background:#f8f0ff}
body.light .sc-name{color:#6040a0}
body.light .sc-item.sc-active .sc-name{color:#d0005a}
body.light .sc-item.sc-unavail .sc-name{color:#c0b0d8}
body.light .sc-load{border-color:rgba(200,50,120,.3);color:#a02080}
body.light .sc-load:hover{background:rgba(255,62,160,.1);border-color:#ff3ea0;color:#d0005a}
body.light #sl-settings{background:#f5f0ff;border-color:rgba(130,60,200,.2)}
body.light .sl-settings-hdr{color:#8040b0}
body.light .sl-settings-key{color:#6020a0}
body.light .sl-sg-label{color:#8050b0}
body.light .sl-sg-value{color:#4030a0}

/* ── Theme toggle button ────────────────────────────────────────────── */
#header-row{display:flex;align-items:center;gap:10px;width:1110px}
#header-row h1{flex:1}
#theme-toggle{
  padding:3px 10px;border-radius:12px;font-size:9px;font-family:inherit;
  border:1px solid rgba(255,62,160,.35);background:rgba(80,20,120,.4);
  color:#d080ff;cursor:pointer;letter-spacing:.5px;text-transform:uppercase;
  transition:all .12s;
}
#theme-toggle:hover{border-color:#ff3ea0;color:#ff3ea0;background:rgba(255,62,160,.12)}

/* ── Light mode overrides ───────────────────────────────────────────── */
body.light{
  background:
    radial-gradient(ellipse 80% 60% at 20% 10%,rgba(176,64,255,.1) 0%,transparent 60%),
    radial-gradient(ellipse 60% 50% at 85% 80%,rgba(0,160,220,.09) 0%,transparent 55%),
    #f7f2ff;
  color:#2a1050;
}
body.light::before{opacity:.08}
body.light h1{color:#8840c0}
body.light #theme-toggle{
  border-color:rgba(130,60,200,.4);background:rgba(220,200,255,.5);
  color:#6030b0;
}
body.light #theme-toggle:hover{border-color:#ff3ea0;color:#d0005a;background:rgba(255,62,160,.1)}

/* session panel */
body.light #session-panel{
  background:#fff;
  box-shadow:0 0 0 1px rgba(176,64,255,.15),0 4px 20px rgba(120,60,200,.12);
}
body.light #sess-title{color:#8040b0}
body.light #bpm-badge{color:#8040b0}
body.light .sess-slot{background:#f0e8ff;border-color:#c0a0e0;color:#6030a0}
body.light .sess-slot:hover{border-color:#8040c0;color:#4020a0}
body.light .sess-slot.active{background:#ff3ea0;border-color:#ff3ea0;color:#fff;box-shadow:0 0 6px rgba(255,62,160,.5)}
body.light .sess-slot.on-disk{border-color:#9060d0;color:#7040b0}
body.light .sess-slot.on-disk:hover{border-color:#6030b0;color:#4010a0}
body.light #session-grid{background:#d8caf0}
body.light .sg-corner{background:#ede6ff}
body.light .sg-track-hdr{background:#f5f0ff}
body.light .sg-track-hdr:hover{background:#ece4ff}
body.light .sg-track-hdr.selected-col{background:#e4d4ff}
body.light .sg-track-name{color:#5030a0}
body.light .sg-track-type{color:#9060c0}
body.light .sg-track-hdr.t-drum .sg-track-type{color:#b04060}
body.light .sg-track-hdr.t-synth .sg-track-type{color:#1080b0}
body.light .sg-track-hdr.t-sample .sg-track-type{color:#4070b0}
body.light .sg-track-hdr.muted .sg-track-name{opacity:.35}
body.light .sg-track-hdr.soloed .sg-track-name{color:#b08000;text-shadow:none}
body.light .sg-loop-num{background:#ede6ff;color:#a090c0}
body.light .sg-cell{background:#f5f0ff}
body.light .sg-cell.empty-track{background:#faf7ff}
body.light .sg-cell.has-content{background:#e0d4f8}
body.light .sg-cell.is-playing{background:#c8f4e0}
body.light .sg-cell.is-active{background:#c8dff8}
body.light .sg-cell.is-finishing{background:#f8f0c0}
body.light .sg-cell.is-playing::after{background:#00a060;box-shadow:0 0 5px rgba(0,160,96,.7)}
body.light .sg-cell.is-finishing::after{background:#c09000;box-shadow:0 0 4px rgba(192,144,0,.7)}
body.light .sg-cell.is-active:not(.is-playing)::after{background:#0080c0;box-shadow:0 0 4px rgba(0,128,192,.6)}

/* waveform panel */
body.light #waveform-panel{
  background:#fff;
  box-shadow:0 0 0 1px rgba(176,64,255,.15),0 4px 20px rgba(120,60,200,.12);
}
body.light #wform-top{border-bottom-color:rgba(176,64,255,.15)}
body.light #wform-title{color:#8040b0}
body.light #wform-sample-name{color:#a040c0}
body.light #wform-chop-count{color:#6080a0}
body.light .wform-btn{
  background:#f0e8ff;border-color:#c090e0;color:#7030b0;
}
body.light .wform-btn:hover{
  border-color:#ff3ea0;color:#d0005a;background:#ffe8f4;box-shadow:none;
}
body.light #wform-canvas-wrap{background:#faf5ff}
body.light #wform-play-mode{
  background:rgba(220,200,255,.6)!important;
  border-color:rgba(160,80,220,.4)!important;
  color:#7030b0!important;
}

/* controller chassis */
body.light #ctrl{
  background:linear-gradient(175deg,#ede0ff 0%,#e4d4f8 60%,#dccef4 100%);
  box-shadow:
    0 0 0 1px rgba(176,64,255,.18),
    0 0 0 2px rgba(255,62,160,.06),
    0 10px 30px rgba(100,50,180,.15);
}
body.light #pads{background:#f0e8ff;box-shadow:inset 0 0 12px rgba(180,140,240,.15)}
body.light #logo{color:#7050a0}
body.light .enc{
  background:radial-gradient(circle at 38% 32%,#e4d4f8,#c8b4e8);
  border-color:#b090d8;
  box-shadow:0 2px 5px rgba(100,60,180,.25),inset 0 1px 0 rgba(255,255,255,.5);
}
body.light .enc-label{color:#7050a0}
body.light .enc-val{color:#4030a0}
body.light .pm-btn{background:#ece4ff;border-color:#c0a8e0;color:#7050a0}
body.light .mode-btn{background:#e8e0f8;border-color:#c0a8e0;color:#6040a0}
body.light .sk-btn{background:#f4f0fc;border-color:#d0c0ec;border-top-color:#d0c0ec}
body.light .sk-btn-title{color:#7050a0}
body.light .sk-btn-val{color:#4030a0}
body.light #oled-screen{
  background:#01000c;border-color:#3a1860;
  box-shadow:inset 0 0 18px rgba(0,0,30,.95),0 0 0 1px rgba(176,64,255,.12);
}
body.light #enc9{
  background:radial-gradient(circle at 38% 32%,#e4d4f8,#c8b4e8);
  border-color:#b090d8;color:#7050a0;
  box-shadow:0 3px 8px rgba(100,60,180,.2);
}
body.light .nav-sm{background:#ece4ff;border-color:#c0a8e0;color:#7050a0}
body.light .slot-btn{background:#ece4ff;border-color:#c0a8e0;color:#7050a0}
body.light .tr-btn{background:#e8e0f8;border-color:#c0a8e0;color:#6040a0}
body.light .tr-btn.play.lit{
  background:#00b060;border-color:#00b060;color:#fff;
  box-shadow:0 0 8px rgba(0,176,96,.45);
}
body.light .tr-btn.stop.lit{background:#c0b0e0;border-color:#a090c0;color:#1a0840;box-shadow:none}
body.light .tr-btn.rec.lit{
  background:#e01840;border-color:#e01840;color:#fff;
  box-shadow:0 0 8px rgba(224,24,64,.5);
}
body.light .tr-btn.metro.lit{
  background:#0090d4;border-color:#0090d4;color:#fff;
  box-shadow:0 0 8px rgba(0,144,212,.45);
}
body.light #ts-wrap{background:#ece4ff;border-color:#c0a8e0}
body.light .nav-btn{background:#ece4ff;border-color:#c0a8e0;color:#7050a0}
body.light #btn-shift{
  background:#ff3ea0;border-color:#cc1070;color:#fff;
  box-shadow:0 0 6px rgba(255,62,160,.4);
}
body.light #btn-shift.held{
  background:#e09000;border-color:#b06000;color:#fff;
  box-shadow:0 0 10px rgba(224,144,0,.6);
}
body.light .pad{
  background:#e4d8f8;border-color:#c0a8e0;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.6);
}
body.light .pad-lbl{color:rgba(100,60,180,.3)}
body.light #status{color:#8060b0}
</style>
</head>
<body>
<div id="header-row"><h1>Eden</h1><button id="theme-toggle">☀ Light</button></div>

<!-- ── Session view ─────────────────────────────────────────────────────── -->
<div id="session-panel" class="hidden">
  <div id="sess-top">
    <div id="sess-title">Session</div>
    <div id="bpm-badge"></div>
    <div class="sess-slots" id="sess-slots"></div>
  </div>
  <div id="session-grid"></div>
</div>

<!-- ── Waveform editor ──────────────────────────────────────────────────── -->
<div id="waveform-panel" class="hidden">
  <div id="wform-top">
    <div id="wform-title">Sample</div>
    <div id="wform-sample-name">—</div>
    <div id="wform-chop-count"></div>
    <div id="wform-play-mode" title="Click to cycle play mode" style="padding:2px 8px;border-radius:3px;border:1px solid rgba(176,64,255,.35);background:rgba(80,20,120,.4);color:#d080ff;font-size:8px;font-family:inherit;cursor:pointer;text-transform:uppercase;letter-spacing:.5px;transition:all .08s"></div>
    <div style="width:1px;background:rgba(176,64,255,.2);height:16px;margin:0 2px"></div>
    <button class="wform-btn" id="btn-normalize">Norm</button>
    <button class="wform-btn" id="btn-auto-detect">Detect</button>
    <button class="wform-btn" id="btn-auto4">÷4</button>
    <button class="wform-btn" id="btn-auto8">÷8</button>
    <button class="wform-btn" id="btn-auto16">÷16</button>
    <button class="wform-btn" id="btn-chop-clear">Clear</button>
  </div>
  <div id="wform-canvas-wrap">
    <canvas id="wform-canvas"></canvas>
  </div>
</div>

<!-- ── Instrument timeline ──────────────────────────────────────────────── -->
<div id="inst-timeline" class="hidden">
  <div id="tl-header">
    <div id="tl-title">Timeline</div>
    <div id="tl-info"></div>
  </div>
  <div id="tl-canvas-wrap">
    <canvas id="tl-canvas"></canvas>
  </div>
  <div id="fx-strip">
    <div class="fx-meter" id="fxm0"><div class="fx-meter-label" id="fxm0l">—</div><div class="fx-meter-bar-wrap"><div class="fx-meter-bar" id="fxm0b" style="height:0%"></div></div><div class="fx-meter-val" id="fxm0v">—</div></div>
    <div class="fx-meter" id="fxm1"><div class="fx-meter-label" id="fxm1l">—</div><div class="fx-meter-bar-wrap"><div class="fx-meter-bar" id="fxm1b" style="height:0%"></div></div><div class="fx-meter-val" id="fxm1v">—</div></div>
    <div class="fx-meter" id="fxm2"><div class="fx-meter-label" id="fxm2l">—</div><div class="fx-meter-bar-wrap"><div class="fx-meter-bar" id="fxm2b" style="height:0%"></div></div><div class="fx-meter-val" id="fxm2v">—</div></div>
    <div class="fx-meter" id="fxm3"><div class="fx-meter-label" id="fxm3l">—</div><div class="fx-meter-bar-wrap"><div class="fx-meter-bar" id="fxm3b" style="height:0%"></div></div><div class="fx-meter-val" id="fxm3v">—</div></div>
  </div>
</div>

<!-- ── Sample library ───────────────────────────────────────────────────── -->
<div id="sample-lib">
  <div id="sample-lib-top" onclick="toggleSampleLib()">
    <div id="sample-lib-title">Sample Library</div>
    <div id="sample-count"></div>
    <div id="sample-lib-toggle">▼</div>
  </div>
  <div id="sample-lib-body">
    <div id="sl-tabs">
      <button id="sl-tab-drums" class="sl-tab active" onclick="switchTab('drums')">Drums</button>
      <button id="sl-tab-samples" class="sl-tab" onclick="switchTab('samples')">Samples</button>
      <button id="sample-upload-btn" onclick="document.getElementById('sample-upload-input').click()">⬆ Upload .wav</button>
      <input id="sample-upload-input" type="file" accept=".wav" multiple onchange="uploadSamples(this)">
    </div>
    <!-- Drums pane -->
    <div id="sl-drums-pane" class="sl-pane active">
      <div id="drum-filter-row">
        <input id="drum-search" type="text" placeholder="filter drum categories…" oninput="renderDrumList()">
      </div>
      <div id="drum-list"></div>
    </div>
    <!-- Samples pane -->
    <div id="sl-samples-pane" class="sl-pane">
      <div id="samples-filter-row">
        <input id="samples-search" type="text" placeholder="filter samples…" oninput="renderSampleCatalog()">
      </div>
      <div id="sample-catalog-list"></div>
      <div id="sl-settings" class="hidden">
        <div class="sl-settings-hdr">Settings — <span class="sl-settings-key" id="sl-settings-key">—</span></div>
        <div class="sl-settings-grid">
          <span class="sl-sg-label">Mode</span><span class="sl-sg-value" id="sl-s-mode">—</span>
          <span class="sl-sg-label">Pan</span><span class="sl-sg-value" id="sl-s-pan">C</span>
          <span class="sl-sg-label">Attack</span><span class="sl-sg-value" id="sl-s-attack">0ms</span>
          <span class="sl-sg-label">Release</span><span class="sl-sg-value" id="sl-s-release">50ms</span>
          <span class="sl-sg-label">Stretch</span><span class="sl-sg-value" id="sl-s-stretch">off</span>
          <span class="sl-sg-label">Bars</span><span class="sl-sg-value" id="sl-s-bars">1</span>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ── Controller chassis ───────────────────────────────────────────────── -->
<div id="ctrl">
  <div id="top">
    <div id="logo">AT<span class="o">O</span>M&nbsp;SQ<small>Eden M5</small></div>
    <div id="encs">
      <div class="enc-row">
        <div class="enc-spacer"></div>
        <div class="enc" id="enc1"><span class="enc-label" id="enc1l">ENC</span><span class="enc-val" id="enc1v">1</span></div>
        <div class="enc" id="enc2"><span class="enc-label" id="enc2l">ENC</span><span class="enc-val" id="enc2v">2</span></div>
        <div class="enc" id="enc3"><span class="enc-label" id="enc3l">ENC</span><span class="enc-val" id="enc3v">3</span></div>
        <div class="enc" id="enc4"><span class="enc-label" id="enc4l">ENC</span><span class="enc-val" id="enc4v">4</span></div>
      </div>
      <div class="enc-row">
        <div class="pm-pair">
          <div class="pm-btn">+</div>
          <div class="pm-btn">&#8722;</div>
        </div>
        <div class="enc" id="enc5"><span class="enc-label" id="enc5l">ENC</span><span class="enc-val" id="enc5v">5</span></div>
        <div class="enc" id="enc6"><span class="enc-label" id="enc6l">ENC</span><span class="enc-val" id="enc6v">6</span></div>
        <div class="enc" id="enc7"><span class="enc-label" id="enc7l">ENC</span><span class="enc-val" id="enc7v">7</span></div>
        <div class="enc" id="enc8"><span class="enc-label" id="enc8l">ENC</span><span class="enc-val" id="enc8v">8</span></div>
      </div>
    </div>
    <div id="rpanel">
      <div id="mode-col">
        <button id="btn-song" class="mode-btn">Song</button>
        <button id="btn-inst" class="mode-btn">Inst</button>
        <button id="btn-edit" class="mode-btn">Edit</button>
        <button id="btn-user" class="mode-btn">User</button>
      </div>
      <div id="oled-block">
        <div class="sk-btn-row">
          <div class="sk-btn" id="sk1"><div class="sk-btn-title" id="sk1t"></div><div class="sk-btn-val" id="sk1v"></div></div>
          <div class="sk-btn" id="sk2"><div class="sk-btn-title" id="sk2t"></div><div class="sk-btn-val" id="sk2v"></div></div>
          <div class="sk-btn" id="sk3"><div class="sk-btn-title" id="sk3t"></div><div class="sk-btn-val" id="sk3v"></div></div>
        </div>
        <div id="oled-screen">
          <div class="main-line" id="main1">&nbsp;</div>
          <div class="main-line" id="main2">&nbsp;</div>
        </div>
        <div class="sk-btn-row">
          <div class="sk-btn" id="sk4"><div class="sk-btn-title" id="sk4t"></div><div class="sk-btn-val" id="sk4v"></div></div>
          <div class="sk-btn" id="sk5"><div class="sk-btn-title" id="sk5t"></div><div class="sk-btn-val" id="sk5v"></div></div>
          <div class="sk-btn" id="sk6"><div class="sk-btn-title" id="sk6t"></div><div class="sk-btn-val" id="sk6v"></div></div>
        </div>
      </div>
      <div id="nav-col">
        <div id="enc9">NAV</div>
        <div class="nav-pair">
          <div class="nav-sm" title="Back">&#9664;</div>
          <div class="nav-sm" title="Forward">&#9654;</div>
        </div>
      </div>
    </div>
  </div>

  <div id="mid">
    <div id="mid-left">
      <div class="slots">
        <div class="slot-btn" id="slot-0">A</div>
        <div class="slot-btn" id="slot-1">B</div>
        <div class="slot-btn" id="slot-2">C</div>
        <div class="slot-btn" id="slot-3">D</div>
        <div class="slot-btn" id="slot-4">E</div>
        <div class="slot-btn" id="slot-5">F</div>
        <div class="slot-btn" id="slot-6">G</div>
        <div class="slot-btn" id="slot-7">H</div>
      </div>
      <div class="tr-row">
        <div class="tr-btn stop"  id="btn-stop">&#9632;</div>
        <div class="tr-btn play"  id="btn-play">&#9654;</div>
        <div class="tr-btn rec"   id="btn-rec">&#9679;</div>
        <div class="tr-btn metro" id="btn-metro">&#9833;</div>
      </div>
    </div>
    <div id="ts-wrap"><div id="ts-pos"></div></div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:5px;flex-shrink:0">
      <div id="nav-cross">
        <div></div><div class="nav-btn">&#9650;</div><div></div>
        <div class="nav-btn">&#9664;</div><div></div><div class="nav-btn">&#9654;</div>
        <div></div><div class="nav-btn">&#9660;</div><div></div>
      </div>
      <button id="btn-shift">SHIFT</button>
    </div>
  </div>

  <div id="pads">
    <div class="pad-row" id="pr-top"></div>
    <div class="pad-row" id="pr-bot"></div>
  </div>

  <div id="status">connecting&hellip;</div>
</div>

<script>
// ── Pad rows ────────────────────────────────────────────────────────────────
(function(){
  const top=document.getElementById('pr-top');
  const bot=document.getElementById('pr-bot');
  for(let i=0;i<16;i++){
    const mk=idx=>{
      const d=document.createElement('div');
      d.className='pad';d.id='pad-'+idx;
      d.innerHTML='<span class="pad-lbl">'+idx+'</span>';
      return d;
    };
    top.appendChild(mk(i+16));
    bot.appendChild(mk(i));
  }
})();

// ── OLED mapping ────────────────────────────────────────────────────────────
const SK_TEXT={
  '0':'sk1t','1':'sk2t','2':'sk3t',
  '3':'sk1v','4':'sk2v','5':'sk3v',
  '6':'main1','7':'main2',
  '8':'sk4t','9':'sk5t','10':'sk6t',
  '11':'sk4v','12':'sk5v','13':'sk6v',
};
const SK_BORDER={'0':'sk1','1':'sk2','2':'sk3','8':'sk4','9':'sk5','10':'sk6'};
const rgb=(r,g,b)=>`rgb(${r},${g},${b})`;
const setLit=(id,on)=>{const e=document.getElementById(id);if(e)e.classList.toggle('lit',!!on);};

// ── Session view builder ────────────────────────────────────────────────────
const SLOTS='ABCDEFGH';

// Build slot buttons in session panel header
(function(){
  const wrap=document.getElementById('sess-slots');
  for(let i=0;i<8;i++){
    const btn=document.createElement('div');
    btn.className='sess-slot';
    btn.id='sess-slot-'+i;
    btn.textContent=SLOTS[i];
    btn.title=`Load session ${SLOTS[i]}`;
    btn.addEventListener('click',()=>post({type:'song_slot',slot:i}));
    wrap.appendChild(btn);
  }
})();

let _gridBuilt=false;

function buildSessionGrid(trackData){
  if(_gridBuilt) return;
  _gridBuilt=true;
  const grid=document.getElementById('session-grid');
  grid.innerHTML='';

  // corner
  const corner=document.createElement('div');
  corner.className='sg-corner';
  grid.appendChild(corner);

  // track headers
  for(let ti=0;ti<16;ti++){
    const hdr=document.createElement('div');
    hdr.className='sg-track-hdr';
    hdr.id='sg-hdr-'+ti;
    const t=trackData[ti];
    if(t){
      hdr.classList.add('t-'+t.type);
      hdr.innerHTML=`<div class="sg-track-name">${t.name}</div><div class="sg-track-type">${t.type}</div>`;
    } else {
      hdr.innerHTML='<div class="sg-track-name" style="color:#222">—</div>';
    }
    hdr.addEventListener('click',()=>post({type:'select_cell',track:ti,loop:0}));
    grid.appendChild(hdr);
  }

  // loop rows
  for(let li=0;li<16;li++){
    const numCell=document.createElement('div');
    numCell.className='sg-loop-num';
    numCell.textContent=li;
    grid.appendChild(numCell);
    for(let ti=0;ti<16;ti++){
      const cell=document.createElement('div');
      cell.className='sg-cell';
      cell.id=`sg-${ti}-${li}`;
      cell.addEventListener('click',()=>post({type:'select_cell',track:ti,loop:li}));
      grid.appendChild(cell);
    }
  }
}

function updateSessionGrid(s){
  // Update header state
  for(let ti=0;ti<16;ti++){
    const hdr=document.getElementById('sg-hdr-'+ti);
    if(!hdr) continue;
    const t=s.track_data[ti];
    hdr.className='sg-track-hdr'+(t?' t-'+t.type:'');
    if(t){
      if(t.muted) hdr.classList.add('muted');
      if(t.soloed) hdr.classList.add('soloed');
    }
    if(ti===s.selected_track) hdr.classList.add('selected-col');
    // Rebuild name if track appeared/disappeared
    if(t){
      const nameEl=hdr.querySelector('.sg-track-name');
      if(nameEl && nameEl.textContent!==t.name){ nameEl.textContent=t.name; }
    }
  }

  // Update cells
  for(let ti=0;ti<16;ti++){
    for(let li=0;li<16;li++){
      const cell=document.getElementById(`sg-${ti}-${li}`);
      if(!cell) continue;
      const loops=s.loop_matrix[ti];
      let cls='sg-cell';
      if(!loops){ cls+=' empty-track'; }
      else {
        const lp=loops[li];
        if(lp.filled) cls+=' has-content';
        if(lp.playing) cls+=' is-playing';
        else if(lp.active) cls+=' is-active';
        if(lp.finishing) cls+=' is-finishing';
        if(ti===s.selected_track && li===s.selected_loop) cls+=' selected';
      }
      cell.className=cls;
    }
  }
}

// ── Waveform editor ─────────────────────────────────────────────────────────
const canvas=document.getElementById('wform-canvas');
const canvasWrap=document.getElementById('wform-canvas-wrap');

let wfPeaks=null;
let wfDividers=[];      // sorted array of 0..1 positions (interior chop boundaries)
let wfTrimStart=0.0;    // trim start handle position
let wfTrimEnd=1.0;      // trim end handle position
let wfSampleKey=null;
let wfTrackIdx=-1;
let wfDragIdx=-1;       // index into wfDividers (-1 = none, -10 = trim-start, -11 = trim-end)
let wfDragStartX=0;
let wfPlayMode='oneshot';

function chopsToDiv(chops){
  // chops = [[start, end, name], ...]  → extract interior dividers
  if(!chops || chops.length<=1) return [];
  const divs=[];
  for(let i=0;i<chops.length-1;i++) divs.push(chops[i][1]);
  return divs.filter(d=>d>0&&d<1).sort((a,b)=>a-b);
}

function divToChops(dividers){
  const bounds=[0,...dividers.sort((a,b)=>a-b),1];
  return bounds.slice(0,-1).map((s,i)=>[s,bounds[i+1],'']);
}

function drawWaveform(){
  const W=canvas.width, H=canvas.height;
  const ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,W,H);

  const tsX=wfTrimStart*W, teX=wfTrimEnd*W;

  // Trim-out shading (before trim_start, after trim_end)
  ctx.fillStyle='rgba(0,0,0,0.6)';
  if(tsX>0) ctx.fillRect(0,0,tsX,H);
  if(teX<W) ctx.fillRect(teX,0,W-teX,H);

  // Alternating chop region backgrounds (within trim window)
  const allBounds=[0,...wfDividers,1];
  for(let i=0;i<allBounds.length-1;i++){
    // Map chop bounds into trim window pixel space
    const x0=tsX+allBounds[i]*(teX-tsX), x1=tsX+allBounds[i+1]*(teX-tsX);
    ctx.fillStyle=i%2===0?'#0d0320':'#120428';
    ctx.fillRect(x0,0,x1-x0,H);
  }

  if(wfPeaks && wfPeaks.length>0){
    const centerY=H/2;
    const barW=Math.max(1,W/wfPeaks.length);
    // Waveform body
    for(let i=0;i<wfPeaks.length;i++){
      const x=(i/wfPeaks.length)*W;
      const inTrim=x>=tsX&&x<=teX;
      ctx.fillStyle=inTrim?'#380c60':'#180828';
      const h=wfPeaks[i]*H*0.88;
      ctx.fillRect(x,centerY-h/2,barW,h);
    }
    // Peak outline top
    ctx.lineWidth=1;ctx.beginPath();
    for(let i=0;i<wfPeaks.length;i++){
      const x=(i/wfPeaks.length)*W+barW/2;
      const inTrim=x>=tsX&&x<=teX;
      ctx.strokeStyle=inTrim?'#ff3ea0':'#6020a0';
      const y=centerY-wfPeaks[i]*H*0.88/2;
      if(i===0){ctx.moveTo(x,y);}
      else{ctx.lineTo(x,y);ctx.stroke();ctx.beginPath();ctx.moveTo(x,y);}
    }
    ctx.stroke();
    // Peak outline bottom
    ctx.beginPath();
    for(let i=0;i<wfPeaks.length;i++){
      const x=(i/wfPeaks.length)*W+barW/2;
      const inTrim=x>=tsX&&x<=teX;
      ctx.strokeStyle=inTrim?'#ff3ea0':'#6020a0';
      const y=centerY+wfPeaks[i]*H*0.88/2;
      if(i===0){ctx.moveTo(x,y);}
      else{ctx.lineTo(x,y);ctx.stroke();ctx.beginPath();ctx.moveTo(x,y);}
    }
    ctx.stroke();
    // Centre line
    ctx.strokeStyle='#2a0850';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(0,centerY);ctx.lineTo(W,centerY);ctx.stroke();
  }

  // Chop dividers (within trim window) — hot pink
  for(let i=0;i<wfDividers.length;i++){
    const x=tsX+wfDividers[i]*(teX-tsX);
    const hot=i===wfDragIdx;
    ctx.strokeStyle=hot?'#ff80c8':'#ff3ea0';
    ctx.lineWidth=hot?3:2;
    ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();
    ctx.fillStyle=hot?'#ff80c8':'#ff3ea0';
    ctx.beginPath();ctx.arc(x,10,5,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#200010';ctx.font='bold 8px monospace';
    ctx.fillText(String(i+1),x+3,H-4);
  }

  // Chop region index labels
  ctx.font='9px monospace';
  for(let i=0;i<allBounds.length-1;i++){
    const x0=tsX+allBounds[i]*(teX-tsX), x1=tsX+allBounds[i+1]*(teX-tsX);
    if(x1-x0<16) continue;
    ctx.fillStyle='rgba(176,64,255,.55)';
    ctx.fillText(String(i),x0+3,14);
  }

  // Trim handles (cyan, drawn on top)
  const drawTrimHandle=(x,hot)=>{
    ctx.strokeStyle=hot?'#80f4ff':'#00b8d4';
    ctx.lineWidth=hot?4:3;
    ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();
    ctx.fillStyle=hot?'#80f4ff':'#00e5ff';
    ctx.fillRect(x-5,0,11,14);
    ctx.fillStyle='#010c10';ctx.font='bold 8px monospace';
    ctx.textAlign='center';ctx.fillText('T',x,11);ctx.textAlign='left';
  };
  drawTrimHandle(tsX,wfDragIdx===-10);
  drawTrimHandle(teX,wfDragIdx===-11);
}

function posToRatio(clientX){
  const rect=canvas.getBoundingClientRect();
  return Math.max(0,Math.min(1,(clientX-rect.left)/rect.width));
}

function nearestDivider(ratio,threshPx=10){
  const W=canvas.getBoundingClientRect().width;
  let best=-1, bestDist=threshPx/W;
  for(let i=0;i<wfDividers.length;i++){
    const d=Math.abs(wfDividers[i]-ratio);
    if(d<bestDist){bestDist=d;best=i;}
  }
  return best;
}

// Nearest trim handle index: -10=trim-start, -11=trim-end, or nearest chop index
function nearestTarget(ratio, threshPx=10){
  const W=canvas.getBoundingClientRect().width;
  const thresh=threshPx/W;
  // Check trim handles first (higher priority)
  if(Math.abs(ratio-wfTrimStart)<thresh) return -10;
  if(Math.abs(ratio-wfTrimEnd)<thresh) return -11;
  return nearestDivider(ratio, threshPx);
}

// Convert raw canvas ratio → chop-space ratio (0-1 within trim window)
function rawToChopRatio(ratio){
  const span=wfTrimEnd-wfTrimStart||0.0001;
  return (ratio-wfTrimStart)/span;
}
function chopToRawRatio(cr){
  return wfTrimStart+cr*(wfTrimEnd-wfTrimStart);
}

canvas.addEventListener('mousedown',e=>{
  e.preventDefault();
  const ratio=posToRatio(e.clientX);
  const target=nearestTarget(ratio);
  wfDragIdx=target;
  wfDragStartX=e.clientX;
});

canvas.addEventListener('mousemove',e=>{
  if(wfDragIdx===undefined||wfDragIdx===null) return;
  const ratio=posToRatio(e.clientX);
  if(wfDragIdx===-10){
    wfTrimStart=Math.max(0,Math.min(wfTrimEnd-0.01,ratio));
    drawWaveform();
  } else if(wfDragIdx===-11){
    wfTrimEnd=Math.min(1,Math.max(wfTrimStart+0.01,ratio));
    drawWaveform();
  } else if(wfDragIdx>=0){
    const cr=rawToChopRatio(ratio);
    wfDividers[wfDragIdx]=Math.max(0.001,Math.min(0.999,cr));
    wfDividers.sort((a,b)=>a-b);
    const nearCr=rawToChopRatio(posToRatio(e.clientX));
    wfDragIdx=nearestDivider(nearCr,40);
    drawWaveform();
    updateChopCount();
  }
});

canvas.addEventListener('mouseup',e=>{
  const wasTrim=wfDragIdx===-10||wfDragIdx===-11;
  wfDragIdx=-1;
  if(wasTrim) dispatchTrim();
  else dispatchChops();
});

canvas.addEventListener('mouseleave',e=>{
  if(wfDragIdx!==-1){
    const wasTrim=wfDragIdx===-10||wfDragIdx===-11;
    wfDragIdx=-1;
    if(wasTrim) dispatchTrim(); else dispatchChops();
  }
});

canvas.addEventListener('dblclick',e=>{
  const ratio=posToRatio(e.clientX);
  const target=nearestTarget(ratio,12);
  if(target<0) return; // near a handle, skip
  // Add chop divider in chop space
  const cr=rawToChopRatio(ratio);
  if(cr>0.001&&cr<0.999){
    wfDividers.push(cr);
    wfDividers.sort((a,b)=>a-b);
    drawWaveform();
    updateChopCount();
    dispatchChops();
  }
});

canvas.addEventListener('contextmenu',e=>{
  e.preventDefault();
  const ratio=posToRatio(e.clientX);
  const cr=rawToChopRatio(ratio);
  const near=nearestDivider(cr,16);
  if(near>=0){
    wfDividers.splice(near,1);
    drawWaveform();
    updateChopCount();
    dispatchChops();
  }
});

function updateChopCount(){
  const n=wfDividers.length+1;
  document.getElementById('wform-chop-count').textContent=`${n} chop${n!==1?'s':''}`;
}

function dispatchChops(){
  if(wfTrackIdx<0) return;
  post({type:'set_chops',track_idx:wfTrackIdx,chops:divToChops(wfDividers)});
}

function dispatchTrim(){
  if(wfTrackIdx<0) return;
  post({type:'set_trim',track_idx:wfTrackIdx,trim_start:wfTrimStart,trim_end:wfTrimEnd});
}

function autoSlice(n){
  wfDividers=[];
  for(let i=1;i<n;i++) wfDividers.push(i/n);
  drawWaveform();
  updateChopCount();
  dispatchChops();
}

document.getElementById('btn-auto4').addEventListener('click',()=>autoSlice(4));
document.getElementById('btn-auto8').addEventListener('click',()=>autoSlice(8));
document.getElementById('btn-auto16').addEventListener('click',()=>autoSlice(16));
document.getElementById('btn-chop-clear').addEventListener('click',()=>{
  wfDividers=[];drawWaveform();updateChopCount();dispatchChops();
});
document.getElementById('btn-normalize').addEventListener('click',()=>{
  if(wfTrackIdx<0) return;
  post({type:'normalize',track_idx:wfTrackIdx}).then(()=>{
    // Re-fetch waveform to show normalized peaks
    if(wfSampleKey) fetchWaveform(wfSampleKey);
  });
});
document.getElementById('btn-auto-detect').addEventListener('click',()=>{
  if(wfTrackIdx<0) return;
  const n=wfDividers.length+1||8;
  post({type:'auto_chop',track_idx:wfTrackIdx,n_slices:Math.max(2,n)});
});
document.getElementById('wform-play-mode').addEventListener('click',()=>{
  // Cycle play mode via softkey 0 equivalent — just update display optimistically
  const modes=['oneshot','gate','legato'];
  const next=modes[(modes.indexOf(wfPlayMode)+1)%modes.length];
  wfPlayMode=next;
  updatePlayModeDisplay();
  // Dispatch a softkey that triggers cycle_play_mode in reduce
  post({type:'cycle_play_mode',track_idx:wfTrackIdx});
});

let _lastSampleKey=null;

const PM_LABELS={'oneshot':'One-shot','gate':'Gate','legato':'Legato'};
const PM_COLORS={'oneshot':'#ff3ea0','gate':'#00e5ff','legato':'#b040ff'};

function updatePlayModeDisplay(){
  const el=document.getElementById('wform-play-mode');
  if(!el) return;
  el.textContent=PM_LABELS[wfPlayMode]||wfPlayMode;
  const c=PM_COLORS[wfPlayMode]||'#d080ff';
  el.style.color=c;
  el.style.borderColor=c;
  el.style.boxShadow=`0 0 8px ${c}55`;
}

function resizeCanvas(){
  const w=canvasWrap.getBoundingClientRect().width;
  canvas.width=Math.floor(w)||1086;
  canvas.height=120;
  drawWaveform();
}
window.addEventListener('resize',resizeCanvas);
resizeCanvas();

async function fetchWaveform(key){
  try{
    const r=await fetch('/waveform?key='+encodeURIComponent(key));
    if(!r.ok){wfPeaks=null;}
    else{const j=await r.json();wfPeaks=j.peaks;}
  }catch(e){wfPeaks=null;}
  drawWaveform();
}

// ── POST helper ─────────────────────────────────────────────────────────────
async function post(action){
  try{
    await fetch('/action',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(action),
    });
  }catch(e){}
}

// ── Timeline canvas ──────────────────────────────────────────────────────────
const tlCanvas=document.getElementById('tl-canvas');
const tlWrap=document.getElementById('tl-canvas-wrap');

function resizeTlCanvas(){
  const w=tlWrap.getBoundingClientRect().width;
  tlCanvas.width=Math.floor(w)||1086;
  tlCanvas.height=60;
}
window.addEventListener('resize',resizeTlCanvas);
resizeTlCanvas();

function drawTimeline(stepData, trackType, playhead){
  const W=tlCanvas.width, H=tlCanvas.height;
  const ctx=tlCanvas.getContext('2d');
  ctx.clearRect(0,0,W,H);
  if(!stepData||!stepData.steps||stepData.steps.length===0) return;

  const steps=stepData.steps;
  const n=steps.length;
  const sw=W/n;

  if(trackType==='drum'){
    // Drum: colored tick marks per step
    for(let i=0;i<n;i++){
      const x=i*sw;
      const st=steps[i];
      // Beat grid
      const beatInterval=Math.max(1,Math.round(n/(stepData.bars*4)));
      if(i%beatInterval===0){
        ctx.fillStyle='rgba(255,255,255,.04)';
        ctx.fillRect(x,0,sw,H);
      }
      if(st.on){
        const alpha=0.4+0.6*(st.velocity/127);
        ctx.fillStyle=`rgba(255,62,160,${alpha})`;
        ctx.fillRect(x+1,H*0.25,sw-2,H*0.5);
        // Pink dot at top
        ctx.beginPath();
        ctx.arc(x+sw/2,H*0.2,Math.min(sw*0.35,5),0,Math.PI*2);
        ctx.fillStyle=`rgba(255,120,200,${alpha})`;
        ctx.fill();
      }
    }
  } else {
    // Synth: pitch-colored note blocks
    // Find min/max pitch for color mapping
    let minP=127,maxP=0;
    for(const st of steps) if(st.on&&st.pitches&&st.pitches.length) {
      for(const p of st.pitches){if(p<minP)minP=p;if(p>maxP)maxP=p;}
    }
    if(minP>=maxP){minP=Math.max(0,minP-12);maxP=Math.min(127,maxP+12);}
    const pRange=maxP-minP||1;

    for(let i=0;i<n;i++){
      const x=i*sw;
      const st=steps[i];
      const beatInterval=Math.max(1,Math.round(n/(stepData.bars*4)));
      if(i%beatInterval===0){
        ctx.fillStyle='rgba(255,255,255,.04)';
        ctx.fillRect(x,0,sw,H);
      }
      if(st.on&&st.pitches&&st.pitches.length){
        const p=st.pitches[0];
        const t=(p-minP)/pRange; // 0=low, 1=high
        // Interpolate deep purple → cyan
        const r=Math.round(80*(1-t));
        const g=Math.round(100*t+20*(1-t));
        const b=Math.round(255*t+80*(1-t));
        const alpha=0.4+0.6*(st.velocity/127);
        ctx.fillStyle=`rgba(${r},${g},${b},${alpha})`;
        const noteH=Math.max(4,H*0.6);
        const noteY=H*0.2+(1-t)*(H*0.5-noteH*0.5)-(noteH*0.5);
        ctx.fillRect(x+1,Math.max(0,noteY),sw-2,noteH);
      }
    }
  }

  // Playhead cursor
  if(playhead>=0&&playhead<n){
    const px=playhead*sw+sw/2;
    ctx.strokeStyle='rgba(255,255,100,.85)';
    ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(px,0);ctx.lineTo(px,H);ctx.stroke();
    // Arrowhead
    ctx.fillStyle='rgba(255,255,100,.85)';
    ctx.beginPath();ctx.moveTo(px-4,0);ctx.lineTo(px+4,0);ctx.lineTo(px,6);ctx.fill();
  }

  // Step grid lines (subtle)
  ctx.strokeStyle='rgba(100,60,160,.3)';
  ctx.lineWidth=1;
  for(let i=1;i<n;i++){
    const x=i*sw;
    ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();
  }
}

// ── Main update ─────────────────────────────────────────────────────────────
let _firstUpdate=true;

function update(s){
  lastState=s;
  const isSession=s.mode==='SESSION';
  const isSampleInst=s.mode==='INSTRUMENT'&&s.sample_key!=null;
  const isDrumSynthInst=s.mode==='INSTRUMENT'&&s.sample_key==null&&s.step_data!=null;

  // Track active sample key and available samples for library
  if(s.available_samples) slAvailableSamples=s.available_samples;
  if(s.sample_key&&s.sample_key!==slCurrentKey){
    slCurrentKey=s.sample_key;
    if(document.getElementById('sample-lib-body').classList.contains('open')){
      if(slActiveTab==='drums') renderDrumList();
      else{renderSampleCatalog();renderSampleSettings();}
    }
  }
  if(document.getElementById('sample-lib-body').classList.contains('open')&&slActiveTab==='samples'){
    renderSampleSettings();
  }

  // Panel visibility
  document.getElementById('session-panel').classList.toggle('hidden',!isSession);
  document.getElementById('waveform-panel').classList.toggle('hidden',!isSampleInst);
  document.getElementById('inst-timeline').classList.toggle('hidden',!isDrumSynthInst);

  // Session view
  if(isSession){
    if(_firstUpdate){
      buildSessionGrid(s.track_data);
      _firstUpdate=false;
    }
    updateSessionGrid(s);
    document.getElementById('bpm-badge').textContent=s.bpm.toFixed(0)+' BPM';
    // Session slot A-H with disk state
    for(let i=0;i<8;i++){
      const btn=document.getElementById('sess-slot-'+i);
      if(!btn) continue;
      btn.className='sess-slot';
      if(i===s.slot) btn.classList.add('active');
      if(s.disk_slots[i]) btn.classList.add('on-disk');
    }
  }

  // Waveform editor
  if(isSampleInst){
    const key=s.sample_key;
    const ti=s.selected_track;
    if(key!==_lastSampleKey){
      _lastSampleKey=key;
      wfSampleKey=key;
      wfTrackIdx=ti;
      document.getElementById('wform-sample-name').textContent=key||'—';
      wfPeaks=null;
      // Reset trim to state values when sample changes
      wfTrimStart=s.trim_start??0;
      wfTrimEnd=s.trim_end??1;
      fetchWaveform(key);
    }
    wfTrackIdx=ti;
    // Sync from state while not dragging
    if(wfDragIdx===-1||wfDragIdx===undefined){
      const newDiv=chopsToDiv(s.chops);
      if(JSON.stringify(newDiv)!==JSON.stringify(wfDividers)){
        wfDividers=newDiv;
        drawWaveform();
      }
      const ts=s.trim_start??0, te=s.trim_end??1;
      if(Math.abs(ts-wfTrimStart)>0.001||Math.abs(te-wfTrimEnd)>0.001){
        wfTrimStart=ts; wfTrimEnd=te;
        drawWaveform();
      }
    }
    // Sync play mode
    if(s.play_mode&&s.play_mode!==wfPlayMode){
      wfPlayMode=s.play_mode;
      updatePlayModeDisplay();
    }
    updateChopCount();
  } else {
    _lastSampleKey=null;
    wfTrackIdx=-1;
  }

  // FX encoder knobs
  if(s.fx_knobs){
    for(let i=0;i<8;i++){
      const knob=s.fx_knobs[i];
      if(!knob) continue;
      const lEl=document.getElementById('enc'+(i+1)+'l');
      const vEl=document.getElementById('enc'+(i+1)+'v');
      if(lEl) lEl.textContent=knob.label;
      if(vEl) vEl.textContent=knob.value;
    }
  }

  // Instrument timeline (drum/synth)
  if(isDrumSynthInst&&s.step_data){
    const td=s.track_data[s.selected_track];
    const ttype=td?td.type:'drum';
    document.getElementById('tl-info').textContent=
      (td?td.name:'—')+' · L'+(s.selected_loop+1)+
      ' · '+s.step_data.step_count+' steps / '+s.step_data.bars+' bar'+(s.step_data.bars!==1?'s':'');
    drawTimeline(s.step_data, ttype, s.playhead);
  }

  // FX meters (first 4 knobs of page 0, always shown in inst-timeline)
  if(isDrumSynthInst&&s.fx_knobs){
    for(let i=0;i<4;i++){
      const knob=s.fx_knobs[i];
      if(!knob) continue;
      const lEl=document.getElementById('fxm'+i+'l');
      const bEl=document.getElementById('fxm'+i+'b');
      const vEl=document.getElementById('fxm'+i+'v');
      if(lEl) lEl.textContent=knob.label;
      if(vEl) vEl.textContent=knob.value;
      // Map value string back to a rough percentage for bar height
      // We store normalized 0-1 in fx_knobs_raw if available, else estimate from display
    }
    // Use raw fx values for bar heights
    if(s.fx_knobs_raw){
      for(let i=0;i<4;i++){
        const bEl=document.getElementById('fxm'+i+'b');
        if(bEl) bEl.style.height=Math.round(s.fx_knobs_raw[i]*100)+'%';
      }
    }
  }

  // Pads
  for(let i=0;i<32;i++){
    const [r,g,b]=s.pads[i];
    const el=document.getElementById('pad-'+i);
    if(el) el.style.backgroundColor=(r+g+b>6)?rgb(r,g,b):'#0a0a0a';
  }

  // OLED reset
  for(const id of Object.values(SK_TEXT)){
    const el=document.getElementById(id);
    if(el){el.textContent=' ';el.style.color='';}
  }
  for(const id of Object.values(SK_BORDER)){
    const el=document.getElementById(id);
    if(el) el.style.borderTopColor='#1e1e1e';
  }
  // OLED fill
  for(const [sid,elId] of Object.entries(SK_TEXT)){
    const entry=s.oled[sid];
    const el=document.getElementById(elId);
    if(!el||!entry) continue;
    const [text,r,g,b]=entry;
    el.textContent=text||' ';
    if(sid in SK_BORDER){
      const col=rgb(r,g,b);
      el.style.color=col;
      const sk=document.getElementById(SK_BORDER[sid]);
      if(sk) sk.style.borderTopColor=col;
    }
  }

  // LEDs
  setLit('btn-play',s.play); setLit('btn-stop',s.stop);
  setLit('btn-rec',s.rec);   setLit('btn-song',s.song);
  setLit('btn-inst',s.inst); setLit('btn-metro',s.metro);
  document.getElementById('btn-shift').classList.toggle('held',!!s.shift);

  // Session slots (controller mirror)
  for(let i=0;i<8;i++)
    document.getElementById('slot-'+i).classList.toggle('active',i===s.slot);

  // Status bar
  const L='ABCDEFGH'[s.slot]||'?';
  const armed=s.armed.length?s.armed.map(a=>'T'+(a+1)).join('+'):'--';
  document.getElementById('status').textContent=
    `MODE: ${s.mode}  |  BPM: ${s.bpm.toFixed(0)}  |  STEP: ${s.playhead}  |  `+
    `SLOT: ${L}  |  TRACK: T${s.track+1}  |  ARMED: ${armed}`+
    (s.finishing?' · FINISHING':'');
}

const es=new EventSource('/events');
es.onmessage=e=>{try{update(JSON.parse(e.data));}catch(err){console.error(err);}};
es.onerror=()=>{document.getElementById('status').textContent='disconnected — reload to reconnect';};

// ── Sample library ───────────────────────────────────────────────────
let slCatalog=null;
let slLoadedNames=[];
let slCurrentKey=null;
let slActiveTab='drums';
let slAvailableSamples=[];

async function loadCatalog(){
  try{
    const r=await fetch('/catalog');
    slCatalog=await r.json();
  }catch(e){}
}

async function loadSampleList(){
  try{
    const r=await fetch('/samples');
    const d=await r.json();
    slLoadedNames=d.samples||[];
    document.getElementById('sample-count').textContent=slLoadedNames.length+' loaded';
  }catch(e){}
}

function switchTab(tab){
  slActiveTab=tab;
  document.getElementById('sl-tab-drums').classList.toggle('active',tab==='drums');
  document.getElementById('sl-tab-samples').classList.toggle('active',tab==='samples');
  document.getElementById('sl-drums-pane').classList.toggle('active',tab==='drums');
  document.getElementById('sl-samples-pane').classList.toggle('active',tab==='samples');
  if(tab==='drums') renderDrumList();
  else{renderSampleCatalog();renderSampleSettings();}
}

function renderDrumList(){
  if(!slCatalog) return;
  const q=(document.getElementById('drum-search').value||'').toLowerCase();
  const el=document.getElementById('drum-list');
  el.innerHTML='';
  for(const catSet of slCatalog.drum_sets){
    const catLow=catSet.cat.toLowerCase();
    const vars=catSet.variations.filter(v=>
      !q||catLow.includes(q)||v.var.toLowerCase().includes(q)||v.key.includes(q)
    );
    if(!vars.length) continue;
    const sec=document.createElement('div');
    sec.className='drum-cat-section';
    const lbl=document.createElement('div');
    lbl.className='drum-cat-label';lbl.textContent=catSet.cat;
    const row=document.createElement('div');
    row.className='drum-var-row';
    for(const v of vars){
      const btn=document.createElement('button');
      const isLoaded=slLoadedNames.includes(v.key);
      btn.className='drum-var-btn'+(isLoaded?' loaded':'');
      btn.textContent=v.var;btn.title=v.key;
      btn.onclick=()=>{
        const curTrack=lastState?lastState.selected_track:-1;
        post({type:'load_sample',track_idx:curTrack,sample_key:v.key,track_type:'drum'});
        setTimeout(()=>loadSampleList().then(renderDrumList),300);
      };
      row.appendChild(btn);
    }
    sec.append(lbl,row);el.appendChild(sec);
  }
}

function renderSampleCatalog(){
  if(!slCatalog) return;
  const q=(document.getElementById('samples-search').value||'').toLowerCase();
  const el=document.getElementById('sample-catalog-list');
  el.innerHTML='';
  for(const catGroup of slCatalog.sample_catalog){
    const entries=catGroup.entries.filter(e=>
      !q||e.name.toLowerCase().includes(q)||e.key.includes(q)
    );
    if(!entries.length) continue;
    const sec=document.createElement('div');sec.className='scat-section';
    const hdr=document.createElement('div');hdr.className='scat-header';
    const tog=document.createElement('span');tog.className='scat-toggle';
    const body=document.createElement('div');body.className='scat-body';
    const hasActive=entries.some(e=>e.key===slCurrentKey);
    const autoOpen=!!q||hasActive;
    if(autoOpen){body.classList.add('open');tog.textContent='▼';}
    else tog.textContent='▶';
    hdr.innerHTML=`<span class="scat-name">${catGroup.cat}</span>`;
    hdr.appendChild(tog);
    hdr.onclick=()=>{
      body.classList.toggle('open');
      tog.textContent=body.classList.contains('open')?'▼':'▶';
    };
    for(const entry of entries){
      const isActive=entry.key===slCurrentKey;
      const isAvail=slAvailableSamples.includes(entry.key)||slLoadedNames.includes(entry.key);
      const item=document.createElement('div');
      item.className='sc-item'+(isActive?' sc-active':'')+(isAvail?'':' sc-unavail');
      const nm=document.createElement('span');nm.className='sc-name';
      nm.textContent=entry.name;nm.title=entry.key;
      const loadBtn=document.createElement('button');loadBtn.className='sc-load';
      loadBtn.textContent='Load';
      loadBtn.onclick=async()=>{
        const curTrack=lastState?lastState.selected_track:-1;
        await post({type:'load_sample',track_idx:curTrack,sample_key:entry.key,track_type:'sample'});
        slCurrentKey=entry.key;
        renderSampleCatalog();renderSampleSettings();
      };
      item.append(nm,loadBtn);body.appendChild(item);
    }
    sec.append(hdr,body);el.appendChild(sec);
  }
}

function renderSampleSettings(){
  const el=document.getElementById('sl-settings');
  if(!lastState||!lastState.sample_key){el.classList.add('hidden');return;}
  el.classList.remove('hidden');
  document.getElementById('sl-settings-key').textContent=lastState.sample_key;
  const PM={'oneshot':'One-shot','gate':'Gate','legato':'Legato'};
  document.getElementById('sl-s-mode').textContent=PM[lastState.play_mode]||lastState.play_mode||'—';
  const p=lastState.pan??0;
  document.getElementById('sl-s-pan').textContent=
    Math.abs(p)<0.01?'C':(p>0?'R'+Math.round(p*100):'L'+Math.round(-p*100));
  document.getElementById('sl-s-attack').textContent=Math.round((lastState.amp_attack||0)*1000)+'ms';
  document.getElementById('sl-s-release').textContent=Math.round((lastState.amp_release||0.05)*1000)+'ms';
  document.getElementById('sl-s-stretch').textContent=lastState.stretch_mode||'off';
  document.getElementById('sl-s-bars').textContent=lastState.stretch_bars??1;
}

function toggleSampleLib(){
  const body=document.getElementById('sample-lib-body');
  const tog=document.getElementById('sample-lib-toggle');
  const open=body.classList.toggle('open');
  tog.textContent=open?'▲':'▼';
  if(open){
    if(!slCatalog) loadCatalog().then(()=>{renderDrumList();renderSampleCatalog();});
    if(!slLoadedNames.length) loadSampleList().then(renderDrumList);
  }
}

async function uploadSamples(input){
  const files=Array.from(input.files);
  if(!files.length)return;
  const fd=new FormData();
  files.forEach(f=>fd.append('file',f,f.name));
  try{
    const r=await fetch('/upload_sample',{method:'POST',body:fd});
    const d=await r.json();
    if(d.saved&&d.saved.length){
      slSamples=[...new Set([...slSamples,...d.saved])].sort();
      document.getElementById('sample-count').textContent=slSamples.length+' samples';
      renderSampleList();
    }
  }catch(e){console.error('upload failed',e);}
  input.value='';
}

let lastState=null;

// ── Theme toggle ──────────────────────────────────────────────────────
const themeBtn=document.getElementById('theme-toggle');
function applyTheme(light){
  document.body.classList.toggle('light',light);
  themeBtn.textContent=light?'☾ Dark':'☀ Light';
  try{localStorage.setItem('eden-theme',light?'light':'dark');}catch(e){}
}
applyTheme(localStorage.getItem('eden-theme')==='light');
themeBtn.addEventListener('click',()=>applyTheme(!document.body.classList.contains('light')));
</script>
</body>
</html>
"""


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    from eden.state import default_state
    state_ref = StateRef(default_state())
    ui = WebUI(state_ref)
    ui.run_blocking()
