# Starmod size target: <= 6 MB compressed bzImage

## Why 6 MB?

Starillus is designed to be lightweight. A smaller kernel means:
- Faster boot (less to decompress and load)
- Lower memory footprint at boot
- Smaller live ISO / installer image

## How we reach 6 MB

| Technique | Effect |
|-----------|--------|
| `CONFIG_EXPERT=y` + `CONFIG_BASE_SMALL` | exposes small-config options |
| Built-in only essential FS (ext4, squashfs, tmpfs) | most FS drivers become modules |
| Graphics/sound mostly modular | Pillarium X11 uses simplefb/vesa fallback |
| Minimal networking (TCP/IP + Bluetooth/Wi-Fi core) | drops exotic protocols |
| Aggressive compression (LZ4HC / XZ) | smallest bzImage |
| Module compression (ZSTD) | small on-demand modules |

## Measured expectations

A kernel built with `starmod_defconfig` on x86_64 typically produces:

- Uncompressed vmlinux: 8–12 MB
- Compressed bzImage: 3–6 MB (depending on LZ4HC vs XZ)

If the result exceeds 6 MB, reduce further by:
- Turning more drivers into modules (`=m`)
- Disabling unneeded architectures in `processor family`
- Removing SELinux/IMA/EVM integrity subsystems

## Building

```
./build.sh fetch
./build.sh config
./build.sh
ls -lh output/*.bzImage
```
