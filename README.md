# hyprmctl

macOS Mission Control for Hyprland — full-screen window overview as a GTK4 layer-shell overlay.

Windows are grouped by app into stacks. Hover a stack to explode it radially, revealing all windows individually. Click any window to focus it.

```
SUPER+SPACE → overlay opens → hover Firefox stack → 4 windows fan out → click one → overlay closes, window focused
```

![CI](https://github.com/GameLostException/hyprmctl/actions/workflows/ci.yml/badge.svg)

---

## What it does

- **Stack layout** — each app class occupies its own equal-area cell (squarified treemap). Multiple windows of the same app fan slightly so the stack is visible.
- **Radial explosion on hover** — windows animate outward from the app icon. Direction adapts to cell position: corner stacks explode inward (90°), edge stacks get 180°, center stacks get full 360°.
- **Spring physics animation** — stiff spring for pop-out, overdamped for snap-back. Mid-animation reversals are smooth (velocity preserved).
- **Window thumbnails** — live screenshots shown in tiles (via `hyprshot`, a small C helper). Tiles fall back to a coloured card with app icon while thumbnails are being captured.
- **App icons** — resolved from GTK icon theme + `.desktop` files, initials fallback.
- **Click to focus** — works in all Hyprland layouts including monocle.
- **Keyboard navigation** — arrow keys / `hjkl`, `Enter` to focus, `Escape` to close.
- **Multi-monitor** — overlay pins to the active monitor.
- **No Hyprland plugin API** — uses only stable public interfaces; survives compositor updates.

---

## How it works

hyprmctl runs as a **persistent background daemon**. The daemon stays alive between overlay openings, keeping a warm thumbnail cache so tiles show screenshots immediately.

```
exec-once = python3 hyprmctl.py        # start daemon at login
bind = $mod, SPACE, exec, python3 REPO_PATH/hyprmctl.py --show   # open overlay
```

When `--show` is sent, the daemon opens the overlay window. When the overlay closes (click or Escape), the daemon keeps running. Thumbnails continue to be captured in the background.

---

## Requirements

### System packages

| Package | Arch | Purpose |
|---------|------|---------|
| `python-gobject` | `python-gobject` | PyGObject / GI bindings |
| `gtk4` | `gtk4` | GTK4 toolkit |
| `gtk4-layer-shell` | `gtk4-layer-shell` | Wayland layer surface |
| `wayland-client` | `wayland` | Required to build hyprshot |
| `libpng` | `libpng` | Required to build hyprshot |
| `pkg-config` | `pkgconf` | Required to build hyprshot |
| `gcc` | `gcc` | Required to build hyprshot |

```bash
# Arch Linux
sudo pacman -S python-gobject gtk4 gtk4-layer-shell wayland libpng pkgconf gcc
```

### Python — no pip required

No pip dependencies. All runtime libraries come from the system GObject packages above.

Dev dependencies (for tests/linting only):
```bash
pip install pytest pytest-cov ruff
# or:
pipx install ruff
```

### hyprshot (required — build once)

`hyprshot` is a small C helper in `hyprshot/` that captures any window's framebuffer via the `hyprland-toplevel-export-v1` Wayland protocol. It works for any window regardless of Z-order or monocle stacking — no focus switching, no disruption.

```bash
cd ~/Lab/hyprmctl/hyprshot
make
```

`hyprmctl.py` auto-builds it at startup if the binary is missing (uses the `Makefile` in `hyprshot/`). If the build fails, thumbnails are unavailable but the overlay still works with colour-fill tiles.

---

## Install

```bash
git clone https://github.com/GameLostException/hyprmctl.git ~/Lab/hyprmctl
cd ~/Lab/hyprmctl
make build    # builds the hyprshot capture helper (required once)
```

`make build` compiles `hyprshot/hyprshot` — the C binary that captures window framebuffers. This is the only build step. The Python code runs directly from the repo.

No system-wide installation is needed. All paths in `hyprland.conf` point directly into the repo.

Available make targets:
```bash
make build     # build hyprshot (required once, and after hyprshot.c changes)
make run       # start daemon in foreground (for testing)
make test      # run test suite (no Wayland needed)
make bounce    # kill running daemon and restart fresh
make lint      # ruff linter
```

---

## Hyprland configuration

Add to `~/.config/hypr/hyprland.conf`. Replace `REPO_PATH` with wherever you cloned the repo (e.g. `~/Lab/hyprmctl` or `/home/yourname/hyprmctl`):

```ini
# Start the persistent daemon at login (warms thumbnail cache)
exec-once = python3 REPO_PATH/hyprmctl.py

# SUPER+SPACE opens the overlay
$mod = SUPER
bind = $mod, SPACE, exec, python3 REPO_PATH/hyprmctl.py --show
```

> **Why `exec-once` for the daemon and `exec` for the bind?**  
> The `exec-once` starts the daemon once at login. The `exec` on the keybind sends `--show` to the running daemon via IPC. If the daemon isn't running for some reason, `--show` starts a new one and opens the overlay immediately.

### Toggle vs show

```ini
# Open (never close if already open):
bind = $mod, SPACE, exec, python3 REPO_PATH/hyprmctl.py --show

# Toggle (open if closed, close if open):
bind = $mod, SPACE, exec, python3 REPO_PATH/hyprmctl.py --toggle
```

---

## Controls

| Action | Input |
|--------|-------|
| Open overlay | `SUPER+SPACE` |
| Focus window | Click its tile, or `Enter` when keyboard-focused |
| Navigate tiles | Arrow keys / `hjkl` |
| Expand stack | Hover over any tile in the stack |
| Collapse stack | Move cursor away (250ms debounce) |
| Close without focusing | `Escape`, or click background |

---

## Thumbnail capture

Thumbnails are captured by the background daemon using `hyprshot`, which reads window framebuffers directly from the compositor. This means:

- Works for windows behind other windows, in monocle stacks, on non-active workspaces.
- No focus switching, no cursor warping, no disruption.
- Captured frames are stored in RAM (no disk writes).

**Capture strategy:**
- On `activewindowv2` event: capture the newly focused window immediately.
- On `openwindow` event: capture the new window after 300ms (let it render first).
- Rolling loop: cycles through all visible windows every ~2s each, active workspace first. Full refresh cycle ≈ 22s for 20 windows.

**First open after fresh login:** tiles may show colour-fill for windows not yet captured. They'll be replaced as the cache warms up.

**Overlay opens instantly** — the overlay never waits for captures.

---

## Architecture

```
hyprmctl.py          entry point — LD_PRELOAD re-exec, IPC routing, daemon start
src/
  app.py             Gtk.Application daemon — hold()/release() lifecycle, IPC socket
  overlay.py         MissionControlOverlay — layer-shell window, stack system, animation
  layout.py          pure geometry — squarified treemap + fan positions (no GTK)
  hypr.py            hyprctl IPC wrappers (injectable runner for tests)
  icons.py           GTK IconTheme + .desktop index → icon name resolution
  tiles.py           TileWidget — screenshot or colour-fill tile with title bar
hyprshot/
  hyprshot.c         C binary — captures window framebuffer via hyprland-toplevel-export-v1
  Makefile
tests/               pytest unit tests (72 tests, runs without Wayland)
.github/workflows/
  ci.yml             lint (ruff) + test on Python 3.11 & 3.12
```

### Key design decisions

**`KeyboardMode.ON_DEMAND` (not `EXCLUSIVE`)**  
`EXCLUSIVE` causes Hyprland to save the previously focused window and restore it when the overlay surface is destroyed — clobbering any `focuswindow` dispatch. `ON_DEMAND` avoids this while still receiving keyboard events.

**`movecursor` before `focuswindow`**  
With `follow_mouse=1`, Hyprland refocuses whatever is under the cursor when a surface closes. We dispatch `movecursor <cx> <cy>` to the target window's center before `focuswindow`, so the cursor is already there when the overlay closes.

**Layer.TOP (not OVERLAY)**  
`TOP` is the same layer as waybar. Using `OVERLAY` would keep the overlay visible over fullscreen windows, which is wrong. `TOP` surfaces are correctly hidden when a window goes fullscreen.

**`_built` guard on `_on_mapped`**  
The layer-shell `map` signal can fire multiple times. A boolean flag ensures stacks are built exactly once.

**Persistent daemon with IPC socket**  
The daemon listens on `/tmp/hyprmctl-{uid}.sock`. `--show`, `--toggle`, `--hide` commands are delivered via this socket. If the daemon isn't running, the command-line tool starts it directly.

---

## Running tests

```bash
cd REPO_PATH
GDK_BACKEND=offscreen python3 -m pytest tests/ -v
```

With coverage:
```bash
GDK_BACKEND=offscreen python3 -m pytest tests/ --cov=src --cov-report=term-missing
```

`GDK_BACKEND=offscreen` is required because GTK initialises even in headless tests. Tests do not require a live Wayland session.

CI runs automatically on every push via GitHub Actions (lint + test, Python 3.11 & 3.12).

---

## Troubleshooting

**Overlay doesn't open (SUPER+SPACE does nothing)**  
Check that the daemon is running:
```bash
ps aux | grep hyprmctl
```
If not running, start it manually:
```bash
python3 REPO_PATH/hyprmctl.py
```
Then try `--show` again.

**Tiles show colour cards, no screenshots**  
`hyprshot` may not be built:
```bash
ls REPO_PATH/hyprshot/hyprshot
# if missing:
cd REPO_PATH/hyprshot && make
```
Then restart the daemon (`bash REPO_PATH/bounce.sh` or kill + restart).

**App icon missing (shows initials)**  
The app's `.desktop` file was not found in `/usr/share/applications/`. This is normal for apps installed outside the standard path or with unusual class names. The initials fallback is intentional.

**Overlay appears on wrong monitor**  
hyprmctl pins to the Hyprland-focused monitor at the time `--show` is called. Focus the correct monitor first, or use `SUPER+CTRL+arrows` to move focus before pressing `SUPER+SPACE`.

**`libgtk4-layer-shell.so` not found**  
```bash
find /usr -name "libgtk4-layer-shell.so*" 2>/dev/null
```
Update `_LAYER_SHELL_SO` near the top of `hyprmctl.py` if it's at a non-standard path.

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — Overlay shell | ✅ | GTK4 layer-shell, Escape/click-to-close |
| 2 — Window tiles | ✅ | Live hyprctl data, coloured tiles, keyboard nav |
| 3 — Interaction | ✅ | Click-to-focus (all layouts), hover, keyboard nav |
| 4 — Polish | ✅ | App icons, fade-in, multi-monitor |
| 5.1 — Stack layout | ✅ | Squarified treemap, fanned stacks, radial explosion, spring physics |
| 5.2 — Window state | 🔲 | Floating/fullscreen/pinned windows, state restore on close |
| 6 — Thumbnails | ✅ | hyprshot captures, rolling daemon, event-driven refresh |
| 7 — Fly-in / fly-back | 🔲 | Tiles animate from real window positions (requires Phase 6) |
