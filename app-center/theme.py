"""Theme integration for the Starillus App Center.

Reads Pillarium 2.0 theme tokens so the App Center matches the desktop
shell exactly (colours, radius, fonts).
"""

from __future__ import annotations

import json
import os
from typing import Any

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - customtkinter may be absent at import
    ctk = None  # type: ignore


class AppCenterTheme:
    """Token-based theme for the App Center, synced with Pillarium 2.0."""

    def __init__(self, theme_path: str | None = None):
        self.path = theme_path or self._default_theme_path()
        self._tokens: dict[str, Any] = self._load()

    @staticmethod
    def _default_theme_path() -> str:
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, ".pillarium", "themes", "starillus-dark.json"),
            os.path.join(home, ".config", "starillus", "theme.json"),
            "/usr/share/starillus/themes/starillus-dark.theme.json",
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return ""

    def _load(self) -> dict[str, Any]:
        if not self.path or not os.path.exists(self.path):
            return self._fallback()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data.get("colors", data)
        except (OSError, ValueError):
            return self._fallback()

    @staticmethod
    def _fallback() -> dict[str, Any]:
        return {
            "background": "#0f1115",
            "surface": "#1a1d23",
            "surface_alt": "#252933",
            "panel": "#16181d",
            "panel_hover": "#2a2e3a",
            "accent": "#7b2cbf",
            "accent_hover": "#9b4eda",
            "border": "#3a3f4b",
            "border_strong": "#545a6b",
            "text": "#e8eaf0",
            "text_dim": "#9aa0ae",
            "text_faint": "#6b707e",
            "success": "#2ecc71",
            "warning": "#f1c40f",
            "error": "#e74c3c",
            "info": "#3498db",
        }

    def get(self, key: str, default: str = "#ffffff") -> str:
        return str(self._tokens.get(key, default))

    def apply_to_ctk(self) -> None:
        """Apply the theme to customtkinter's global appearance."""
        if ctk is None:
            return
        mode = "dark"  # Starillus default theme is dark
        ctk.set_appearance_mode(mode)
        ctk.set_default_color_theme("blue")


THEME = AppCenterTheme()
