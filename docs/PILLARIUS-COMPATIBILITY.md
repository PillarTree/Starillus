# Starillus vs Pillarius compatibility

Starillus is a downstream derivative of Pillarius Desktop. This document maps
each Pillarius component to its Starillus equivalent and notes what changed.

## Component mapping

| Pillarius component | Starillus equivalent | Notes |
|---------------------|----------------------|-------|
| Pillarium 2.0 (window manager/shell) | Pillarium 2.0 (unchanged) | Starillus ships Pillarium 2.0 as its desktop shell. |
| Spacer (LightDM greeter) | Spacer 2.0 (customtkinter) | LightDM greeter rewritten with customtkinter instead of raw X11. |
| Cadet (companion apps/toolkit) | Cadet (unchanged) | Companion toolkit and small utilities. |
| Planet (package manager) | Planet (unchanged) | APT front-end for the desktop. |
| Planet Control Center (settings) | Planet Control Center (unchanged) | Desktop settings GUI. |
| Rocky (office suite) | LibreOffice | RockyWrite, RockyGraphite, RockySheet, RockyPresent removed; LibreOffice Writer, Calc, Impress, Draw, Base, Math ship instead. |
| Default browser (varies) | Pilot (Chromium fork) | Pilot is the Starillus default browser. |
| `pillarius-desktop` metapackage | `starillus-desktop` (proposed) | Meta-package pulling in Pillarius + Starillus additions. |
| — | Flatpak support | New in Starillus; not part of Pillarius. |
| — | Starillus App Center | New central app platform with anti-virus. |
| — | starillus-av anti-virus | New daemon backing App Center scanning. |

## What changed from Pillarius

1. **Browser.** Pillarius does not pin a specific browser; Starillus makes Pilot
   the default and ships `pilot.desktop`.
2. **Flatpak.** Pillarius does not enable Flatpak by default; Starillus installs
   `flatpak`, adds Flathub, and pre-installs a set of Flatpak runtimes/apps.
3. **App Center.** Pillarius relies on Planet/APT for package management.
   Starillus adds the Starillus App Center as a graphical central platform.
4. **Anti-virus.** Pillarius has no anti-virus; Starillus ships `starillus-av`
   and integrates it into the App Center and Flatpak install path.
5. **Office suite.** Pillarius ships the Rocky office suite (RockyWrite,
   RockyGraphite, RockySheet, RockyPresent). Starillus removes these unused
   apps and ships LibreOffice instead.
6. **Login greeter.** Pillarius ships Spacer 1.x written in pure Xlib/python-xlib.
   Starillus upgrades to Spacer 2.0, which is rebuilt with customtkinter for a
   modern, themeable login screen.
7. **Branding.** Starillus ships its own themes (`themes/starillus-dark`) and
   wallpapers (`wallpapers/`).

## Pillarium 2.0 app alignment

The Pillarius default config (`config.json` in the Pillarium repo) historically
pointed quick-launch and desktop icons at user-specific paths such as
`/home/sushipie314/.local/bin/rockywrite`. Starillus replaces these with
generic, system-wide `.desktop`-backed entries (Pilot, Terminal, App Center,
Settings) so the desktop works out of the box on any machine. See
`config/default-config.json`.
