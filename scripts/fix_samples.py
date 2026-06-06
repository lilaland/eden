"""
Repair drum/sample WAV files for clean playback:
  - Add 2ms silence pre-roll so engine fade-in starts from 0 (eliminates onset click)
  - Apply short 5ms fade-in after the pre-roll (smooth transient entry)
  - Apply 10ms fade-out to files with abrupt tails (prevent loop pops)
  - Normalize peak to -1 dBFS (0.891) — leaves headroom for multi-track mixing
  - Skip already-silent files
  - Write repaired files back in-place (keeps originals as .bak if --backup)

Usage:
    python scripts/fix_samples.py [--backup] [samples/]
"""

import argparse
import os
import sys
import numpy as np
import soundfile as sf

SAMPLE_RATE = 44100
PRE_ROLL_MS = 2.0        # ms of silence added before transient
FADE_IN_MS = 1.0         # ms linear ramp after pre-roll
FADE_OUT_MS = 10.0       # ms fade-out applied to tail if abrupt
TAIL_THRESHOLD = 0.005   # abs amplitude at last frame considered "abrupt"
ONSET_THRESHOLD = 0.005  # abs amplitude at first frame considered "non-zero onset"
TARGET_PEAK = 0.891      # -1 dBFS — leaves ~1 dB headroom per track


def ms_to_frames(ms: float) -> int:
    return int(SAMPLE_RATE * ms / 1000.0)


def repair(path: str, backup: bool) -> tuple[str, list[str]]:
    """Return (filename, list_of_applied_fixes)."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    fixes = []

    if sr != SAMPLE_RATE:
        return os.path.basename(path), [f"SKIP: unexpected sr={sr}"]

    peak = float(np.abs(data).max())
    if peak < 1e-6:
        return os.path.basename(path), ["SKIP: silent file"]

    # 1. Normalize to target peak
    data = data * (TARGET_PEAK / peak)
    fixes.append(f"normalize {peak:.4f}→{TARGET_PEAK:.4f}")

    # 2. Pre-roll silence + fade-in if onset is non-zero
    onset = float(np.abs(data[0]).max())
    if onset > ONSET_THRESHOLD:
        pre = ms_to_frames(PRE_ROLL_MS)
        fade = ms_to_frames(FADE_IN_MS)
        silence = np.zeros((pre, data.shape[1]), dtype="float32")
        # Apply fade-in to the first `fade` frames of the existing audio
        ramp = np.linspace(0.0, 1.0, fade, dtype="float32")[:, np.newaxis]
        data = data.copy()
        data[:fade] *= ramp
        data = np.concatenate([silence, data], axis=0)
        fixes.append(f"pre-roll+fade-in (onset was {onset:.4f})")

    # 3. Tail fade-out if abrupt ending
    tail = float(np.abs(data[-1]).max())
    if tail > TAIL_THRESHOLD:
        fade_out = ms_to_frames(FADE_OUT_MS)
        fade_out = min(fade_out, len(data))
        ramp = np.linspace(1.0, 0.0, fade_out, dtype="float32")[:, np.newaxis]
        data = data.copy()
        data[-fade_out:] *= ramp
        fixes.append(f"tail fade-out (tail was {tail:.4f})")

    if backup and not os.path.exists(path + ".bak"):
        import shutil
        shutil.copy2(path, path + ".bak")

    sf.write(path, data, SAMPLE_RATE, subtype="FLOAT")
    return os.path.basename(path), fixes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sample_dir", nargs="?", default="samples/")
    parser.add_argument("--backup", action="store_true", help="Save .bak before overwriting")
    args = parser.parse_args()

    sample_dir = args.sample_dir
    if not os.path.isdir(sample_dir):
        print(f"ERROR: {sample_dir!r} is not a directory", file=sys.stderr)
        sys.exit(1)

    files = sorted(f for f in os.listdir(sample_dir) if f.lower().endswith(".wav"))
    print(f"Processing {len(files)} WAV files in {sample_dir!r}...")

    total_fixed = 0
    for fname in files:
        path = os.path.join(sample_dir, fname)
        name, applied = repair(path, args.backup)
        if any(f.startswith("SKIP") for f in applied):
            print(f"  {name}: {applied[0]}")
        else:
            total_fixed += 1
            print(f"  {name}: {', '.join(applied)}")

    print(f"\nDone. Repaired {total_fixed}/{len(files)} files.")


if __name__ == "__main__":
    main()
