# Starillus installer

Graphical installation wizard for Starillus OS, modelled on `pillarius-installer`
(`../pillarius-installer`). It is a full-screen Python/Xlib wizard that walks the
user through user account, computer name, timezone, language/keyboard, appearance
(theme/wallpaper), software bundles and disk partitioning, then writes a Debian
installer preseed and boots it with kexec.

Starillus-specific steps:

1. **Software bundles** — choose whether to install the Starillus App Center and
   anti-virus, Flatpak support, and the Pilot browser.
2. **Appearance** — Starillus theme (`starillus-dark`) and wallpaper
   (`starillus-dawn`) are offered as defaults.

## Running

```sh
python3 -m starillus_installer
```
