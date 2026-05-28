"""debug_ui.py — Read-only pygame mirror window for Eden jambox state.

Displays pad grid, OLED slots, and status bar at ~30 fps.
Must be run on the main thread on macOS (SDL2 requirement).
"""

from __future__ import annotations

try:
    import pygame
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

from eden.audio import StateRef
from eden.render import render_pads, render_oled

# ── Theme ─────────────────────────────────────────────────────────────────────

WINDOW_BG    = (5, 2, 12)
CELL_BORDER  = (30, 30, 40)
TEXT_COLOR   = (220, 220, 220)
ACCENT_COLOR = (0, 180, 120)
STATUS_BG    = (12, 5, 25)
OLED_BG      = (8, 3, 18)

# ── OLED slot IDs → display labels ───────────────────────────────────────────

_OLED_SLOTS: tuple[tuple[int, str], ...] = (
    (0x00, "SK1:"),
    (0x01, "SK2:"),
    (0x02, "SK3:"),
    (0x08, "SK4:"),
    (0x09, "SK5:"),
    (0x06, "MAIN1:"),
    (0x07, "MAIN2:"),
)

# ── Layout ────────────────────────────────────────────────────────────────────

WINDOW_W = 900
WINDOW_H = 600

PAD_COLS  = 16
PAD_ROWS  = 2
CELL_SIZE = 50
CELL_GAP  = 2
GRID_MARGIN_Y = 40

_GRID_W = PAD_COLS * CELL_SIZE + (PAD_COLS - 1) * CELL_GAP
GRID_OFFSET_X = (WINDOW_W - _GRID_W) // 2

OLED_Y   = GRID_MARGIN_Y + PAD_ROWS * (CELL_SIZE + CELL_GAP) + 10
OLED_H   = 100
STATUS_H = 30
STATUS_Y = WINDOW_H - STATUS_H


class DebugUI:
    def __init__(self, state_ref: StateRef) -> None:
        self._state_ref = state_ref

    def run_blocking(self) -> None:
        """Run the pygame window on the calling thread. Blocks until closed."""
        if not _PYGAME_AVAILABLE:
            print("[DebugUI] pygame not installed — debug window unavailable.")
            return

        pygame.init()
        screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption("EDEN debug")
        clock = pygame.time.Clock()

        mono_font  = pygame.font.SysFont("monospace", 11)
        label_font = pygame.font.SysFont("monospace", 9)

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_q:
                    running = False

            state      = self._state_ref.get()
            pad_colors = render_pads(state)
            oled_data  = render_oled(state)

            screen.fill(WINDOW_BG)
            _draw_title(screen, mono_font)
            _draw_pads(screen, pad_colors, label_font)
            _draw_oled(screen, oled_data, mono_font)
            _draw_status(screen, state, mono_font)

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _draw_title(screen, font) -> None:
    surf = font.render("EDEN debug", True, ACCENT_COLOR)
    screen.blit(surf, (GRID_OFFSET_X, 12))


def _draw_pads(screen, pad_colors, label_font) -> None:
    """Row 0 (top) = pads 16-31; row 1 (bottom) = pads 0-15.
    Colors are 7-bit; scale to 8-bit by ×2."""
    for row in range(PAD_ROWS):
        pad_base = (1 - row) * 16
        for col in range(PAD_COLS):
            pad_idx = pad_base + col
            raw = pad_colors[pad_idx]
            color = (raw[0] * 2, raw[1] * 2, raw[2] * 2)

            x = GRID_OFFSET_X + col * (CELL_SIZE + CELL_GAP)
            y = GRID_MARGIN_Y + row * (CELL_SIZE + CELL_GAP)

            cell_rect = pygame.Rect(x, y, CELL_SIZE, CELL_SIZE)
            pygame.draw.rect(screen, CELL_BORDER, cell_rect)
            inner = cell_rect.inflate(-2, -2)
            pygame.draw.rect(screen, color, inner)

            idx_surf = label_font.render(str(pad_idx), True, CELL_BORDER)
            screen.blit(idx_surf, (x + 2, y + 2))


def _draw_oled(screen, oled_data: dict, font) -> None:
    """Render OLED text on a dark panel."""
    panel_rect = pygame.Rect(GRID_OFFSET_X, OLED_Y, _GRID_W, OLED_H)
    pygame.draw.rect(screen, OLED_BG, panel_rect)
    pygame.draw.rect(screen, CELL_BORDER, panel_rect, 1)

    row1_slots = _OLED_SLOTS[:3]
    row2_slots = _OLED_SLOTS[3:5]
    row3_slots = _OLED_SLOTS[5:]

    line_h = 22
    for row_i, slot_row in enumerate((row1_slots, row2_slots, row3_slots)):
        y = OLED_Y + 8 + row_i * line_h
        x = GRID_OFFSET_X + 8
        for slot_id, label in slot_row:
            entry = oled_data.get(slot_id)
            text = entry[0] if entry else ""
            line = f"{label} {text}"
            surf = font.render(line, True, TEXT_COLOR)
            screen.blit(surf, (x, y))
            x += surf.get_width() + 24


def _draw_status(screen, state, font) -> None:
    bar_rect = pygame.Rect(0, STATUS_Y, WINDOW_W, STATUS_H)
    pygame.draw.rect(screen, STATUS_BG, bar_rect)
    pygame.draw.line(screen, CELL_BORDER, (0, STATUS_Y), (WINDOW_W, STATUS_Y))

    armed_str = str(tuple(state.armed_tracks)) if state.armed_tracks else "()"
    text = (
        f"MODE: {state.mode.name}"
        f"  |  BPM: {state.tempo_bpm:.0f}"
        f"  |  STEP: {state.playhead}"
        f"  |  TRACK: {state.selected_track}"
        f"  |  ARMED: {armed_str}"
        f"  |  SLOT: {state.active_session_slot}"
    )
    surf = font.render(text, True, TEXT_COLOR)
    y = STATUS_Y + (STATUS_H - surf.get_height()) // 2
    screen.blit(surf, (GRID_OFFSET_X, y))


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    from eden.state import default_state

    state_ref = StateRef(default_state())
    ui = DebugUI(state_ref)
    ui.run_blocking()
