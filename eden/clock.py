"""
eden/clock.py — High-precision sequencer clock for Eden jambox.

Uses time.perf_counter() for timing and busy-wait / short-sleep hybrid to
achieve sub-millisecond tick accuracy without accumulating drift.
"""

from __future__ import annotations

import queue
import sys
import time
import threading
from typing import Callable, List, Optional

from eden.events import ClockTicked


# ---------------------------------------------------------------------------
# SequencerClock
# ---------------------------------------------------------------------------

class SequencerClock:
    """
    Dedicated sequencer clock that fires step callbacks at a steady BPM.

    Timing model
    ------------
    The clock thread computes the absolute target time for every tick using
    perf_counter().  Instead of sleeping for the full inter-tick interval
    (which accumulates OS scheduling jitter), it sleeps for 80 % of the
    remaining interval and then busy-waits for the last 20 %.  This gives
    near-perfect timing (<< 1 ms error) without pinning a CPU core.

    Thread safety
    -------------
    * set_bpm() is safe to call from any thread.
    * on_tick() should be called before start() (no lock used for the list
      because modifying it after start() could race with the clock thread).
    * Tick callbacks are invoked on the clock thread; they must be
      thread-safe themselves.

    Parameters
    ----------
    bpm :   float — beats per minute (default 120)
    steps : int   — steps per pattern loop (default 16)
    ppq :   int   — pulses per quarter note (default 4 → 16th-note steps)
    """

    def __init__(
        self,
        bpm: float = 120.0,
        steps: int = 16,
        ppq: int = 4,
        event_queue: queue.SimpleQueue | None = None,
    ) -> None:
        self._bpm: float = float(bpm)
        self._steps: int = int(steps)
        self._ppq: int = int(ppq)

        self._event_queue: queue.SimpleQueue | None = event_queue

        self._callbacks: List[Callable[[int], None]] = []
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None

        # Threading primitive used only for _bpm reads/writes so that a
        # 64-bit float assignment stays atomic on platforms where it isn't.
        self._bpm_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_bpm(self, bpm: float) -> None:
        """Update BPM while the clock is running or stopped."""
        with self._bpm_lock:
            self._bpm = float(bpm)

    def on_tick(self, callback: Callable[[int], None]) -> None:
        """
        Register a callback invoked on every tick.

        The callback receives the current step index (0 .. steps-1).
        Call before start().
        """
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start the clock thread.  No-op if already running."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            name="SequencerClock",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the clock thread and wait for it to finish."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ------------------------------------------------------------------
    # Internal clock loop
    # ------------------------------------------------------------------

    def _tick_interval(self) -> float:
        """Return the duration of one tick in seconds given current BPM."""
        with self._bpm_lock:
            bpm = self._bpm
        # One quarter note = 60/bpm seconds; each tick is 1/ppq of that.
        return 60.0 / (bpm * self._ppq)

    def _run(self) -> None:
        """
        Main clock loop.

        Strategy: track the *absolute* next-tick target time so that any
        overshoot in one iteration is automatically corrected in the next —
        no drift accumulation.
        """
        step: int = 0
        next_tick: float = time.perf_counter()

        while self._running:
            interval = self._tick_interval()
            next_tick += interval

            # --- Drift-corrected sleep ----------------------------------
            now = time.perf_counter()
            remaining = next_tick - now

            if remaining > 0:
                # Sleep for 80 % of remaining time to let the OS schedule
                # other work, then busy-wait for the final stretch.
                sleep_duration = remaining * 0.80
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

                # Busy-wait until the target moment.
                while time.perf_counter() < next_tick:
                    pass  # tight spin — only a fraction of a millisecond
            # If remaining <= 0 the previous tick ran long; skip the sleep
            # entirely and fire immediately to recover.

            if not self._running:
                break

            # --- Fire callbacks ----------------------------------------
            for cb in self._callbacks:
                try:
                    cb(step)
                except Exception as exc:
                    # Don't crash the clock on a bad callback.
                    print(f"[clock] callback error: {exc}", file=sys.stderr)

            if self._event_queue:
                self._event_queue.put(ClockTicked())

            step = (step + 1) % self._steps


# ---------------------------------------------------------------------------
# CLI demo entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Print step indices at 120 BPM for 2 bars (32 sixteenth-note steps at
    ppq=4, steps=16) then exit.
    """

    BPM = 120.0
    STEPS = 16
    PPQ = 4
    BARS = 2
    TOTAL_TICKS = STEPS * BARS  # 32

    fired: list[int] = []
    done = threading.Event()

    def on_step(step: int) -> None:
        fired.append(step)
        bar = len(fired) // STEPS + 1
        print(f"bar {bar:2d}  step {step:02d}", flush=True)
        if len(fired) >= TOTAL_TICKS:
            done.set()

    clock = SequencerClock(bpm=BPM, steps=STEPS, ppq=PPQ)
    clock.on_tick(on_step)
    clock.start()

    # One bar at 120 BPM = 2 s; two bars = 4 s.  Add a small margin.
    done.wait(timeout=6.0)
    clock.stop()

    if len(fired) < TOTAL_TICKS:
        print(f"[clock] warning: only {len(fired)}/{TOTAL_TICKS} ticks fired before timeout")

    print("Clock demo finished.")
