"""catalog.py — Instrument type/category/variation hierarchy for new track selection."""

from __future__ import annotations

# ── Type list ──────────────────────────────────────────────────────────────────
# type_idx: 0=DRUMS, 1=KEYS, 2=1-SHOT sample, 3=CHOPPED sample

INSTRUMENT_TYPES: tuple[str, ...] = ("DRUMS", "KEYS", "1-SHOT", "CHOPPED")

# ── Drum catalog ───────────────────────────────────────────────────────────────

DRUM_CATEGORIES: tuple[str, ...] = (
    "Kick",
    "Snare",
    "Cl.Hat",
    "Op.Hat",
    "Clap",
    "Tom Hi",
    "Tom Lo",
    "Rim",
    "Cowbell",
    "Cymbal",
    "Shaker",
    "Tambourn",
    "Conga Hi",
    "Conga Lo",
    "Bongo Hi",
    "Bongo Lo",
    "Cabasa",
    "Maracas",
    "Woodblk",
    "Agogo",
    "Crash",
    "Ride",
)

DRUM_VARIATIONS: tuple[str, ...] = ("Techno", "House", "Disco", "Jazz", "RnB",
                                    "Afro", "Latin", "Funk", "Rock")

_DRUM_SAMPLE_KEYS: dict[str, str] = {
    "Kick":     "kick",
    "Snare":    "snare",
    "Cl.Hat":   "clhat",
    "Op.Hat":   "ophat",
    "Clap":     "clap",
    "Tom Hi":   "tom_hi",
    "Tom Lo":   "tom_lo",
    "Rim":      "rim",
    "Cowbell":  "cowbell",
    "Cymbal":   "cymbal",
    "Shaker":   "shaker",
    "Tambourn": "tambourn",
    "Conga Hi": "conga_hi",
    "Conga Lo": "conga_lo",
    "Bongo Hi": "bongo_hi",
    "Bongo Lo": "bongo_lo",
    "Cabasa":   "cabasa",
    "Maracas":  "maracas",
    "Woodblk":  "woodblk",
    "Agogo":    "agogo",
    "Crash":    "crash",
    "Ride":     "ride",
}

_DRUM_TRACK_NAMES: dict[str, str] = {
    "Kick":     "KICK",
    "Snare":    "SNARE",
    "Cl.Hat":   "CLHAT",
    "Op.Hat":   "OPHAT",
    "Clap":     "CLAP",
    "Tom Hi":   "TOM-H",
    "Tom Lo":   "TOM-L",
    "Rim":      "RIM  ",
    "Cowbell":  "COWBL",
    "Cymbal":   "CYMBL",
    "Shaker":   "SHKR ",
    "Tambourn": "TAMB ",
    "Conga Hi": "CNG-H",
    "Conga Lo": "CNG-L",
    "Bongo Hi": "BNG-H",
    "Bongo Lo": "BNG-L",
    "Cabasa":   "CBSA ",
    "Maracas":  "MRCS ",
    "Woodblk":  "WDBLK",
    "Agogo":    "AGOGO",
    "Crash":    "CRASH",
    "Ride":     "RIDE ",
}

_VARIATION_KEYS: dict[str, str] = {
    "Techno": "techno",
    "House":  "house",
    "Disco":  "disco",
    "Jazz":   "jazz",
    "RnB":    "rnb",
    "Afro":   "afro",
    "Latin":  "latin",
    "Funk":   "funk",
    "Rock":   "rock",
}

# ── Keys (synth) catalog ──────────────────────────────────────────────────────

