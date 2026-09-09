# hyprmctl

Mission Control for Hyprland — macOS-style window overview as a full-screen overlay.

Windows are grouped into stacks by app. Each stack explodes outward on hover,
revealing all windows individually. Click any window to focus it.

![status](https://github.com/GameLostException/hyprmctl/actions/workflows/ci.yml/badge.svg)

---

## Features

- **Stack-based layout** — each app class occupies an equal-area cell (squarified treemap)
- **Fanned stacks** — multiple windows of the same app fan slightly so the group is visible
- **Radial explosion on hover** — windows animate outward from the app icon into available
  screen space; direction driven by cell position (corner → 90°, edge → 180°, center → 360°)
- **App icons** — resolved from GTK icon theme + `.desktop` files, initials fallback
- **Click to focus** — works in all Hyprland layouts including monocle
- **Keyboard navigation** — arrow keys / hjkl, Enter to focus, Escape to close
- **Multi-monitor** — overlay pins to the active monitor
- **No Hyprland plugin API** — uses only stable public interfaces; survives compositor updates

---

## Usage

### Trigger

```
SUPER+SPACE
```

Configured in `~/.config/hypr/hyprland.conf`:

```
bind = $mod, SPACE, exec, python3 /home/boris/Lab/hyprmctl/hyprmctl.py
```

### Controls

| Action | Keys / Mouse |
|--------|-------------|
| Open | `SUPER+SPACE` |
| Focus window | Click tile, or `Enter` |
| Navigate | Arrow keys / `hjkl` |
| Close without focusing | `Escape` or click background |
| Expand stack | Hover over any tile in the stack |
| Collapse stack | Move cursor away (200ms debounce) |

---

## Architecture

```
hyprmctl.py          ← entry point; re-execs with LD_PRELOAD for gtk4-layer-shell
src/
  app.py             ← Gtk.Application subclass
  overlay.py         ← MissionControlOverlay: layer-shell window, stack management,
                        explosion animation, hover/focus logic
  layout.py          ← pure geometry: squarified treemap → fanned stacks
  hypr.py            ← hyprctl IPC: clients, monitors, active workspace
  icons.py           ← GTK IconTheme + .desktop index → icon name resolution
  tiles.py           ← TileWidget: icon + app class + title, per-app HSL colour
tests/
  test_hypr.py
  test_icons.py
  test_interaction.py
  test_layout.py
  test_tiles.py
  fixtures/
    clients.json     ← real hyprctl output
    monitors.json
.github/workflows/
  ci.yml             ← lint (ruff) + test (pytest) on Python 3.11 & 3.12
```

### Key design decisions

**gtk4-layer-shell preload** — the library must be loaded before `libwayland-client`.
`hyprmctl.py` detects the missing preload and re-execs itself via `os.execv` with
`LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so` set.

**KeyboardMode.ON_DEMAND** — using `EXCLUSIVE` causes Hyprland to save the previously
focused window and restore it on surface destruction, clobbering any `focuswindow`
dispatch. `ON_DEMAND` avoids this; keyboard events (Escape, arrows, Enter) still work.

**Focus + movecursor** — `follow_mouse=1` refocuses whatever window is under the cursor
when a surface is destroyed. We dispatch `movecursor <cx> <cy>` to the target window
center before `focuswindow`, so the cursor is already over the right window when the
overlay closes.

**_built guard on `_on_mapped`** — the layer-shell `map` signal can fire multiple times.
A boolean guard ensures stacks are only built once.

**Stack hover with _hover_count** — each stack tracks how many of its widgets are under
the cursor. Moving between icon and tiles within the same stack never triggers a collapse.
A 200ms debounce handles brief cursor gaps.

---

## Dependencies

### Runtime (system packages)

| Package | Purpose |
|---------|---------|
| `python-gobject` | PyGObject / GI bindings |
| `gtk4` | GTK4 toolkit |
| `gtk4-layer-shell` | Wayland layer surface (includes `Gtk4LayerShell-1.0` GIR) |

All available via `pacman` on Arch/Hyprland.

### Dev / CI

```
pytest>=8.0
pytest-cov>=5.0
ruff>=0.4
```

Install via `pipx install ruff` and system `pytest`.

---

## Running tests

```bash
cd ~/Lab/hyprmctl
GDK_BACKEND=offscreen python3 -m pytest tests/ -v --cov=src --cov-report=term-missing
```

CI runs automatically on every push via GitHub Actions (lint + test, Python 3.11 & 3.12).

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Overlay shell | ✅ | GTK4 layer-shell overlay, Escape/click-to-close |
| 2 — Window tiles | ✅ | Live hyprctl data, coloured tiles, keyboard nav |
| 3 — Interaction | ✅ | Click-to-focus (all layouts), hover highlight, keyboard nav |
| 4 — Polish | ✅ | App icons, fade-in animation, multi-monitor |
| 5.1 — Stack layout | ✅ | Squarified treemap, fanned stacks, radial explosion |
| 5.2 — Window state | 🔲 | Floating / fullscreen / hidden windows, state restore on close |
| 6 — Live thumbnails | 🔲 | `grim -g` per-window screenshots, refresh loop |
| 7 — Fly-in / fly-back | 🔲 | Windows animate from real positions, back on click |
