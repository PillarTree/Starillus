# Starmod — Starillus Linux kernel fork

Starmod is Starillus's fork of the Linux kernel, stripped down to a minimal
size target of **6 MB or less** (compressed `bzImage`) for fast boot and low
memory footprint on the Pillarium desktop.

## Status

Starmod is a **kernel configuration and patch set** built on top of the
official Linux stable sources. The full kernel source is not stored here; the
build script clones/checks out a specific Linux stable version and applies the
Starmod defconfig and patches.

> **Size reality check:** A general-purpose Linux kernel that boots to a
> desktop with modules loaded on demand can approach ~6 MB compressed with an
> extremely aggressive `.config` (no built-in drivers, minimal subsystems,
> `CONFIG_MODPROBE_PATH`, etc.). Removing all loadable-module support and
> building only what Pillarium 2.0 needs gets closest to the target. Starmod
> ships with `modprobe` + initramfs modules as the practical compromise: a
> ~6–10 MB compressed kernel plus small on-demand modules.

## Getting the source

```
./build.sh fetch          # clone Linux stable (v6.6 LTS recommended)
./build.sh config         # apply starmod_defconfig
./build.sh menuconfig     # tune interactively (optional)
./build.sh                # build bzImage
```

## What is stripped

- All filesystem drivers except `ext4`, `squashfs`, `f2fs` and `tmpfs`
- All network protocols except TCP/IP (IPv4/IPv6) and Bluetooth/Wi-Fi core
- Sound, graphics (DRM/KMS), and GPU drivers removed (Pillarium uses X11 on
  simplefb/vesa fallback; GPU drivers are optional modules)
- All unused architectures, file systems, crypto algorithms, and device
  classes
- Kernel same-page merging, hibernation, swapping (zswap/zram kept optional)

## Build output

```
output/linux-starmod-<version>-amd64.bzImage   # compressed kernel (~6 MB target)
output/linux-starmod-<version>-amd64.map       # symbol map
```

## Patches

See `patches/` for Starmod-specific patches (boot logo removal, console
loglevel reduction, Pillarium-friendly X11/EFI framebuffer defaults).
