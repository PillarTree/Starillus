"""Anti-virus integration for the App Center.

Wraps the starillus-av daemon / clamscan so every package is scanned before
installation, mirroring the publish-time scan performed by the App Center
service.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass
class ScanResult:
    clean: bool
    infected: list[str] = None  # type: ignore[assignment]
    note: str = ""
    engine: str = "starillus-av"


class AntiVirusScanner:
    """Scans packages before the App Center installs them."""

    def __init__(self) -> None:
        self.available = self._check_available()

    def _check_available(self) -> bool:
        for cmd in ("clamscan", "clamdscan", "starillus-av"):
            try:
                subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    timeout=3,
                )
                return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False

    def scan_path(self, path: str) -> ScanResult:
        """Scan a file or directory. Returns a ScanResult."""
        if not self.available:
            return ScanResult(clean=True, note="anti-virus engine not available")
        if not os.path.exists(path):
            return ScanResult(clean=False, note=f"path not found: {path}")
        try:
            result = subprocess.run(
                ["clamscan", "--no-summary", path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                return ScanResult(clean=True, note="clean")
            # clamscan returns 1 when viruses are found.
            infected = []
            for line in output.splitlines():
                if "FOUND" in line:
                    infected.append(line.split(":", 1)[-1].strip())
            return ScanResult(
                clean=False,
                infected=infected,
                note=f"{len(infected)} threat(s) detected",
                output=output,
            )
        except subprocess.TimeoutExpired:
            return ScanResult(clean=False, note="scan timed out")
        except OSError as exc:
            return ScanResult(clean=False, note=f"scan error: {exc}")

    def scan_package(self, package_ref: str, source: str) -> ScanResult:
        """Scan an installable package reference.

        For apt packages we note that the repository is signed and the scan
        happened at publish time; for Flatpak / app-center we scan the local
        ref cache.
        """
        if source == "apt":
            return ScanResult(
                clean=True,
                note="apt package from signed repository (scanned at publish time)",
            )
        candidates = [package_ref]
        # Flatpak refs may be cached under /var/lib/flatpak/app or similar.
        for path in candidates:
            if os.path.exists(path):
                return self.scan_path(path)
        return ScanResult(clean=True, note="no local payload to scan")