# Each preset: (display_name, track_name, osc_type, extra_synth_params)
_KEYS_PRESETS: dict[str, tuple] = {
    "Raw": (
        ("Saw",       "SAW",   "saw",      {}),
        ("Square",    "SQR",   "square",   {}),
        ("Sine",      "SINE",  "sine",     {}),
        ("Tri",       "TRI",   "triangle", {}),
    ),
    "Bass": (
        ("Sub Bass",  "SBASS", "sine",     {"filter_cutoff": 180.0, "amp_attack": 0.01, "amp_release": 0.4}),
        ("Reese",     "REESE", "saw",      {"filter_cutoff": 400.0, "filter_res": 0.5}),
        ("FM Bass",   "FMBAS", "sine",     {"filter_cutoff": 600.0, "amp_attack": 0.005, "amp_release": 0.2}),
        ("Wobble",    "WOBBL", "saw",      {"filter_cutoff": 300.0, "filter_res": 0.6, "amp_attack": 0.01}),
    ),
    "Lead": (
        ("Mono Lead", "LEAD",  "saw",      {"filter_cutoff": 3000.0}),
        ("Supersaw",  "SSAW",  "saw",      {"filter_cutoff": 5000.0, "amp_attack": 0.05, "max_voices": 4}),
        ("Screamer",  "SCRM",  "square",   {"filter_cutoff": 2500.0, "filter_res": 0.3}),
    ),
    "Pad": (
        ("Warm Pad",   "WPAD",  "sine",    {"amp_attack": 0.5, "amp_sustain": 0.8, "amp_release": 1.2, "filter_cutoff": 1500.0}),
        ("Evolv.Pad",  "EPAD",  "triangle",{"amp_attack": 1.0, "amp_sustain": 0.7, "amp_release": 2.0, "filter_cutoff": 2000.0}),
        ("String Pad", "STRNG", "saw",     {"amp_attack": 0.3, "amp_release": 0.9, "filter_cutoff": 3500.0}),
    ),
    "Pluck": (
        ("Pluck",      "PLUCK", "triangle",{"amp_attack": 0.001, "amp_sustain": 0.0, "amp_release": 0.5, "filter_cutoff": 4000.0}),
    ),
    "Keys": (
        ("Keys",       "KEYS",  "square",  {"amp_attack": 0.01, "amp_sustain": 0.7, "amp_release": 0.3, "filter_cutoff": 6000.0}),
    ),
}

KEYS_FOLDERS: tuple[str, ...] = tuple(_KEYS_PRESETS.keys())

# ── Sample catalog ─────────────────────────────────────────────────────────────

SAMPLE_CATEGORIES: tuple[str, ...] = ("Breaks", "Vocals", "Instr", "Texture", "FX")

# (display_name, track_name, sample_key)
# sample_key must appear in available_samples (AppState) to be selectable at runtime.
_SAMPLE_CATALOG: dict[str, tuple] = {
    "Breaks": (
        ("Amen",     "AMEN",  "amen_break"),
        ("Think",    "THINK", "think_break"),
        ("Apache",   "APACH", "apache_break"),
        ("Funky D",  "FUNKD", "funky_drummer"),
    ),
    "Vocals": (
        ("Vox 1",    "VOX1",  "vocal_chop_1"),
        ("Vox 2",    "VOX2",  "vocal_chop_2"),
    ),
    "Instr": (
        ("Rhodes",   "RHDS",  "rhodes_loop"),
        ("Bass Riff","BSRIF", "bass_riff"),
        ("Guitar",   "GTR",   "guitar_loop"),
    ),
    "Texture": (
        ("Vinyl",    "VINL",  "vinyl_texture"),
        ("Rain",     "RAIN",  "rain_foley"),
        ("Crowd",    "CRWD",  "crowd_foley"),
    ),
    "FX": (
        ("Riser",    "RISR",  "riser_fx"),
        ("Impact",   "IMPCT", "impact_fx"),
        ("Downlift", "DNLFT", "downlift_fx"),
    ),
}

