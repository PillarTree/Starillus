#!/usr/bin/env python3
"""StarApt — Starillus package manager.

A fork of apt's user-facing workflow supporting Debian packages (.deb), AUR
packages and Flatpak, with anti-virus scanning of every install.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional

from . import backend_apt, backend_aur, backend_flatpak, scanner


def _detect_backend(package: str, force: Optional[str]) -> str:
    if force:
        return force
    # Flatpak refs contain a slash or reverse-domain notation.
    if "/" in package and not package.startswith("-"):
        return "flatpak"
    # AUR packages commonly end in -bin, -git or are known AUR names.
    if package.endswith(("-bin", "-git", "-dkms")):
        return "aur"
    return "apt"


def cmd_install(args: argparse.Namespace) -> int:
    scanner_ = scanner.AntiVirusScanner()
    failures = 0
    for package in args.package:
        backend = _detect_backend(package, args.backend)
        # Anti-virus scan (best-effort; apt packages are scanned at publish time).
        result = scanner_.scan_package(package, backend)
        if not result.clean:
            print(f"[starapt] blocked {package}: {result.note}", file=sys.stderr)
            failures += 1
            continue
        try:
            if backend == "apt":
                backend_apt.install(package)
            elif backend == "aur":
                backend_aur.install(package)
            else:
                backend_flatpak.install(package)
            print(f"[starapt] installed {package} ({backend})")
        except Exception as exc:  # noqa: BLE001
            print(f"[starapt] failed to install {package}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def cmd_remove(args: argparse.Namespace) -> int:
    failures = 0
    for package in args.package:
        backend = _detect_backend(package, args.backend)
        try:
            if backend == "apt":
                backend_apt.remove(package)
            elif backend == "aur":
                backend_aur.remove(package)
            else:
                backend_flatpak.remove(package)
            print(f"[starapt] removed {package} ({backend})")
        except Exception as exc:  # noqa: BLE001
            print(f"[starapt] failed to remove {package}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def cmd_update(args: argparse.Namespace) -> int:
    failures = 0
    if args.backend in (None, "apt"):
        try:
            backend_apt.update()
            print("[starapt] apt package lists updated")
        except Exception as exc:  # noqa: BLE001
            print(f"[starapt] apt update failed: {exc}", file=sys.stderr)
            failures += 1
    if args.backend in (None, "flatpak"):
        try:
            backend_flatpak.update()
            print("[starapt] flatpak remotes updated")
        except Exception as exc:  # noqa: BLE001
            print(f"[starapt] flatpak update failed: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    try:
        if args.backend in (None, "apt"):
            backend_apt.upgrade()
        if args.backend in (None, "flatpak"):
            backend_flatpak.upgrade()
        print("[starapt] upgrade complete")
    except Exception as exc:  # noqa: BLE001
        print(f"[starapt] upgrade failed: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    results = []
    if args.backend in (None, "apt"):
        results.extend(backend_apt.search(args.query))
    if args.backend in (None, "aur"):
        results.extend(backend_aur.search(args.query))
    if args.backend in (None, "flatpak"):
        results.extend(backend_flatpak.search(args.query))
    for line in results:
        print(line)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    lines = []
    if args.backend in (None, "apt"):
        lines.extend(backend_apt.list_installed())
    if args.backend in (None, "aur"):
        lines.extend(backend_aur.list_installed())
    if args.backend in (None, "flatpak"):
        lines.extend(backend_flatpak.list_installed())
    for line in lines:
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="starapt", description="Starillus package manager (apt + AUR + Flatpak)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("package", nargs="+", help="Package(s) to operate on")
        p.add_argument("--apt", dest="backend", action="store_const", const="apt", help="Use apt backend")
        p.add_argument("--aur", dest="backend", action="store_const", const="aur", help="Use AUR backend")
        p.add_argument("--flatpak", dest="backend", action="store_const", const="flatpak", help="Use Flatpak backend")

    p_install = sub.add_parser("install", help="Install package(s)")
    add_common(p_install)
    p_install.set_defaults(func=cmd_install)

    p_remove = sub.add_parser("remove", help="Remove package(s)")
    add_common(p_remove)
    p_remove.set_defaults(func=cmd_remove)

    p_update = sub.add_parser("update", help="Refresh package lists")
    p_update.add_argument("--apt", dest="backend", action="store_const", const="apt")
    p_update.add_argument("--flatpak", dest="backend", action="store_const", const="flatpak")
    p_update.set_defaults(func=cmd_update)

    p_upgrade = sub.add_parser("upgrade", help="Upgrade all packages")
    p_upgrade.add_argument("--apt", dest="backend", action="store_const", const="apt")
    p_upgrade.add_argument("--flatpak", dest="backend", action="store_const", const="flatpak")
    p_upgrade.set_defaults(func=cmd_upgrade)

    p_search = sub.add_parser("search", help="Search for a package")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--apt", dest="backend", action="store_const", const="apt")
    p_search.add_argument("--aur", dest="backend", action="store_const", const="aur")
    p_search.add_argument("--flatpak", dest="backend", action="store_const", const="flatpak")
    p_search.set_defaults(func=cmd_search)

    p_list = sub.add_parser("list", help="List installed packages")
    p_list.add_argument("--installed", action="store_true", default=True)
    p_list.add_argument("--apt", dest="backend", action="store_const", const="apt")
    p_list.add_argument("--aur", dest="backend", action="store_const", const="aur")
    p_list.add_argument("--flatpak", dest="backend", action="store_const", const="flatpak")
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
