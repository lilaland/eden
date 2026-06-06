"""Tests for SampleTrack, ChopPoint, and related features."""
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from eden.state import (
    AppState, Mode, InstrumentSubmode, SampleTrack, ChopPoint, StepNote, Scene,
    default_state, default_track_loops, Loop,
)
from eden.reduce import reduce
from eden.events import SoftkeyPressed, PadPressed, ModeButtonPressed
import eden.catalog as catalog
import eden.sessions as sessions


# ── Catalog ───────────────────────────────────────────────────────────────────

def test_catalog_sample_type_exists():
    assert "SAMPLE" in catalog.INSTRUMENT_TYPES

def test_catalog_sample_categories():
    cats = catalog.get_categories(2)
    assert len(cats) > 0

def test_catalog_sample_variations():
    vars_ = catalog.get_variations(2, 0)
    assert len(vars_) > 0

def test_catalog_sample_track_params():
    name, key = catalog.get_track_params(2, 0, 0)
    assert isinstance(name, str) and len(name) > 0
    assert isinstance(key, str) and len(key) > 0


# ── StepNote new fields ───────────────────────────────────────────────────────

def test_stepnote_default_probability():
    s = StepNote(on=True)
    assert s.probability == 100

def test_stepnote_default_lock_cutoff():
    s = StepNote(on=True)
    assert s.lock_cutoff is None

def test_stepnote_off_has_default_probability():
    s = StepNote.off()
    assert s.probability == 100


# ── SampleTrack dataclass ─────────────────────────────────────────────────────

def test_sample_track_default_chops():
    t = SampleTrack(name="T", sample_key="kick", loops=default_track_loops())
    assert t.chops == ()

def test_sample_track_one_shot_default():
    t = SampleTrack(name="T", sample_key="kick", loops=default_track_loops())
    assert t.one_shot is True

def test_chop_point_offsets():
    c = ChopPoint(start_offset=0.0, end_offset=0.5)
    assert c.start_offset == 0.0
    assert c.end_offset == 0.5


# ── Session serialization ──��──────────────────────────────────────────────────

def test_sample_track_roundtrip():
    chops = (ChopPoint(0.0, 0.5, "a"), ChopPoint(0.5, 1.0, "b"))
    t = SampleTrack(name="AMEN", sample_key="amen_break",
                    loops=default_track_loops(), chops=chops)
    d = sessions._track_to_dict(t)
    assert d["type"] == "sample"
    assert len(d["chops"]) == 2
    t2 = sessions._dict_to_track(d)
    assert isinstance(t2, SampleTrack)
    assert t2.sample_key == "amen_break"
    assert len(t2.chops) == 2
    assert t2.chops[0].start_offset == 0.0

def test_stepnote_probability_roundtrip():
    from eden.state import default_loop
    loop = default_loop()
    steps = list(loop.steps)
    steps[0] = dataclasses.replace(steps[0], on=True, probability=50)
    loop2 = dataclasses.replace(loop, steps=tuple(steps))
    d = sessions._loop_to_dict(loop2)
    assert "probabilities" in d
    loop3 = sessions._dict_to_loop(d)
    assert loop3.steps[0].probability == 50

def test_stepnote_lock_cutoff_roundtrip():
    from eden.state import default_loop
    loop = default_loop()
    steps = list(loop.steps)
    steps[0] = dataclasses.replace(steps[0], on=True, lock_cutoff=500.0)
    loop2 = dataclasses.replace(loop, steps=tuple(steps))
    d = sessions._loop_to_dict(loop2)
    assert "lock_cutoffs" in d
    loop3 = sessions._dict_to_loop(d)
    assert loop3.steps[0].lock_cutoff == 500.0


# ── Reduce: create SampleTrack via picker ─────────────────────────────────────

def _state_with_empty_slot_sample():
    s = default_state()
    return dataclasses.replace(s, mode=Mode.SESSION, selected_track=0,
                               new_slot_type_idx=2, new_slot_cat_idx=0, new_slot_var_idx=0,
                               new_slot_active_ctrl="",
                               tracks=(None,) + s.tracks[1:])

def test_create_sample_track_via_picker():
    s = _state_with_empty_slot_sample()
    s2 = reduce(s, SoftkeyPressed(key=4))  # SK5 = CREATE
    assert isinstance(s2.tracks[0], SampleTrack)

