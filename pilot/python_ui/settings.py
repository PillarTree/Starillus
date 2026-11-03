"""Persistent browser settings (JSON in ~/.config/pilot/settings.json)."""

from __future__ import annotations

import json
import os

DEFAULTS = {
    "home_url": "pilot://home",
    "new_tab_url": "pilot://home",
    "zoom": 1.0,
    "theme": "dark",           # dark | light (chrome colors)
    "status_bar": True,
    "ui_font_size": 13,
    "base_font_size": 16,      # CSS default font size
    "image_loading": True,
    "javascript": True,
    "devtools_open": False,
    "devtools_height": 220,
    "user_agent": None,
}

_valid = {"home_url": str, "new_tab_url": str, "zoom": float, "theme": str,
          "status_bar": bool, "ui_font_size": int, "base_font_size": int,
          "image_loading": bool, "javascript": bool, "devtools_open": bool,
          "devtools_height": int, "user_agent": str}


def _config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "pilot")


def config_path() -> str:
    return os.path.join(_config_dir(), "settings.json")


class Settings:
    def __init__(self):
        self.data = dict(DEFAULTS)
        self._load()

    def _load(self):
        try:
            with open(config_path(), "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in _valid and isinstance(v, _valid[k]):
                        self.data[k] = v
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(_config_dir(), exist_ok=True)
            with open(config_path(), "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, sort_keys=True)
        except OSError:
            pass

    def get(self, name, default=None):
        return self.data.get(name, default if default is not None
                             else DEFAULTS.get(name))

    def set(self, name, value):
        if name not in _valid:
            return False
        try:
            value = _valid[name](value)
        except (TypeError, ValueError):
            return False
        self.data[name] = value
        return True


settings = Settings()


def apply_to_theme():
    """Mutate pilot.theme colors for the configured chrome theme."""
    from . import theme
    if settings.get("theme") == "light":
        theme.PANEL        = (235, 237, 241)
        theme.PANEL_LINE   = (200, 204, 212)
        theme.TEXT         = (30, 34, 42)
        theme.TEXT_DIM     = (86, 94, 108)
        theme.TEXT_FAINT   = (122, 130, 144)
        theme.INPUT_BG     = (255, 255, 255)
        theme.INPUT_BORDER = (170, 178, 190)
        theme.TAB_ACTIVE   = (226, 230, 236)
        theme.TAB_INACTIVE = (214, 218, 226)
        theme.SELECT       = (186, 200, 222)
        theme.SELECT_FOC   = (168, 190, 222)
        theme.ROW_HOVER    = (205, 213, 224)
        theme.SCROLL_THUMB = (150, 160, 176)
        theme.ACCENT       = (51, 92, 140)
        theme.ACCENT_HOT   = (30, 70, 120)
        theme.LINK         = (26, 90, 160)
        theme.LINK_VISITED = (110, 84, 168)
        theme.BG           = (235, 237, 241)
    else:
        theme.PANEL        = (46, 51, 60)
        theme.PANEL_LINE   = (24, 27, 32)
        theme.TEXT         = (216, 222, 233)
        theme.TEXT_DIM     = (139, 147, 163)
        theme.TEXT_FAINT   = (100, 108, 122)
        theme.INPUT_BG     = (28, 31, 37)
        theme.INPUT_BORDER = (70, 78, 90)
        theme.TAB_ACTIVE   = (52, 58, 68)
        theme.TAB_INACTIVE = (38, 43, 51)
        theme.SELECT       = (76, 86, 106)
        theme.SELECT_FOC   = (59, 70, 89)
        theme.ROW_HOVER    = (52, 59, 71)
        theme.SCROLL_THUMB = (76, 86, 106)
        theme.ACCENT       = (94, 129, 172)
        theme.ACCENT_HOT   = (129, 161, 193)
        theme.LINK         = (114, 168, 218)
        theme.LINK_VISITED = (150, 120, 210)
        theme.BG           = (38, 42, 50)