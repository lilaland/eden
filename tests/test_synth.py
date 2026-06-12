"""tests/test_synth.py — Phase 3 tests: SynthTrack state, catalog, reduce, sessions, render."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from eden.state import (
    AppState, SynthTrack, DrumTrack, StepNote, Loop, Mode, InstrumentSubmode,
    default_state, default_loop, default_track_loops,
)
from eden.events import (
    ClockTicked, EncoderTurned, PadPressed, PadReleased, SoftkeyPressed,
    ModeButtonPressed, TransportPressed,
)
from eden.reduce import reduce
import eden.catalog as catalog
import eden.sessions as sessions
from eden.render import render_oled, render_pads


# ── SynthTrack defaults ───────────────────────────────────────────────────────


def test_synth_track_default_osc():
    t = SynthTrack(name="SAW", loops=default_track_loops())
    assert t.osc_type == "saw"


def test_synth_track_default_filter():
    t = SynthTrack(name="SAW", loops=default_track_loops())
    assert t.filter_cutoff == 8000.0
    assert t.filter_res == 0.2


def test_synth_track_default_envelope():
    t = SynthTrack(name="SAW", loops=default_track_loops())
    assert t.amp_attack == pytest.approx(0.005)
    assert t.amp_sustain == pytest.approx(0.85)


def test_synth_track_default_volume():
    t = SynthTrack(name="SAW", loops=default_track_loops())
    assert t.volume == pytest.approx(0.8)
    assert t.max_voices == 8


# ── Catalog: KEYS type ────────────────────────────────────────────────────────


def test_catalog_instrument_types_has_keys():
    assert "KEYS" in catalog.INSTRUMENT_TYPES


def test_catalog_keys_categories():
    cats = catalog.get_categories(1)
    assert len(cats) >= 4
    assert "Raw" in cats
    assert "Bass" in cats
    assert "Lead" in cats
    assert "Pad" in cats


def test_catalog_keys_variations_raw():
    vars_ = catalog.get_variations(1, 0)  # cat_idx=0 = Raw folder
    assert "Saw" in vars_
    assert "Square" in vars_
    assert "Sine" in vars_
    assert "Tri" in vars_


def test_catalog_keys_variations_bass():
    vars_ = catalog.get_variations(1, 1)  # cat_idx=1 = Bass folder
    assert "Sub Bass" in vars_
    assert "Reese" in vars_


def test_catalog_keys_track_params_saw():
    name, param = catalog.get_track_params(1, 0, 0)  # Raw/Saw
    assert name == "SAW"
    assert param == "saw"


def test_catalog_keys_track_params_square():
    name, param = catalog.get_track_params(1, 0, 1)  # Raw/Square
    assert name == "SQR"
    assert param == "square"


def test_catalog_keys_track_params_sine():
    name, param = catalog.get_track_params(1, 0, 2)  # Raw/Sine
    assert name == "SINE"
    assert param == "sine"


def test_catalog_keys_track_params_tri():
    name, param = catalog.get_track_params(1, 0, 3)  # Raw/Tri
    assert name == "TRI"
    assert param == "triangle"


def test_catalog_keys_preset_extras_raw_has_no_extras():
    extras = catalog.get_synth_preset_extras(0, 0)  # Raw/Saw
    assert extras == {}


def test_catalog_keys_preset_extras_bass_has_filter():
    extras = catalog.get_synth_preset_extras(1, 0)  # Bass/Sub Bass
    assert "filter_cutoff" in extras


# ── Creating a SynthTrack via the new-slot picker ─────────────────────────────


def _state_with_empty_slot_and_keys():
    """AppState with slot 2 selected (empty), type=KEYS, cat=Saw."""
    s = default_state()
    return dataclasses.replace(
        s,
        selected_track=2,
        new_slot_type_idx=1,
        new_slot_cat_idx=0,
        new_slot_var_idx=0,
        new_slot_active_ctrl="",
    )


def test_create_synth_track_via_picker():
    s = _state_with_empty_slot_and_keys()
    s2 = reduce(s, SoftkeyPressed(key=4))  # SK5 = CREATE
    assert isinstance(s2.tracks[2], SynthTrack)


def test_create_synth_track_osc_type():
    s = _state_with_empty_slot_and_keys()
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert s2.tracks[2].osc_type == "saw"


def test_create_synth_track_square():
    s = dataclasses.replace(_state_with_empty_slot_and_keys(), new_slot_cat_idx=0, new_slot_var_idx=1)
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert s2.tracks[2].osc_type == "square"


def test_create_synth_track_has_16_loops():
    s = _state_with_empty_slot_and_keys()
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert len(s2.tracks[2].loops) == 16


def test_new_synth_track_inherits_last_scale_and_root():
    """New SynthTrack picks up last_synth_scale / last_synth_root instead of chromatic/C."""
    from eden.events import EncoderTurned
    s = _state_with_empty_slot_and_keys()
    # Create a first track and arm it so we can change its scale/root
    s2 = reduce(s, SoftkeyPressed(key=4))
    # Switch to INSTRUMENT mode on the newly created track and change scale + root
    s2 = dataclasses.replace(s2, mode=Mode.INSTRUMENT, armed_tracks=(2,),
                              instrument_active_ctrl="SCALE")
    s2 = reduce(s2, EncoderTurned(encoder=9, delta=1))   # advance scale
    s2 = dataclasses.replace(s2, instrument_active_ctrl="ROOT")
    s2 = reduce(s2, EncoderTurned(encoder=9, delta=2))   # advance root by 2
    saved_scale = s2.tracks[2].scale
    saved_root  = s2.tracks[2].root_note
    assert s2.last_synth_scale == saved_scale
    assert s2.last_synth_root  == saved_root
    # Now create a second synth track at slot 3 — should inherit saved values
    s3 = dataclasses.replace(s2, mode=Mode.SESSION, selected_track=3,
                              tracks=s2.tracks[:3] + (None,) + s2.tracks[4:],
                              new_slot_type_idx=1)
    s3 = reduce(s3, SoftkeyPressed(key=4))
    new_track = s3.tracks[3]
    assert isinstance(new_track, SynthTrack)
    assert new_track.scale    == saved_scale
    assert new_track.root_note == saved_root


# ── Step editing on SynthTrack ────────────────────────────────────────────────


def _armed_synth_state():
    """State with a SynthTrack at slot 0, armed, in INSTRUMENT mode."""
    s = default_state()
    synth = SynthTrack(name="SAW", loops=default_track_loops())
    tracks = (synth,) + s.tracks[1:]
    return dataclasses.replace(
        s,
        tracks=tracks,
        selected_track=0,
        armed_tracks=(0,),
        mode=Mode.INSTRUMENT,
        instrument_submode=InstrumentSubmode.STEPS,
    )


def test_synth_step_toggle_on():
    # Top row (pad 16) = step 0 in STEPS mode
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=16, velocity=100))
    assert s2.tracks[0].loops[0].steps[0].on is True


def test_synth_step_toggle_off():
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=16, velocity=100))
    s3 = reduce(s2, PadPressed(pad_index=16, velocity=100))
    assert s3.tracks[0].loops[0].steps[0].on is False


def test_synth_bottom_row_sets_pitch():
    # Bottom row (pad 0-15) sets pitch on cursor step when step is OFF
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s2.tracks[0].loops[0].steps[0].on is True
    from eden.scales import degree_to_pitch
    expected = degree_to_pitch(60, "chromatic", 0)
    assert s2.tracks[0].loops[0].steps[0].pitches == (expected,)


def test_synth_bottom_row_advances_cursor():
    s = _armed_synth_state()
    assert s.step_cursor == 0
    s2 = reduce(s, PadPressed(pad_index=5, velocity=100))  # bottom row
    assert s2.step_cursor == 1  # cursor advanced


def test_synth_bottom_row_adds_chord_tone():
    """Pressing a second different pitch on an already-ON step merges chord, cursor stays."""
    s = _armed_synth_state()
    # Press pad 0: step 0 OFF → ON with pitch A, cursor advances to 1
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s2.step_cursor == 1
    # Move cursor back to step 0
    s2 = dataclasses.replace(s2, step_cursor=0)
    # Press pad 2 (different pitch): step 0 is ON → add chord tone, cursor stays at 0
    s3 = reduce(s2, PadPressed(pad_index=2, velocity=100))
    from eden.scales import degree_to_pitch
    p0 = degree_to_pitch(60, "chromatic", 0)
    p2 = degree_to_pitch(60, "chromatic", 2)
    assert s3.tracks[0].loops[0].steps[0].pitches == (p0, p2)
    assert s3.step_cursor == 0  # cursor did NOT advance


def test_synth_bottom_row_removes_chord_tone():
    """Pressing an already-present pitch removes it from the chord."""
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    s2 = dataclasses.replace(s2, step_cursor=0)
    s3 = reduce(s2, PadPressed(pad_index=2, velocity=100))  # add 2nd pitch
    from eden.scales import degree_to_pitch
    p0 = degree_to_pitch(60, "chromatic", 0)
    p2 = degree_to_pitch(60, "chromatic", 2)
    assert s3.tracks[0].loops[0].steps[0].pitches == (p0, p2)
    # Press pad 0 again: remove p0, only p2 remains
    s4 = reduce(s3, PadPressed(pad_index=0, velocity=100))
    assert s4.tracks[0].loops[0].steps[0].pitches == (p2,)
    assert s4.step_cursor == 0  # still didn't advance


def test_synth_bottom_row_remove_last_pitch_turns_step_off():
    """Removing the last pitch from a chord turns the step off."""
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s2.tracks[0].loops[0].steps[0].on
    s2 = dataclasses.replace(s2, step_cursor=0)
    s3 = reduce(s2, PadPressed(pad_index=0, velocity=100))  # remove the only pitch
    assert not s3.tracks[0].loops[0].steps[0].on


# ── Synth encoder controls in INSTRUMENT mode ─────────────────────────────────


def _armed_synth_with_ctrl(ctrl: str):
    return dataclasses.replace(_armed_synth_state(), instrument_active_ctrl=ctrl)


def test_synth_osc_ctrl_toggle_on():
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    s2 = reduce(s, SoftkeyPressed(key=0))  # Shift+SK1 = OSC
    assert s2.instrument_active_ctrl == "OSC"


def test_synth_osc_ctrl_toggle_off():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="OSC", shift_held=True)
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.instrument_active_ctrl == ""


def test_synth_cutoff_ctrl():
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    s2 = reduce(s, SoftkeyPressed(key=1))  # Shift+SK2 = CUTOFF
    assert s2.instrument_active_ctrl == "CUTOFF"


def test_synth_sk3_shift_opens_attack():
    # Shift+SK3 = ATTACK
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    s2 = reduce(s, SoftkeyPressed(key=2))
    assert s2.instrument_active_ctrl == "ATTACK"


def test_synth_sk3_normal_opens_bars():
    # Normal SK3 = LEN (loop bars)
    s = _armed_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=2))
    assert s2.instrument_active_ctrl == "BARS"


def test_synth_sk4_toggles_free_mode():
    # SK4: STEP → FREE enters free mode
    s = _armed_synth_state()
    assert s.tracks[0].quantized is True
    s2 = reduce(s, SoftkeyPressed(key=3))
    assert s2.tracks[0].quantized is False


def test_synth_sk4_quant_in_free_mode_converts_and_switches():
    """SK4 in free mode runs quantize and switches back to step mode."""
    from eden.state import NoteEvent
    s = dataclasses.replace(_armed_synth_state())
    # Enter free mode
    s = reduce(s, SoftkeyPressed(key=3))
    assert s.tracks[0].quantized is False
    # Plant a free_event to simulate a recorded note
    loop = s.tracks[0].loops[0]
    spb = loop.steps_per_bar
    evt = NoteEvent(tick=0, pitch=60, velocity=80, gate=0.5, aftertouch=0.0)
    new_loop = dataclasses.replace(loop, free_events=(evt,))
    new_loops = (new_loop,) + s.tracks[0].loops[1:]
    new_track = dataclasses.replace(s.tracks[0], loops=new_loops)
    s = dataclasses.replace(s, tracks=(new_track,) + s.tracks[1:])
    # Press SK4 (QUANT) in free mode
    s2 = reduce(s, SoftkeyPressed(key=3))
    assert s2.tracks[0].quantized is True
    assert s2.tracks[0].loops[0].steps[0].on is True
    assert s2.tracks[0].loops[0].free_events == ()


def test_synth_sk4_shift_toggles_aftertouch():
    # Shift+SK4 = toggle aftertouch
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    before = s.tracks[0].aftertouch
    s2 = reduce(s, SoftkeyPressed(key=3))
    assert s2.tracks[0].aftertouch is not before


def test_synth_sk5_shift_opens_release():
    # Shift+SK5 = RELEASE
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert s2.instrument_active_ctrl == "RELEASE"


def test_synth_encoder_increases_attack():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="ATTACK")
    original = s.tracks[0].amp_attack
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].amp_attack > original


def test_synth_encoder_decreases_attack():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="ATTACK")
    original = s.tracks[0].amp_attack
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-1))
    assert s2.tracks[0].amp_attack < original


def test_synth_encoder_increases_sustain():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="SUSTAIN")
    original = s.tracks[0].amp_sustain
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].amp_sustain > original


def test_synth_encoder_decreases_release():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="RELEASE")
    original = s.tracks[0].amp_release
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-1))
    assert s2.tracks[0].amp_release < original


def test_synth_encoder_cycles_osc_forward():
    s = _armed_synth_with_ctrl("OSC")
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].osc_type == "square"


def test_synth_encoder_cycles_osc_backward():
    s = _armed_synth_with_ctrl("OSC")
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-1))
    # saw → backward wraps to triangle
    assert s2.tracks[0].osc_type == "triangle"


def test_synth_encoder_increases_cutoff():
    s = _armed_synth_with_ctrl("CUTOFF")
    original = s.tracks[0].filter_cutoff
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].filter_cutoff > original


def test_synth_encoder_decreases_cutoff():
    s = _armed_synth_with_ctrl("CUTOFF")
    original = s.tracks[0].filter_cutoff
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-1))
    assert s2.tracks[0].filter_cutoff < original


def test_synth_cutoff_clamped_low():
    s = dataclasses.replace(
        _armed_synth_with_ctrl("CUTOFF"),
        tracks=(dataclasses.replace(s.tracks[0], filter_cutoff=20.0),) + default_state().tracks[1:]
        if False else None,
    )
    # Manually construct a state with very low cutoff
    synth = dataclasses.replace(SynthTrack(name="SAW", loops=default_track_loops()), filter_cutoff=20.0)
    s = dataclasses.replace(_armed_synth_state(), tracks=(synth,) + default_state().tracks[1:],
                            instrument_active_ctrl="CUTOFF")
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-10))
    assert s2.tracks[0].filter_cutoff >= 20.0


def test_synth_encoder_increases_reso():
    s = _armed_synth_with_ctrl("RESO")
    original = s.tracks[0].filter_res
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].filter_res > original


def test_synth_encoder_reso_clamped_high():
    synth = dataclasses.replace(SynthTrack(name="SAW", loops=default_track_loops()), filter_res=0.98)
    s = dataclasses.replace(_armed_synth_state(), tracks=(synth,) + default_state().tracks[1:],
                            instrument_active_ctrl="RESO")
    s2 = reduce(s, EncoderTurned(encoder=9, delta=10))
    assert s2.tracks[0].filter_res <= 0.99


def test_synth_encoder_reso_clamped_low():
    synth = dataclasses.replace(SynthTrack(name="SAW", loops=default_track_loops()), filter_res=0.01)
    s = dataclasses.replace(_armed_synth_state(), tracks=(synth,) + default_state().tracks[1:],
                            instrument_active_ctrl="RESO")
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-10))
    assert s2.tracks[0].filter_res >= 0.0


# ── Session serialization of SynthTrack ───────────────────────────────────────


def test_synth_track_to_dict():
    t = SynthTrack(name="SAW", loops=default_track_loops(), osc_type="square",
                   filter_cutoff=2000.0, filter_res=0.5)
    d = sessions._track_to_dict(t)
    assert d is not None
    assert d["type"] == "synth"
    assert d["name"] == "SAW"
    assert d["osc_type"] == "square"
    assert d["filter_cutoff"] == 2000.0
    assert d["filter_res"] == 0.5


def test_synth_track_from_dict():
    d = {
        "type": "synth",
        "name": "TRI",
        "osc_type": "triangle",
        "amp_attack": 0.01,
        "amp_decay": 0.2,
        "amp_sustain": 0.6,
        "amp_release": 0.3,
        "filter_cutoff": 3000.0,
        "filter_res": 0.4,
        "volume": 0.7,
        "max_voices": 4,
        "loops": [],
    }
    t = sessions._dict_to_track(d)
    assert isinstance(t, SynthTrack)
    assert t.osc_type == "triangle"
    assert t.filter_cutoff == 3000.0
    assert t.max_voices == 4
    assert len(t.loops) == 16  # padded to 16


def test_synth_track_roundtrip():
    synth = SynthTrack(
        name="SAW", loops=default_track_loops(), osc_type="sine",
        filter_cutoff=5000.0, filter_res=0.3, amp_attack=0.02,
    )
    d = sessions._track_to_dict(synth)
    back = sessions._dict_to_track(d)
    assert isinstance(back, SynthTrack)
    assert back.osc_type == "sine"
    assert back.filter_cutoff == pytest.approx(5000.0)
    assert back.filter_res == pytest.approx(0.3)
    assert back.amp_attack == pytest.approx(0.02)


def test_synth_session_roundtrip_with_active_loop():
    synth = SynthTrack(name="SAW", loops=default_track_loops())
    state = dataclasses.replace(default_state(), tracks=(synth,) + default_state().tracks[1:])
    data = sessions.state_to_session(state, "test")
    patch = sessions.session_to_state_patch(data, 0)
    restored = dataclasses.replace(state, **patch)
    assert isinstance(restored.tracks[0], SynthTrack)
    assert restored.tracks[0].name == "SAW"


# ── OLED render for SynthTrack ────────────────────────────────────────────────


def test_oled_synth_armed_shows_osc_in_main_line():
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_MAIN_LINE1
    assert "saw" in out[OLED_MAIN_LINE1][0].lower()


def test_oled_synth_shows_scale_button():
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN1_TITLE
    assert out[OLED_BTN1_TITLE][0] == "SCALE"


def test_oled_synth_shows_root_button():
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN2_TITLE
    assert out[OLED_BTN2_TITLE][0] == "ROOT"


def test_oled_synth_shows_len_button():
    # Normal page SK3 is LEN (loop bars)
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN3_TITLE
    assert out[OLED_BTN3_TITLE][0] == "LEN"


def test_oled_synth_shift_shows_osc_button():
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    out = render_oled(s)
    from controller_map import OLED_BTN1_TITLE
    assert out[OLED_BTN1_TITLE][0] == "OSC"


def test_oled_synth_shift_shows_cutoff_button():
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    out = render_oled(s)
    from controller_map import OLED_BTN2_TITLE
    assert out[OLED_BTN2_TITLE][0] == "CUTOFF"


def test_oled_synth_shift_shows_attack_button():
    # Shift page SK3 is ATTACK
    s = dataclasses.replace(_armed_synth_state(), shift_held=True)
    out = render_oled(s)
    from controller_map import OLED_BTN3_TITLE
    assert out[OLED_BTN3_TITLE][0] == "ATTACK"


def test_oled_drum_still_shows_bars():
    """DrumTrack armed in INSTRUMENT mode still shows BARS/NUMER/SIZE."""
    s = default_state()
    s = dataclasses.replace(
        s, armed_tracks=(0,), mode=Mode.INSTRUMENT,
        instrument_submode=InstrumentSubmode.STEPS,
    )
    out = render_oled(s)
    from controller_map import OLED_BTN1_TITLE
    assert out[OLED_BTN1_TITLE][0] == "BARS"


def test_oled_synth_cutoff_active_lights_bar():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="CUTOFF", shift_held=True)
    out = render_oled(s)
    from controller_map import OLED_BTN2_TITLE
    label, r, g, b = out[OLED_BTN2_TITLE]
    assert label == "CUTOFF"
    assert (r, g, b) != (0, 0, 0)  # active color applied


# ── Piano keyboard (FREE) mode ────────────────────────────────────────────────


def _free_synth_state():
    """Armed SynthTrack in INSTRUMENT mode with quantized=False (FREE piano).

    pitch_window_offset=28 puts C4 (MIDI 60) at pad 7 (white_idx 35).
    free_recording=True so pad presses write notes (active recording session).
    """
    s = default_state()
    tracks = list(s.tracks)
    tracks[0] = SynthTrack(name="SAW", loops=default_track_loops(),
                           osc_type="saw", quantized=False)
    s = dataclasses.replace(s, tracks=tuple(tracks),
                            armed_tracks=(0,), mode=Mode.INSTRUMENT,
                            instrument_submode=InstrumentSubmode.STEPS,
                            pitch_window_offset=28,
                            free_recording=True)
    return s


def test_synth_free_sk1_opens_scale():
    s = _free_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.instrument_active_ctrl == "SCALE"


def test_synth_free_sk2_opens_root():
    s = _free_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=1))
    assert s2.instrument_active_ctrl == "ROOT"


def test_synth_free_sk3_extends_loop():
    # In FREE mode SK3 extends the loop by one bar instead of opening BARS encoder
    s = _free_synth_state()
    track = s.tracks[s.armed_tracks[0]]
    original_bars = track.loops[s.selected_loop].bars
    s2 = reduce(s, SoftkeyPressed(key=2))
    new_track = s2.tracks[s2.armed_tracks[0]]
    assert new_track.loops[s2.selected_loop].bars == original_bars + 1


def test_synth_sk3_opens_bars():
    # SK3 normal = LEN (opens BARS ctrl)
    s = _armed_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=2))
    assert s2.instrument_active_ctrl == "BARS"


def test_synth_free_sk5_opens_octave():
    s = _free_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert s2.instrument_active_ctrl == "OCTAVE"


def test_synth_free_pad_white_key_records_pitch():
    s = _free_synth_state()
    # offset=28: pad 7 = white_idx 35 = C4=60
    # Press → note lands in free_pending_ticks (committed to free_events on release)
    s2 = reduce(s, PadPressed(pad_index=7, velocity=100))
    assert any(p[2] == 60 for p in s2.free_pending_ticks)  # C4 in pending


def test_synth_free_pad_black_key_records_pitch():
    s = _free_synth_state()
    # offset=28: top-row pad 23 (16+7) = black_key_at(35) = C#4=61
    s2 = reduce(s, PadPressed(pad_index=23, velocity=100))
    assert any(p[2] == 61 for p in s2.free_pending_ticks)  # C#4 in pending


def test_synth_free_dead_key_no_note():
    s = _free_synth_state()
    # offset=28: top-row pad 16+9=25 → black_key_at(37)=None (dead key)
    s2 = reduce(s, PadPressed(pad_index=25, velocity=100))
    assert s2.free_pending_ticks == s.free_pending_ticks  # nothing added


def test_synth_free_octave_offset_shifts_pitch():
    # offset=28: pad 7 = white_idx 35 = C4; octave_offset=1 → C5=72
    s = dataclasses.replace(_free_synth_state(), octave_offset=1)
    s2 = reduce(s, PadPressed(pad_index=7, velocity=100))
    assert any(p[2] == 72 for p in s2.free_pending_ticks)  # C5 in pending


def test_synth_quantized_field_persisted():
    import eden.sessions as sessions
    s = _free_synth_state()
    d = sessions.state_to_session(s, "test")
    assert d["tracks"][0]["quantized"] is False


def test_synth_quantized_field_restored():
    import eden.sessions as sessions
    s = _free_synth_state()
    d = sessions.state_to_session(s, "test")
    patch = sessions.session_to_state_patch(d, slot=0)
    assert patch["tracks"][0].quantized is False


def test_render_pads_free_mode_white_keys_lit():
    s = _free_synth_state()
    colors = render_pads(s)
    # Bottom row (pads 0-15) are white keys — should not all be PAD_OFF
    white_key_colors = [colors[i] for i in range(16)]
    assert any(c != (0, 0, 0) for c in white_key_colors)


def test_render_pads_free_mode_dead_keys_off():
    s = _free_synth_state()
    colors = render_pads(s)
    # Pad 18 = 16 + 2 = E# dead position — must be PAD_OFF
    assert colors[18] == (0, 0, 0)


def test_oled_synth_free_shows_scale_and_octave():
    s = _free_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN1_TITLE, OLED_BTN5_TITLE
    assert out[OLED_BTN1_TITLE][0] == "SCALE"
    assert out[OLED_BTN5_TITLE][0] == "OCTAVE"


def test_oled_synth_free_line2_recording_shows_rec():
    from controller_map import OLED_MAIN_LINE2
    s = _free_synth_state()  # free_recording=True
    out = render_oled(s)
    line2 = out[OLED_MAIN_LINE2][0]
    assert "●" in line2
    assert "L1" in line2


def test_oled_synth_free_line2_free_play_shows_bbt_position():
    from controller_map import OLED_MAIN_LINE2
    s = dataclasses.replace(_free_synth_state(), free_recording=False)
    out = render_oled(s)
    line2 = out[OLED_MAIN_LINE2][0]
    assert "." in line2   # BBT format (bar.beat.sub)
    assert "L1" in line2


def test_oled_synth_free_line2_pending_shows_arm():
    from controller_map import OLED_MAIN_LINE2
    s = dataclasses.replace(_free_synth_state(), free_recording=False,
                             free_record_pending=True, playhead=16)
    out = render_oled(s)
    line2 = out[OLED_MAIN_LINE2][0]
    assert "ARM" in line2
    assert "L1" in line2


def test_synth_sk3_bars_encoder_extends_loop():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="BARS")
    original_bars = s.tracks[0].loops[s.selected_loop].bars
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].loops[s2.selected_loop].bars > original_bars


def test_synth_sk3_bars_encoder_contracts_loop():
    # Build a 2-bar loop then shrink it
    from eden.events import EncoderTurned
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="BARS")
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))  # now 2 bars
    s3 = reduce(s2, EncoderTurned(encoder=9, delta=-1))  # back to 1
    assert s3.tracks[0].loops[s3.selected_loop].bars == 1


# ── Hold-based note duration (FREE mode) ──────────────────────────────────────


def test_free_pad_press_writes_note_no_cursor_advance():
    """PadPressed in FREE mode adds to pending ticks but does NOT advance cursor yet."""
    s = dataclasses.replace(_free_synth_state(), step_cursor=0)
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert len(s2.free_pending_ticks) == 1  # note pending, not yet committed
    assert s2.step_cursor == 0  # cursor stays until release


def test_free_clock_wrap_starts_loop_and_recording():
    """ClockTicked at bar boundary starts both loop playback and recording."""
    s = default_state()
    synth = SynthTrack(name="SAW", loops=default_track_loops(), quantized=False)
    tracks = s.tracks[:2] + (synth,) + s.tracks[3:]
    s = dataclasses.replace(
        s, tracks=tracks,
        armed_tracks=(2,), mode=Mode.INSTRUMENT,
        instrument_submode=InstrumentSubmode.STEPS,
        pitch_window_offset=28,
        free_record_pending=True,
        is_playing=True, playhead=31,
    )
    s2 = reduce(s, ClockTicked())
    assert s2.playhead == 0
    assert s2.free_recording is True
    assert (2, 0) in s2.playing_loops


def test_free_pad_press_placeholder_gate():
    """PadPressed adds note to pending ticks with placeholder velocity."""
    s = _free_synth_state()
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    # Note is pending (not yet committed to free_events until release)
    assert len(s2.free_pending_ticks) == 1
    assert s2.free_pending_ticks[0][3] == 100  # velocity preserved


def test_free_pad_release_commits_gate():
    """PadReleased commits NoteEvent with gate computed from hold_seconds and tempo."""
    from eden.events import PadReleased
    # At 120 BPM, step_size=16: step_dur = 60/120 / (16/4) = 0.125s
    # hold 0.5s → gate = 0.5/0.125 = 4.0 → quarter note
    s = dataclasses.replace(_free_synth_state(), step_cursor=0)
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    s2 = reduce(s, PadReleased(pad_index=0, hold_seconds=0.5))
    free_events = s2.tracks[0].loops[0].free_events
    assert len(free_events) == 1
    assert abs(free_events[0].gate - 4.0) < 0.01


def test_free_pad_release_does_not_advance_cursor():
    """Cursor does NOT advance on pad release in clock-driven mode."""
    from eden.events import PadReleased
    s = dataclasses.replace(_free_synth_state(), step_cursor=0)
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    s2 = reduce(s, PadReleased(pad_index=0, hold_seconds=0.5))
    assert s2.step_cursor == 0


def test_free_pad_press_writes_at_playhead_position():
    """With playhead=16, raw_tick=16; note is in pending at tick 16."""
    s = dataclasses.replace(_free_synth_state(), playhead=16)
    s2 = reduce(s, PadPressed(pad_index=7, velocity=100))  # C4
    # raw_tick = bar_offset(0) * 32 + playhead(16) = 16
    assert any(p[1] == 16 for p in s2.free_pending_ticks)


def test_free_pad_release_short_tap_minimum_gate():
    """Very short tap gets minimum gate of 0.1 in committed NoteEvent."""
    from eden.events import PadReleased
    s = dataclasses.replace(_free_synth_state(), step_cursor=0)
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    s2 = reduce(s, PadReleased(pad_index=0, hold_seconds=0.001))
    free_events = s2.tracks[0].loops[0].free_events
    assert len(free_events) == 1
    assert free_events[0].gate == pytest.approx(0.1)
    assert s2.step_cursor == 0  # cursor does NOT advance


def test_oled_free_sk3_shows_len_extend():
    """FREE mode SK3 shows LEN+ (extend loop) instead of LEN encoder."""
    s = _free_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN3_TITLE
    assert out[OLED_BTN3_TITLE][0] == "LEN+"


# ── RANGE encoder (granular ±1) ───────────────────────────────────────────────


def test_range_encoder_increments_by_one():
    """RANGE ctrl encoder steps pitch_window_offset by +1."""
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="RANGE")
    original = s.pitch_window_offset
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.pitch_window_offset == original + 1


def test_range_encoder_decrements_by_one():
    """RANGE ctrl encoder steps pitch_window_offset by -1."""
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="RANGE",
                            pitch_window_offset=5)
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-1))
    assert s2.pitch_window_offset == 4


def test_range_encoder_free_cw_slides_right():
    """FREE RANGE encoder CW (delta>0) decrements index: window slides right."""
    s = dataclasses.replace(_free_synth_state(), instrument_active_ctrl="RANGE",
                            pitch_window_offset=36)
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.pitch_window_offset == 35  # one white key lower (D4→C4 as leftmost)


def test_range_encoder_free_ccw_slides_left():
    """FREE RANGE encoder CCW (delta<0) increments index: window slides left."""
    s = dataclasses.replace(_free_synth_state(), instrument_active_ctrl="RANGE",
                            pitch_window_offset=35)
    s2 = reduce(s, EncoderTurned(encoder=9, delta=-1))
    assert s2.pitch_window_offset == 36  # one white key higher (D4 becomes leftmost)


def test_range_encoder_free_every_step_is_one():
    """FREE encoder always steps by exactly 1 regardless of E/F or B/C boundaries."""
    from eden.scales import white_idx_to_midi
    s = dataclasses.replace(_free_synth_state(), instrument_active_ctrl="RANGE")
    # Slide across several positions and confirm each CW step is -1
    for start in (35, 36, 37, 38, 39, 40, 41):
        s2 = dataclasses.replace(s, pitch_window_offset=start)
        s3 = reduce(s2, EncoderTurned(encoder=9, delta=1))
        assert s3.pitch_window_offset == start - 1


def test_piano_layout_white_keys_correct():
    """Verify white key column pitches starting from C4 (white_idx=35)."""
    from eden.scales import white_idx_to_midi, black_key_at
    # C4 octave: C D E F G A B
    assert white_idx_to_midi(35) == 60   # C4
    assert white_idx_to_midi(36) == 62   # D4
    assert white_idx_to_midi(37) == 64   # E4
    assert white_idx_to_midi(38) == 65   # F4
    assert white_idx_to_midi(39) == 67   # G4
    assert white_idx_to_midi(40) == 69   # A4
    assert white_idx_to_midi(41) == 71   # B4
    assert white_idx_to_midi(42) == 72   # C5


def test_piano_layout_black_keys_and_dead_positions():
    """Verify black key positions and dead slots (no E#/B#) from C4."""
    from eden.scales import black_key_at
    assert black_key_at(35) == 61   # C#4 (between C4 and D4)
    assert black_key_at(36) == 63   # D#4 (between D4 and E4)
    assert black_key_at(37) is None  # dead — no black key between E4 and F4
    assert black_key_at(38) == 66   # F#4
    assert black_key_at(39) == 68   # G#4
    assert black_key_at(40) == 70   # A#4
    assert black_key_at(41) is None  # dead — no black key between B4 and C5


def test_piano_layout_slides_correctly():
    """After pressing - once, every key moves one column right."""
    from eden.scales import white_idx_to_midi, black_key_at
    # Before: C4 at col 0 (offset=35); after -: offset=34, col 0=B3, C4 at col 1
    assert white_idx_to_midi(34) == 59   # B3 (now leftmost)
    assert white_idx_to_midi(35) == 60   # C4 (now at col 1)
    # Black key at col 0 (B3 position): no black key between B3 and C4
    assert black_key_at(34) is None


def test_piano_offset_clamps_at_zero():
    """+ button at offset=0 stays at 0 (+ decreases offset, floor is 0)."""
    from eden.events import PlusMinusPressed
    s = dataclasses.replace(_free_synth_state(), pitch_window_offset=0)
    s2 = reduce(s, PlusMinusPressed(button="+", pressed=True))
    assert s2.pitch_window_offset == 0


def test_piano_offset_clamps_at_max():
    """- button at max offset stays at 59 (- increases offset, ceiling is 59)."""
    from eden.events import PlusMinusPressed
    s = dataclasses.replace(_free_synth_state(), pitch_window_offset=59)
    s2 = reduce(s, PlusMinusPressed(button="-", pressed=True))
    assert s2.pitch_window_offset == 59


# ── RANGE +/- buttons (granular in FREE mode, flipped: + lowers, - raises) ───


def test_range_plus_free_decrements_offset():
    """+ in FREE mode decrements white key index by 1 (shows lower notes)."""
    from eden.events import PlusMinusPressed
    s = dataclasses.replace(_free_synth_state(), pitch_window_offset=35)
    s2 = reduce(s, PlusMinusPressed(button="+", pressed=True))
    assert s2.pitch_window_offset == 34


def test_range_minus_free_increments_offset():
    """- in FREE mode increments white key index by 1 (shows higher notes)."""
    from eden.events import PlusMinusPressed
    s = dataclasses.replace(_free_synth_state(), pitch_window_offset=35)
    s2 = reduce(s, PlusMinusPressed(button="-", pressed=True))
    assert s2.pitch_window_offset == 36


def test_range_plus_quant_shifts_one_degree():
    """+ button in QUANT mode shifts one degree (not a full scale octave)."""
    from eden.events import PlusMinusPressed
    s = dataclasses.replace(_armed_synth_state(), pitch_window_offset=10)
    s2 = reduce(s, PlusMinusPressed(button="+", pressed=True))
    assert s2.pitch_window_offset == 9  # decremented by 1


# ── InstrumentUndo ────────────────────────────────────────────────────────────


def test_instrument_undo_restores_tracks():
    """InstrumentUndo restores tracks to the pre-edit snapshot."""
    from eden.events import InstrumentUndo
    s = _armed_synth_state()
    original_tracks = s.tracks
    # Record a note (saves undo snapshot)
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s2.tracks != original_tracks
    # Undo
    s3 = reduce(s2, InstrumentUndo())
    assert s3.tracks == original_tracks


def test_instrument_undo_restores_cursor():
    """InstrumentUndo also restores step_cursor to pre-edit position."""
    from eden.events import InstrumentUndo
    s = dataclasses.replace(_armed_synth_state(), step_cursor=3)
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    # Cursor may have advanced
    s3 = reduce(s2, InstrumentUndo())
    assert s3.step_cursor == 3


def test_instrument_undo_no_op_without_snapshot():
    """InstrumentUndo without a prior edit is a no-op (no crash)."""
    from eden.events import InstrumentUndo
    s = _armed_synth_state()
    assert s.undo_snapshot is None
    s2 = reduce(s, InstrumentUndo())
    assert s2.tracks == s.tracks


# ── InstrumentReset ───────────────────────────────────────────────────────────


def test_instrument_reset_clears_loop():
    """InstrumentReset blanks the selected loop to all-off steps."""
    from eden.events import InstrumentReset
    s = _armed_synth_state()
    # Put a note in
    s = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert any(step.on for step in s.tracks[0].loops[0].steps)
    # Reset
    s2 = reduce(s, InstrumentReset())
    assert not any(step.on for step in s2.tracks[0].loops[0].steps)


def test_instrument_reset_resets_cursor():
    """InstrumentReset returns step_cursor to 0."""
    from eden.events import InstrumentReset
    s = dataclasses.replace(_armed_synth_state(), step_cursor=7)
    s2 = reduce(s, InstrumentReset())
    assert s2.step_cursor == 0


def test_instrument_reset_removes_from_playing():
    """InstrumentReset removes the loop from playing_loops and active_loops."""
    from eden.events import InstrumentReset
    s = _armed_synth_state()
    loop_key = (s.selected_track, s.selected_loop)
    # Ensure it's playing
    s = dataclasses.replace(s, playing_loops=frozenset({loop_key}),
                            active_loops=frozenset({loop_key}))
    s2 = reduce(s, InstrumentReset())
    assert loop_key not in s2.playing_loops
    assert loop_key not in s2.active_loops


# ── FREE recording state machine ──────────────────────────────────────────────


def _free_play_state():
    """FREE piano state in free-play mode (not recording)."""
    return dataclasses.replace(_free_synth_state(), free_recording=False)


def test_free_play_pad_does_not_write():
    """Pad press in free-play mode (not recording) writes no steps."""
    s = _free_play_state()
    s2 = reduce(s, PadPressed(pad_index=7, velocity=100))
    assert not any(step.on for step in s2.tracks[0].loops[0].steps)


def test_free_rec_arm_sets_pending():
    """REC press in free-play mode arms recording (pending)."""
    s = _free_play_state()
    s2 = reduce(s, TransportPressed(button="REC", pressed=True))
    assert s2.free_record_pending is True
    assert s2.free_recording is False


def test_free_rec_release_while_pending_cancels_arm():
    """REC release while pending (before bar boundary) cancels the arm."""
    s = dataclasses.replace(_free_play_state(), free_record_pending=True)
    s2 = reduce(s, TransportPressed(button="REC", pressed=False))
    assert s2.free_record_pending is False
    assert s2.free_recording is False


def test_free_clock_wrap_starts_recording():
    """ClockTicked wrapping to playhead=0 transitions pending → recording."""
    s = dataclasses.replace(_free_play_state(), playhead=31, free_record_pending=True)
    s2 = reduce(s, ClockTicked())
    assert s2.playhead == 0
    assert s2.free_recording is True
    assert s2.free_record_pending is False


def test_free_clock_wrap_starts_overdub_on_existing_loop():
    """Recording start on a non-empty loop enters overdub (preserves existing notes)."""
    s = _free_synth_state()
    from eden.state import StepNote
    loop = s.tracks[0].loops[0]
    note_step = StepNote(on=True, pitches=(60,))
    new_steps = (note_step,) + loop.steps[1:]
    new_loop = dataclasses.replace(loop, steps=new_steps)
    new_loops = s.tracks[0].loops[:0] + (new_loop,) + s.tracks[0].loops[1:]
    new_track = dataclasses.replace(s.tracks[0], loops=new_loops)
    new_tracks = s.tracks[:0] + (new_track,) + s.tracks[1:]
    s_with_note = dataclasses.replace(s, tracks=new_tracks,
                                      free_recording=False, free_record_pending=True,
                                      playhead=31)
    s2 = reduce(s_with_note, ClockTicked())
    assert s2.free_recording is True
    # Existing note is preserved — this is overdub, not a fresh clear
    assert s2.tracks[0].loops[0].steps[0].on is True
    assert s2.tracks[0].loops[0].steps[0].pitches == (60,)
    # free_loop_length set to loop's existing step count
    assert s2.free_loop_length == loop.step_count


def test_free_rec_release_stops_recording():
    """REC release while recording stops recording (loop keeps playing)."""
    s = dataclasses.replace(_free_synth_state(), free_recording=True)
    s2 = reduce(s, TransportPressed(button="REC", pressed=False))
    assert s2.free_recording is False


def test_free_shift_rec_press_starts_hold_timer():
    """Shift+REC press starts the hold timer (doesn't clear immediately)."""
    s = dataclasses.replace(_free_synth_state(), shift_held=True)
    s2 = reduce(s, TransportPressed(button="REC", pressed=True))
    assert s2.rec_held_shift is True
    assert s2.rec_held_ticks == 0
    assert s2.free_recording is False  # recording paused while shift held


def test_free_shift_rec_short_release_undoes_session():
    """Shift+REC quick release (< 32 ticks) undoes the last recording session."""
    from eden.state import StepNote
    s = dataclasses.replace(_free_synth_state(), shift_held=True,
                             rec_held_shift=True, rec_held_ticks=5)
    # Set up a note in the loop to verify it gets undone
    loop = s.tracks[0].loops[0]
    note_step = StepNote(on=True, pitches=(60,))
    new_loop = dataclasses.replace(loop, steps=(note_step,) + loop.steps[1:])
    new_loops = s.tracks[0].loops[:0] + (new_loop,) + s.tracks[0].loops[1:]
    new_track = dataclasses.replace(s.tracks[0], loops=new_loops)
    s = dataclasses.replace(s, tracks=s.tracks[:0] + (new_track,) + s.tracks[1:],
                            free_undo_loops=((0, 0, loop),))
    s2 = reduce(s, TransportPressed(button="REC", pressed=False))
    # Note is gone (loop restored to snapshot)
    assert not s2.tracks[0].loops[0].steps[0].on
    assert s2.rec_held_shift is False


def test_free_undo_removes_from_playing_loops_when_snapshot_empty():
    """Undo restores an empty snapshot loop and removes it from playing_loops."""
    s = dataclasses.replace(_free_synth_state(), shift_held=True,
                             rec_held_shift=True, rec_held_ticks=5)
    empty_loop = s.tracks[0].loops[0]  # default empty loop = snapshot
    # Simulate loop got pre-allocated and added to playing_loops during REC
    from eden.state import StepNote
    filled_loop = dataclasses.replace(empty_loop, steps=tuple(StepNote.off() for _ in range(16)))
    new_loops = (filled_loop,) + s.tracks[0].loops[1:]
    new_track = dataclasses.replace(s.tracks[0], loops=new_loops)
    s = dataclasses.replace(s,
                             tracks=(new_track,) + s.tracks[1:],
                             playing_loops=frozenset({(0, 0)}),
                             free_undo_loops=((0, 0, empty_loop),))
    s2 = reduce(s, TransportPressed(button="REC", pressed=False))
    assert (0, 0) not in s2.playing_loops
    assert s2.free_recording is False


def test_free_shift_rec_long_release_clears_all():
    """Shift+REC held for >=32 ticks then released clears the whole pattern."""
    from eden.state import StepNote
    s = dataclasses.replace(_free_synth_state(), shift_held=True,
                             rec_held_shift=True, rec_held_ticks=32)
    loop = s.tracks[0].loops[0]
    note_step = StepNote(on=True, pitches=(60,))
    new_loop = dataclasses.replace(loop, steps=(note_step,) + loop.steps[1:])
    new_loops = s.tracks[0].loops[:0] + (new_loop,) + s.tracks[0].loops[1:]
    new_track = dataclasses.replace(s.tracks[0], loops=new_loops)
    s = dataclasses.replace(s, tracks=s.tracks[:0] + (new_track,) + s.tracks[1:])
    s2 = reduce(s, TransportPressed(button="REC", pressed=False))
    assert s2.free_recording is False
    assert s2.rec_held_shift is False
    assert not any(step.on for step in s2.tracks[0].loops[0].steps)


def test_free_stop_clears_recording_state():
    """STOP in INSTRUMENT mode clears free_recording and free_record_pending."""
    s = dataclasses.replace(_free_synth_state(), free_record_pending=True)
    s2 = reduce(s, TransportPressed(button="STOP", pressed=True))
    assert s2.free_recording is False
    assert s2.free_record_pending is False


# ── Layered-loop playback (scheduler) ─────────────────────────────────────────

import types


class _CaptureEngine:
    def __init__(self):
        self.calls = []
    def note_on(self, p, a, g, t):
        self.calls.append(p)
    def release_all(self):
        self.calls.append("REL")


def _loop_with_note(pitch, step=0):
    steps = [StepNote.off() for _ in range(16)]
    steps[step] = StepNote(on=True, pitches=(pitch,), velocity=100)
    return Loop(steps=tuple(steps))


def _bare_scheduler():
    from eden.audio import StepScheduler
    sched = StepScheduler.__new__(StepScheduler)
    sched._mixer = types.SimpleNamespace(_sr=44100)
    sched._arp_tracks = {}
    return sched


def test_layered_loops_on_one_track_both_fire():
    """Two playing loops on the same track must both trigger (loop layering)."""
    loops = list(default_track_loops())
    loops[0] = _loop_with_note(60)
    loops[1] = _loop_with_note(72)
    track = SynthTrack(name="S", loops=tuple(loops))
    eng = _CaptureEngine()
    _bare_scheduler()._trigger_loops(
        loops={(0, 0), (0, 1)}, tracks=(track,), offsets={}, playhead=0,
        muted=frozenset(), bpm=120.0, get_engine=lambda i: eng, apply_effects=True,
    )
    assert sorted(eng.calls) == [60, 72]


def test_retrigger_releases_once_across_layered_loops():
    """With retrigger on, layered loops share a single release_all so they don't cut each other."""
    loops = list(default_track_loops())
    loops[0] = _loop_with_note(60)
    loops[1] = _loop_with_note(72)
    track = SynthTrack(name="S", loops=tuple(loops), retrigger=True)
    eng = _CaptureEngine()
    _bare_scheduler()._trigger_loops(
        loops={(0, 0), (0, 1)}, tracks=(track,), offsets={}, playhead=0,
        muted=frozenset(), bpm=120.0, get_engine=lambda i: eng, apply_effects=True,
    )
    assert eng.calls.count("REL") == 1
    assert sorted(p for p in eng.calls if p != "REL") == [60, 72]