# Optional tags per sample key — used for web library filtering.
SAMPLE_TAGS: dict[str, tuple[str, ...]] = {
    "amen_break":     ("dnb", "classic", "breaks", "fast"),
    "think_break":    ("hip-hop", "classic", "breaks"),
    "apache_break":   ("hip-hop", "funk", "classic", "breaks"),
    "funky_drummer":  ("funk", "classic", "breaks"),
    "vocal_chop_1":   ("vocals", "pop"),
    "vocal_chop_2":   ("vocals", "rnb"),
    "eden_vocal_hey": ("vocals", "eden", "synth"),
    "eden_break_hit": ("breaks", "eden", "synth", "oneshot"),
    "eden_piano_hit": ("keys", "eden", "synth", "oneshot"),
    "eden_vinyl":     ("texture", "eden", "synth", "ambient"),
    "rhodes_loop":    ("jazz", "melodic", "keys"),
    "bass_riff":      ("bass", "funk", "melodic"),
    "guitar_loop":    ("guitar", "organic", "melodic"),
    "vinyl_texture":  ("ambient", "texture", "vintage"),
    "rain_foley":     ("ambient", "texture", "organic"),
    "crowd_foley":    ("ambient", "texture", "organic"),
    "riser_fx":       ("fx", "tension"),
    "impact_fx":      ("fx", "drop", "dark"),
    "downlift_fx":    ("fx", "transition"),
    "eden_riser":     ("fx", "eden", "synth", "tension"),
    "eden_loop":      ("breaks", "eden", "synth"),
    "eden_rhodes":    ("keys", "rhodes", "melodic", "eden"),
    "eden_guitar":    ("guitar", "acoustic", "melodic", "eden"),
    "eden_strings":   ("strings", "ensemble", "melodic", "eden"),
}

# Bundled default samples — always visible regardless of available_samples pool.
# These .wav files are generated by scripts/gen_samples.py.
_BUNDLED_ONESHOT: dict[str, tuple] = {
    "Breaks":  (("Eden Hit",  "EHIT",  "eden_break_hit"),),
    "Vocals":  (("Eden Hey",  "EHEY",  "eden_vocal_hey"),),
    "Instr":   (("Eden Pno",  "EPNO",  "eden_piano_hit"),
                ("Rhodes",    "RHODE", "eden_rhodes"),
                ("Guitar",    "GUITR", "eden_guitar"),
                ("Strings",   "STRGS", "eden_strings"),),
    "Texture": (("Eden Vnl",  "EVNL",  "eden_vinyl"),),
    "FX":      (("Eden Rise", "ERISE", "eden_riser"),),
}
_BUNDLED_CHOPPED: dict[str, tuple] = {
    "Breaks": (("Eden Loop", "EDNLP", "eden_loop"),),
}

# Sentinel key used when the user selects "record new sample"
_RECORD_SENTINEL = "__record__"
_RECORD_ENTRY: tuple = ("+ New...", "NEW", _RECORD_SENTINEL)


def _sample_variations(
    type_idx: int,
    cat_name: str,
    available: tuple[str, ...] = (),
) -> tuple[tuple[str, str, str], ...]:
    """Return (display_name, track_name, sample_key) tuples for a 1-SHOT or CHOPPED category.

    Bundled defaults appear first (always), then catalog entries whose sample_key
    is in ``available`` (or all catalog entries when available is empty).
    The record-new sentinel entry is appended last.
    """
    bundled_map = _BUNDLED_ONESHOT if type_idx == 2 else _BUNDLED_CHOPPED
    bundled = bundled_map.get(cat_name, ())
    catalog_all = _SAMPLE_CATALOG.get(cat_name, ())
    if available:
        catalog_filtered = tuple(e for e in catalog_all if e[2] in available)
    else:
        catalog_filtered = catalog_all
    return bundled + catalog_filtered + (_RECORD_ENTRY,)


