# Eden color palette — all RGB values 0–127 (MIDI 7-bit velocity range)

THEME_NAME = "eden-tropical"

# Sequencer / pad states
PAD_ACTIVE   = (0, 90, 10)    # palm green — active step in sequencer
PAD_PLAYHEAD = (120, 45, 0)   # sunset orange — current playhead position
PAD_SELECTED = (0, 70, 60)    # jungle teal — selected track/pad
PAD_INACTIVE = (20, 0, 40)    # deep purple — inactive step
PAD_OFF      = (0, 0, 0)      # pad off

# Accents and UI — reserved for future use
ACCENT_GOLD  = (110, 80, 0)   # warm gold — transport buttons, highlights
ACCENT_CORAL = (120, 30, 20)  # coral/salmon — record arm, alert states
BG_DARK      = (5, 0, 10)     # near-black purple — off-state variation

PAD_DRUM     = (0, 70, 60)    # jungle teal — drum track type color (same as PAD_SELECTED)
PAD_SYNTH    = (90, 20, 50)   # hibiscus pink — synth track type color
PAD_SAMPLE   = (120, 30, 20)  # deep coral — sample track type color (same as ACCENT_CORAL)
PAD_NEW_SLOT = (0, 100, 0)    # bright green — empty slot selected, ready to arm/create

# Session view highlights
PAD_PINK     = (100, 0, 80)   # hot pink — selected instrument or loop
PAD_ARMED    = (120, 0, 0)    # bright red — armed track
