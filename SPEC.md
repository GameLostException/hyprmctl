# hyprmctl — Project Specification

**Mission Control for Hyprland**
Standalone GTK4 overlay showing all open windows as tiles, grouped by app.
Click to focus. No Hyprland plugin API — survives compositor updates.

---

## Principles

- **Standalone**: only stable public interfaces (`hyprctl`, `grim`, `gtk4-layer-shell`)
- **Branch per phase**: each phase is developed on `phase/N-name`, merged to `main` before next
- **Tests first**: every module has a companion test file; CI runs on every push
- **No live window capture until Phase 5**: tiles are icon + title, not live content

---

## Repository Layout

```
hyprmctl/
├── hyprmctl.py          # entry point (thin launcher)
├── src/
│   ├── __init__.py
│   ├── app.py           # Gtk.Application subclass
│   ├── overlay.py       # MissionControlOverlay window + layer shell
│   ├── layout.py        # tile geometry calculation (pure, no GTK)
│   ├── hypr.py          # hyprctl data fetching + parsing
│   ├── icons.py         # .desktop file / icon theme lookup
│   ├── tiles.py         # GTK tile widgets
│   └── thumbnails.py    # grim screenshot capture (Phase 5)
├── tests/
│   ├── __init__.py
│   ├── test_layout.py
│   ├── test_hypr.py
│   ├── test_icons.py
│   └── test_tiles.py
├── .github/
│   └── workflows/
│       └── ci.yml       # lint + test on every push / PR
├── SPEC.md              # this file
├── README.md
├── .gitignore
└── requirements-dev.txt
```

---

## Phases

### Phase 1 — Overlay shell ✅ (branch: `phase/1-overlay-shell`)

**Goal**: Full-screen dimmed overlay that opens and closes correctly.

**Deliverables**:
- GTK4 window via `gtk4-layer-shell` at OVERLAY layer, full-screen, all edges anchored
- Semi-transparent black background (`rgba(0,0,0,0.75)`)
- Keyboard exclusive mode (captures all keys while open)
- Closes on Escape or click on background
- Placeholder label (removed in Phase 2)
- Entry point: `python3 hyprmctl.py`
- Hyprland keybind: `SUPER+SPACE` → `hyprctl dispatch exec hyprmctl`

**Tests**:
- `test_overlay.py`: instantiation smoke test (headless via `GDK_BACKEND=offscreen`)
- `test_css.py`: CSS provider loads without error

**Definition of done**: overlay opens, dims screen, closes on Escape and click.

---

### Phase 2 — Window data + grid layout (branch: `phase/2-layout`)

**Goal**: Parse live window data, compute tile geometry, render placeholder tiles.

**Deliverables**:

**`src/hypr.py`**:
- `get_clients() -> list[dict]` — calls `hyprctl clients -j`, returns parsed JSON
- `get_monitors() -> list[dict]` — calls `hyprctl monitors -j`
- `get_active_monitor() -> dict` — returns the monitor where the focused workspace lives
- Filters clients to active monitor + active workspace only
- Handles empty workspace gracefully

**`src/layout.py`** (pure functions, no GTK, fully testable):
- `compute_layout(clients, monitor_w, monitor_h, padding, gap) -> list[TileGeometry]`
- `TileGeometry`: dataclass with `x, y, w, h, client` fields
- Algorithm: pack clients into rows, scale each to fit preserving aspect ratio, then
  group by `class` (same app class = adjacent tiles), sort groups by window count desc
- `group_by_class(clients) -> dict[str, list[dict]]` — groups clients by `wm_class`
- Target: tiles use ~80% of screen area, padding 40px from edges, 12px gap between tiles

**`src/tiles.py`**:
- `TileWidget(Gtk.Frame)` — displays app class name + window title in a colored box
- Color derived from app class string hash → hue → HSL → CSS rgba
- Hover state: subtle brightness increase via CSS class

**`src/overlay.py`** refactored:
- Removes placeholder label
- On `present()`: fetches clients, computes layout, instantiates `TileWidget` for each
- Uses `Gtk.Fixed` as layout container (absolute positioning matches computed geometry)

**Tests**:
- `test_hypr.py`: mocks `subprocess.run`, asserts parsing of sample JSON fixtures
- `test_layout.py`: grid computation with known inputs → assert tile positions/sizes
- `test_tiles.py`: widget instantiation with mock client data

**Fixtures**: `tests/fixtures/clients.json`, `tests/fixtures/monitors.json`
(real `hyprctl` output, committed to repo)

**Definition of done**: overlay shows a colored tile per window, correctly grouped by app.

---

### Phase 3 — Interaction (branch: `phase/3-interaction`)

**Goal**: Click a tile to focus the window; keyboard navigation.

**Deliverables**:

**Click-to-focus**:
- `TileWidget` gets a `Gtk.GestureClick` controller
- On click: run `hyprctl dispatch focuswindow address:0x{addr}`, then close overlay
- Background click still closes without focusing (existing behavior)

**Hover highlight**:
- CSS: `.tile:hover { background-color: rgba(255,255,255,0.12); }`
- Scale-up on hover: CSS `transition: all 0.1s ease` (GTK4 CSS transitions)

**Keyboard navigation**:
- Arrow keys move focus between tiles (logical order: left→right, top→bottom)
- `Enter` / `Return` → focus selected window + close
- `Escape` → close without focusing
- Focused tile gets `.tile-focused` CSS class (visible ring)

**Group label**:
- Above each app group: small `Gtk.Label` with app class name, muted color

**Tests**:
- `test_interaction.py`: mock `subprocess.run`, assert correct `hyprctl dispatch` call
- Keyboard nav: simulate key events, assert focused tile index changes correctly

