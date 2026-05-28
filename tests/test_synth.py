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
    EncoderTurned, PadPressed, SoftkeyPressed, ModeButtonPressed,
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
    assert t.amp_sustain == pytest.approx(0.7)


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
    assert "Saw" in cats


def test_catalog_keys_no_variations():
    vars_ = catalog.get_variations(1, 0)
    assert len(vars_) == 0


def test_catalog_keys_track_params_saw():
    name, param = catalog.get_track_params(1, 0, 0)
    assert name == "SAW"
    assert param == "saw"


def test_catalog_keys_track_params_square():
    name, param = catalog.get_track_params(1, 1, 0)
    assert name == "SQR"
    assert param == "square"


def test_catalog_keys_track_params_sine():
    name, param = catalog.get_track_params(1, 2, 0)
    assert name == "SINE"
    assert param == "sine"


def test_catalog_keys_track_params_tri():
    name, param = catalog.get_track_params(1, 3, 0)
    assert name == "TRI"
    assert param == "triangle"


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
    s = dataclasses.replace(_state_with_empty_slot_and_keys(), new_slot_cat_idx=1)
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert s2.tracks[2].osc_type == "square"


def test_create_synth_track_has_16_loops():
    s = _state_with_empty_slot_and_keys()
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert len(s2.tracks[2].loops) == 16


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
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    assert s2.tracks[0].loops[0].steps[0].on is True


def test_synth_step_toggle_off():
    s = _armed_synth_state()
    s2 = reduce(s, PadPressed(pad_index=0, velocity=100))
    s3 = reduce(s2, PadPressed(pad_index=0, velocity=100))
    assert s3.tracks[0].loops[0].steps[0].on is False


# ── Synth encoder controls in INSTRUMENT mode ─────────────────────────────────


def _armed_synth_with_ctrl(ctrl: str):
    return dataclasses.replace(_armed_synth_state(), instrument_active_ctrl=ctrl)


def test_synth_osc_ctrl_toggle_on():
    s = _armed_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=0))  # SK1 = OSC
    assert s2.instrument_active_ctrl == "OSC"


def test_synth_osc_ctrl_toggle_off():
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="OSC")
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.instrument_active_ctrl == ""


def test_synth_cutoff_ctrl():
    s = _armed_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=1))  # SK2 = CUTOFF
    assert s2.instrument_active_ctrl == "CUTOFF"


def test_synth_reso_ctrl():
    s = _armed_synth_state()
    s2 = reduce(s, SoftkeyPressed(key=2))  # SK3 = RESO
    assert s2.instrument_active_ctrl == "RESO"


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


def test_oled_synth_shows_osc_button():
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN1_TITLE
    assert out[OLED_BTN1_TITLE][0] == "OSC"


def test_oled_synth_shows_cutoff_button():
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN2_TITLE
    assert out[OLED_BTN2_TITLE][0] == "CUTOFF"


def test_oled_synth_shows_reso_button():
    s = _armed_synth_state()
    out = render_oled(s)
    from controller_map import OLED_BTN3_TITLE
    assert out[OLED_BTN3_TITLE][0] == "RESO"


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
    s = dataclasses.replace(_armed_synth_state(), instrument_active_ctrl="CUTOFF")
    out = render_oled(s)
    from controller_map import OLED_BTN2_TITLE
    from eden.theme import ACCENT_GOLD
    _, r, g, b = out[OLED_BTN2_TITLE]
    assert (r, g, b) == ACCENT_GOLD
