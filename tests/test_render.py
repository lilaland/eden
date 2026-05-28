"""test_render.py — Pure unit tests for eden.render (no hardware required)."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from eden.state import (
    AppState, Mode, InstrumentSubmode, DrumTrack, SynthTrack, Loop,
    default_state, default_loop, default_track_loops,
)
from eden.theme import (
    PAD_INACTIVE, PAD_OFF, PAD_DRUM, PAD_SYNTH, PAD_PLAYHEAD, ACCENT_GOLD,
    PAD_PINK, PAD_ARMED, PAD_NEW_SLOT,
)
from eden.render import render_oled, render_pads, render_button_leds
from controller_map import (
    OLED_MAIN_LINE1, OLED_MAIN_LINE2,
    OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
    OLED_BTN4_TITLE, OLED_BTN5_TITLE,
    OLED_BTN1_VALUE, OLED_BTN2_VALUE, OLED_BTN3_VALUE,
    OLED_BTN4_VALUE, OLED_BTN5_VALUE,
    NATIVE_LED_PLAY, NATIVE_LED_STOP, NATIVE_LED_INST, NATIVE_LED_SONG,
)


def _t(oled: dict, slot: int) -> str:
    """Extract text from an OLED render entry (text, r, g, b)."""
    return oled[slot][0]


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def armed_single_state() -> AppState:
    """INSTRUMENT mode, single arm on track 0, playhead=6 (col 3 at SIZE=16, ticks_per_step=2)."""
    s = default_state()
    # Give track 0 a 32-step loop at selected_loop=0
    t0 = s.tracks[0]
    loop32 = Loop(steps=tuple(i % 4 == 0 for i in range(32)))  # steps 0,4,8...
    new_loops = (loop32,) + t0.loops[1:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    new_tracks = (new_t0,) + s.tracks[1:]
    return dataclasses.replace(
        s,
        mode=Mode.INSTRUMENT,
        instrument_submode=InstrumentSubmode.STEPS,
        armed_tracks=(0,),
        tracks=new_tracks,
        playhead=6,
        is_playing=True,
    )


def armed_dual_state() -> AppState:
    """INSTRUMENT mode, dual arm on tracks 0 and 1."""
    s = armed_single_state()
    # Give track 1 a 16-step loop at selected_loop=0 with step 0 on
    t1 = s.tracks[1]
    steps = tuple(i == 0 for i in range(16))
    loop16 = Loop(steps=steps)
    new_loops = (loop16,) + t1.loops[1:]
    new_t1 = dataclasses.replace(t1, loops=new_loops)
    new_tracks = (s.tracks[0], new_t1) + s.tracks[2:]
    return dataclasses.replace(s, armed_tracks=(0, 1), tracks=new_tracks)


# ── render_pads — SESSION mode ────────────────────────────────────────────────


def test_render_pads_returns_32_colors():
    """Test 1: Output always has length 32."""
    pads = render_pads(default_state())
    assert len(pads) == 32


def test_render_pads_session_empty_slot_is_inactive():
    """Test 2: Empty track slot (tracks[2] = None) → PAD_INACTIVE at pad 2."""
    s = default_state()
    assert s.tracks[2] is None
    pads = render_pads(s)
    assert pads[2] == PAD_INACTIVE


def test_render_pads_session_selected_track_is_pink():
    """Test 3: Selected track with content → PAD_PINK."""
    s = default_state()  # track 0 selected, has content
    pads = render_pads(s)
    assert pads[0] == PAD_PINK


def test_render_pads_session_selected_track_is_brighter():
    """Test 4: Selected track (0, pad 0) brighter than non-selected drum (track 1, pad 1)."""
    s = default_state()
    pads = render_pads(s)
    selected_pad = pads[0]   # track 0 selected
    nonselected_pad = pads[1]  # track 1 not selected, same type
    assert sum(selected_pad) > sum(nonselected_pad)


def test_render_pads_session_armed_track_is_red():
    """Test 5: Armed track gets PAD_ARMED (red)."""
    s = dataclasses.replace(default_state(), armed_tracks=(1,))
    pads = render_pads(s)
    assert pads[1] == PAD_ARMED


def test_render_pads_session_muted_track_gets_dim_color():
    """Test 6: Muted track gets a dim color (not the normal type color)."""
    s = dataclasses.replace(default_state(), muted_tracks=frozenset({1}))
    pads = render_pads(s)
    assert pads[1] != PAD_DRUM
    assert sum(pads[1]) < sum(PAD_DRUM)


def test_render_pads_session_empty_loop_is_inactive():
    """Test 7: Empty loop in top row → PAD_INACTIVE at pad 17 (loop 1)."""
    s = dataclasses.replace(default_state(), playing_loops=frozenset())
    # Loop 1 of track 0 is empty; it maps to pad 16+1=17
    pads = render_pads(s)
    assert pads[17] == PAD_INACTIVE


def test_render_pads_session_playing_loop_pulses_type_color():
    """Test 8: Non-selected playing loop pulses in track type color."""
    s = default_state()
    t0 = s.tracks[0]
    steps = tuple(i == 0 for i in range(16))
    loop_with_step = Loop(steps=steps)
    new_loops = t0.loops[:1] + (loop_with_step,) + t0.loops[2:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    new_tracks = (new_t0,) + s.tracks[1:]
    # playhead=0 → pulse on (% 4 < 2) → full track color
    s = dataclasses.replace(
        s,
        tracks=new_tracks,
        playing_loops=frozenset({(0, 1)}),
        selected_loop=0,  # loop 0 selected, loop 1 is the playing one
        playhead=0,
    )
    pads = render_pads(s)
    assert pads[17] == PAD_DRUM  # pulse-on phase = full drum color

    # playhead=2 → pulse off (% 4 >= 2) → dim track color
    s2 = dataclasses.replace(s, playhead=2)
    pads2 = render_pads(s2)
    assert pads2[17] == tuple(int(c / 3) for c in PAD_DRUM)


def test_render_pads_session_selected_loop_not_playing_is_solid_pink():
    """Test 8b: Selected loop with content, not playing → solid PAD_PINK."""
    s = default_state()
    # Loop 0 selected; remove it from playing_loops so it's selected-but-not-playing
    s = dataclasses.replace(s, playing_loops=frozenset())
    pads = render_pads(s)
    assert pads[16] == PAD_PINK


def test_render_pads_session_selected_loop_playing_pulses_pink():
    """Test 8b2: Selected loop that is also playing → pulses PAD_PINK."""
    s = default_state()
    # Loop 0 selected and playing; playhead=0 → pulse on → full PAD_PINK
    s = dataclasses.replace(s, playing_loops=frozenset({(0, 0)}), playhead=0)
    pads = render_pads(s)
    assert pads[16] == PAD_PINK  # pulse-on phase

    # playhead=2 → pulse off → dim PAD_PINK
    s2 = dataclasses.replace(s, playhead=2)
    pads2 = render_pads(s2)
    assert pads2[16] == tuple(int(c / 3) for c in PAD_PINK)


def test_render_pads_session_selected_empty_track_is_green():
    """Test 8c: Selected empty track slot → PAD_NEW_SLOT (green)."""
    s = dataclasses.replace(default_state(), selected_track=2)  # track 2 is None
    pads = render_pads(s)
    assert pads[2] == PAD_NEW_SLOT


def test_render_pads_session_selected_empty_loop_is_green():
    """Test 8d: Selected empty loop slot → PAD_NEW_SLOT (green)."""
    s = dataclasses.replace(default_state(), selected_loop=1)  # loop 1 is empty
    pads = render_pads(s)
    assert pads[17] == PAD_NEW_SLOT  # loop 1 → pad 17


def test_render_pads_session_unselected_track_is_dim():
    """Test 8e: Non-selected, non-armed track → dim type color."""
    s = default_state()  # track 0 selected; track 1 is unselected drum
    pads = render_pads(s)
    assert pads[1] == tuple(int(c / 3) for c in PAD_DRUM)


# ── render_pads — INSTRUMENT single-arm ──────────────────────────────────────


def test_render_pads_instrument_single_returns_32():
    """Test 9: Single-arm INSTRUMENT mode returns 32 colors."""
    pads = render_pads(armed_single_state())
    assert len(pads) == 32


def test_render_pads_instrument_single_active_step_not_inactive():
    """Test 10: Active step (e.g. step 0 = pad 0) has non-PAD_INACTIVE color."""
    s = armed_single_state()
    pads = render_pads(s)
    # Step 0 is True (i % 4 == 0) and playhead=3 so step 0 is not playhead
    assert pads[0] != PAD_INACTIVE


def test_render_pads_instrument_single_inactive_step_is_inactive():
    """Test 11: Inactive step (step 1 = pad 1) → PAD_INACTIVE."""
    s = armed_single_state()
    pads = render_pads(s)
    # Step 1 is False (1 % 4 != 0) and not playhead
    assert pads[1] == PAD_INACTIVE


def test_render_pads_instrument_single_playhead_step_is_playhead():
    """Test 12: Playhead step (step 3 = pad 3) → PAD_PLAYHEAD."""
    s = armed_single_state()
    pads = render_pads(s)
    assert pads[3] == PAD_PLAYHEAD


def test_render_pads_instrument_single_top_row_maps_step_16():
    """Test 13: Top row pad 16 = step 16 (True in 32-step loop)."""
    s = armed_single_state()
    pads = render_pads(s)
    # Step 16 = 16 % 4 == 0, so it's True → not PAD_INACTIVE, and not playhead (playhead=3)
    assert pads[16] != PAD_INACTIVE
    assert pads[16] != PAD_PLAYHEAD


# ── render_pads — INSTRUMENT single-arm interleaved (size=32) ────────────────


def _interleaved_state() -> AppState:
    """Single-arm INSTRUMENT with step_size=32 (32 steps per bar) → interleaved view."""
    s = default_state()
    t0 = s.tracks[0]
    # 1 bar, 4 beats, 1/32 → 32 steps; step 0 on
    loop32 = Loop(steps=(True,) + tuple(False for _ in range(31)), bars=1, numerator=4, step_size=32)
    new_loops = (loop32,) + t0.loops[1:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    return dataclasses.replace(
        s,
        mode=Mode.INSTRUMENT,
        instrument_submode=InstrumentSubmode.STEPS,
        armed_tracks=(0,),
        tracks=(new_t0,) + s.tracks[1:],
        selected_loop=0,
        is_playing=False,
        playhead=0,
        playing_loops=frozenset(),  # clear default_state's pre-playing loops
    )


def test_render_pads_interleaved_pad0_is_step0():
    """Interleaved: pad 0 (row 0, col 0) → step 0 (on-beat)."""
    s = _interleaved_state()
    pads = render_pads(s)
    # step 0 is True → active color, not PAD_INACTIVE
    assert pads[0] != PAD_INACTIVE


def test_render_pads_interleaved_pad16_is_step1():
    """Interleaved: pad 16 (row 1, col 0) → step 1 (half-step). Step 1 is False → inactive."""
    s = _interleaved_state()
    pads = render_pads(s)
    assert pads[16] == PAD_INACTIVE


def test_render_pads_interleaved_pad1_is_step2():
    """Interleaved: pad 1 (row 0, col 1) → step 2. Step 2 is False → inactive."""
    s = _interleaved_state()
    pads = render_pads(s)
    assert pads[1] == PAD_INACTIVE


def test_render_pads_interleaved_step1_active_shows_on_pad16():
    """Interleaved: step 1 (half-step) active → appears on pad 16 (row 1, col 0)."""
    s = _interleaved_state()
    t0 = s.tracks[0]
    loop = t0.loops[0]
    # Turn on step 1
    new_steps = (True, True) + loop.steps[2:]
    new_loop = dataclasses.replace(loop, steps=new_steps)
    new_loops = (new_loop,) + t0.loops[1:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    s = dataclasses.replace(s, tracks=(new_t0,) + s.tracks[1:])
    pads = render_pads(s)
    assert pads[16] != PAD_INACTIVE


def test_render_pads_interleaved_playhead_at_step0_highlights_pad0():
    """Interleaved playing: effective_step=0 → PAD_PLAYHEAD at pad 0."""
    s = _interleaved_state()
    key = (0, 0)
    s = dataclasses.replace(
        s,
        is_playing=True,
        playhead=0,
        playing_loops=frozenset({key}),
        loop_measure_offsets=((key, 0),),
    )
    pads = render_pads(s)
    assert pads[0] == PAD_PLAYHEAD


def test_render_pads_interleaved_playhead_at_tick1_highlights_pad16():
    """Interleaved: tick 1 → row=1,col=0 → pad 16 (half-step of beat 1)."""
    s = _interleaved_state()
    key = (0, 0)
    s = dataclasses.replace(
        s,
        is_playing=True,
        playhead=1,
        playing_loops=frozenset({key}),
        loop_measure_offsets=((key, 0),),
    )
    pads = render_pads(s)
    # Tick 1: col=1//2=0, row=1%2=1 → pad 16 (row 1, col 0)
    assert pads[16] == PAD_PLAYHEAD
    # Pad 0 (row 0, col 0) is step 0 — active color but NOT playhead this tick
    assert pads[0] != PAD_PLAYHEAD
    # Pad 1 (row 0, col 1) — not current column
    assert pads[1] != PAD_PLAYHEAD


def test_render_pads_interleaved_step_beyond_count_is_inactive():
    """Interleaved: pads beyond step_count are PAD_INACTIVE."""
    s = _interleaved_state()
    # step_count=32, so all 32 pads map to steps 0-31, none beyond
    # Use a shorter loop to test: 1 bar, numer=2, size=32 → 16 steps
    t0 = s.tracks[0]
    short_loop = Loop(steps=tuple(False for _ in range(16)), bars=1, numerator=2, step_size=32)
    new_loops = (short_loop,) + t0.loops[1:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    s = dataclasses.replace(s, tracks=(new_t0,) + s.tracks[1:])
    pads = render_pads(s)
    # steps_per_bar = 2 * 8 = 16... not > 16, falls back to normal view
    # Use numer=3, size=32 → steps_per_bar=24 > 16, step_count=24
    medium_loop = Loop(steps=tuple(False for _ in range(24)), bars=1, numerator=3, step_size=32)
    new_loops2 = (medium_loop,) + t0.loops[1:]
    new_t0b = dataclasses.replace(t0, loops=new_loops2)
    s2 = dataclasses.replace(s, tracks=(new_t0b,) + s.tracks[1:])
    pads2 = render_pads(s2)
    # steps_per_bar=24: pad 12 → step 24 (>= 24) → PAD_OFF (fully dark, not selectable)
    assert pads2[12] == PAD_OFF  # row 0, col 12 → step 24 >= 24


# ── render_pads — INSTRUMENT dual-arm ────────────────────────────────────────


def test_render_pads_instrument_dual_bottom_pad0_reflects_track0_step0():
    """Test 14: Pad 0 reflects step 0 of armed_tracks[0]."""
    s = armed_dual_state()
    pads = render_pads(s)
    # Track 0 loop: step 0 is True (0 % 4 == 0) and playhead=3, so pad 0 = PAD_DRUM color
    assert pads[0] != PAD_INACTIVE


def test_render_pads_instrument_dual_top_pad16_reflects_track1_step0():
    """Test 15: Pad 16 reflects step 0 of armed_tracks[1]."""
    s = armed_dual_state()
    pads = render_pads(s)
    # Track 1 loop: step 0 is True → pad 16 is non-inactive
    assert pads[16] != PAD_INACTIVE


# ── render_oled — SESSION mode ────────────────────────────────────────────────


def test_render_oled_session_main_line1_track_name():
    """Test 16: SESSION mode MAIN_LINE1 = track name for default state."""
    oled = render_oled(default_state())
    assert _t(oled, OLED_MAIN_LINE1) == "KICK"


def test_render_oled_session_btn1_is_mute():
    """Test 17: SESSION mode BTN1_TITLE = 'MUTE' when selected track is not muted."""
    oled = render_oled(default_state())
    assert _t(oled, OLED_BTN1_TITLE) == "MUTE"


def test_render_oled_session_btn1_is_unmute_when_muted():
    """BTN1_TITLE = 'UNMUTE' when selected track is muted."""
    s = dataclasses.replace(default_state(), muted_tracks=frozenset({0}))
    oled = render_oled(s)
    assert _t(oled, OLED_BTN1_TITLE) == "UNMUTE"


def test_render_oled_session_btn2_is_unsolo_when_soloed():
    """BTN2_TITLE = 'UNSOLO' when selected track is soloed."""
    s = dataclasses.replace(default_state(), soloed_tracks=frozenset({0}))
    oled = render_oled(s)
    assert _t(oled, OLED_BTN2_TITLE) == "UNSOLO"


def test_render_oled_session_btn2_is_solo_when_not_soloed():
    """BTN2_TITLE = 'SOLO' when selected track is not soloed."""
    oled = render_oled(default_state())
    assert _t(oled, OLED_BTN2_TITLE) == "SOLO"


def test_render_oled_session_btn4_is_arm1_when_unarmed():
    """Test 18: SESSION mode BTN4_TITLE = 'ARM1' when nothing armed."""
    oled = render_oled(default_state())
    assert _t(oled, OLED_BTN4_TITLE) == "ARM1"


def test_render_oled_session_arm1_shows_name_slot_loop():
    """ARM1 set: BTN4_TITLE = track name, BTN4_VALUE = 'S{slot} L{loop}'."""
    s = dataclasses.replace(default_state(), armed_tracks=(0,), selected_loop=2)
    oled = render_oled(s)
    assert _t(oled, OLED_BTN4_TITLE) == "KICK"
    assert _t(oled, OLED_BTN4_VALUE) == "S1 L3"


def test_render_oled_session_arm2_shows_name_slot_loop():
    """ARM2 set: BTN5_TITLE = track name, BTN5_VALUE = 'S{slot} L{loop}'."""
    s = dataclasses.replace(default_state(), armed_tracks=(0, 1), selected_loop=0)
    oled = render_oled(s)
    assert _t(oled, OLED_BTN5_TITLE) == "SNARE"
    assert _t(oled, OLED_BTN5_VALUE) == "S2 L1"


def test_render_oled_session_btn5_is_arm2_when_unarmed():
    """BTN5_TITLE = 'ARM2' when no arm2 is set."""
    oled = render_oled(default_state())
    assert _t(oled, OLED_BTN5_TITLE) == "ARM2"


def test_render_oled_instrument_single_arm_main_line1():
    """Test 19: INSTRUMENT single-arm MAIN_LINE1 = 'KICK'."""
    oled = render_oled(armed_single_state())
    assert _t(oled, OLED_MAIN_LINE1) == "KICK"


def test_render_oled_instrument_dual_arm_main_line1():
    """Test 20: INSTRUMENT dual-arm MAIN_LINE1 = 'KICK+SNARE'."""
    oled = render_oled(armed_dual_state())
    assert _t(oled, OLED_MAIN_LINE1) == "KICK+SNARE"


def test_render_oled_instrument_btn4_is_back():
    """Test 21: INSTRUMENT mode BTN4_TITLE = '< BACK'."""
    oled = render_oled(armed_single_state())
    assert _t(oled, OLED_BTN4_TITLE) == "< BACK"


def test_render_oled_session_loop_count_zero_shows_inf():
    """Test 22: loop_count=0 → 'inf' appears in MAIN_LINE2."""
    oled = render_oled(default_state())
    assert "inf" in _t(oled, OLED_MAIN_LINE2)


def test_render_oled_session_arm1_updates_main_line2():
    """ARM1 set → MAIN_LINE2 shows ARM: <name> for immediate OLED feedback."""
    s = dataclasses.replace(default_state(), armed_tracks=(0,))
    oled = render_oled(s)
    assert "ARM" in _t(oled, OLED_MAIN_LINE2)
    assert "KICK" in _t(oled, OLED_MAIN_LINE2)


def test_render_oled_session_arm2_updates_main_line2():
    """ARM1+ARM2 set → MAIN_LINE2 shows ARM: <name1>+<name2>."""
    s = dataclasses.replace(default_state(), armed_tracks=(0, 1))
    oled = render_oled(s)
    assert "KICK" in _t(oled, OLED_MAIN_LINE2)
    assert "SNARE" in _t(oled, OLED_MAIN_LINE2)


def test_render_oled_session_no_arm_shows_loop():
    """No arms → MAIN_LINE2 shows loop info (not arm info)."""
    oled = render_oled(default_state())
    assert "LOOP" in _t(oled, OLED_MAIN_LINE2)


# ── render_oled — bar colors ──────────────────────────────────────────────────

from eden.render import _OLED_MUTED, _OLED_SOLOED, _OLED_DIM, _OLED_ARMED, _OLED_ACTIVE


def _color(oled: dict, slot: int) -> tuple:
    return oled[slot][1:]


def test_render_oled_session_mute_bar_color_when_not_muted():
    """BTN1 bar is dim when track is not muted."""
    oled = render_oled(default_state())
    assert _color(oled, OLED_BTN1_TITLE) == _OLED_DIM


def test_render_oled_session_mute_bar_color_when_muted():
    """BTN1 bar is coral when track is muted."""
    s = dataclasses.replace(default_state(), muted_tracks=frozenset({0}))
    oled = render_oled(s)
    assert _color(oled, OLED_BTN1_TITLE) == _OLED_MUTED


def test_render_oled_session_solo_bar_color_when_not_soloed():
    """BTN2 bar is dim when track is not soloed."""
    oled = render_oled(default_state())
    assert _color(oled, OLED_BTN2_TITLE) == _OLED_DIM


def test_render_oled_session_solo_bar_color_when_soloed():
    """BTN2 bar is amber when track is soloed."""
    s = dataclasses.replace(default_state(), soloed_tracks=frozenset({0}))
    oled = render_oled(s)
    assert _color(oled, OLED_BTN2_TITLE) == _OLED_SOLOED


def test_render_oled_session_arm1_bar_color_when_armed():
    """BTN4 bar is orange when track is armed."""
    s = dataclasses.replace(default_state(), armed_tracks=(0,))
    oled = render_oled(s)
    assert _color(oled, OLED_BTN4_TITLE) == _OLED_ARMED


def test_render_oled_instrument_bars_bar_dim_when_inactive():
    """SK1 (BARS) bar is dim when not active control."""
    oled = render_oled(armed_single_state())
    assert _color(oled, OLED_BTN1_TITLE) == _OLED_DIM


def test_render_oled_instrument_bars_bar_active_when_selected():
    """SK1 (BARS) bar is gold when instrument_active_ctrl == 'BARS'."""
    s = dataclasses.replace(armed_single_state(), instrument_active_ctrl="BARS")
    oled = render_oled(s)
    assert _color(oled, OLED_BTN1_TITLE) == _OLED_ACTIVE


def test_render_oled_instrument_numer_bar_active_when_selected():
    """SK2 (NUMER) bar is gold when instrument_active_ctrl == 'NUMER'."""
    s = dataclasses.replace(armed_single_state(), instrument_active_ctrl="NUMER")
    oled = render_oled(s)
    assert _color(oled, OLED_BTN2_TITLE) == _OLED_ACTIVE


def test_render_oled_instrument_size_bar_active_when_selected():
    """SK3 (SIZE) bar is gold when instrument_active_ctrl == 'SIZE'."""
    s = dataclasses.replace(armed_single_state(), instrument_active_ctrl="SIZE")
    oled = render_oled(s)
    assert _color(oled, OLED_BTN3_TITLE) == _OLED_ACTIVE


def test_render_oled_instrument_bars_count_in_value():
    """SK1 VALUE shows bars count of the first armed loop (default 1 bar)."""
    s = armed_single_state()
    oled = render_oled(s)
    assert _t(oled, OLED_BTN1_VALUE) == "1"


def test_render_oled_instrument_numer_in_value():
    """SK2 VALUE shows numerator (default 4)."""
    s = armed_single_state()
    oled = render_oled(s)
    assert _t(oled, OLED_BTN2_VALUE) == "4"


def test_render_oled_instrument_size_in_value():
    """SK3 VALUE shows size as '1/{size}' (default '1/16')."""
    s = armed_single_state()
    oled = render_oled(s)
    assert _t(oled, OLED_BTN3_VALUE) == "1/16"


def test_render_oled_instrument_bars_not_disabled_in_dual_arm():
    """SK1 (BARS) bar is dim (not disabled) in dual-arm — all controls are available."""
    oled = render_oled(armed_dual_state())
    assert _color(oled, OLED_BTN1_TITLE) == _OLED_DIM


# ── render_button_leds ────────────────────────────────────────────────────────


def test_render_button_leds_play_on_when_playing():
    """Test 23: PLAY LED on when is_playing=True."""
    s = dataclasses.replace(default_state(), is_playing=True)
    leds = render_button_leds(s)
    assert leds[NATIVE_LED_PLAY] is True


def test_render_button_leds_stop_on_when_not_playing():
    """Test 24: STOP LED on when is_playing=False."""
    s = dataclasses.replace(default_state(), is_playing=False)
    leds = render_button_leds(s)
    assert leds[NATIVE_LED_STOP] is True


def test_render_button_leds_inst_on_when_instrument_mode():
    """Test 25: INST LED on when mode == INSTRUMENT."""
    s = dataclasses.replace(default_state(), mode=Mode.INSTRUMENT)
    leds = render_button_leds(s)
    assert leds[NATIVE_LED_INST] is True


def test_render_button_leds_song_on_when_session_mode():
    """Test 26: SONG LED on when mode == SESSION."""
    s = default_state()  # default mode is SESSION
    leds = render_button_leds(s)
    assert leds[NATIVE_LED_SONG] is True
