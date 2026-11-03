# Starillus App Center

A graphical central platform for browsing and installing applications — similar
to the Ubuntu App Center — with built-in anti-virus scanning of every package
before installation.

## Supported sources

- **APT** (Debian packages from the Starillus / pt-apt-repo repository)
- **Flatpak** (Flathub and other configured remotes)
- **App Center** (Starillus-curated submissions, scanned at publish time)

## Anti-virus

Every install is scanned by `starillus-av` (ClamAV-backed) before files are
written to disk. Infected packages are blocked and the user is alerted.

## Running

```sh
python3 -m starillus_app_center        # from the app-center directory
starillus-app-center                   # once installed (see packaging)
```

The App Center reads the Pillarium 2.0 theme tokens so it matches the desktop
shell exactly. It appears in the Pillarium launcher (`Alt+Space`) and can be
pinned to the taskbar through the standard "Add to Quick Launch" flow.

## Packaging

A Debian package (`starillus-app-center`) ships this directory as
`/opt/starillus/app-center` with a wrapper script at `/usr/bin/starillus-app-center`.
