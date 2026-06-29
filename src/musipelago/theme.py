"""Central theme palettes for the Musipelago apps.

Pure data + helpers, no Kivy import, so it loads headless and is unit-testable.
The app binds its ``col_*`` ColorProperties to one of these palettes and the kv
references ``app.col_*``; switching palette at runtime re-themes every widget.

Each palette is a dict of named RGBA 4-tuples (floats 0..1):
  bg        window / root background
  surface   list / panel background
  card      individual list-row card
  accent    primary action buttons, highlights
  text      primary text
  text_dim  secondary / helper text
  border    subtle separators / outlines
"""

# Ordered so callers can validate every palette exposes the same keys.
KEYS = ("bg", "surface", "card", "accent", "text", "text_dim", "border")

DARK = {
    "bg": (0.10, 0.10, 0.12, 1),
    "surface": (0.15, 0.15, 0.17, 1),
    "card": (0.19, 0.19, 0.22, 1),
    "accent": (0.30, 0.55, 0.90, 1),
    "text": (0.95, 0.95, 0.96, 1),
    "text_dim": (0.70, 0.70, 0.73, 1),
    "border": (0.28, 0.28, 0.32, 1),
}

LIGHT = {
    "bg": (0.96, 0.96, 0.97, 1),
    "surface": (0.91, 0.91, 0.93, 1),
    "card": (1.00, 1.00, 1.00, 1),
    "accent": (0.20, 0.50, 0.85, 1),
    "text": (0.10, 0.10, 0.12, 1),
    "text_dim": (0.26, 0.26, 0.30, 1),  # darkened: 0.38 was too faint on the light bg
    "border": (0.80, 0.80, 0.84, 1),
}

PALETTES = {"dark": DARK, "light": LIGHT}

# Shared geometry (in dp; the kv multiplies by dp()).
RADIUS = 8
SPACING = 10
PADDING = 10


def get_palette(name):
    """Return the palette for ``name`` (case-insensitive), falling back to DARK."""
    return PALETTES.get(str(name).lower(), DARK)
