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
    # SAMPLE was split into 1-SHOT (type 2) and CHOPPED (type 3)
    assert "1-SHOT" in catalog.INSTRUMENT_TYPES
    assert "CHOPPED" in catalog.INSTRUMENT_TYPES

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

def test_sample_track_play_mode_default():
    t = SampleTrack(name="T", sample_key="kick", loops=default_track_loops())
    assert t.play_mode == "oneshot"

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


# ── New field tests ────────────────────────────────────────────────────────────

def test_chop_point_tune_reverse():
    """ChopPoint supports tune and reverse fields."""
    c = ChopPoint(start_offset=0.0, end_offset=0.5, name="beat", tune=-3.0, reverse=True)
    assert c.tune == -3.0
    assert c.reverse is True


def test_chop_point_defaults():
    """ChopPoint tune/reverse default to 0.0/False."""
    c = ChopPoint(start_offset=0.0, end_offset=1.0)
    assert c.tune == 0.0
    assert c.reverse is False


def test_sample_track_play_mode():
    """SampleTrack.play_mode field cycles correctly via reducer."""
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break", loops=default_track_loops())
    tracks = (t,) + s.tracks[1:]
    s = dataclasses.replace(s, tracks=tracks, armed_tracks=(0,), mode=Mode.INSTRUMENT,
                             instrument_submode=InstrumentSubmode.SAMPLE_CHOPS,
                             instrument_oled_page=1)
    # SK1 on page 1 cycles play_mode
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.tracks[0].play_mode == "gate"
    s3 = reduce(s2, SoftkeyPressed(key=0))
    assert s3.tracks[0].play_mode == "legato"
    s4 = reduce(s3, SoftkeyPressed(key=0))
    assert s4.tracks[0].play_mode == "oneshot"


def test_sample_track_new_fields():
    """SampleTrack has trim, pan, attack, release, mute_group fields."""
    t = SampleTrack(
        name="T", sample_key="kick", loops=default_track_loops(),
        trim_start=0.1, trim_end=0.9, amp_attack=0.01, amp_release=0.1,
        pan=0.5, mute_group=2,
    )
    assert t.trim_start == 0.1
    assert t.trim_end == 0.9
    assert t.amp_attack == 0.01
    assert t.amp_release == 0.1
    assert t.pan == 0.5
    assert t.mute_group == 2


def test_set_trim_event():
    """SetTrim reducer updates trim_start/end on SampleTrack."""
    from eden.events import SetTrim
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break", loops=default_track_loops())
    tracks = (t,) + s.tracks[1:]
    s = dataclasses.replace(s, tracks=tracks)
    s2 = reduce(s, SetTrim(track_idx=0, trim_start=0.1, trim_end=0.8))
    assert s2.tracks[0].trim_start == 0.1
    assert s2.tracks[0].trim_end == 0.8


def test_auto_chop_event():
    """AutoChop reducer creates ChopPoints from boundaries."""
    from eden.events import AutoChop
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break", loops=default_track_loops())
    tracks = (t,) + s.tracks[1:]
    s = dataclasses.replace(s, tracks=tracks)
    boundaries = (0.25, 0.5, 0.75)
    s2 = reduce(s, AutoChop(track_idx=0, n_slices=4, boundaries=boundaries))
    assert len(s2.tracks[0].chops) == 4
    assert s2.tracks[0].chops[0].start_offset == 0.0
    assert s2.tracks[0].chops[0].end_offset == 0.25
    assert s2.tracks[0].chops[3].start_offset == 0.75
    assert s2.tracks[0].chops[3].end_offset == 1.0


def test_sample_record_stop():
    """SampleRecordStop reducer updates sample_key and clears sample_recording."""
    from eden.events import SampleRecordStart, SampleRecordStop
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break", loops=default_track_loops())
    tracks = (t,) + s.tracks[1:]
    s = dataclasses.replace(s, tracks=tracks)
    s2 = reduce(s, SampleRecordStart(track_idx=0))
    assert s2.sample_recording is True
    s3 = reduce(s2, SampleRecordStop(track_idx=0, new_key="recorded_01"))
    assert s3.sample_recording is False
    assert s3.tracks[0].sample_key == "recorded_01"


