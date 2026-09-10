# hyprmctl — Technical Specification

**Mission Control for Hyprland**
Standalone GTK4 overlay. No Hyprland plugin API — uses only stable public interfaces.

---

## Principles

- **Standalone** — only `hyprctl`, `grim`, `gtk4-layer-shell`; survives compositor updates
- **Branch per phase** — `phase/N-name` → CI → merge to `main`
- **Tests first** — every module has a companion test file; CI on every push
- **Pure layout engine** — `layout.py` has zero GTK imports; fully unit-testable

---

## Repository layout

```
hyprmctl/
├── hyprmctl.py                  # entry point (LD_PRELOAD re-exec + Gtk.Application)
├── src/
│   ├── app.py                   # Gtk.Application subclass
│   ├── overlay.py               # MissionControlOverlay + Stack explosion system
│   ├── layout.py                # squarified treemap + fan geometry (pure)
│   ├── hypr.py                  # hyprctl IPC wrappers
│   ├── icons.py                 # GTK IconTheme + .desktop index
│   └── tiles.py                 # TileWidget (icon + class + title + HSL colour)
├── tests/
│   ├── fixtures/
│   │   ├── clients.json         # real hyprctl clients -j output
│   │   └── monitors.json        # real hyprctl monitors -j output
│   ├── test_hypr.py
│   ├── test_icons.py
│   ├── test_interaction.py
│   ├── test_layout.py
│   └── test_tiles.py
├── .github/workflows/ci.yml
├── pytest.ini
├── ruff.toml
└── requirements-dev.txt
```

---

## Completed phases

### Phase 1 — Overlay shell ✅

GTK4 window via `Gtk4LayerShell` at OVERLAY layer, all edges anchored, full-screen.
Semi-transparent black background. `KeyboardMode.ON_DEMAND` (not EXCLUSIVE — see note).
Closes on Escape or background click.

**Critical note — KeyboardMode**: `EXCLUSIVE` causes Hyprland to save the previously
focused window and restore it on surface destruction. This clobbers any `focuswindow`
dispatch, breaking monocle layout. `ON_DEMAND` avoids this.

**Critical note — LD_PRELOAD**: `gtk4-layer-shell` must be loaded before
`libwayland-client`. `hyprmctl.py` detects the missing preload and re-execs itself
with `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`.

---

### Phase 2 — Window tiles ✅

**`src/hypr.py`**:
- `get_clients(runner)` / `get_monitors(runner)` — injectable runner for testing
- `get_active_monitor()` — monitor with `focused: true`
- `get_active_workspace_clients()` — filters to active ws, excludes hidden

**`src/tiles.py`**:
- `TileWidget(Gtk.Box)` — icon + app class label + title
- Per-app HSL colour: `_class_to_hue(app_class)` → deterministic hue → CSS rgba
- `set_focused(bool)` — toggles `.tile-focused` CSS class (white border ring)

**`src/icons.py`**:
- `resolve_icon_name(app_class)` — GTK `IconTheme.has_icon()` lookup
- Candidate chain: direct class name → `.desktop` Icon= field → generic fallbacks
- `_build_desktop_index()` — `@lru_cache` scan of `/usr/share/applications/*.desktop`

---

### Phase 3 — Interaction ✅

**Click-to-focus**:
```python
hyprctl --batch "dispatch movecursor {cx} {cy} ; dispatch focuswindow address:{addr}"
```
`movecursor` is required because `follow_mouse=1` refocuses whatever is under the cursor
when the overlay surface is destroyed. Warping first ensures the right window is under
the cursor at destroy time.

**Keyboard navigation**: arrow keys / hjkl cycle `_tiles` list, Enter calls
`_on_tile_click`, Escape closes.

---

### Phase 4 — Polish ✅