def test_create_sample_track_has_16_loops():
    s = _state_with_empty_slot_sample()
    s2 = reduce(s, SoftkeyPressed(key=4))
    assert len(s2.tracks[0].loops) == 16


# ── Reduce: SAMPLE_CHOPS pad assignment ───────────────────────────────────────

def _armed_sample_state():
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break",
                    loops=default_track_loops(),
                    chops=(ChopPoint(0.0, 0.5), ChopPoint(0.5, 1.0)))
    tracks = (t,) + s.tracks[1:]
    return dataclasses.replace(s, tracks=tracks, selected_track=0, armed_tracks=(0,),
                               mode=Mode.INSTRUMENT,
                               instrument_submode=InstrumentSubmode.SAMPLE_CHOPS,
                               step_cursor=0)

def test_sample_top_row_selects_step():
    s = _armed_sample_state()
    s2 = reduce(s, PadPressed(pad_index=18, velocity=100))  # top row step 2
    assert s2.step_cursor == 2

def test_sample_bottom_row_assigns_chop_to_step():
    s = _armed_sample_state()
    # Select step 0 (already at step_cursor=0), assign chop 1
    s2 = reduce(s, PadPressed(pad_index=1, velocity=100))  # bottom row chop 1
    assert s2.tracks[0].loops[0].steps[0].on is True
    assert s2.tracks[0].loops[0].steps[0].pitches == (1,)


# ── Scene ─────────────────────────────────────────────────────────────────────

def test_scene_default_is_none():
    s = default_state()
    assert all(sc is None for sc in s.scenes)

def test_scene_save_via_softkey():
    s = default_state()
    s2 = dataclasses.replace(s, mode=Mode.SESSION, shift_held=True, armed_tracks=())
    s3 = reduce(s2, SoftkeyPressed(key=0))  # Shift+SK1 = save scene
    assert s3.scenes[0] is not None
    assert isinstance(s3.scenes[0], Scene)

def test_scene_load_restores_tracks():
    from eden.state import DrumTrack
    s = default_state()
    # Plant a track and save scene
    drum = DrumTrack(name="KICK", sample_name="kick_techno", loops=default_track_loops())
    s = dataclasses.replace(s, tracks=(drum,) + s.tracks[1:], mode=Mode.SESSION,
                             shift_held=True, armed_tracks=())
    s2 = reduce(s, SoftkeyPressed(key=0))  # save scene 0
    # Clear tracks
    s3 = dataclasses.replace(s2, tracks=default_state().tracks, shift_held=True)
    # Load scene (Shift+SK2)
    s4 = reduce(s3, SoftkeyPressed(key=1))
    assert isinstance(s4.tracks[0], DrumTrack)


# ── Scene serialization roundtrip ─────────────────────────────────────────────

def test_scene_roundtrip():
    """Save and reload a state with a saved scene."""
    from eden.state import DrumTrack
    s = default_state()
    drum = DrumTrack(name="KICK", sample_name="kick_techno", loops=default_track_loops())
    s = dataclasses.replace(s, tracks=(drum,) + s.tracks[1:], mode=Mode.SESSION,
                             shift_held=True, armed_tracks=())
    # Save a scene
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.scenes[0] is not None

    # Roundtrip through session serialization
    data = sessions.state_to_session(s2, "test")
    assert "scenes" in data
    patch = sessions.session_to_state_patch(data, 0)
    s3 = dataclasses.replace(s2, **patch)
    assert s3.scenes[0] is not None
    assert isinstance(s3.scenes[0].tracks[0], DrumTrack)


# ── Entering INSTRUMENT mode for SampleTrack sets SAMPLE_CHOPS submode ────────

def test_entering_instrument_for_sample_track_sets_sample_chops_submode():
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break", loops=default_track_loops())
    tracks = (t,) + s.tracks[1:]
    s = dataclasses.replace(s, tracks=tracks, selected_track=0, armed_tracks=())
    s2 = reduce(s, ModeButtonPressed(button="INST", pressed=True))
    assert s2.mode == Mode.INSTRUMENT
    assert s2.instrument_submode == InstrumentSubmode.SAMPLE_CHOPS
