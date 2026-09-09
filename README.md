# hyprmctl

Mission Control for Hyprland. Shows all open windows as live thumbnails in a
full-screen overlay, grouped by app. Click to focus.

## Architecture

- **Capture:** `grim` (wlr-screencopy) — per-window screenshot crops
- **Overlay:** GTK4 + `gtk4-layer-shell` — proper Wayland layer surface
- **Data:** `hyprctl clients -j` / `hyprctl monitors -j`
- **Focus:** `hyprctl dispatch focuswindow address:X`
- **Trigger:** keybind → `hyprctl dispatch exec hyprmctl`

## No Hyprland plugin API

Unlike hyprview, hyprmctl does NOT use the Hyprland plugin system.
It runs as a standalone process using only stable public interfaces.
This means it survives Hyprland updates.

## Vision

Exactly what macOS Mission Control does:
- All windows spread across the screen, floating over a dimmed background
- Scaled down to fit, preserving aspect ratios
- Grouped by app (windows of the same app cluster together)
- Click a window → it becomes focused, overlay closes
- Scoped to the active workspace + active monitor

No live window content needed — each "thumbnail" shows:
- The app icon (from .desktop file)
- The window title
- A coloured border matching the app (like a group indicator)

## Incremental Build Plan

### Phase 1 — Overlay shell (no content yet)
- [ ] GTK4 window with `gtk4-layer-shell` at overlay layer, full screen
- [ ] Dims the background (semi-transparent black overlay)
- [ ] Closes on Escape or click outside
- [ ] Triggered via `hyprctl dispatch exec hyprmctl`
- [ ] Hyprland keybind: `SUPER+SPACE`

### Phase 2 — Window data + layout
- [ ] Fetch windows for active workspace + active monitor via `hyprctl clients -j`
- [ ] Fetch monitor geometry via `hyprctl monitors -j`
- [ ] Implement grid layout that spreads windows preserving aspect ratios
- [ ] Group windows by app class (same class = same group, visually adjacent)
- [ ] Each tile shows: app icon + window title (no live content)
- [ ] App icon lookup from `.desktop` files / icon theme

### Phase 3 — Interaction
- [ ] Click a tile → `hyprctl dispatch focuswindow address:X` → close overlay
- [ ] Hover highlight
- [ ] Keyboard navigation (arrow keys between tiles, Enter to focus, Escape to close)
- [ ] Show group label (app name) above each cluster

### Phase 4 — Polish
- [ ] Scale-in animation when overlay opens
- [ ] Scale-out animation when closing
- [ ] Smooth tile positioning
- [ ] App grouping visual: subtle background behind each app's tiles
- [ ] Multi-monitor: separate overlay per monitor, triggered on focused monitor

### Phase 5 — Live thumbnails (optional, later)
- [ ] Replace solid-color tiles with `grim -g` screenshots
- [ ] Refresh on open (not live — snapshot at open time)

## TODO

- [ ] Check `gtk4-layer-shell` is installed
- [ ] Check `python3-gi` GTK4 bindings work
- [ ] Scaffold Phase 1 overlay window
