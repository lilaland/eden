"""
scripts/dl_samples.py — Download CC0 one-shot samples from Freesound.

Usage:
    FREESOUND_KEY=your_api_key python scripts/dl_samples.py [--force]

    --force  Overwrite files that already exist.

Get a free API key (takes ~2 min):
    https://freesound.org/apiv2/apply/

Each sample is downloaded as the original file, resampled to 44100 Hz stereo,
and written to samples/{key}.wav. Already-existing files are skipped unless
--force is given.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.request
import urllib.parse

import numpy as np
import soundfile as sf

SR = 44100
OUT_DIR = "samples"
API_KEY = os.environ.get("FREESOUND_KEY", "")
BASE = "https://freesound.org/apiv2"

# ── Target samples ────────────────────────────────────────────────────────────
# Each entry: sample_key → (display_name, search_query, max_duration_sec)
# Search finds the best CC0 match under max_duration_sec seconds.

TARGETS: dict[str, tuple[str, str, float]] = {
    # Breaks — drum loops / breaks
    "amen_break":    ("Amen break",      "amen break drum loop",          10.0),
    "think_break":   ("Think break",     "think break drum loop",         10.0),
    "apache_break":  ("Apache break",    "apache break drum loop",        10.0),
    "funky_drummer": ("Funky Drummer",   "funky drummer break loop",      10.0),

    # Vocals — short vocal chops / hits
    "vocal_chop_1":  ("Vocal chop 1",   "vocal chop stab one shot",       2.0),
    "vocal_chop_2":  ("Vocal chop 2",   "voice stab sample hit",          2.0),

    # Instruments — melodic loops / riffs
    "rhodes_loop":   ("Rhodes loop",    "rhodes electric piano loop",      6.0),
    "bass_riff":     ("Bass riff",      "bass guitar funk loop riff",      6.0),
    "guitar_loop":   ("Guitar loop",    "guitar funk loop clean",          6.0),

    # Texture — ambient / foley
    "vinyl_texture": ("Vinyl texture",  "vinyl crackle noise texture",     6.0),
    "rain_foley":    ("Rain foley",     "rain ambient foley",              8.0),
    "crowd_foley":   ("Crowd foley",    "crowd ambience background",       8.0),

    # FX
    "riser_fx":      ("Riser FX",       "riser sweep effect build up",     4.0),
    "impact_fx":     ("Impact FX",      "impact hit effect cinematic",     3.0),
    "downlift_fx":   ("Downlift FX",    "downlift whoosh effect",          3.0),
}


# ── Freesound helpers ─────────────────────────────────────────────────────────

def _api(path: str, **params) -> dict:
    params["token"] = API_KEY
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _search_cc0(query: str, max_dur: float) -> list[dict]:
    try:
        data = _api(
            "/search/text/",
            query=query,
            license="Creative Commons 0",
            fields="id,name,duration,previews,type",
            page_size=15,
            filter=f"duration:[0 TO {max_dur}]",
        )
        return data.get("results", [])
    except Exception as exc:
        print(f"    search error: {exc}")
        return []


def _read_audio(raw: bytes) -> np.ndarray:
    buf = io.BytesIO(raw)
    arr, sr = sf.read(buf, dtype="float32", always_2d=True)
    if sr != SR:
        new_len = int(len(arr) * SR / sr)
        idxs = (np.arange(new_len) * sr / SR).astype(np.int32).clip(0, len(arr) - 1)
        arr = arr[idxs]
    if arr.shape[1] == 1:
        arr = np.hstack([arr, arr])
    elif arr.shape[1] > 2:
        arr = arr[:, :2]
    return arr.astype(np.float32)


def _download_full(sound_id: int) -> np.ndarray:
    url = f"{BASE}/sounds/{sound_id}/download/?token={API_KEY}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read()
    return _read_audio(raw)


def _download_preview(previews: dict) -> np.ndarray:
    url = (previews.get("preview-hq-ogg")
           or previews.get("preview-hq-mp3")
           or previews.get("preview-lq-mp3"))
    if not url:
        raise ValueError("no preview URL available")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return _read_audio(raw)


def _write(name: str, arr: np.ndarray) -> None:
    path = os.path.join(OUT_DIR, f"{name}.wav")
    peak = np.max(np.abs(arr))
    if peak > 0:
        arr = arr / peak * 0.85
    sf.write(path, arr, SR)
    dur = len(arr) / SR
    print(f"    wrote  {name}.wav  ({dur:.2f} s)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main(force: bool = False) -> None:
    if not API_KEY:
        print(
            "ERROR: FREESOUND_KEY environment variable not set.\n"
            "\n"
            "  1. Create a free account at https://freesound.org/\n"
            "  2. Visit https://freesound.org/apiv2/apply/ to get an API key\n"
            "  3. Run:  FREESOUND_KEY=your_key python scripts/dl_samples.py\n"
        )
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)
    ok = 0
    skipped = 0
    failed: list[str] = []

    for key, (display, query, max_dur) in TARGETS.items():
        out_path = os.path.join(OUT_DIR, f"{key}.wav")
        if os.path.exists(out_path) and not force:
            print(f"  skip   {key}.wav (exists — use --force to overwrite)")
            skipped += 1
            continue

        print(f"\n  {display}  [{query!r}]")
        results = _search_cc0(query, max_dur)
        if not results:
            print(f"    no CC0 results")
            failed.append(key)
            continue

        # Pick shortest result that fits under max_dur
        best = min(results, key=lambda r: r["duration"])
        print(f"    found: {best['name']!r}  id={best['id']}  {best['duration']:.1f}s")

        try:
            arr = _download_full(best["id"])
            print(f"    downloaded full file")
        except Exception as exc:
            print(f"    full download failed ({exc}), trying preview")
            try:
                arr = _download_preview(best.get("previews", {}))
                print(f"    downloaded preview")
            except Exception as exc2:
                print(f"    preview also failed: {exc2}")
                failed.append(key)
                continue

        _write(key, arr)
        ok += 1
        time.sleep(0.4)   # polite rate limiting

    print(f"\n── Summary ──────────────────────")
    print(f"  downloaded: {ok}")
    print(f"  skipped:    {skipped}")
    if failed:
        print(f"  failed:     {len(failed)}  ({', '.join(failed)})")
    print()


if __name__ == "__main__":
    main(force="--force" in sys.argv)
