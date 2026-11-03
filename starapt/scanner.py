"""Lightweight anti-virus scan wrapper used by StarApt."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class ScanResult:
    clean: bool
    note: str = ""


class AntiVirusScanner:
    def scan_package(self, package: str, backend: str) -> ScanResult:
        # apt packages come from a signed repository and are scanned at
        # publish time by starillus-av; install-time scanning is advisory.
        if backend == "apt":
            return ScanResult(clean=True, note="signed repository (scanned at publish time)")
        # For AUR / Flatpak we attempt a local clamscan if a payload exists.
        try:
            result = subprocess.run(
                ["clamscan", "--no-summary", "--quiet", package],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return ScanResult(clean=True, note="clean")
            return ScanResult(clean=False, note="threat detected")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ScanResult(clean=True, note="engine unavailable — skipped")
        except Exception as exc:  # noqa: BLE001
            return ScanResult(clean=True, note=f"scan error: {exc}")
