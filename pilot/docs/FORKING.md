# Forking Chromium for Pilot

Pilot is a downstream fork of Chromium. This document describes the workflow.

## 1. Install depot_tools

```
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH="$PATH:$(pwd)/depot_tools"
```

## 2. Fetch Chromium source

```
fetch --no-history chromium
cd src
```

This downloads several gigabytes of source. Use `--no-history` to keep it
smaller.

## 3. Apply Pilot patches

```
git apply ../pilot/patches/0001-starillus-branding.patch
```

## 4. Generate build files with Pilot GN args

```
gn gen out/Release --args='import("//pilot/build/args.gn")'
```

## 5. Build

```
autoninja -C out/Release pilot
```

## 6. Install

Copy `out/Release/pilot` to `/usr/lib/starillus/pilot/pilot` and ship the
`pilot.desktop` file from `pilot/pilot.desktop`.

## Note on the original Python Pilot

The original hand-rolled X11 browser (../Pilot) is preserved under
`pilot/python_ui/` as a reference implementation and fallback. It now uses
customtkinter for its window and event loop instead of raw X11, while keeping
the same software rendering engine (Pillow framebuffer → CTkImage). It is
useful on systems where building Chromium is not feasible.
