"""catalog.py — Instrument type/category/variation hierarchy for new track selection."""

from __future__ import annotations

# ── Type list ─────────────────────────────────────────────────────────────────

INSTRUMENT_TYPES: tuple[str, ...] = ("DRUMS", "KEYS")

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


# ── Public API ─────────────────────────────────────────────────────────────────


def get_categories(type_idx: int) -> tuple[str, ...]:
    """Return category list for the given type index."""
    if type_idx == 0:  # DRUMS
        return DRUM_CATEGORIES
    if type_idx == 1:  # KEYS — folders
        return KEYS_FOLDERS
    return ()


def get_variations(type_idx: int, cat_idx: int) -> tuple[str, ...]:
    """Return variation list for the given type/category indices."""
    if type_idx == 0:  # DRUMS
        return DRUM_VARIATIONS
    if type_idx == 1:  # KEYS — presets within selected folder
        folder = KEYS_FOLDERS[cat_idx % len(KEYS_FOLDERS)]
        return tuple(p[0] for p in _KEYS_PRESETS[folder])
    return ()


def get_track_params(type_idx: int, cat_idx: int, var_idx: int) -> tuple[str, str]:
    """Return (track_display_name, type_param) for the current selection.

    For DRUMS: type_param is the sample file stem, e.g. ``kick_techno``.
    For KEYS:  type_param is the osc_type engine key, e.g. ``saw``.
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
    return "EMPTY", ""


def get_synth_preset_extras(cat_idx: int, var_idx: int) -> dict:
    """Return extra SynthTrack constructor kwargs for the selected KEYS preset."""
    folder = KEYS_FOLDERS[cat_idx % len(KEYS_FOLDERS)]
    presets = _KEYS_PRESETS[folder]
    _, _, _, extras = presets[var_idx % len(presets)]
    return dict(extras)