def _visible_sample_categories(
    type_idx: int,
    available: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return SAMPLE_CATEGORIES visible for the given type (2=1-SHOT, 3=CHOPPED).

    A category is visible if it has bundled defaults OR at least one entry in available.
    When available is empty, all categories are shown.
    """
    bundled_map = _BUNDLED_ONESHOT if type_idx == 2 else _BUNDLED_CHOPPED
    result = []
    for cat in SAMPLE_CATEGORIES:
        has_bundled = bool(bundled_map.get(cat))
        if has_bundled or not available:
            result.append(cat)
            continue
        catalog_entries = _SAMPLE_CATALOG.get(cat, ())
        if any(e[2] in available for e in catalog_entries):
            result.append(cat)
    return tuple(result)


# ── Public API ─────────────────────────────────────────────────────────────────


def get_categories(type_idx: int, available: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Return category list for the given type index.

    For 1-SHOT (2) and CHOPPED (3): filters out empty categories based on available pool.
    """
    if type_idx == 0:  # DRUMS
        return DRUM_CATEGORIES
    if type_idx == 1:  # KEYS — folders
        return KEYS_FOLDERS
    if type_idx in (2, 3):  # 1-SHOT or CHOPPED
        return _visible_sample_categories(type_idx, available)
    return ()


def get_variations(
    type_idx: int,
    cat_idx: int,
    available: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Return variation display-name list for the given type/category indices.

    For SAMPLE types (2/3): if ``available`` is non-empty, only include entries whose
    sample_key appears in the pool (plus always-visible bundled defaults).
    Falls back to full catalog when pool is empty.
    """
    if type_idx == 0:  # DRUMS
        return DRUM_VARIATIONS
    if type_idx == 1:  # KEYS — presets within selected folder
        folder = KEYS_FOLDERS[cat_idx % len(KEYS_FOLDERS)]
        return tuple(p[0] for p in _KEYS_PRESETS[folder])
    if type_idx in (2, 3):  # 1-SHOT or CHOPPED
        cats = _visible_sample_categories(type_idx, available)
        cat_name = cats[cat_idx % len(cats)] if cats else ""
        return tuple(e[0] for e in _sample_variations(type_idx, cat_name, available))
    return ()


def get_track_params(
    type_idx: int,
    cat_idx: int,
    var_idx: int,
    available: tuple[str, ...] = (),
) -> tuple[str, str]:
    """Return (track_display_name, type_param) for the current selection.

    For DRUMS: type_param is the sample file stem, e.g. ``kick_techno``.
    For KEYS:  type_param is the osc_type engine key, e.g. ``saw``.
    For 1-SHOT/CHOPPED: type_param is the sample_key, e.g. ``amen_break``.
      Special value ``__record__`` means the user wants to record a new sample.
    """
    if type_idx == 0:  # DRUMS
        cats = DRUM_CATEGORIES
        vars_ = DRUM_VARIATIONS
        cat = cats[cat_idx % len(cats)]
        var = vars_[var_idx % len(vars_)]
        cat_key = _DRUM_SAMPLE_KEYS[cat]
        var_key = _VARIATION_KEYS[var]
        return _DRUM_TRACK_NAMES[cat], f"{cat_key}_{var_key}"
    if type_idx == 1:  # KEYS
        folder = KEYS_FOLDERS[cat_idx % len(KEYS_FOLDERS)]
        presets = _KEYS_PRESETS[folder]
        _, track_name, osc_type, _ = presets[var_idx % len(presets)]
        return track_name, osc_type
    if type_idx in (2, 3):  # 1-SHOT or CHOPPED
        cats = _visible_sample_categories(type_idx, available)
        cat_name = cats[cat_idx % len(cats)] if cats else ""
        entries = _sample_variations(type_idx, cat_name, available)
        if not entries:
            return "SMPL", ""
        _, track_name, sample_key = entries[var_idx % len(entries)]
        return track_name, sample_key
    return "EMPTY", ""


def get_synth_preset_extras(cat_idx: int, var_idx: int) -> dict:
    """Return extra SynthTrack constructor kwargs for the selected KEYS preset."""
    folder = KEYS_FOLDERS[cat_idx % len(KEYS_FOLDERS)]
    presets = _KEYS_PRESETS[folder]
    _, _, _, extras = presets[var_idx % len(presets)]
    return dict(extras)
