"""eden/web_ui.py — Browser-based real-time controller mirror for Eden.

Serves on http://localhost:8765, zero extra deps (stdlib http.server + SSE).
Streams state at ~30 fps via Server-Sent Events.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eden.audio import StateRef
from eden.render import render_pads, render_oled, render_button_leds
from controller_map import (
    OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
    OLED_BTN4_TITLE, OLED_BTN5_TITLE,
    OLED_BTN1_VALUE, OLED_BTN2_VALUE, OLED_BTN3_VALUE,
    OLED_BTN4_VALUE, OLED_BTN5_VALUE,
    OLED_MAIN_LINE1, OLED_MAIN_LINE2,
    NATIVE_LED_PLAY, NATIVE_LED_STOP, NATIVE_LED_REC,
    NATIVE_LED_SONG, NATIVE_LED_INST,
)

PORT = 8765

# ── State serializer ──────────────────────────────────────────────────────────

def _to_json(state) -> str:
    pads  = render_pads(state)
    oled  = render_oled(state)
    leds  = render_button_leds(state)

    # Scale 7-bit → 8-bit for CSS rgb()
    pad_data = [[c[0] * 2, c[1] * 2, c[2] * 2] for c in pads]
    oled_data = {
        str(k): [t, r * 2, g * 2, b * 2]
        for k, (t, r, g, b) in oled.items()
    }

    return json.dumps({
        "pads":      pad_data,
        "oled":      oled_data,
        "play":      leds.get(NATIVE_LED_PLAY, False),
        "stop":      leds.get(NATIVE_LED_STOP, False),
        "rec":       leds.get(NATIVE_LED_REC, False),
        "song":      leds.get(NATIVE_LED_SONG, False),
        "inst":      leds.get(NATIVE_LED_INST, False),
        "mode":      state.mode.name,
        "bpm":       state.tempo_bpm,
        "playhead":  state.playhead,
        "shift":     state.shift_held,
        "metro":     state.metronome_held,
        "track":     state.selected_track,
        "slot":      state.active_session_slot,
        "armed":     list(state.armed_tracks),
        "playing":   state.is_playing,
        "finishing": len(state.finishing_loops) > 0,
    })


# ── HTTP handler ──────────────────────────────────────────────────────────────

def _make_handler(state_ref: StateRef):
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # silence access log

        def do_GET(self):
            if self.path == "/":
                body = _HTML.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(body))
                self.end_headers()
                self.wfile.write(body)

            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    while True:
                        data = _to_json(state_ref.get())
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(1 / 30)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            else:
                self.send_response(404)
                self.end_headers()

    return _Handler


# ── Public class ──────────────────────────────────────────────────────────────

class WebUI:
    def __init__(self, state_ref: StateRef, port: int = PORT) -> None:
        self._state_ref = state_ref
        self._port = port

    def run_blocking(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", self._port), _make_handler(self._state_ref))
        url = f"http://localhost:{self._port}"
        print(f"[UI] Controller mirror → {url}")
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


# ── HTML/CSS/JS (embedded) ────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Eden — Controller Mirror</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:#060606;
  min-height:100vh;
  display:flex;
  flex-direction:column;
  align-items:center;
  justify-content:center;
  font-family:'Courier New',Consolas,monospace;
  color:#bbb;
  padding:24px 16px;
}
h1{font-size:11px;color:#444;letter-spacing:3px;text-transform:uppercase;margin-bottom:14px}

/* ── chassis ── */
#ctrl{
  background:linear-gradient(175deg,#222 0%,#1a1a1a 60%,#161616 100%);
  border-radius:14px;
  padding:14px 14px 12px;
  width:1060px;
  box-shadow:0 0 0 1px rgba(255,255,255,0.06),0 16px 48px rgba(0,0,0,0.85);
}

/* ── sections ── */
#top{display:flex;align-items:flex-start;gap:10px;margin-bottom:8px}
#mid{display:flex;align-items:center;gap:8px;margin-bottom:8px}
#pads{background:#0f0f0f;border-radius:8px;padding:10px 10px 8px}

/* ── logo ── */
#logo{
  min-width:64px;
  padding-top:6px;
  font-size:11px;
  font-weight:bold;
  letter-spacing:2px;
  text-transform:uppercase;
  color:#555;
  line-height:1.6;
}
#logo .o{color:#e07800}
#logo small{display:block;font-size:7px;letter-spacing:1px;color:#333;margin-top:1px}

/* ── encoders ── */
#encs{display:flex;flex-direction:column;gap:5px;padding-top:2px}
.enc-row{display:flex;gap:5px}
.enc{
  width:40px;height:40px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#363636,#111);
  border:1px solid #2e2e2e;
  display:flex;align-items:center;justify-content:center;
  font-size:8px;color:#3a3a3a;
  box-shadow:0 3px 7px rgba(0,0,0,.55),inset 0 1px 0 rgba(255,255,255,.06);
}

/* ── right panel (mode + oled + enc9) ── */
#rpanel{display:flex;align-items:flex-start;gap:7px;margin-left:auto}

.mode-group{display:grid;grid-template-columns:1fr 1fr;gap:4px}
.mode-btn{
  width:50px;height:24px;border-radius:4px;
  background:#1e1e1e;border:1px solid #2a2a2a;
  color:#555;font-size:8px;font-family:inherit;
  text-transform:uppercase;letter-spacing:.4px;cursor:default;
  transition:all .06s;
}
.mode-btn.lit{background:#e07800;border-color:#e07800;color:#000;box-shadow:0 0 8px rgba(224,120,0,.55)}

/* ── OLED ── */
#oled{
  width:210px;
  background:#010307;
  border-radius:6px;border:1px solid #1e1e1e;
  padding:7px 8px 6px;
  box-shadow:inset 0 0 18px rgba(0,0,20,.9),0 1px 0 rgba(255,255,255,.04);
}
.sk-row{display:flex;gap:5px;margin-bottom:3px}
.sk{flex:1;border-top:2px solid #1e1e1e;padding-top:2px;min-width:0}
.sk-title{
  font-size:8px;color:#3a3a3a;text-transform:uppercase;
  letter-spacing:.4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.sk-val{
  font-size:9px;color:#888;white-space:nowrap;overflow:hidden;
}
#oled-main{border-top:1px solid #111;margin-top:4px;padding-top:4px}
.main-line{font-size:11px;color:#ddd;white-space:nowrap;overflow:hidden;line-height:1.5}

/* ── enc9 (nav wheel) ── */
#enc9{
  width:54px;height:54px;border-radius:50%;
  background:radial-gradient(circle at 38% 32%,#353535,#101010);
  border:2px solid #2e2e2e;
  display:flex;align-items:center;justify-content:center;
  font-size:7px;color:#383838;
  box-shadow:0 4px 12px rgba(0,0,0,.6);
  flex-shrink:0;
}

/* ── slot buttons A-H ── */
.slots{display:flex;gap:3px;margin-bottom:5px}
.slot-btn{
  width:26px;height:22px;border-radius:3px;
  background:#181818;border:1px solid #252525;
  color:#444;font-size:8px;text-align:center;line-height:22px;
  cursor:default;transition:all .06s;
}
.slot-btn.active{background:#e07800;border-color:#e07800;color:#000;box-shadow:0 0 6px rgba(224,120,0,.5)}

/* ── transport buttons ── */
.tr-row{display:flex;gap:4px}
.tr-btn{
  width:34px;height:28px;border-radius:4px;
  background:#1e1e1e;border:1px solid #2a2a2a;
  color:#555;font-size:11px;text-align:center;line-height:28px;
  cursor:default;transition:all .06s;
}
.tr-btn.play.lit {background:#00b060;border-color:#00b060;color:#000;box-shadow:0 0 7px rgba(0,176,96,.5)}
.tr-btn.stop.lit {background:#444;border-color:#555;color:#ddd}
.tr-btn.rec.lit  {background:#c0302a;border-color:#c0302a;color:#fff;box-shadow:0 0 7px rgba(192,48,42,.5)}
.tr-btn.metro.lit{background:#555;border-color:#666;color:#ddd}

/* ── touchstrip ── */
#ts-wrap{
  flex:1;height:12px;background:#0d0d0d;
  border-radius:6px;border:1px solid #202020;
  position:relative;overflow:hidden;
}
#ts-pos{
  position:absolute;width:18px;height:100%;
  background:#e07800;border-radius:5px;
  left:50%;transform:translateX(-50%);
  opacity:0;transition:left .04s,opacity .1s;
}

/* ── nav arrows + shift ── */
#nav-cluster{display:grid;grid-template-columns:26px 26px;gap:3px}
.nav-btn{
  width:26px;height:26px;border-radius:4px;
  background:#1e1e1e;border:1px solid #2a2a2a;
  color:#555;font-size:10px;text-align:center;line-height:26px;
  cursor:default;
}
#btn-shift{
  width:52px;height:28px;border-radius:4px;
  background:#e07800;border:1px solid #b05800;
  color:#000;font-size:8px;font-family:inherit;
  text-transform:uppercase;font-weight:bold;letter-spacing:.5px;
  cursor:default;transition:all .06s;
}
#btn-shift.held{background:#ffaa00;box-shadow:0 0 10px rgba(255,170,0,.65)}

/* ── back / forward nav ── */
.nav-pair{display:flex;gap:3px;align-items:center}
.nav-sm{
  width:28px;height:22px;border-radius:3px;
  background:#1a1a1a;border:1px solid #272727;
  color:#444;font-size:10px;text-align:center;line-height:22px;
  cursor:default;
}

/* ── pad grid ── */
.pad-row{display:flex;gap:4px;margin-bottom:4px}
.pad-row:last-child{margin-bottom:0}
.pad{
  width:60px;height:46px;border-radius:5px;
  background:#0a0a0a;border:1px solid #1c1c1c;
  position:relative;transition:background-color .04s;
  flex-shrink:0;
}
.pad-lbl{
  position:absolute;bottom:3px;left:4px;
  font-size:7px;color:rgba(255,255,255,.12);
}

/* ── status bar ── */
#status{
  text-align:center;font-size:9px;color:#383838;
  padding-top:7px;letter-spacing:.5px;
}
</style>
</head>
<body>
<h1>Eden &mdash; Controller Mirror</h1>

<div id="ctrl">

  <!-- TOP: logo · encoders · [spacer] · mode buttons · OLED · enc9 -->
  <div id="top">

    <div id="logo">
      AT<span class="o">O</span>M&nbsp;SQ
      <small>Eden M2</small>
    </div>

    <div id="encs">
      <div class="enc-row">
        <div class="enc">1</div><div class="enc">2</div>
        <div class="enc">3</div><div class="enc">4</div>
      </div>
      <div class="enc-row">
        <div class="enc">5</div><div class="enc">6</div>
        <div class="enc">7</div><div class="enc">8</div>
      </div>
    </div>

    <div id="rpanel">
      <div class="mode-group">
        <button id="btn-song" class="mode-btn">Song</button>
        <button id="btn-inst" class="mode-btn">Inst</button>
        <button id="btn-edit" class="mode-btn">Edit</button>
        <button id="btn-user" class="mode-btn">User</button>
      </div>

      <div id="oled">
        <div class="sk-row">
          <div class="sk" id="sk1"><div class="sk-title" id="sk1t"></div><div class="sk-val" id="sk1v"></div></div>
          <div class="sk" id="sk2"><div class="sk-title" id="sk2t"></div><div class="sk-val" id="sk2v"></div></div>
          <div class="sk" id="sk3"><div class="sk-title" id="sk3t"></div><div class="sk-val" id="sk3v"></div></div>
        </div>
        <div class="sk-row">
          <div class="sk" id="sk4"><div class="sk-title" id="sk4t"></div><div class="sk-val" id="sk4v"></div></div>
          <div class="sk" id="sk5"><div class="sk-title" id="sk5t"></div><div class="sk-val" id="sk5v"></div></div>
        </div>
        <div id="oled-main">
          <div class="main-line" id="main1">&nbsp;</div>
          <div class="main-line" id="main2">&nbsp;</div>
        </div>
      </div>

      <div id="enc9">NAV</div>
    </div>
  </div>

  <!-- MIDDLE: slots · transport · touchstrip · nav · shift -->
  <div id="mid">

    <div>
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
        <div class="tr-btn metro" id="btn-metro">&#119137;</div>
      </div>
    </div>

    <div id="ts-wrap"><div id="ts-pos"></div></div>

    <div style="display:flex;gap:8px;align-items:center;flex-shrink:0">
      <div class="nav-pair">
        <div class="nav-sm">&#9664;</div>
        <div class="nav-sm">&#9654;</div>
      </div>
      <div id="nav-cluster">
        <div class="nav-btn">&#9664;</div>
        <div class="nav-btn">&#9650;</div>
        <div class="nav-btn">&#9660;</div>
        <div class="nav-btn">&#9654;</div>
      </div>
      <button id="btn-shift">SHIFT</button>
    </div>
  </div>

  <!-- PADS: top row = 16-31, bottom row = 0-15 -->
  <div id="pads">
    <div class="pad-row" id="pr-top"></div>
    <div class="pad-row" id="pr-bot"></div>
  </div>

  <div id="status">connecting&hellip;</div>
</div>

<script>
// Build pad rows
(function() {
  const top = document.getElementById('pr-top');
  const bot = document.getElementById('pr-bot');
  for (let i = 0; i < 16; i++) {
    const mk = (idx) => {
      const d = document.createElement('div');
      d.className = 'pad'; d.id = 'pad-' + idx;
      d.innerHTML = '<span class="pad-lbl">' + idx + '</span>';
      return d;
    };
    top.appendChild(mk(i + 16));
    bot.appendChild(mk(i));
  }
})();

// OLED slot-id → [titleElId, valueElId, skEl]
// slot IDs from controller_map.py:
//  0=BTN1_TITLE, 1=BTN2_TITLE, 2=BTN3_TITLE
//  3=BTN1_VAL,   4=BTN2_VAL,   5=BTN3_VAL
//  6=MAIN_LINE1, 7=MAIN_LINE2
//  8=BTN4_TITLE, 9=BTN5_TITLE
//  11=BTN4_VAL,  12=BTN5_VAL
const SK_MAP = {
  '0':'sk1t','1':'sk2t','2':'sk3t',
  '3':'sk1v','4':'sk2v','5':'sk3v',
  '6':'main1','7':'main2',
  '8':'sk4t','9':'sk5t',
  '11':'sk4v','12':'sk5v',
};
const SK_BORDERS = {'0':'sk1','1':'sk2','2':'sk3','8':'sk4','9':'sk5'};

function rgb(r,g,b){return `rgb(${r},${g},${b})`}

function setLit(id, on) {
  const el = document.getElementById(id);
  if (el) el.classList.toggle('lit', !!on);
}

function update(s) {
  // Pads
  for (let i = 0; i < 32; i++) {
    const [r,g,b] = s.pads[i];
    const el = document.getElementById('pad-'+i);
    if (!el) continue;
    el.style.backgroundColor = (r+g+b > 6) ? rgb(r,g,b) : '#0a0a0a';
  }

  // Clear all OLED elements
  for (const id of Object.values(SK_MAP)) {
    const el = document.getElementById(id);
    if (el) { el.textContent = ' '; el.style.color = ''; }
  }
  for (const id of Object.values(SK_BORDERS)) {
    const el = document.getElementById(id);
    if (el) el.style.borderTopColor = '#1e1e1e';
  }

  // Fill OLED from state
  for (const [sid, elId] of Object.entries(SK_MAP)) {
    const entry = s.oled[sid];
    const el = document.getElementById(elId);
    if (!el) continue;
    if (entry) {
      const [text, r, g, b] = entry;
      el.textContent = text || ' ';
      // Title slots: color the text and the border
      if (sid in SK_BORDERS) {
        const col = rgb(r, g, b);
        el.style.color = col;
        const skEl = document.getElementById(SK_BORDERS[sid]);
        if (skEl) skEl.style.borderTopColor = col;
      }
    }
  }

  // LEDs
  setLit('btn-play', s.play);
  setLit('btn-stop', s.stop);
  setLit('btn-rec',  s.rec);
  setLit('btn-song', s.song);
  setLit('btn-inst', s.inst);
  setLit('btn-metro', s.metro);

  // Shift
  document.getElementById('btn-shift').classList.toggle('held', !!s.shift);

  // Session slots
  for (let i = 0; i < 8; i++) {
    document.getElementById('slot-'+i).classList.toggle('active', i === s.slot);
  }

  // Status
  const slotLetter = 'ABCDEFGH'[s.slot] || '?';
  const armed = s.armed.length ? s.armed.map(a=>'T'+(a+1)).join('+') : '—';
  const fin = s.finishing ? '  FINISHING' : '';
  document.getElementById('status').textContent =
    `MODE: ${s.mode}  |  BPM: ${s.bpm.toFixed(0)}  |  STEP: ${s.playhead}  |  ` +
    `SLOT: ${slotLetter}  |  TRACK: T${s.track+1}  |  ARMED: ${armed}${fin}`;
}

// SSE connection
const es = new EventSource('/events');
es.onmessage = e => { try { update(JSON.parse(e.data)); } catch(err) { console.error(err); } };
es.onerror   = () => { document.getElementById('status').textContent = 'disconnected — reload to reconnect'; };
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
