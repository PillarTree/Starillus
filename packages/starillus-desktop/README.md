# starillus-desktop metapackage

Installs the complete Starillus desktop in one step:

```
sudo apt install starillus-desktop
```

Depends on `pillarium (>= 2.0.0)` — this is the key alignment with Pillarium 2.0:
the previous Pillarius metapackage depended on `pillarium (>= 1.0.0)`, so this
updates the dependency to require the 2.0 shell.

Starillus-specific additions over the Pillarius metapackage:

- `libreoffice` — LibreOffice office suite (replaces the unused Rocky office suite)
- `pilot` — Pilot web browser (Chromium fork)
- `flatpak` + `flatpak-xdg-utils` — Flatpak support
- `starillus-app-center` — central app platform with anti-virus
- `starillus-av` — resident anti-virus daemon
Build:

```
./build_deb.sh   # or: dpkg-buildpackage -b -uc -us
```
