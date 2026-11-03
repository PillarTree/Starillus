# Patches applied to Pillarium 2.0 for Starillus

These patches align the Pillarius apps and the Pillarium default configuration
with Pillarium 2.0.

## 0001-align-default-config-with-pillarium-2.0

**File patched:** `pillarium/defaults/config.json` (in the Pillarium repository)

**Problem:** The Pillarius default config pointed quick-launch and desktop icons
at user-specific paths such as
`/home/sushipie314/.local/bin/rockywrite`, which only work on the original
developer's machine and do not ship a working desktop out of the box.

**Fix:** Replace those hardcoded user paths with generic, system-wide
`.desktop`-backed entries that work on any machine:

- `pilot` (Pilot browser, the Starillus default) replaces the browser entry
- `xterm` terminal
- `starillus-app-center` (Starillus App Center with anti-virus)
- `planet-control-center` (desktop settings)

The desktop icons are likewise changed to Pilot, Terminal and App Center. This
makes the Pillarium 2.0 launcher (`Alt+Space`) and taskbar useful immediately
after install, and is the config shipped by Starillus as
`config/default-config.json`.

**How to apply:** copy `config/default-config.json` from this Starillus tree to
`pillarium/defaults/config.json` in the Pillarium repository, or apply the
equivalent key/value changes by hand.

## Scope note

Starillus does not modify the Pillarium window-manager core. Pillarium 2.0 is
shipped unchanged as the Starillus desktop shell; only the default application
configuration (which apps are pinned and shown) is adjusted so Pillarius apps
match the Pillarium 2.0 desktop.
