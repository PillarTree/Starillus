"""Flatpak backend: Flatpak apps/runtimes from Flathub and other remotes."""

from __future__ import annotations

import subprocess


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def install(ref: str) -> None:
    _run(["pkexec", "flatpak", "install", "-y", "flathub", ref])


def remove(ref: str) -> None:
    _run(["pkexec", "flatpak", "uninstall", "-y", ref])


def update() -> None:
    _run(["pkexec", "flatpak", "update", "-y"])


def upgrade() -> None:
    update()


def search(query: str) -> list[str]:
    result = subprocess.run(
        ["flatpak", "search", query],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    lines = [f"[flatpak] {line.strip()}" for line in result.stdout.splitlines() if line.strip()]
    # Drop header/separator lines.
    return [l for l in lines if not l.startswith("[flatpak] Name") and not l.startswith("[flatpak] --")]


def list_installed() -> list[str]:
    result = subprocess.run(
        ["flatpak", "list", "--app", "--columns=name,version"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f"[flatpak] {line}" for line in result.stdout.splitlines() if line.strip()]
