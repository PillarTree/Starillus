# Starillus OS

A lightweight, Linux-based desktop operating system built on **Pillarius Desktop**
(which is itself assembled from **Pillarium 2.0**, the customtkinter X11 window
manager and desktop shell).

Starillus is designed to be small, fast and simple: a minimal base system, the
Pillarium desktop, the **Pilot** web browser (a Chromium fork), full **Flatpak**
support, and the **Starillus App Center** — a central place to browse and install
applications with built-in **anti-virus** scanning of every package before it is
installed.

## What Starillus is

| Property | Value |
|----------|-------|
| Base | Debian (stable) |
| Desktop | Pillarius Desktop (Pillarium 2.0 shell) |
| Window manager | Pillarium 2.0 (customtkinter, X11) |
| Package management | StarApt (apt + AUR + Flatpak) |
| Web browser | Pilot (Chromium fork) |
| Kernel | Starmod (Linux fork, <= 6 MB target) |
| App center | Starillus App Center (with anti-virus) |
| Init | systemd |
| Architectures | amd64, arm64 |

## Components

| Component | Directory | Description |
|-----------|-----------|-------------|
| Starillus App Center | `app-center/` | Graphical app store (APT/Flatpak) with anti-virus |
| StarApt package manager | `starapt/` | apt fork supporting AUR and Flatpak |
| Starmod kernel | `starmod/` | Linux fork stripped to <= 6 MB |
| Pilot browser | `pilot/` | Chromium fork (GN/Ninja build) |
| Antivirus daemon | `antivirus/` | starillus-av (ClamAV-backed) |
| Live ISO | `live/` | live-build configuration |
| Installer | `installer/` | graphical installer wizard |
| APT sources | `apt/` | Starillus repository sources |
| Flatpak remotes | `flatpak/` | Flathub configuration |
| Patches | `patches/pillarium/` | Pillarium 2.0 alignment patches |
| Themes | `themes/` | Starillus dark theme for Pillarium 2.0 |
| Config | `config/` | OS-wide and default Pillarium config |

## Features

- **Lightweight.** Pillarium 2.0 draws every surface with customtkinter and talks
  to the X server directly, so the desktop stays small and responsive.
- **CTK-based UI.** All shipped graphical applications use customtkinter:
  Pilot browser, Starillus App Center, Spacer 2.0 login greeter, and the
  Pillarium 2.0 shell itself. The unused Rocky office suite apps have been
  removed.
- **Package management.** StarApt wraps apt and adds AUR and Flatpak backends,
  so one tool installs `.deb`, AUR and Flatpak packages.
- **Pilot browser.** A fork of Chromium re-packaged as Pilot, the default web
  browser for Starillus.
- **Flatpak support.** Flatpak runtimes and applications are enabled out of the
  box, so Starillus can run Flatpak apps from Flathub or any other remote.
- **Starillus App Center.** A central graphical store for applications (similar
  to Ubuntu's App Center). Every application is scanned by the integrated
  anti-virus engine before it is published, and every install is re-scanned
  locally before the files are written to disk.
- **Anti-virus.** A resident anti-virus daemon scans downloads, Flatpak
  reflections and App Center packages, with real-time on-access scanning and
  scheduled full-system scans.
- **Starmod kernel.** A Linux fork stripped down to a <= 6 MB compressed
  `bzImage` target for fast boot and low memory footprint.

## Project layout

```
Starillus/
├── README.md              # this file
├── os-release             # /etc/os-release style identity file
├── config/                # Starillus OS-wide configuration
├── packages/              # package lists + starillus-desktop metapackage
├── app-center/            # Starillus App Center UI + anti-virus hooks
├── starapt/               # package manager fork (apt + AUR + Flatpak)
├── starmod/               # Linux kernel fork (<= 6 MB target)
├── pilot/                 # Pilot browser (Chromium fork)
├── antivirus/             # anti-virus daemon and scanning rules
├── live/                  # live ISO build configuration
├── installer/             # graphical installer
├── systemd/               # systemd units
├── themes/                # Starillus themes for Pillarium 2.0
├── wallpapers/            # Starillus wallpapers
├── docs/                  # additional documentation
└── patches/pillarium/     # patches applied to Pillarium 2.0 for Starillus
```

## Getting started

Starillus is assembled from Pillarius Desktop, so the quickest way to try it is
to install the `pillarius-desktop` metapackage from pt-apt-repo on top of a
Debian base, then layer the Starillus configuration, Pilot browser, Flatpak
support and the App Center on top:

```sh
# On a Debian base system
sudo apt install pillarius-desktop
sudo apt install flatpak
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

Then copy the Starillus config and themes into place:

```sh
sudo cp config/starillus.conf /etc/starillus/
sudo cp config/default-config.json /etc/skel/.pillarium/config.json
```

Install the App Center:

```sh
cd app-center
pip install -r requirements.txt   # customtkinter
python3 -m starillus_app_center
```

Build the Starmod kernel:

```sh
cd starmod
./build.sh fetch
./build.sh config
./build.sh
```

Build Pilot:

```sh
cd pilot
# see docs/FORKING.md
```

## Relationship to Pillarius

Starillus is a downstream derivative of Pillarius Desktop. Where Pillarius ships
the `pillarius-desktop` metapackage (Pillarium + Spacer + Cadet + Rocky office
suite), Starillus keeps that foundation and replaces the unused Rocky office
suite with LibreOffice, then adds:

- the **Pilot** browser in place of the default browser,
- **Flatpak** support,
- the **Starillus App Center** with anti-virus,
- **StarApt** package manager (apt + AUR + Flatpak),
- **Starmod** kernel fork (<= 6 MB target),
- Starillus-specific branding, themes and wallpapers.

See `docs/PILLARIUS-COMPATIBILITY.md` for the full mapping of Pillarius
components to Starillus equivalents.

## License

MIT. See the individual component directories for component-specific licenses.