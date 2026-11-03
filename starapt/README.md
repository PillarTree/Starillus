# StarApt — Starillus package manager

A fork of apt's user-facing workflow that supports **Debian packages** (apt),
**AUR** (Arch User Repository) and **Flatpak** in a single command-line tool.

StarApt is not a replacement for libapt; it is a Python front-end that:

- installs/removes/updates `.deb` packages via `apt-get` / `dpkg`
- builds and installs AUR packages via `makepkg` + `pacman` (Arch toolchain
  present on the system)
- installs Flatpak apps/runtimes from Flathub or any remote
- runs every install through the Starillus anti-virus scanner first

## Usage

```
starapt install <package>...        # install (auto-detects apt / aur / flatpak)
starapt remove <package>...         # remove
starapt update                      # refresh package lists
starapt upgrade                     # upgrade all packages
starapt search <query>              # search all sources
starapt list --installed            # list installed packages
starapt install --aur <pkg>         # force AUR backend
starapt install --flatpak <ref>     # force Flatpak backend
starapt install --apt <pkg>         # force apt backend
```

## Backends

| Backend | Command | Source |
|---------|---------|--------|
| apt | `apt-get install` | Debian/Starillus repositories |
| aur | `makepkg -si` | AUR (https://aur.archlinux.org) |
| flatpak | `flatpak install` | Flathub / configured remotes |

## Anti-virus

Every package is scanned by `starillus-av` before installation, matching the
App Center's publish-time scan.

## Installation

```
pip install -r requirements.txt
sudo cp starapt /usr/bin/starapt
sudo chmod +x /usr/bin/starapt
```
