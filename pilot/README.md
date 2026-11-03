# Pilot — Starillus web browser (Chromium fork)

Pilot is Starillus's fork of the Chromium web browser. It is the default
browser for Starillus OS, with a customtkinter-based Python reference
implementation as the fallback when the Chromium build is unavailable.

## Project structure

```
pilot/
├── README.md                 # this file
├── pilot.py                  # entry point (launches the Chromium-based browser)
├── src/                      # Chromium source (checked out separately; see DEPS)
├── build/                    # Chromium GN/Ninja build configuration
│   └── args.gn               # Starmod/Starillus build flags
├── DEPS                      # Chromium dependency manifest
├── patches/                  # Pilot-specific Chromium patches
│   └── 0001-starillus-branding.patch
├── docs/
│   └── FORKING.md            # how to fork Chromium for Pilot
└── python_ui/                # reference Python browser UI (customtkinter-based)
    └── ...
```

## Building Pilot

Pilot is built with Chromium's GN/Ninja toolchain:

```
# 1. Fetch depot_tools (Chromium's toolchain)
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git

# 2. Fetch Chromium source (this is large, several GB)
fetch --no-history chromium

# 3. Apply Pilot patches
cd src
git apply ../patches/0001-starillus-branding.patch

# 4. Generate build files
gn gen out/Release --args="import(\"//pilot/build/args.gn\")"

# 5. Build
autoninja -C out/Release pilot
```

## Relationship to the original Python Pilot

The original Pilot was a hand-rolled browser written in pure Python
(HTML/CSS/JS engine, layout, networking). It now uses **customtkinter** for its
window and event loop (instead of raw X11), while keeping the same software
rendering engine (Pillow framebuffer → CTkImage). That implementation lives
under `python_ui/` and is the fallback when the Chromium-based build is not
available. The Chromium-based Pilot is the production browser for Starillus.

## Branding patch

`patches/0001-starillus-branding.patch` renames Chromium to Pilot, changes the
default user agent, and sets Starillus as the default homepage/search provider.