- **App icons**: `Gtk.Image.new_from_icon_name()` at 32px, initials fallback
- **Staggered fade-in**: `.tile-animate` (opacity 0) → `.tile-animate-in` (opacity 1)
  via CSS transition, `GLib.timeout_add(20 + i*15ms)`
- **Multi-monitor**: `LayerShell.set_monitor()` on the active monitor's `GdkMonitor`

---

### Phase 5.1 — Stack layout ✅

**Layout algorithm** (`src/layout.py`):

1. `group_by_class(clients)` → groups sorted by size descending
2. `_squarify(n, w, h)` → divide screen into n equal-area near-square cells
3. `_place_stack(group, cell, ...)` → fan windows within cell:
   - Hero (largest window) fills `HERO_FILL=0.78` of cell
   - Each window behind hero offset by `FAN_STEP_X=10, FAN_STEP_Y=8`
   - All windows scaled by same factor (preserves relative sizes)

**Explosion system** (`src/overlay.py`):

```
Stack
  .widgets[]          TileWidget list (hero last = highest z-order)
  .icon_widget        Gtk.Image at cell center (always visible)
  .collapsed_pos[]    (orig_x, orig_y) per widget
  .exploded_pos[]     computed from _explosion_arc + _explosion_positions
  ._hover_count       widgets currently under cursor (prevents flicker)
  ._collapse_id       pending GLib source for debounced collapse
  ._anim_id           running animation source
  ._cur_x, _cur_y     current animated position (enables mid-anim reversal)
```

**Arc direction** (`_explosion_arc`):
- Determines available screen space from cell center `rel_x, rel_y`
- Corners → 90° arc; edges → 180° arc; center → 360°
- Explosion goes AWAY from nearest edge:
  - Top-left → SE (0°, span 90°)
  - Top-right → SW (90°, span 90°)
  - Bottom-left → NE (−90°, span 90°)
  - Bottom-right → NW (180°, span 90°)
  - Top edge → downward (0°, span 180°)
  - Bottom edge → upward (−180°, span 180°)

**Animation** (`_animate_stack`):
- 60fps via `GLib.timeout_add(16, tick)`
- 220ms duration, ease-out-cubic explode / ease-in-cubic collapse
- `from_pos` = `_cur_x/_cur_y` → smooth mid-animation reversal
- One stack exploded at a time; entering a new stack collapses the previous

**Hover guard** (`_on_stack_enter / _on_stack_leave`):
- `_hover_count` incremented on enter, decremented on leave
- Collapse only fires when `_hover_count == 0` after 200ms debounce
- Prevents flicker when cursor moves between icon and tiles within same stack

**`_built` guard on `_on_mapped`**:
- Layer-shell `map` signal can fire multiple times
- Boolean flag ensures stacks are built exactly once

---

## TODO (before next phase)

1. **Stack label** — app name under icon shows "..." — should be clean app name
   (e.g. "Thunar", "Kitty"). Centered under icon, not truncated.

2. **Explosion flicker** — when cursor is between the icon and exploded windows,
   the animation oscillates between exploded and collapsed indefinitely. Fix hover
   debounce / enter-leave detection so mid-path cursor doesn't trigger collapse.

3. **Window opacity** — tiles must be 100% opaque. No transparency on the tile itself.

4. **Tile border** — thin shadowed border matching Hyprland's active window border
   colour (currently `rgba(3daee9ff)`), like windows look on the regular screen.

5. **Hover highlight** — hovering any tile (exploded or single-window stack) smoothly
   borders it blue (focus colour). Border removed on mouse-out.

6. **Readable titles in stack** — when fanned/exploded, window title bars must not
   overlap each other. Fan offset must be large enough that all titles are visible.

---

### Phase 5.2 — Window state completeness 🔲

Include all window types in the overlay:
- Floating, maximized, fullscreen, pinned, special/minimized workspace
- Capture full state at open time (`floating`, `fullscreen`, `pinned`, `at`, `size`)
- On close/click: restore each window's exact state
- Visual distinction: floating tiles get dashed border; fullscreen get a badge