def test_sample_keys_submode():
    """SK2 on page 0 in SAMPLE_CHOPS enters SAMPLE_KEYS; SK1 in SAMPLE_KEYS goes back."""
    s = default_state()
    t = SampleTrack(name="AMEN", sample_key="amen_break",
                    loops=default_track_loops(),
                    chops=(ChopPoint(0.0, 0.5), ChopPoint(0.5, 1.0)))
    tracks = (t,) + s.tracks[1:]
    s = dataclasses.replace(s, tracks=tracks, armed_tracks=(0,), mode=Mode.INSTRUMENT,
                             instrument_submode=InstrumentSubmode.SAMPLE_CHOPS,
                             instrument_oled_page=0)
    # SK2 enters SAMPLE_KEYS
    s2 = reduce(s, SoftkeyPressed(key=1))
    assert s2.instrument_submode == InstrumentSubmode.SAMPLE_KEYS
    # SK1 goes back to SAMPLE_CHOPS
    s3 = reduce(s2, SoftkeyPressed(key=0))
    assert s3.instrument_submode == InstrumentSubmode.SAMPLE_CHOPS


def test_sessions_sample_track_new_fields():
    """Round-trip serialization preserves all new SampleTrack fields."""
    t = SampleTrack(
        name="AMEN", sample_key="amen_break",
        loops=default_track_loops(),
        play_mode="gate", trim_start=0.05, trim_end=0.95,
        amp_attack=0.02, amp_release=0.15, pan=-0.3, mute_group=1,
    )
    d = sessions._track_to_dict(t)
    assert d["play_mode"] == "gate"
    assert d["trim_start"] == 0.05
    assert d["trim_end"] == 0.95
    assert d["amp_attack"] == 0.02
    assert d["amp_release"] == 0.15
    assert d["pan"] == -0.3
    assert d["mute_group"] == 1
    t2 = sessions._dict_to_track(d)
    assert isinstance(t2, SampleTrack)
    assert t2.play_mode == "gate"
    assert t2.trim_start == 0.05
    assert t2.trim_end == 0.95
    assert t2.amp_attack == 0.02
    assert t2.amp_release == 0.15
    assert t2.pan == -0.3
    assert t2.mute_group == 1


def test_sessions_chop_tune_reverse():
    """Round-trip serialization preserves ChopPoint.tune and .reverse."""
    chops = (
        ChopPoint(0.0, 0.5, "a", tune=2.0, reverse=False),
        ChopPoint(0.5, 1.0, "b", tune=-1.5, reverse=True),
    )
    t = SampleTrack(name="AMEN", sample_key="amen_break",
                    loops=default_track_loops(), chops=chops)
    d = sessions._track_to_dict(t)
    assert d["chops"][0]["tune"] == 2.0
    assert d["chops"][0]["reverse"] is False
    assert d["chops"][1]["tune"] == -1.5
    assert d["chops"][1]["reverse"] is True
    t2 = sessions._dict_to_track(d)
    assert t2.chops[0].tune == 2.0
    assert t2.chops[0].reverse is False
    assert t2.chops[1].tune == -1.5
    assert t2.chops[1].reverse is True


def test_sessions_legacy_one_shot_migration():
    """Legacy one_shot=True maps to play_mode='oneshot'."""
    d = {
        "type": "sample", "name": "T", "sample_key": "k",
        "one_shot": True, "volume": 1.0,
        "loops": [None] * 16, "chops": [],
    }
    t = sessions._dict_to_track(d)
    assert t.play_mode == "oneshot"

    d2 = {
        "type": "sample", "name": "T", "sample_key": "k",
        "one_shot": False, "volume": 1.0,
        "loops": [None] * 16, "chops": [],
    }
    t2 = sessions._dict_to_track(d2)
    assert t2.play_mode == "gate"


def test_sample_chop_cursor_default():
    """AppState.sample_chop_cursor defaults to 0."""
    s = default_state()
    assert s.sample_chop_cursor == 0


def test_sample_recording_default():
    """AppState.sample_recording defaults to False."""
    s = default_state()
    assert s.sample_recording is False


# ── Feature 3: DEMO soft key ───────────────────────────────────────────────────

