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
from eden.theme import PAD_INACTIVE, PAD_DRUM, PAD_SYNTH, PAD_PLAYHEAD, ACCENT_GOLD
from eden.render import render_pads, render_oled, render_button_leds
from controller_map import (
    OLED_MAIN_LINE1, OLED_MAIN_LINE2,
    OLED_BTN1_TITLE, OLED_BTN2_TITLE, OLED_BTN3_TITLE,
    OLED_BTN4_TITLE, OLED_BTN5_TITLE,
    NATIVE_LED_PLAY, NATIVE_LED_STOP, NATIVE_LED_INST, NATIVE_LED_SONG,
)


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def armed_single_state() -> AppState:
    """INSTRUMENT mode, single arm on track 0, playhead=3."""
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
        playhead=3,
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


def test_render_pads_session_drum_track_gets_drum_color():
    """Test 3: Track 0 (DrumTrack) at pad 0 has PAD_DRUM or brighter variant."""
    s = default_state()
    # Track 0 is selected so it will be brightened; confirm it is not PAD_INACTIVE
    pads = render_pads(s)
    assert pads[0] != PAD_INACTIVE
    # The color must be derived from PAD_DRUM (each channel >= PAD_DRUM channel)
    for ch_result, ch_base in zip(pads[0], PAD_DRUM):
        assert ch_result >= ch_base


def test_render_pads_session_selected_track_is_brighter():
    """Test 4: Selected track (0, pad 0) brighter than non-selected drum (track 1, pad 1)."""
    s = default_state()
    pads = render_pads(s)
    selected_pad = pads[0]   # track 0 selected
    nonselected_pad = pads[1]  # track 1 not selected, same type
    assert sum(selected_pad) > sum(nonselected_pad)


def test_render_pads_session_armed_track_gets_gold():
    """Test 5: Armed track gets ACCENT_GOLD color."""
    s = dataclasses.replace(default_state(), armed_tracks=(1,))
    pads = render_pads(s)
    assert pads[1] == ACCENT_GOLD


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


def test_render_pads_session_playing_loop_is_playhead():
    """Test 8: Playing loop in top row → PAD_PLAYHEAD at pad 17 (loop 1)."""
    s = default_state()
    t0 = s.tracks[0]
    steps = tuple(i == 0 for i in range(16))
    loop_with_step = Loop(steps=steps)
    new_loops = t0.loops[:1] + (loop_with_step,) + t0.loops[2:]
    new_t0 = dataclasses.replace(t0, loops=new_loops)
    new_tracks = (new_t0,) + s.tracks[1:]
    s = dataclasses.replace(
        s,
        tracks=new_tracks,
        playing_loops=frozenset({(0, 1)}),  # loop 1 playing
        selected_loop=0,                    # loop 0 selected (different → no brightness boost)
    )
    pads = render_pads(s)
    assert pads[17] == PAD_PLAYHEAD  # loop 1 → pad 16+1=17


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
    assert oled[OLED_MAIN_LINE1] == "KICK"


def test_render_oled_session_btn1_is_mute():
    """Test 17: SESSION mode BTN1_TITLE = 'MUTE'."""
    oled = render_oled(default_state())
    assert oled[OLED_BTN1_TITLE] == "MUTE"


def test_render_oled_session_btn4_is_arm1():
    """Test 18: SESSION mode BTN4_TITLE = 'ARM1'."""
    oled = render_oled(default_state())
    assert oled[OLED_BTN4_TITLE] == "ARM1"


def test_render_oled_instrument_single_arm_main_line1():
    """Test 19: INSTRUMENT single-arm MAIN_LINE1 = 'KICK'."""
    oled = render_oled(armed_single_state())
    assert oled[OLED_MAIN_LINE1] == "KICK"


def test_render_oled_instrument_dual_arm_main_line1():
    """Test 20: INSTRUMENT dual-arm MAIN_LINE1 = 'KICK+SNARE'."""
    oled = render_oled(armed_dual_state())
    assert oled[OLED_MAIN_LINE1] == "KICK+SNARE"


def test_render_oled_instrument_btn4_is_back():
    """Test 21: INSTRUMENT mode BTN4_TITLE = '< BACK'."""
    oled = render_oled(armed_single_state())
    assert oled[OLED_BTN4_TITLE] == "< BACK"


def test_render_oled_session_loop_count_zero_shows_inf():
    """Test 22: loop_count=0 → 'inf' appears in MAIN_LINE2."""
    # default state has loop_count=0 on all loops
    oled = render_oled(default_state())
    assert "inf" in oled[OLED_MAIN_LINE2]


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
