"""Application catalog: APT, Flatpak and Starillus App Center submissions."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class App:
    """A single installable application."""

    id: str
    name: str
    summary: str
    description: str
    category: str
    source: str  # "apt", "flatpak", "app-center"
    icon: str | None = None
    installed: bool = False
    size: str | None = None
    version: str | None = None
    antivirus_clean: bool = True
    antivirus_note: str = ""


class AppCatalog:
    """Aggregates applications from APT, Flatpak and the App Center."""

    def __init__(self) -> None:
        self.apps: list[App] = []

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def scan(self) -> list[App]:
        """Rebuild the catalog from all sources."""
        found: list[App] = []
        found.extend(self._scan_apt())
        found.extend(self._scan_flatpak())
        found.extend(self._scan_app_center())
        # Deduplicate by (name, source).
        seen: set[tuple[str, str]] = set()
        unique: list[App] = []
        for app in found:
            key = (app.name.lower(), app.source)
            if key in seen:
                continue
            seen.add(key)
            unique.append(app)
        self.apps = sorted(unique, key=lambda a: a.name.lower())
        return self.apps

    def _scan_apt(self) -> list[App]:
        """List installable packages from apt-cache (best effort)."""
        apps: list[App] = []
        try:
            result = subprocess.run(
                ["apt-cache", "search", "--names-only", "."],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return apps
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split(" - ", 1)
                name = parts[0].strip()
                summary = parts[1].strip() if len(parts) > 1 else ""
                installed = self._is_apt_installed(name)
                apps.append(
                    App(
                        id=name,
                        name=name,
                        summary=summary,
                        description=summary,
                        category=self._category_for(name),
                        source="apt",
                        installed=installed,
                    )
                )
        except (OSError, subprocess.SubprocessError):
            pass
        return apps

    def _scan_flatpak(self) -> list[App]:
        """List available Flatpak apps from configured remotes."""
        apps: list[App] = []
        try:
            result = subprocess.run(
                ["flatpak", "remote-list", "--no-aliases"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return apps
        except (OSError, subprocess.SubprocessError):
            return apps
        try:
            result = subprocess.run(
                ["flatpak", "search", "--limit=100", ""],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return apps
            lines = result.stdout.splitlines()
            # flatpak search output has a header + separator; skip them.
            for line in lines:
                line = line.strip()
                if not line or line.startswith("Name") or line.startswith("-"):
                    continue
                fields = [f.strip() for f in line.split("|")]
                if not fields:
                    continue
                app_id = fields[0] if len(fields) > 0 else ""
                name = fields[1] if len(fields) > 1 else app_id
                summary = fields[2] if len(fields) > 2 else ""
                if app_id:
                    installed = self._is_flatpak_installed(app_id)
                    apps.append(
                        App(
                            id=app_id,
                            name=name,
                            summary=summary,
                            description=summary,
                            category="Flatpak",
                            source="flatpak",
                            icon=app_id,
                            installed=installed,
                        )
                    )
        except (OSError, subprocess.SubprocessError):
            pass
        return apps

    def _scan_app_center(self) -> list[App]:
        """Starillus App Center curated submissions (stub: reads local index)."""
        apps: list[App] = []
        index_path = os.path.expanduser("~/.local/share/starillus/app-center/index.json")
        if not os.path.exists(index_path):
            return apps
        try:
            import json

            with open(index_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            for entry in data.get("apps", []):
                apps.append(
                    App(
                        id=str(entry.get("id", "")),
                        name=str(entry.get("name", "")),
                        summary=str(entry.get("summary", "")),
                        description=str(entry.get("description", "")),
                        category=str(entry.get("category", "App Center")),
                        source="app-center",
                        icon=entry.get("icon"),
                        antivirus_clean=bool(entry.get("antivirus_clean", True)),
                        antivirus_note=str(entry.get("antivirus_note", "")),
                    )
                )
        except (OSError, ValueError):
            pass
        return apps

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_apt_installed(package: str) -> bool:
        try:
            result = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}", package],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return "install ok installed" in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _is_flatpak_installed(app_id: str) -> bool:
        try:
            result = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return app_id in result.stdout
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _category_for(name: str) -> str:
        lowered = name.lower()
        if any(k in lowered for k in ("browser", "firefox", "chrome", "pilot")):
            return "Web"
        if any(k in lowered for k in ("office", "writer", "calc", "impress")):
            return "Office"
        if any(k in lowered for k in ("gimp", "inkscape", "image", "paint")):
            return "Graphics"
        if any(k in lowered for k in ("video", "vlc", "player")):
            return "Video"
        if any(k in lowered for k in ("music", "audio")):
            return "Audio"
        if any(k in lowered for k in ("terminal", "console")):
            return "System"
        if any(k in lowered for k in ("settings", "control-center")):
            return "Settings"
        return "Other"

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def search(self, query: str) -> list[App]:
        q = query.lower()
        return [app for app in self.apps if q in app.name.lower() or q in app.summary.lower()]

    def by_category(self, category: str) -> list[App]:
        return [app for app in self.apps if app.category == category]

    def categories(self) -> list[str]:
        return sorted({app.category for app in self.apps})

    def get(self, app_id: str, source: str) -> App | None:
        for app in self.apps:
            if app.id == app_id and app.source == source:
                return app
        return None
