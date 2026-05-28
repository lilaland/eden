"""catalog.py — Instrument type/category/variation hierarchy for new track selection."""

from __future__ import annotations

# ── Type list (M1: DRUMS only; M3: KEYS; M5: SAMPLER) ─────────────────────────

INSTRUMENT_TYPES: tuple[str, ...] = ("DRUMS",)

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

# ── Public API ─────────────────────────────────────────────────────────────────


def get_categories(type_idx: int) -> tuple[str, ...]:
    """Return category list for the given type index."""
    if type_idx == 0:  # DRUMS
        return DRUM_CATEGORIES
    return ()


def get_variations(type_idx: int, cat_idx: int) -> tuple[str, ...]:
    """Return variation list for the given type/category indices."""
    if type_idx == 0:  # DRUMS — same variation set for every category
        return DRUM_VARIATIONS
    return ()


def get_track_params(type_idx: int, cat_idx: int, var_idx: int) -> tuple[str, str]:
    """Return (track_display_name, sample_file_stem) for the current selection.

    Sample stem follows the pattern ``{category_key}_{variation_key}``,
    e.g. ``kick_techno``, ``snare_house``.
    """
    if type_idx == 0:  # DRUMS
        cats = DRUM_CATEGORIES
        vars_ = DRUM_VARIATIONS
        cat = cats[cat_idx % len(cats)]
        var = vars_[var_idx % len(vars_)]
        cat_key = _DRUM_SAMPLE_KEYS[cat]
        var_key = _VARIATION_KEYS[var]
        return _DRUM_TRACK_NAMES[cat], f"{cat_key}_{var_key}"
    return "EMPTY", "empty"
