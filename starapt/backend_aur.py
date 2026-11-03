"""AUR backend: Arch User Repository packages via makepkg.

Requires the Arch toolchain (base-devel, git, makepkg) and an AUR helper or
manual clone+build. StarApt clones the AUR Git repo and builds with makepkg.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

AUR_BASE = "https://aur.archlinux.org"


def _run(cmd: list[str], cwd: str | None = None) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=cwd)


def install(package: str) -> None:
    repo_url = f"{AUR_BASE}/{package}.git"
    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = os.path.join(tmp, package)
        _run(["git", "clone", "--depth", "1", repo_url, clone_dir])
        # Build and install. makepkg -si needs root; use pkexec if available.
        makepkg = ["makepkg", "-si", "--noconfirm"]
        try:
            _run(makepkg, cwd=clone_dir)
        except FileNotFoundError:
            # Fall back to running makepkg under pkexec for the -si step.
            _run(["pkexec", "pacman", "-U", "--noconfirm"] + [os.path.join(clone_dir, "*.pkg.tar.zst")], cwd=clone_dir)


def remove(package: str) -> None:
    _run(["pkexec", "pacman", "-Rns", "--noconfirm", package])


def update() -> None:
    # AUR has no package lists to refresh; just sync the AUR git index locally.
    pass


def upgrade() -> None:
    _run(["pkexec", "pacman", "-Syu", "--noconfirm"])


def search(query: str) -> list[str]:
    # Query the AUR RPC interface.
    import json
    import urllib.request

    url = f"{AUR_BASE}/rpc/?v=5&type=search&arg={query}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = []
        for res in data.get("results", []):
            results.append(f"[aur] {res.get('Name', '')} — {res.get('Description', '')}")
        return results
    except Exception:
        return []


def list_installed() -> list[str]:
    result = subprocess.run(
        ["pacman", "-Qm"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f"[aur] {line}" for line in result.stdout.splitlines() if line.strip()]