def test_demo_key_does_not_create_track():
    """SK4 on new-slot picker does NOT create a track (app.py intercepts it)."""
    s = _state_with_empty_slot_sample()
    s2 = reduce(s, SoftkeyPressed(key=3))  # SK4 = DEMO (intercepted before reducer in app.py)
    # The reducer sees key=3 as BACK (clears active ctrl), but app.py intercepts first.
    # In the reducer path (sans app.py), key=3 just clears new_slot_active_ctrl.
    assert s2.tracks[0] is None  # no track created


def test_demo_render_shows_demo_label():
    """New-slot picker OLED shows DEMO on SK4."""
    from eden.render import render_oled
    from controller_map import OLED_BTN4_TITLE
    s = _state_with_empty_slot_sample()
    oled = render_oled(s)
    assert oled.get(OLED_BTN4_TITLE, ("",))[0] == "DEMO"


# ── Feature 1: SAMPLE_EDIT submode ────────────────────────────────────────────

def _armed_sample_state_with_chops():
    s = default_state()
    t = SampleTrack(
        name="AMEN", sample_key="amen_break",
        loops=default_track_loops(),
        chops=(
            ChopPoint(0.0, 0.25),
            ChopPoint(0.25, 0.5),
            ChopPoint(0.5, 0.75),
            ChopPoint(0.75, 1.0),
        ),
    )
    tracks = (t,) + s.tracks[1:]
    return dataclasses.replace(s, tracks=tracks, selected_track=0, armed_tracks=(0,),
                               mode=Mode.INSTRUMENT,
                               instrument_submode=InstrumentSubmode.SAMPLE_EDIT,
                               sample_chop_cursor=0)


def test_sample_edit_top_row_selects_chop():
    """Top row pad in SAMPLE_EDIT selects chop."""
    s = _armed_sample_state_with_chops()
    s2 = reduce(s, PadPressed(pad_index=18, velocity=100))  # pad 18 = chop 2
    assert s2.sample_chop_cursor == 2


def test_sample_edit_top_row_out_of_range_noop():
    """Top row pad beyond available chops is a no-op."""
    s = _armed_sample_state_with_chops()
    s2 = reduce(s, PadPressed(pad_index=20, velocity=100))  # chop 4 doesn't exist
    assert s2.sample_chop_cursor == 0  # unchanged


def test_sample_edit_shift_bottom_left_sets_start():
    """Shift + bottom pad < 8 sets chop start_offset."""
    s = _armed_sample_state_with_chops()
    s2 = dataclasses.replace(s, shift_held=True)
    s3 = reduce(s2, PadPressed(pad_index=3, velocity=100))  # pos = 3/15 = 0.2
    chop = s3.tracks[0].chops[0]
    assert abs(chop.start_offset - 3 / 15.0) < 0.01


def test_sample_edit_shift_bottom_right_sets_end():
    """Shift + bottom pad >= 8 sets chop end_offset."""
    s = _armed_sample_state_with_chops()
    s2 = dataclasses.replace(s, shift_held=True, sample_chop_cursor=1)
    s3 = reduce(s2, PadPressed(pad_index=12, velocity=100))  # pos = 12/15 = 0.8
    chop = s3.tracks[0].chops[1]
    assert abs(chop.end_offset - 12 / 15.0) < 0.01


def test_sample_edit_normal_bottom_noop_in_reducer():
    """Normal (no-shift) bottom pad press in SAMPLE_EDIT is a no-op in reducer."""
    s = _armed_sample_state_with_chops()
    s2 = reduce(s, PadPressed(pad_index=5, velocity=100))
    assert s2 is s  # state unchanged (scrub is audio side-effect only)


def test_sample_edit_sk1_back_to_chops():
    """SK1 in SAMPLE_EDIT returns to SAMPLE_CHOPS submode."""
    s = _armed_sample_state_with_chops()
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.instrument_submode == InstrumentSubmode.SAMPLE_CHOPS


