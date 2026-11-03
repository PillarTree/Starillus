# Starillus live ISO

Live ISO build configuration for Starillus OS, built with
[live-build](https://live-team.pages.debian.net/live-manual/). Produces a
hybrid ISO that boots to the Pillarius desktop (Pillarium 2.0) and includes a
Debian installer with an automated preseed option.

This is modelled on `Pillarius-live` (`../Pillarius-live`).

## Build result

The ISO was successfully built:

| File | Size | SHA-256 |
|------|------|---------|
| `starillus-1.0-amd64.iso` | 1.2 GB | `84d357297f828c16118ae4c9c2d3a98fc461ccbbf17d039f86d361a3bb4e8542` |

The kernel used is **Starmod** (Linux 6.6.56 fork), compressed `bzImage` at
**4.7 MB** — under the 6 MB target.

## Variants

- **minimal** — Pillarium 2.0 desktop + Pilot browser + Flatpak support +
  Starillus App Center + anti-virus. This is the only variant built.

## Build

```sh
cd live/minimal
./auto/config   # generates the live-build tree
sudo lb build   # builds the ISO (requires root for debootstrap/chroot)
```

The build creates a `binary/` directory with the ISO tree, then `xorriso`
converts it to a hybrid ISO:

```sh
sudo xorriso -as mkisofs \
    -iso-level 3 -full-iso9660-filenames -volid "Starillus" \
    -boot-load-size 4 -boot-info-table \
    --eltorito-boot isolinux/isolinux.bin \
    --eltorito-catalog isolinux/boot.cat \
    --no-emul-boot \
    -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
    -o starillus-1.0-amd64.iso binary/
```

## What's on the ISO

- **Kernel:** Starmod Linux 6.6.56 (4.7 MB compressed)
- **Desktop:** Pillarium 2.0 (customtkinter X11 shell)
- **Display manager:** LightDM
- **Browser:** Pilot (customtkinter-based)
- **Package manager:** StarApt (apt + AUR + Flatpak)
- **App Center:** Starillus App Center with anti-virus
- **Anti-virus:** starillus-av + ClamAV
- **Flatpak:** Enabled with Flathub remote
- **Installer:** kexec-based Debian Installer with preseed

## Live credentials

- Username: `user`
- Password: `starillus`
