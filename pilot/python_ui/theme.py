"""Palette, fonts and layout constants for Pilot (same family as Cadet)."""

from pathlib import Path

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BG           = (38, 42, 50)      # page background
TEXT         = (216, 222, 233)   # primary text
TEXT_DIM     = (139, 147, 163)
TEXT_FAINT   = (100, 108, 122)
ACCENT       = (94, 129, 172)
ACCENT_HOT   = (129, 161, 193)
PANEL        = (46, 51, 60)
PANEL_LINE   = (24, 27, 32)
SELECT       = (76, 86, 106)
SELECT_FOC   = (59, 70, 89)
ROW_HOVER    = (52, 59, 71)
LINK         = (114, 168, 218)   # hyperlink blue
LINK_VISITED = (150, 120, 210)
ERR_RED      = (191, 97, 106)
OK_GREEN     = (163, 190, 140)
WARN_YELLOW  = (235, 203, 139)
INPUT_BG     = (28, 31, 37)
INPUT_BORDER = (70, 78, 90)
TAB_ACTIVE   = (52, 58, 68)
TAB_INACTIVE = (38, 43, 51)
SCROLL_THUMB = (76, 86, 106)

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
FONT_DIRS = [
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/usr/share/fonts/truetype/noto"),
    Path("/usr/share/fonts/truetype/freefont"),
    Path("/usr/share/fonts/truetype/ubuntu"),
]

SANS = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "NotoSans-Regular.ttf",
        "FreeSans.ttf", "Ubuntu-Regular.ttf"]
SANS_B = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"]
SANS_I = ["DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"]
SANS_BI = ["DejaVuSans-BoldOblique.ttf", "LiberationSans-BoldItalic.ttf"]
SERIF = ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "FreeSerif.ttf"]
SERIF_B = ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf"]
SERIF_I = ["DejaVuSerif-Italic.ttf", "LiberationSerif-Italic.ttf"]
SERIF_BI = ["DejaVuSerif-BoldItalic.ttf", "LiberationSerif-BoldItalic.ttf"]
MONO = ["DejaVuSansMono.ttf", "LiberationMono-Regular.ttf", "FreeMono.ttf"]
MONO_B = ["DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf"]
MONO_I = ["DejaVuSansMono-Oblique.ttf", "LiberationMono-Italic.ttf"]
MONO_BI = ["DejaVuSansMono-BoldOblique.ttf", "LiberationMono-BoldItalic.ttf"]

FONT_CACHE: dict = {}


def _find(names):
    for fd in FONT_DIRS:
        if fd.is_dir():
            for name in names:
                p = fd / name
                if p.is_file():
                    return str(p)
    return None


def font(kind, weight, style, size):
    """Return a cached PIL truetype font.

    kind: "sans" | "serif" | "mono"; weight: "normal"|"bold";
    style: "normal"|"italic".
    """
    key = (kind, weight, style, size)
    f = FONT_CACHE.get(key)
    if f is not None:
        return f
    if kind == "serif":
        table = (SERIF, SERIF_B, SERIF_I, SERIF_BI)
    elif kind == "mono":
        table = (MONO, MONO_B, MONO_I, MONO_BI)
    else:
        table = (SANS, SANS_B, SANS_I, SANS_BI)
    idx = (1 if weight == "bold" else 0) + (2 if style == "italic" else 0)
    path = _find(table[idx]) or _find(SANS)
    try:
        f = __import__("PIL.ImageFont", fromlist=["ImageFont"]).truetype(path, size)
    except Exception:
        f = __import__("PIL.ImageFont", fromlist=["ImageFont"]).load_default(size)
    if len(FONT_CACHE) > 400:
        FONT_CACHE.clear()
    FONT_CACHE[key] = f
    return f


# ---------------------------------------------------------------------------
# Layout (browser chrome)
# ---------------------------------------------------------------------------
SIZE_W       = 1120
SIZE_H       = 760
TABBAR_H     = 34
NAVBAR_H     = 40
STATUSBAR_H  = 24
BTN_H        = 26
ADDRBAR_H    = 28
SCROLL_W     = 12
PAD          = 6
MIN_TAB_W    = 120
MAX_TAB_W    = 210
TAB_H        = 26
FIND_H       = 26

BASE_FONT    = 16          # CSS default font size (px)
ZOOM_MIN     = 8
ZOOM_MAX     = 32

# Key repeat throttle
KEY_REPEAT_DELAY = 0.45
KEY_REPEAT_RATE  = 0.05

POLL_INTERVAL = 0.05

HOME_URL = "pilot://home"

USER_AGENT = ("Mozilla/5.0 (Pilot/1.0; X11; Linux x86_64) "
              "AppleWebKit/0.0 (KHTML, like Gecko) Pilot/1.0")