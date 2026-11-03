#!/usr/bin/env python3
"""Pilot — Starillus web browser entry point.

Attempts to launch the Chromium-based Pilot browser (built from src/).
Falls back to the original Python X11 pilot-ui if the Chromium build is not
available.
"""

from __future__ import annotations

import os
import subprocess
import sys


def _chromium_binary() -> str | None:
    """Locate a built Pilot/Chromium binary."""
    candidates = [
        os.path.expanduser("~/pilot/src/out/Release/pilot"),
        os.path.expanduser("~/pilot/src/out/Release/chrome"),
        "/usr/lib/starillus/pilot/pilot",
        "/usr/lib/pilot/pilot",
    ]
    for path in candidates:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    binary = _chromium_binary()

    if binary is not None:
        os.execv(binary, [binary] + argv)

    # Fallback: customtkinter-based Python Pilot (reference implementation).
    # Import in-process with sys.path set so relative imports resolve
    # regardless of the current working directory.
    pilot_ui_dir = os.path.join(os.path.dirname(__file__), "python_ui")
    if os.path.isdir(pilot_ui_dir) and os.path.exists(
        os.path.join(pilot_ui_dir, "__main__.py")
    ):
        sys.path.insert(0, os.path.dirname(__file__))
        from python_ui.__main__ import main as _pilot_ui_main

        return _pilot_ui_main(["pilot"] + argv)

    print(
        "Pilot: no Chromium build found and python_ui fallback is missing.\n"
        "Build Pilot with: gn gen out/Release && autoninja -C out/Release pilot\n"
        "Or ensure pilot/python_ui/ contains the customtkinter Pilot package.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
