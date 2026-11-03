# Starillus Anti-Virus (starillus-av)

The Starillus anti-virus daemon backs the App Center's anti-virus support. It
provides:

- **On-access scanning:** files written to disk are scanned as they arrive
  (downloads, Flatpak reflections, App Center installs).
- **Scheduled scans:** daily full-system scan (configurable).
- **ClamAV engine:** virus definitions are kept current through `clamav-freshclam`.
- **Quarantine:** infected files are moved to `/var/lib/starillus-av/quarantine`
  and the user is alerted through Pillarium notifications.

## Integration points

- **App Center:** every install is scanned before files are written.
- **Flatpak:** Flatpak installs are scanned before extraction.
- **APT:** `.deb` packages are scanned at publish time in the Starillus repo
  (packages are signed, so install-time scanning is optional).

## systemd units

See `../systemd/` for the `starillus-av.service` (daemon) and
`starillus-av-scan.timer` (daily scan) units.