**Definition of done**: click or keyboard nav focuses correct window, overlay closes cleanly.

---

### Phase 4 — Polish (branch: `phase/4-polish`)

**Goal**: Animations, app icons, visual grouping, multi-monitor support.

**Deliverables**:

**App icons** (`src/icons.py`):
- `find_icon(app_class) -> str | None` — searches `/usr/share/applications/*.desktop`
  for `Icon=` matching app class (case-insensitive), resolves via GTK icon theme
- `get_icon_pixbuf(app_class, size) -> GdkPixbuf | None`
- `TileWidget` shows icon (48×48) above title if available, falls back to initials

**Open animation**:
- Tiles start at `opacity=0, scale=0.85`, animate to `opacity=1, scale=1.0` over 150ms
- Staggered: each tile delayed by `index * 15ms`
- Implemented via `Gtk.Widget.set_opacity` + CSS transition or GLib timeout chain

**Close animation**:
- Reverse: fade + scale-down over 100ms, then `self.close()` after animation completes

**Visual grouping**:
- Semi-transparent rounded rect behind each app group (drawn via CSS `background-color`)
- `Gtk.Frame` or overlay `Gtk.Box` per group, positioned by layout engine

**Multi-monitor**:
- `overlay.py`: detect focused monitor at open time via `get_active_monitor()`
- Pass monitor name to `GtkLayerShell.set_monitor()` → overlay on correct screen only
- Layout engine receives that monitor's geometry

**Tests**:
- `test_icons.py`: mock `.desktop` parsing, assert icon resolution
- `test_layout.py`: add multi-monitor fixture, assert layout respects monitor bounds

**Definition of done**: overlay looks polished, icons show, animations play, correct monitor.

---

### Phase 5 — Live thumbnails (branch: `phase/5-thumbnails`)

**Goal**: Replace solid-color tiles with `grim` window screenshots.

**Deliverables**:

**`src/thumbnails.py`**:
- `capture_window(client) -> GdkPixbuf | None`
  - Computes crop rect from `at` (x,y) + `size` (w,h) fields in `hyprctl clients` output
  - Runs: `grim -g "x,y wxh" /tmp/hyprmctl-{addr}.png`
  - Loads result as `GdkPixbuf`, returns `None` on failure
- `capture_all(clients) -> dict[str, GdkPixbuf]` — parallel capture via `ThreadPoolExecutor`
  (max 4 workers to avoid hammering screencopy)

**Integration**:
- `overlay.py` calls `capture_all()` before building tile widgets
- `TileWidget` accepts optional `pixbuf` param; if set, shows scaled screenshot instead
  of color fill; icon + title overlaid as semi-transparent bottom bar

**Performance guard**:
- If capture takes > 500ms, fall back to color tiles silently

**Tests**:
- `test_thumbnails.py`: mock `subprocess.run` + file I/O, assert pixbuf returned on success,
  `None` returned on `grim` failure

**Definition of done**: tiles show window screenshots at overlay open time.

---

## Test Harness

### Framework
- `pytest` — test runner
- `unittest.mock` — mock `subprocess.run`, GTK calls, file I/O
- `pytest-cov` — coverage reporting
- Headless GTK: `GDK_BACKEND=offscreen` env var (set in CI, optional locally)

### Running tests locally
```bash
cd ~/Lab/hyprmctl
GDK_BACKEND=offscreen python3 -m pytest tests/ -v --cov=src --cov-report=term-missing
```

### Coverage targets
| Module          | Target |
|-----------------|--------|
| `hypr.py`       | 90%    |
| `layout.py`     | 95%    |
| `icons.py`      | 80%    |
| `tiles.py`      | 75%    |
| `thumbnails.py` | 80%    |
| `overlay.py`    | 60%    |

---

## CI Pipeline (GitHub Actions)

File: `.github/workflows/ci.yml`

Triggers: push to any branch, pull request to `main`.

Jobs:
1. **lint** — `ruff check src/ tests/`
2. **test** — `GDK_BACKEND=offscreen pytest tests/ --cov=src --cov-report=xml`
3. **coverage-comment** — posts coverage diff as PR comment (via `coverage-comment` action)

Python version: `3.11` (minimum; tested against `3.12` too).

System packages needed in CI: `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-gtklayershell-0.1`
(Ubuntu runner: install via `apt`, or use `conda-forge` if not available).

---

## Git Workflow

```
main
 └── phase/1-overlay-shell   ← merged ✅
 └── phase/2-layout          ← current
 └── phase/3-interaction
 └── phase/4-polish
 └── phase/5-thumbnails
```

- One branch per phase
- Squash-merge or regular merge to `main` when phase passes CI
- Commit convention: `type(scope): message`
  - `feat(overlay): add layer shell init`
  - `test(layout): add grid computation tests`
  - `fix(hypr): handle empty workspace`
  - `docs: update README for phase 2`

---

## Dependencies

### Runtime
- Python ≥ 3.11
- `python3-gi` (PyGObject)
- GTK 4 (`gir1.2-gtk-4.0` / `python-gobject`)
- `gtk4-layer-shell` + GIR (`gir1.2-gtklayershell-0.1`)
- `grim` (Phase 5 only)

### Dev / CI
```
pytest>=8.0
pytest-cov>=5.0
ruff>=0.4
```

File: `requirements-dev.txt`

---

## Acceptance Criteria Summary

| Phase | AC |
|-------|----|
| 1 | Overlay opens full-screen, dims bg, closes on Escape/click |
| 2 | Tiles visible for each window on active workspace, grouped by app |
| 3 | Click tile → window focused, overlay closed; keyboard nav works |
| 4 | Icons shown, open/close animation plays, correct monitor |
| 5 | Tiles show grim screenshots, fallback to color on failure |
