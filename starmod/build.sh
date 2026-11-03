#!/bin/sh
# Starmod kernel build script.
# Builds a stripped-down Linux kernel targeting <= 6 MB compressed bzImage.
set -eu

KERNEL_VERSION="${KERNEL_VERSION:-6.6.56}"
KERNEL_DIR="linux-${KERNEL_VERSION}"
TARBALL="linux-${KERNEL_VERSION}.tar.xz"
DOWNLOAD_URL="https://cdn.kernel.org/pub/linux/kernel/v6.x/${TARBALL}"
OUTPUT="output"
CONFIG_FILE="config/starmod_defconfig"

ARCH="${ARCH:-$(uname -m)}"
JOBS="${JOBS:-$(nproc)}"

case "$1" in
  fetch)
    if [ ! -d "$KERNEL_DIR" ]; then
      echo "[starmod] fetching Linux ${KERNEL_VERSION}…"
      if [ ! -f "$TARBALL" ]; then
        curl -L -o "$TARBALL" "$DOWNLOAD_URL"
      fi
      tar xf "$TARBALL"
    fi
    ;;
  config)
    if [ ! -d "$KERNEL_DIR" ]; then
      echo "[starmod] run './build.sh fetch' first" >&2
      exit 1
    fi
    echo "[starmod] applying starmod_defconfig…"
    cp "$CONFIG_FILE" "$KERNEL_DIR/.config"
    make -C "$KERNEL_DIR" ARCH="$ARCH" olddefconfig
    ;;
  menuconfig)
    if [ ! -d "$KERNEL_DIR" ]; then
      echo "[starmod] run './build.sh fetch' first" >&2
      exit 1
    fi
    make -C "$KERNEL_DIR" ARCH="$ARCH" menuconfig
    cp "$KERNEL_DIR/.config" "$CONFIG_FILE"
    ;;
  build|"")
    if [ ! -d "$KERNEL_DIR" ]; then
      echo "[starmod] run './build.sh fetch' first" >&2
      exit 1
    fi
    mkdir -p "$OUTPUT"
    echo "[starmod] building kernel (${JOBS} jobs)…"
    make -C "$KERNEL_DIR" ARCH="$ARCH" -j"$JOBS" bzImage
    cp "$KERNEL_DIR/arch/$ARCH/boot/bzImage" "$OUTPUT/linux-starmod-${KERNEL_VERSION}-${ARCH}.bzImage"
    cp "$KERNEL_DIR/System.map" "$OUTPUT/linux-starmod-${KERNEL_VERSION}-${ARCH}.map"
    cp "$KERNEL_DIR/.config" "$OUTPUT/linux-starmod-${KERNEL_VERSION}-${ARCH}.config"
    echo "[starmod] done: $OUTPUT/linux-starmod-${KERNEL_VERSION}-${ARCH}.bzImage"
    ls -lh "$OUTPUT"/*.bzImage
    ;;
  modules_install)
    make -C "$KERNEL_DIR" ARCH="$ARCH" -j"$JOBS" modules_install
    ;;
  clean)
    rm -rf "$OUTPUT" linux-*.tar.xz "linux-${KERNEL_VERSION}"
    ;;
  *)
    echo "Usage: $0 {fetch|config|menuconfig|build|modules_install|clean}"
    exit 1
    ;;
esac