### Phase 6 — Thumbnails ✅

**Architecture: event-driven + rolling refresh daemon**

`ThumbnailCache` runs as a background thread inside the persistent daemon:

1. **`openwindow` event** — Hyprland socket2 fires `openwindow>>addr,ws,class,title`
   when a new window is created. The cache captures it immediately in a worker thread.

2. **Rolling refresh** — cycles through all visible windows (active WS first), one
   capture per `_ROLL_INTERVAL` (0.5s sleep + ~0.6s grim = ~1.1s per window).
   With 20 windows, full cycle ≈ 22s. Active WS windows are prioritised so they
   appear in the first ~10s.

3. **`openwindow` + rolling** means: in normal use (daemon running since login),
   every window the user has ever opened or looked at is captured.

**Capture**: `grim -g "x,y WxH" -` → stdout → `GdkPixbuf.PixbufLoader` → downscaled
to 800×500 max. Entirely in RAM, no disk writes.

**Overlay open**: serves from cache instantly. Uncached windows show colour-fill tile.
`warm()` queues uncached windows for background capture (ready next open).

**Rendering**: `pixbuf.scale_simple(tile_w, tile_h-28, BILINEAR)` → `Gdk.Texture`
→ `Gtk.Picture(can_shrink=False)`. Pre-scaling is required — GTK4.14+ deprecated
`Gtk.Image.new_from_pixbuf` and `ContentFit` doesn't render in `Gtk.Fixed`.

**Note on test restarts**: killing and immediately restarting the daemon produces
empty cache on first open. This is expected and only happens during development.
In production (daemon running since login), cache is always warm.

### Phase 7 — Fly-in / fly-back animation 🔲

**Requires Phase 6** (animating colour boxes is pointless).

**Fly-in**: each tile starts at its window's real screen coordinates and size,
animates to its stack position over 250ms via frame-by-frame `Gtk.Fixed.move()`.

**Fly-back** (on click): reverse — all tiles animate from current position back
to real window positions, overlay closes after animation completes (not before).

---

## Test harness

```bash
GDK_BACKEND=offscreen python3 -m pytest tests/ -v --cov=src --cov-report=term-missing
```

| Module | Coverage |
|--------|---------|
| `hypr.py` | 90% |
| `layout.py` | 95% |
| `icons.py` | 85% |
| `tiles.py` | 75% |
| `overlay.py` | headless-only (GTK widget tests require live Wayland) |

GTK widget tests (`TileWidget`, `MissionControlOverlay`) require a live Wayland display
and are skipped in CI (`GDK_BACKEND=offscreen`). They are tested manually via live launch.

---

## CI pipeline

`.github/workflows/ci.yml` — triggers on push to any branch, PR to `main`.

1. **lint** — `ruff check src/ tests/`
2. **test** — `GDK_BACKEND=offscreen pytest tests/ --cov=src` on Python 3.11 + 3.12
3. Coverage XML artifact uploaded per run

---

## Git workflow

```
main  (default, protected)
  phase/1-overlay-shell   ✅ merged
  phase/2-layout          ✅ merged
  phase/3-interaction     ✅ merged
  phase/4-polish          ✅ merged
  phase/5.2-window-state  (next)
  phase/6-thumbnails
  phase/7-fly-animation
```

Commit convention: `type(scope): message`
Types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`

---

## Dependencies

### Runtime

| Package | Version | Notes |
|---------|---------|-------|
| Python | ≥ 3.11 | |
| `python-gobject` | system | PyGObject / GI |
| `gtk4` | system | GTK4 toolkit |
| `gtk4-layer-shell` | system | includes `Gtk4LayerShell-1.0` GIR |
| `grim` | system | Phase 6+ only |

### Dev

```
pytest>=8.0
pytest-cov>=5.0
ruff>=0.4
```
