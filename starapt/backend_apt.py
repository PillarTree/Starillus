"""apt backend: Debian packages via apt-get / dpkg."""

from __future__ import annotations

import subprocess


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def install(package: str) -> None:
    _run(["pkexec", "apt-get", "install", "-y", package])


def remove(package: str) -> None:
    _run(["pkexec", "apt-get", "remove", "-y", package])


def update() -> None:
    _run(["pkexec", "apt-get", "update"])


def upgrade() -> None:
    _run(["pkexec", "apt-get", "upgrade", "-y"])


def search(query: str) -> list[str]:
    result = subprocess.run(
        ["apt-cache", "search", "--names-only", query],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def list_installed() -> list[str]:
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package} ${Version}\n"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f"[apt] {line}" for line in result.stdout.splitlines() if line.strip()]
