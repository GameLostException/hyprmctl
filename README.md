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

## Status

🚧 Initial development

## TODO

- [ ] Screenshot capture via grim per window
- [ ] GTK4 layer-shell overlay window
- [ ] Window thumbnail grid layout
- [ ] App grouping
- [ ] Click to focus
- [ ] Keyboard navigation (arrow keys, Enter, Escape)
- [ ] Animation (scale in/out)
- [ ] Multi-monitor support
- [ ] Hyprland keybind integration
