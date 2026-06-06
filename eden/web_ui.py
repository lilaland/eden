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

    # Which AppState scene slots are occupied
    scenes_saved = [s is not None for s in state.scenes]

    # Which session slots have files on disk
    disk_slots = [False] * 8
    if sessions_dir:
        for i, letter in enumerate(_SLOT_LETTERS):
            path = os.path.join(sessions_dir, f"session_{letter.lower()}.json")
            disk_slots[i] = os.path.isfile(path)

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
    })


# ── Action dispatcher ─────────────────────────────────────────────────────────

def _handle_action(action: dict, state_ref, dispatch_fn, mixer=None) -> None:
    from eden.events import (
        SongSlotPressed, SetChops, WebSelectCell,
        SetTrim, AutoChop, NormalizeAction,
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
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:#040405;min-height:100vh;
  display:flex;flex-direction:column;align-items:center;
  font-family:'Courier New',Consolas,monospace;color:#bbb;
  padding:20px 16px 32px;gap:10px;
}
h1{font-size:10px;color:#333;letter-spacing:3px;text-transform:uppercase}

/* ── Session view ─────────────────────────────────────────────────── */
#session-panel{
  width:1110px;background:#0a0a0d;border-radius:10px;
  padding:10px 12px 12px;
  box-shadow:0 0 0 1px rgba(255,255,255,.04),0 8px 32px rgba(0,0,0,.7);
}
#session-panel.hidden{display:none}
#sess-top{display:flex;align-items:center;gap:10px;margin-bottom:8px}
#sess-title{font-size:9px;color:#444;letter-spacing:2px;text-transform:uppercase;flex:1}
.sess-slots{display:flex;gap:3px}
.sess-slot{
  width:34px;height:22px;border-radius:3px;
  background:#111118;border:1px solid #222230;
  color:#444;font-size:8px;text-align:center;line-height:22px;
  cursor:pointer;transition:all .08s;user-select:none;
}
.sess-slot:hover{border-color:#3a3a50;color:#777}
.sess-slot.active{background:#e07800;border-color:#e07800;color:#000;box-shadow:0 0 6px rgba(224,120,0,.45)}
.sess-slot.on-disk{border-color:#2a2a50;color:#5060a0}
.sess-slot.on-disk:hover{border-color:#4040a0;color:#8090e0}
.sess-slot.active.on-disk{background:#e07800;border-color:#e07800;color:#000}
#bpm-badge{font-size:9px;color:#555;letter-spacing:1px}

/* session grid */
#session-grid{
  display:grid;
  grid-template-columns:24px repeat(16,1fr);
  gap:1px;background:#111116;border-radius:4px;overflow:hidden;
}
.sg-corner{background:#0c0c10}
.sg-track-hdr{
  background:#111118;padding:3px 2px 3px;cursor:pointer;
  min-width:0;overflow:hidden;text-align:center;
}
.sg-track-hdr:hover{background:#18181e}
.sg-track-hdr.selected-col{background:#1a1a25}
.sg-track-name{
  font-size:7px;color:#555;text-transform:uppercase;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  letter-spacing:.3px;
}
.sg-track-type{font-size:6px;color:#333;text-transform:uppercase;margin-top:1px}
.sg-track-hdr.t-drum .sg-track-type{color:#604010}
.sg-track-hdr.t-synth .sg-track-type{color:#104040}
.sg-track-hdr.t-sample .sg-track-type{color:#103040}
.sg-track-hdr.muted .sg-track-name{opacity:.35}
.sg-track-hdr.soloed .sg-track-name{color:#e0a020}
.sg-loop-num{
  background:#0c0c0f;font-size:7px;color:#282830;
  text-align:right;padding-right:3px;line-height:20px;
}
.sg-cell{
  height:20px;background:#0c0c10;cursor:pointer;
  position:relative;transition:background .06s;border:1px solid transparent;
}
.sg-cell.empty-track{background:#080809;cursor:default}
.sg-cell.has-content{background:#181825}
.sg-cell.is-playing{background:#0a2a18}
.sg-cell.is-active{background:#0f1e2d}
.sg-cell.is-finishing{background:#1e1a08}
.sg-cell.selected{border-color:#e07800!important;z-index:1}
.sg-cell:not(.empty-track):hover{filter:brightness(1.35)}

/* play dot inside cells */
.sg-cell.is-playing::after{
  content:'';position:absolute;top:50%;left:50%;
  transform:translate(-50%,-50%);
  width:5px;height:5px;border-radius:50%;
  background:#20c060;box-shadow:0 0 4px rgba(32,192,96,.7);
}
.sg-cell.is-finishing::after{
  background:#c0a020;box-shadow:0 0 4px rgba(192,160,32,.7);
}
.sg-cell.is-active:not(.is-playing)::after{
  background:#2060a0;box-shadow:0 0 4px rgba(32,96,160,.5);
}

/* ── Waveform editor ──────────────────────────────────────────────── */
#waveform-panel{
  width:1110px;background:#06060a;border-radius:10px;
  box-shadow:0 0 0 1px rgba(255,255,255,.04),0 8px 32px rgba(0,0,0,.7);
  overflow:hidden;
}
#waveform-panel.hidden{display:none}
#wform-top{
  display:flex;align-items:center;gap:8px;
  padding:7px 12px 5px;border-bottom:1px solid #111120;
}
#wform-title{font-size:9px;color:#444;letter-spacing:2px;text-transform:uppercase}
#wform-sample-name{font-size:10px;color:#6080a0;letter-spacing:.5px;flex:1}
#wform-chop-count{font-size:9px;color:#446060}
.wform-btn{
  padding:2px 8px;border-radius:3px;border:1px solid #222240;
  background:#0e0e1e;color:#5060a0;font-size:8px;font-family:inherit;
  cursor:pointer;text-transform:uppercase;letter-spacing:.5px;
  transition:all .08s;
}
.wform-btn:hover{border-color:#4040a0;color:#8090e0;background:#121230}
#wform-canvas-wrap{
  position:relative;height:120px;cursor:crosshair;
  background:#050508;
}
#wform-canvas{display:block;width:100%;height:120px}
.chop-handle{
  position:absolute;top:0;bottom:0;width:2px;
  background:#c02020;cursor:col-resize;z-index:10;
}
.chop-handle::before{
  content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);
  width:10px;height:10px;border-radius:50%;
  background:#c02020;border:1px solid #ff4040;
}
.chop-handle:hover{background:#ff3030}
.chop-label{
  position:absolute;bottom:3px;left:3px;
  font-size:7px;color:#c02020;pointer-events:none;
}
/* Trim handle (orange, bracket-style) */
.trim-handle{
  position:absolute;top:0;bottom:0;width:3px;
  background:#c07000;cursor:col-resize;z-index:12;
}
.trim-handle::before{
  content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);
  width:12px;height:12px;
  background:#e08000;border:1px solid #ffb020;border-radius:2px;
}
.trim-handle:hover{background:#e09020}
.trim-handle.trim-start::after{
  content:'◀';position:absolute;top:14px;left:2px;
  font-size:7px;color:#e08000;
}
.trim-handle.trim-end::after{
  content:'▶';position:absolute;top:14px;right:2px;
  font-size:7px;color:#e08000;
}

/* ── Controller chassis (unchanged structure) ─────────────────────── */
#ctrl{
  background:linear-gradient(175deg,#222 0%,#1a1a1a 60%,#161616 100%);
  border-radius:14px;padding:14px;width:1110px;
  box-shadow:0 0 0 1px rgba(255,255,255,.06),0 16px 48px rgba(0,0,0,.85);
}
#top{display:flex;align-items:flex-start;gap:10px;margin-bottom:8px}
#mid{display:flex;align-items:center;gap:8px;margin-bottom:8px}
#pads{background:#0f0f0f;border-radius:8px;padding:10px 10px 8px;overflow:visible}
#logo{min-width:60px;padding-top:6px;font-size:11px;font-weight:bold;
  letter-spacing:2px;text-transform:uppercase;color:#555;line-height:1.6}
#logo .o{color:#e07800}
#logo small{display:block;font-size:7px;letter-spacing:1px;color:#333;margin-top:1px}
#encs{display:flex;flex-direction:column;gap:6px;padding-top:2px}
.enc-row{display:flex;gap:14px;align-items:center}
.enc-spacer{width:63px;flex-shrink:0}
.enc{
  width:40px;height:40px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#363636,#111);
  border:1px solid #2e2e2e;
  display:flex;align-items:center;justify-content:center;
  font-size:8px;color:#3a3a3a;
  box-shadow:0 3px 7px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.06);
}
.pm-pair{display:flex;gap:3px;flex-shrink:0}
.pm-btn{
  width:30px;height:28px;border-radius:3px;
  background:#1a1a1a;border:1px solid #272727;
  color:#555;font-size:12px;text-align:center;line-height:28px;cursor:default;
}
#rpanel{display:flex;align-items:flex-start;gap:8px;margin-left:auto}
#mode-col{display:flex;flex-direction:column;gap:4px;padding-top:2px}
.mode-btn{
  width:62px;height:30px;border-radius:4px;
  background:#1e1e1e;border:1px solid #2a2a2a;
  color:#555;font-size:8px;font-family:inherit;
  text-transform:uppercase;letter-spacing:.4px;cursor:default;transition:all .06s;
}
.mode-btn.lit{background:#e07800;border-color:#e07800;color:#000;box-shadow:0 0 8px rgba(224,120,0,.55)}
#oled-block{display:flex;flex-direction:column;gap:3px}
.sk-btn-row{display:flex;gap:3px}
.sk-btn{
  flex:1;min-width:0;height:42px;border-radius:3px;
  background:#141414;border:1px solid #1e1e1e;border-top:4px solid #1e1e1e;
  padding:2px 5px;cursor:default;transition:border-top-color .08s;
}
.sk-btn-title{
  font-size:8px;color:#2e2e2e;text-transform:uppercase;letter-spacing:.4px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .08s;
}
.sk-btn-val{font-size:9px;color:#555;white-space:nowrap;overflow:hidden}
#oled-screen{
  background:#010307;border-radius:5px;border:1px solid #1a1a1a;
  padding:5px 8px;width:216px;
  box-shadow:inset 0 0 18px rgba(0,0,20,.9);
}
.main-line{font-size:11px;color:#ddd;white-space:nowrap;overflow:hidden;line-height:1.5}
#nav-col{display:flex;flex-direction:column;align-items:center;gap:5px}
#enc9{
  width:56px;height:56px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#353535,#101010);
  border:2px solid #2e2e2e;
  display:flex;align-items:center;justify-content:center;
  font-size:7px;color:#383838;box-shadow:0 4px 12px rgba(0,0,0,.6);
}
.nav-pair{display:flex;gap:3px}
.nav-sm{
  width:28px;height:22px;border-radius:3px;
  background:#1a1a1a;border:1px solid #272727;
  color:#444;font-size:10px;text-align:center;line-height:22px;cursor:default;
}
.slots{display:flex;gap:3px;margin-bottom:3px}
.slot-btn{
  width:32px;height:28px;border-radius:3px;
  background:#181818;border:1px solid #252525;
  color:#444;font-size:8px;text-align:center;line-height:28px;
  cursor:default;transition:all .06s;
}
.slot-btn.active{background:#e07800;border-color:#e07800;color:#000;box-shadow:0 0 6px rgba(224,120,0,.5)}
.tr-row{display:flex;gap:4px;margin-top:4px}
.tr-btn{
  width:42px;height:36px;border-radius:4px;
  background:#1e1e1e;border:1px solid #2a2a2a;
  color:#555;font-size:13px;text-align:center;line-height:36px;
  cursor:default;transition:all .06s;
}
.tr-btn.play.lit {background:#00b060;border-color:#00b060;color:#000;box-shadow:0 0 7px rgba(0,176,96,.5)}
.tr-btn.stop.lit {background:#444;border-color:#555;color:#ddd}
.tr-btn.rec.lit  {background:#c0302a;border-color:#c0302a;color:#fff;box-shadow:0 0 7px rgba(192,48,42,.5)}
.tr-btn.metro.lit{background:#555;border-color:#666;color:#ddd}
#ts-wrap{flex:1;height:18px;background:#0d0d0d;border-radius:8px;border:1px solid #202020;position:relative;overflow:hidden}
#ts-pos{position:absolute;width:22px;height:100%;background:#e07800;border-radius:7px;left:50%;transform:translateX(-50%);opacity:0;transition:left .04s,opacity .1s}
#nav-cross{
  display:grid;
  grid-template-columns:repeat(3,28px);
  grid-template-rows:repeat(3,28px);
  gap:3px;
}
.nav-btn{
  width:28px;height:28px;border-radius:4px;
  background:#1e1e1e;border:1px solid #2a2a2a;
  color:#555;font-size:11px;text-align:center;line-height:28px;cursor:default;
}
#btn-shift{
  width:64px;height:28px;border-radius:4px;
  background:#e07800;border:1px solid #b05800;
  color:#000;font-size:8px;font-family:inherit;
  text-transform:uppercase;font-weight:bold;letter-spacing:.5px;
  cursor:default;transition:all .06s;margin-top:5px;
}
#btn-shift.held{background:#ffaa00;box-shadow:0 0 10px rgba(255,170,0,.65)}
.pad-row{display:flex;gap:3px;margin-bottom:4px}
.pad-row:last-child{margin-bottom:0}
#pr-top{padding-left:30px}
.pad{
  width:58px;height:46px;border-radius:5px;
  background:#0a0a0a;border:1px solid #1c1c1c;
  position:relative;transition:background-color .04s;flex-shrink:0;
}
.pad-lbl{position:absolute;bottom:3px;left:4px;font-size:7px;color:rgba(255,255,255,.12)}
#status{text-align:center;font-size:9px;color:#383838;padding-top:4px;letter-spacing:.5px}
</style>
</head>
<body>
<h1>Eden</h1>

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
    <div id="wform-play-mode" title="Click to cycle play mode" style="padding:2px 8px;border-radius:3px;border:1px solid #222240;background:#0e0e1e;color:#6070a0;font-size:8px;font-family:inherit;cursor:pointer;text-transform:uppercase;letter-spacing:.5px;transition:all .08s"></div>
    <div style="width:1px;background:#222240;height:16px;margin:0 2px"></div>
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

<!-- ── Controller chassis ───────────────────────────────────────────────── -->
<div id="ctrl">
  <div id="top">
    <div id="logo">AT<span class="o">O</span>M&nbsp;SQ<small>Eden M5</small></div>
    <div id="encs">
      <div class="enc-row">
        <div class="enc-spacer"></div>
        <div class="enc">1</div><div class="enc">2</div>
        <div class="enc">3</div><div class="enc">4</div>
      </div>
      <div class="enc-row">
        <div class="pm-pair">
          <div class="pm-btn">+</div>
          <div class="pm-btn">&#8722;</div>
        </div>
        <div class="enc">5</div><div class="enc">6</div>
        <div class="enc">7</div><div class="enc">8</div>
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
    <div>
      <div class="slots">
        <div class="slot-btn" id="slot-0">A</div>
        <div class="slot-btn" id="slot-1">B</div>
        <div class="slot-btn" id="slot-2">C</div>
        <div class="slot-btn" id="slot-3">D</div>
      </div>
      <div class="slots">
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
    ctx.fillStyle=i%2===0?'#050510':'#070718';
    ctx.fillRect(x0,0,x1-x0,H);
  }

  if(wfPeaks && wfPeaks.length>0){
    const centerY=H/2;
    const barW=Math.max(1,W/wfPeaks.length);
    // Waveform body
    for(let i=0;i<wfPeaks.length;i++){
      const x=(i/wfPeaks.length)*W;
      const inTrim=x>=tsX&&x<=teX;
      ctx.fillStyle=inTrim?'#122840':'#0a1420';
      const h=wfPeaks[i]*H*0.88;
      ctx.fillRect(x,centerY-h/2,barW,h);
    }
    // Peak outline top
    ctx.lineWidth=1;ctx.beginPath();
    for(let i=0;i<wfPeaks.length;i++){
      const x=(i/wfPeaks.length)*W+barW/2;
      const inTrim=x>=tsX&&x<=teX;
      ctx.strokeStyle=inTrim?'#3070a0':'#1a3050';
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
      ctx.strokeStyle=inTrim?'#3070a0':'#1a3050';
      const y=centerY+wfPeaks[i]*H*0.88/2;
      if(i===0){ctx.moveTo(x,y);}
      else{ctx.lineTo(x,y);ctx.stroke();ctx.beginPath();ctx.moveTo(x,y);}
    }
    ctx.stroke();
    // Centre line
    ctx.strokeStyle='#0a1e30';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(0,centerY);ctx.lineTo(W,centerY);ctx.stroke();
  }

  // Chop dividers (within trim window)
  for(let i=0;i<wfDividers.length;i++){
    const x=tsX+wfDividers[i]*(teX-tsX);
    const hot=i===wfDragIdx;
    ctx.strokeStyle=hot?'#ff5050':'#cc2222';
    ctx.lineWidth=hot?3:2;
    ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();
    ctx.fillStyle=hot?'#ff5050':'#cc2222';
    ctx.beginPath();ctx.arc(x,10,5,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#cc2222';ctx.font='bold 8px monospace';
    ctx.fillText(String(i+1),x+3,H-4);
  }

  // Chop region index labels
  ctx.font='9px monospace';
  for(let i=0;i<allBounds.length-1;i++){
    const x0=tsX+allBounds[i]*(teX-tsX), x1=tsX+allBounds[i+1]*(teX-tsX);
    if(x1-x0<16) continue;
    ctx.fillStyle='rgba(80,120,160,.5)';
    ctx.fillText(String(i),x0+3,14);
  }

  // Trim handles (orange, drawn on top)
  const drawTrimHandle=(x,hot)=>{
    ctx.strokeStyle=hot?'#ffb020':'#c07000';
    ctx.lineWidth=hot?4:3;
    ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();
    ctx.fillStyle=hot?'#ffb020':'#e08000';
    ctx.fillRect(x-5,0,11,14);
    ctx.fillStyle='#050508';ctx.font='bold 8px monospace';
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
const PM_COLORS={'oneshot':'#5060a0','gate':'#507060','legato':'#705060'};

function updatePlayModeDisplay(){
  const el=document.getElementById('wform-play-mode');
  if(!el) return;
  el.textContent=PM_LABELS[wfPlayMode]||wfPlayMode;
  el.style.color=PM_COLORS[wfPlayMode]||'#6070a0';
  el.style.borderColor=(PM_COLORS[wfPlayMode]||'#5060a0').replace(/[0-9a-f]{2}/gi,h=>Math.min(255,parseInt(h,16)+16).toString(16).padStart(2,'0'));
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

// ── Main update ─────────────────────────────────────────────────────────────
let _firstUpdate=true;

function update(s){
  const isSession=s.mode==='SESSION';
  const isSampleInst=s.mode==='INSTRUMENT'&&s.sample_key!=null;

  // Panel visibility
  document.getElementById('session-panel').classList.toggle('hidden',!isSession);
  document.getElementById('waveform-panel').classList.toggle('hidden',!isSampleInst);

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