def test_sample_chops_sk1_enters_edit():
    """SK1 on page 0 in SAMPLE_CHOPS enters SAMPLE_EDIT."""
    s = _armed_sample_state_with_chops()
    s = dataclasses.replace(s, instrument_submode=InstrumentSubmode.SAMPLE_CHOPS,
                            instrument_oled_page=0)
    s2 = reduce(s, SoftkeyPressed(key=0))
    assert s2.instrument_submode == InstrumentSubmode.SAMPLE_EDIT


# ── Feature 2: SampleTrack stretch fields ─────────────────────────────────────

def test_sample_track_stretch_defaults():
    """SampleTrack stretch_mode defaults to 'off', stretch_bars to 1."""
    t = SampleTrack(name="T", sample_key="k", loops=default_track_loops())
    assert t.stretch_mode == "off"
    assert t.stretch_bars == 1


def test_sample_track_stretch_roundtrip():
    """stretch_mode and stretch_bars survive session serialization."""
    t = SampleTrack(name="AMEN", sample_key="amen_break",
                    loops=default_track_loops(),
                    stretch_mode="stretch", stretch_bars=4)
    d = sessions._track_to_dict(t)
    assert d["stretch_mode"] == "stretch"
    assert d["stretch_bars"] == 4
    t2 = sessions._dict_to_track(d)
    assert t2.stretch_mode == "stretch"
    assert t2.stretch_bars == 4


def test_sample_per_chop_tune_via_encoder():
    """CHOP_TUNE encoder changes selected chop's tune."""
    from eden.events import EncoderTurned
    s = _armed_sample_state_with_chops()
    # Per-chop page (page 2) is reachable from SAMPLE_CHOPS submode
    s = dataclasses.replace(s, instrument_submode=InstrumentSubmode.SAMPLE_CHOPS,
                            instrument_oled_page=2,
                            instrument_active_ctrl="CHOP_TUNE",
                            sample_chop_cursor=0)
    s2 = reduce(s, EncoderTurned(encoder=9, delta=1))
    assert s2.tracks[0].chops[0].tune == 0.5  # +0.5 semitone


def test_sample_per_chop_reverse_toggle():
    """SK2 on page 2 (per-chop) toggles chop reverse."""
    s = _armed_sample_state_with_chops()
    s = dataclasses.replace(s, instrument_submode=InstrumentSubmode.SAMPLE_CHOPS,
                            instrument_oled_page=2, sample_chop_cursor=0)
    s2 = reduce(s, SoftkeyPressed(key=1))
    assert s2.tracks[0].chops[0].reverse is True
    s3 = reduce(s2, SoftkeyPressed(key=1))
    assert s3.tracks[0].chops[0].reverse is False


# ── Feature 4: available_samples + new taxonomy ───────────────────────────────

def test_available_samples_default_empty():
    """AppState.available_samples defaults to empty tuple."""
    s = default_state()
    assert s.available_samples == ()


def test_set_available_samples_event():
    """SetAvailableSamples event updates available_samples."""
    from eden.events import SetAvailableSamples
    s = default_state()
    s2 = reduce(s, SetAvailableSamples(keys=("amen_break", "think_break")))
    assert "amen_break" in s2.available_samples
    assert "think_break" in s2.available_samples


def test_catalog_new_taxonomy():
    """Sample catalog uses new taxonomy: Breaks/Vocals/Instr/Texture/FX."""
    import eden.catalog as cat
    cats = cat.get_categories(2)
    assert "Breaks" in cats
    assert "FX" in cats
    assert "Hits" not in cats  # old taxonomy dropped


def test_catalog_filters_by_available():
    """get_variations filters by available_samples pool when non-empty."""
    import eden.catalog as cat
    # Only amen_break available
    vars_all = cat.get_variations(2, 0)  # Breaks, no filter
    vars_filtered = cat.get_variations(2, 0, ("amen_break",))
    assert len(vars_filtered) < len(vars_all)
    assert "Amen" in vars_filtered   # amen_break is in pool
    assert "Think" not in vars_filtered  # think_break not in pool


def test_catalog_empty_pool_returns_all():
    """Empty available_samples tuple returns full catalog (no filter)."""
    import eden.catalog as cat
    vars_no_filter = cat.get_variations(2, 0, ())
    vars_full = cat.get_variations(2, 0)
    assert vars_no_filter == vars_full
