"""debug_ui.py — Read-only pygame mirror window for Eden jambox state.

Displays pad grid, OLED slots, and status bar at ~30 fps in a daemon thread.
No event injection — purely observational.
"""

from __future__ import annotations

import threading

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from eden.audio import StateRef
from eden.render import render_pads, render_oled

# ── Theme (snake-tropical) ────────────────────────────────────────────────────

WINDOW_BG    = (5, 2, 12)       # near-black purple (BG_DARK scaled to 8-bit)
CELL_BORDER  = (30, 30, 40)     # dim border
TEXT_COLOR   = (220, 220, 220)  # near-white
ACCENT_COLOR = (0, 180, 120)    # palm green — labels and highlights
STATUS_BG    = (12, 5, 25)      # slightly lighter dark for status strip
OLED_BG      = (8, 3, 18)       # OLED panel background

# ── OLED slot labels ──────────────────────────────────────────────────────────

_OLED_SLOTS: tuple[tuple[int, str], ...] = (
    (0x00, "SK1:"),
    (0x01, "SK2:"),
    (0x02, "SK3:"),
    (0x08, "SK4:"),
    (0x09, "SK5:"),
    (0x06, "MAIN1:"),
    (0x07, "MAIN2:"),
)

# ── Layout constants ──────────────────────────────────────────────────────────

WINDOW_W = 900
WINDOW_H = 600

PAD_COLS = 16
PAD_ROWS = 2
CELL_SIZE = 50
CELL_GAP = 2
GRID_MARGIN_X = 10
GRID_MARGIN_Y = 40   # below title bar

# Total grid width: 16 cells * (50 + 2) - 2 (no trailing gap) = 830 px
# Centered in 900 px window
_GRID_W = PAD_COLS * CELL_SIZE + (PAD_COLS - 1) * CELL_GAP
GRID_OFFSET_X = (WINDOW_W - _GRID_W) // 2

OLED_Y = GRID_MARGIN_Y + PAD_ROWS * (CELL_SIZE + CELL_GAP) + 10
OLED_H = 100
STATUS_H = 30
STATUS_Y = WINDOW_H - STATUS_H


class DebugUI:
    def __init__(self, state_ref: StateRef) -> None:
        self._state_ref = state_ref
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Launch the pygame window in a background daemon thread."""
        if not _PYGAME_AVAILABLE:
            print("[DebugUI] pygame not installed — debug window unavailable.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the pygame thread to quit."""
        self._stop_event.set()

    # ── Private ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        pygame.init()
        screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption("EDEN debug")
        clock = pygame.time.Clock()

        mono_font  = pygame.font.SysFont("monospace", 11)
        label_font = pygame.font.SysFont("monospace", 9)

        while not self._stop_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._stop_event.set()
                    return

            state      = self._state_ref.get()
            pad_colors = render_pads(state)
            oled_text  = render_oled(state)

            screen.fill(WINDOW_BG)
            self._draw_title(screen, mono_font)
            self._draw_pads(screen, pad_colors, label_font)
            self._draw_oled(screen, oled_text, mono_font)
            self._draw_status(screen, state, mono_font)

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()

    def _draw_title(self, screen: pygame.Surface, font: pygame.font.Font) -> None:
        surf = font.render("EDEN debug", True, ACCENT_COLOR)
        screen.blit(surf, (GRID_OFFSET_X, 12))

    def _draw_pads(
        self,
        screen: pygame.Surface,
        pad_colors: tuple[tuple[int, int, int], ...],
        label_font: pygame.font.Font,
    ) -> None:
        """Draw 2 rows x 16 cols of pad cells.

        Row 0 (top) = pads 16-31; row 1 (bottom) = pads 0-15.
        Colors from render_pads are 7-bit (0-127); scale to 8-bit by * 2.
        """
        for row in range(PAD_ROWS):
            # pad indices: row 0 → 16-31, row 1 → 0-15
            pad_base = (1 - row) * 16
            for col in range(PAD_COLS):
                pad_idx = pad_base + col
                raw = pad_colors[pad_idx]
                # Scale 7-bit MIDI color values to 8-bit pygame
                color = (raw[0] * 2, raw[1] * 2, raw[2] * 2)

                x = GRID_OFFSET_X + col * (CELL_SIZE + CELL_GAP)
                y = GRID_MARGIN_Y + row * (CELL_SIZE + CELL_GAP)

                cell_rect = pygame.Rect(x, y, CELL_SIZE, CELL_SIZE)
                pygame.draw.rect(screen, CELL_BORDER, cell_rect)
                # Inset fill so border is visible as 1-px outline
                inner = cell_rect.inflate(-2, -2)
                pygame.draw.rect(screen, color, inner)

                # Tiny pad index label in top-left corner of cell
                idx_surf = label_font.render(str(pad_idx), True, CELL_BORDER)
                screen.blit(idx_surf, (x + 2, y + 2))

    def _draw_oled(
        self,
        screen: pygame.Surface,
        oled_text: dict[int, str],
        font: pygame.font.Font,
    ) -> None:
        """Render OLED slot labels and their current text on a dark panel."""
        panel_rect = pygame.Rect(GRID_OFFSET_X, OLED_Y, _GRID_W, OLED_H)
        pygame.draw.rect(screen, OLED_BG, panel_rect)
        pygame.draw.rect(screen, CELL_BORDER, panel_rect, 1)

        # Two display rows; slots laid out left-to-right within each row
        row1_slots = _OLED_SLOTS[:3]   # SK1 SK2 SK3
        row2_slots = _OLED_SLOTS[3:5]  # SK4 SK5
        row3_slots = _OLED_SLOTS[5:]   # MAIN1 MAIN2

        slot_rows = (row1_slots, row2_slots, row3_slots)
        line_h = 22
        for row_i, slot_row in enumerate(slot_rows):
            y = OLED_Y + 8 + row_i * line_h
            x = GRID_OFFSET_X + 8
            for slot_id, label in slot_row:
                text = oled_text.get(slot_id, "")
                line = f"{label} {text}"
                surf = font.render(line, True, TEXT_COLOR)
                screen.blit(surf, (x, y))
                # Advance x by measured width plus a small gap
                x += surf.get_width() + 24

    def _draw_status(
        self,
        screen: pygame.Surface,
        state,
        font: pygame.font.Font,
    ) -> None:
        """Bottom status strip: mode, bpm, playhead, track, armed tracks."""
        bar_rect = pygame.Rect(0, STATUS_Y, WINDOW_W, STATUS_H)
        pygame.draw.rect(screen, STATUS_BG, bar_rect)
        pygame.draw.line(screen, CELL_BORDER, (0, STATUS_Y), (WINDOW_W, STATUS_Y))

        armed_str = str(tuple(state.armed_tracks)) if state.armed_tracks else "()"
        status_text = (
            f"MODE: {state.mode.name}"
            f"  |  BPM: {state.tempo_bpm:.0f}"
            f"  |  STEP: {state.playhead}"
            f"  |  TRACK: {state.selected_track}"
            f"  |  ARMED: {armed_str}"
        )
        surf = font.render(status_text, True, TEXT_COLOR)
        # Vertically center inside the status bar
        y = STATUS_Y + (STATUS_H - surf.get_height()) // 2
        screen.blit(surf, (GRID_OFFSET_X, y))


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    from eden.state import default_state

    state_ref = StateRef(default_state())
    ui = DebugUI(state_ref)
    ui.start()

    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ui.stop()
