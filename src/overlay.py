"""
src/overlay.py — MissionControlOverlay window.

Stack explosion design
======================
Each app class is a "stack":
  - Collapsed: fanned window tiles + app icon on top-center (always visible)
  - Exploded on hover: windows animate outward from stack center into the
    available arc (determined by cell position on screen). Icon stays put.
  - One stack exploded at a time.
  - Smooth animation via 60fps frame interpolation.
"""

from __future__ import annotations

import math
import subprocess
from functools import lru_cache as _lru_cache

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from src.hypr import get_active_monitor, get_active_workspace_clients  # noqa: E402
from src.icons import resolve_icon_name  # noqa: E402
from src.layout import compute_layout  # noqa: E402
from src.tiles import TileWidget  # noqa: E402

# ── App display name ──────────────────────────────────────────────────────────

# Well-known overrides: wm_class → human-readable name
_APP_NAMES: dict[str, str] = {
    "kitty":                        "Kitty",
    "alacritty":                    "Alacritty",
    "foot":                         "Foot",
    "wezterm":                      "WezTerm",
    "firefox":                      "Firefox",
    "firefox-esr":                  "Firefox ESR",
    "chromium":                     "Chromium",
    "google-chrome":                "Chrome",
    "brave-browser":                "Brave",
    "thunar":                       "Thunar",
    "nautilus":                     "Files",
    "nemo":                         "Nemo",
    "dolphin":                      "Dolphin",
    "code":                         "VS Code",
    "code-oss":                     "VS Code",
    "vscodium":                     "VSCodium",
    "nvim":                         "Neovim",
    "vim":                          "Vim",
    "emacs":                        "Emacs",
    "zathura":                      "Zathura",
    "evince":                       "Evince",
    "okular":                       "Okular",
    "vlc":                          "VLC",
    "mpv":                          "mpv",
    "spotify":                      "Spotify",
    "discord":                      "Discord",
    "slack":                        "Slack",
    "telegram-desktop":             "Telegram",
    "signal":                       "Signal",
    "obsidian":                     "Obsidian",
    "gimp":                         "GIMP",
    "gimp-2.10":                    "GIMP",
    "inkscape":                     "Inkscape",
    "libreoffice-writer":           "Writer",
    "libreoffice-calc":             "Calc",
    "libreoffice-impress":          "Impress",
    "libreoffice":                  "LibreOffice",
    "pcmanfm":                      "PCManFM",
    "ranger":                       "Ranger",
    "rofi":                         "Rofi",
    "waybar":                       "Waybar",
    "swaync":                       "Notifications",
    "nm-applet":                    "Network",
    "blueman-applet":               "Bluetooth",
    "pavucontrol":                  "PulseAudio",
    "org.pulseaudio.pavucontrol":   "PulseAudio",
    "htop":                         "htop",
    "btop":                         "btop",
    "neofetch":                     "Neofetch",
    "org.gnome.nautilus":           "Files",
    "org.gnome.calculator":         "Calculator",
    "org.gnome.calendar":           "Calendar",
    "org.gnome.gedit":              "gedit",
    "org.kde.dolphin":              "Dolphin",
    "org.kde.okular":               "Okular",
    "org.kde.konsole":              "Konsole",
    "com.mitchellh.ghostty":        "Ghostty",
    "ghostty":                      "Ghostty",
}


def _display_name(app_class: str) -> str:
    """
    Return a clean human-readable app name from wm_class.
    Falls back to title-cased class if no override is known.
    """
    lower = app_class.lower()
    if lower in _APP_NAMES:
        return _APP_NAMES[lower]
    # Try stripping common suffixes/prefixes and title-case
    name = app_class.replace("-", " ").replace("_", " ")
    # Drop common redundant suffixes
    for suffix in (" desktop", " browser", " stable", " nightly"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
    return name.title()


_ANIM_FPS  = 60
_ANIM_MS   = 1000 // _ANIM_FPS
_ICON_SIZE = 56    # app icon px at stack center
_SHADOW_PAD = 6    # extra pixels around tile for shadow bleed

# ── Cairo shadow helper ───────────────────────────────────────────────────────

def _rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    """Add a rounded rectangle path to a Cairo context."""
    cr.new_sub_path()
    cr.arc(x + r,     y + r,     r, math.pi,       1.5 * math.pi)
    cr.arc(x + w - r, y + r,     r, 1.5 * math.pi, 2 * math.pi)
    cr.arc(x + w - r, y + h - r, r, 0,             0.5 * math.pi)
    cr.arc(x + r,     y + h - r, r, 0.5 * math.pi, math.pi)
    cr.close_path()


@_lru_cache(maxsize=32)
def _make_shadow_texture(
    tile_w: int, tile_h: int,
) -> Gdk.Texture:
    """
    Uniform drop shadow — identical bleed on all 4 sides.
    Uses a single rounded rect stroked at decreasing widths from the edge inward,
    so every side gets the same treatment.
    """
    import cairo as _cairo

    PAD    = _SHADOW_PAD
    RADIUS = 8.0

    da_w = tile_w + PAD * 2
    da_h = tile_h + PAD * 2

    surf = _cairo.ImageSurface(_cairo.FORMAT_ARGB32, da_w, da_h)
    ctx  = _cairo.Context(surf)

    # Stroke concentric rings from tile edge outward.
    # Each ring is at distance d outside the tile, with alpha = 0.22*(1-d/PAD)^2.
    # Using stroke (not fill) means each ring contributes independently — no
    # double-accumulation — so all 4 sides are mathematically identical.
    for d in range(PAD):
        t = 1.0 - d / PAD       # 1.0 at tile edge, 0.0 at PAD
        a = 0.22 * t * t
        inset = PAD - d         # ring position in surface coords
        rw = da_w - inset * 2
        rh = da_h - inset * 2
        r  = max(RADIUS + d * 0.15, 0.5)
        ctx.set_line_width(1.5)
        _rounded_rect(ctx, inset + 0.75, inset + 0.75, rw - 1.5, rh - 1.5, r)
        ctx.set_source_rgba(0, 0, 0, a)
        ctx.stroke()

    surf.flush()
    src = surf.get_data()
    n   = da_w * da_h

    # Fast BGRA→RGBA channel swap using numpy if available, else memoryview
    try:
        import numpy as np
        arr = np.frombuffer(src, dtype=np.uint8).reshape(n, 4)
        rgba_arr = arr[:, [2, 1, 0, 3]]  # BGRA → RGBA
        rgba = rgba_arr.tobytes()
    except ImportError:
        # Fallback: memoryview swap — still pure Python but avoids per-item overhead
        mv  = memoryview(src).cast("B")
        raw = bytearray(mv)
        for i in range(0, n * 4, 4):
            raw[i], raw[i+2] = raw[i+2], raw[i]   # swap B↔R, keep G and A
        rgba = bytes(raw)

    pb = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(rgba),
        GdkPixbuf.Colorspace.RGB, True, 8, da_w, da_h, da_w * 4,
    )
    return Gdk.Texture.new_for_pixbuf(pb)

# Spring physics constants
# Explode: stiff spring, slight overshoot — snappy pop-out
_SPRING_EXPLODE_STIFFNESS = 320.0   # higher = faster
_SPRING_EXPLODE_DAMPING   = 22.0    # lower = more overshoot (critical ≈ 2√k)
# Collapse: overdamped — quick clean snap-back, no bounce
_SPRING_COLLAPSE_STIFFNESS = 400.0
_SPRING_COLLAPSE_DAMPING   = 36.0
# Stop threshold: distance in px below which we snap to target
_SPRING_THRESHOLD = 1.5

_BASE_CSS = """
.mc-root {
    background-color: transparent;
}
.group-label {
    color: rgba(255, 255, 255, 0.88);
    font-size: 11px;
    font-weight: 500;
    background-color: rgba(30, 30, 30, 0.62);
    border-radius: 10px;
    padding: 2px 8px;
}
.tile {
    border-radius: 8px;
}
.tile-class {
    color: rgba(255, 255, 255, 0.55);
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
.tile-title {
    color: rgba(255, 255, 255, 0.90);
    font-size: 13px;
}
.tile-initials {
    color: rgba(255, 255, 255, 0.6);
    font-size: 13px;
    font-weight: bold;
    background-color: rgba(255, 255, 255, 0.12);
    border-radius: 4px;
}
.tile-bar {
    background-color: rgba(15, 15, 20, 0.92);
    padding: 4px 6px;
}
/* Title bar at bottom of tile (default / fan-down) */
.tile-bar-bottom {
    border-radius: 0 0 8px 8px;
}
/* Title bar at top of tile (fan-up / 1h30) */
.tile-bar-top {
    border-radius: 8px 8px 0 0;
}
.tile-bar-title {
    color: rgba(255, 255, 255, 0.92);
    font-size: 11px;
}
.mc-empty {
    color: rgba(255, 255, 255, 0.4);
    font-size: 18px;
}
/* Transparent hit-area for hover zone — no visual rendering */
.hit-area {
    background-color: transparent;
}
.stack-icon {
    border-radius: 8px;
}
/* App name pill in colour-fill tiles */
.name-pill {
    background-color: rgba(30, 30, 30, 0.62);
    border-radius: 10px;
    padding: 2px 8px;
}
.name-pill-text {
    color: rgba(255, 255, 255, 0.88);
    font-size: 11px;
    font-weight: 500;
}
/* Manual drop shadow behind each tile (drawn via Cairo DrawingArea) */
.tile-shadow {
    background-color: transparent;
}
/* No border at rest — blue on hover and keyboard focus */
.tile-screenshot {
    border-radius: 8px;
}
.tile-screenshot:hover,
.tile-focused {
    border-width: 2px;
    border-style: solid;
    border-color: rgba(61, 174, 233, 1.0);
}
"""

# ── Spring physics ────────────────────────────────────────────────────────────

def _spring_tick(
    pos: float, vel: float, target: float,
    stiffness: float, damping: float, dt: float,
) -> tuple[float, float]:
    """
    One step of a damped spring integrator (semi-implicit Euler).
    Returns (new_pos, new_vel).

    F = -k * displacement - d * velocity
    """
    displacement = pos - target
    force        = -stiffness * displacement - damping * vel
    new_vel      = vel + force * dt
    new_pos      = pos + new_vel * dt
    return new_pos, new_vel


# ── Explosion geometry ────────────────────────────────────────────────────────

def _explosion_arc(
    cell_x: float, cell_y: float, cell_w: float, cell_h: float,
    screen_w: float, screen_h: float,
) -> tuple[float, float]:
    """
    Return (arc_start_deg, arc_span_deg).
    0°=right, 90°=down (screen coords, Y increases downward).
    Explosion goes AWAY from the nearest screen edge(s).
    """
    cx = cell_x + cell_w / 2
    cy = cell_y + cell_h / 2
    rel_x = cx / screen_w
    rel_y = cy / screen_h

    near_left   = rel_x < 0.33
    near_right  = rel_x > 0.67
    near_top    = rel_y < 0.33
    near_bottom = rel_y > 0.67

    if near_left and near_top:
        return 0.0, 90.0        # TL → SE
    if near_right and near_top:
        return 90.0, 90.0       # TR → SW
    if near_left and near_bottom:
        return -90.0, 90.0      # BL → NE
    if near_right and near_bottom:
        return 180.0, 90.0      # BR → NW
    if near_top:
        return 0.0, 180.0       # top edge → downward
    if near_bottom:
        return -180.0, 180.0    # bot edge → upward
    if near_left:
        return -90.0, 180.0     # left edge → rightward
    if near_right:
        return 90.0, 180.0      # right edge → leftward
    return 0.0, 360.0           # center → full radial


def _explosion_positions(
    n: int,
    origin_x: float, origin_y: float,
    tile_w: float, tile_h: float,
    arc_start: float, arc_span: float,
) -> list[tuple[float, float]]:
    """
    Compute (x, y) for each of n windows exploded around origin.
    Windows are distributed evenly across the arc at a radius that
    makes them barely non-overlapping (or overlapping homogeneously
    if they must).
    """
    if n == 1:
        # Single window: place directly at origin (hero)
        return [(origin_x, origin_y)]

    # Radius: distance from icon center to tile center
    # Use tile diagonal as minimum so windows don't overlap origin
    tile_diag = math.hypot(tile_w, tile_h)
    radius = tile_diag * 0.65

    positions = []
    if arc_span >= 360:
        # Full circle: distribute evenly, no start bias
        for i in range(n):
            angle_deg = arc_start + i * 360 / n
            angle_rad = math.radians(angle_deg)
            px = origin_x + radius * math.cos(angle_rad)
            py = origin_y + radius * math.sin(angle_rad)
            positions.append((px, py))
    else:
        # Arc: distribute across the span
        for i in range(n):
            if n == 1:
                t = 0.5
            else:
                t = i / (n - 1)
            angle_deg = arc_start + t * arc_span
            angle_rad = math.radians(angle_deg)
            px = origin_x + radius * math.cos(angle_rad)
            py = origin_y + radius * math.sin(angle_rad)
            positions.append((px, py))

    return positions


# ── Stack data ────────────────────────────────────────────────────────────────

class Stack:
    """Holds all widgets and state for one app's stack."""

    def __init__(
        self,
        app_class: str,
        widgets: list[TileWidget],
        icon_widget: Gtk.Widget,
        label_widget: Gtk.Label,
        cell_x: float, cell_y: float, cell_w: float, cell_h: float,
        screen_w: float, screen_h: float,
    ) -> None:
        self.app_class = app_class
        self.widgets = widgets
        self.icon_widget = icon_widget
        self.label_widget = label_widget
        self.cell_x = cell_x
        self.cell_y = cell_y
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.screen_w = screen_w
        self.screen_h = screen_h

        # Icon center (explosion origin)
        self.icon_cx = cell_x + cell_w / 2
        self.icon_cy = cell_y + cell_h / 2

        # Collapsed positions (fanned)
        self.collapsed_pos = [(w._orig_x, w._orig_y) for w in widgets]

        # Explosion arc
        arc_start, arc_span = _explosion_arc(
            cell_x, cell_y, cell_w, cell_h, screen_w, screen_h
        )

        # Exploded positions (centered on icon)
        if widgets:
            tw = widgets[-1]._tile_w
            th = widgets[-1]._tile_h
        else:
            tw, th = 200.0, 150.0

        raw_positions = _explosion_positions(
            len(widgets),
            self.icon_cx, self.icon_cy,
            tw, th,
            arc_start, arc_span,
        )
        # Convert center positions to top-left, then clamp to screen bounds
        # so tiles with large cells (few stacks) never explode off-screen.
        _EDGE_MARGIN = 8.0   # minimum distance from screen edge (px)
        self.exploded_pos = []
        for px, py in raw_positions:
            tlx = px - tw / 2
            tly = py - th / 2
            tlx = max(_EDGE_MARGIN, min(tlx, screen_w - tw - _EDGE_MARGIN))
            tly = max(_EDGE_MARGIN, min(tly, screen_h - th - _EDGE_MARGIN))
            self.exploded_pos.append((tlx, tly))

        self.exploded = False
        self._anim_id = 0
        self._hover_count = 0   # widgets in this stack currently under cursor
        self._collapse_id = 0   # pending collapse GLib source id
        # Per-widget spring velocities (vx, vy) — reset each time animation starts
        self._vel: list[list[float]] = [[0.0, 0.0] for _ in widgets]


# ── Overlay window ────────────────────────────────────────────────────────────

class MissionControlOverlay(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)

        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.TOP)   # TOP not OVERLAY — waybar stays visible
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self, edge, True)

        self.set_decorated(False)

        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._root.set_hexpand(True)
        self._root.set_vexpand(True)
        self._root.add_css_class("mc-root")
        self.set_child(self._root)

        self._fixed = Gtk.Fixed()
        self._fixed.set_hexpand(True)
        self._fixed.set_vexpand(True)
        self._root.append(self._fixed)

        self._tiles: list[TileWidget] = []
        self._stacks: list[Stack] = []
        self._active_stack: Stack | None = None

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        bg_click = Gtk.GestureClick()
        bg_click.connect("pressed", self._on_bg_click)
        self._root.add_controller(bg_click)

        provider = Gtk.CssProvider()
        provider.load_from_data(_BASE_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._built = False  # guard against multiple map events
        self.connect("map", self._on_mapped)

    def _build_background(self, monitor: dict, log_w: int, log_h: int) -> None:
        """
        Load the current waypaper wallpaper and place it as background.
        Then fade in a dark overlay on top so tiles are readable.
        Falls back to solid dark if wallpaper can't be loaded.
        """
        import configparser
        import os

        wallpaper_path = ""
        try:
            cfg = configparser.ConfigParser()
            cfg.read(os.path.expanduser("~/.config/waypaper/config.ini"))
            wallpaper_path = os.path.expanduser(
                cfg.get("Settings", "wallpaper", fallback="")
            )
        except Exception:
            pass

        if wallpaper_path and os.path.exists(wallpaper_path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    wallpaper_path, log_w, log_h, False
                )
                tex = Gdk.Texture.new_for_pixbuf(pb)
                pic = Gtk.Picture.new_for_paintable(tex)
                pic.set_can_shrink(False)
                pic.set_size_request(log_w, log_h)
                self._fixed.put(pic, 0, 0)
            except Exception:
                pass  # fallback: mc-root stays transparent (black compositor bg)

    def _make_shadow(self, tile_w: int, tile_h: int) -> Gtk.Picture:
        """
        Create a shadow widget from a pre-rendered Gdk.Texture.
        Computed once at build time — zero cost during animation.
        """
        tex = _make_shadow_texture(tile_w, tile_h)
        da_w = tile_w + _SHADOW_PAD * 2
        da_h = tile_h + _SHADOW_PAD * 2
        pic = Gtk.Picture.new_for_paintable(tex)
        pic.set_can_shrink(False)
        pic.set_size_request(da_w, da_h)
        pic.add_css_class("tile-shadow")
        return pic

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _on_mapped(self, _widget) -> None:
        if self._built:
            return
        self._built = True
        monitor = get_active_monitor()
        if monitor is None:
            self._show_empty("No monitor detected")
            return

        display = Gdk.Display.get_default()
        if display is not None:
            mon_list = display.get_monitors()
            connector = monitor.get("name", "")
            for i in range(mon_list.get_n_items()):
                m = mon_list.get_item(i)
                if hasattr(m, "get_connector") and m.get_connector() == connector:
                    LayerShell.set_monitor(self, m)
                    break

        mon_w = monitor.get("width", 1920)
        mon_h = monitor.get("height", 1080)
        scale = monitor.get("scale", 1.0)
        log_w = int(mon_w / scale)
        log_h = int(mon_h / scale)

        # Background: blurred desktop screenshot (wallpaper shows through)
        self._build_background(monitor, log_w, log_h)

        clients = get_active_workspace_clients()
        if not clients:
            self._show_empty("No windows on this workspace")
            return

        # Serve from cache — tiles show colour-fill if not yet captured.
        # The rolling daemon will fill them in on next open.
        from src.thumbnails import get_cache
        cache = get_cache()
        thumbnails = {c["address"]: cache.get(c["address"]) for c in clients}
        tiles = compute_layout(clients, log_w, log_h, padding=52, gap=14)
        self._build_stacks(tiles, log_w, log_h, thumbnails)

    def _build_stacks(self, tiles, screen_w: int, screen_h: int, thumbnails: dict) -> None:
        from collections import defaultdict
        by_class: dict[str, list] = defaultdict(list)
        tile_widgets: dict[str, list[TileWidget]] = defaultdict(list)

        # Place all tile widgets
        for i, tile_geo in enumerate(tiles):
            addr   = tile_geo.client.get("address", "")
            pixbuf = thumbnails.get(addr)
            cls    = tile_geo.client.get("class") or tile_geo.client.get("initialClass") or "unknown"
            widget = TileWidget(
                tile_geo.client,
                on_click=self._on_tile_click,
                pixbuf=pixbuf,
                tile_w=int(tile_geo.w),
                tile_h=int(tile_geo.h),
                title_at_top=tile_geo.title_at_top,
                display_name=_display_name(cls),
            )
            widget.set_size_request(int(tile_geo.w), int(tile_geo.h))
            widget._orig_x = tile_geo.x
            widget._orig_y = tile_geo.y
            widget._cur_x  = tile_geo.x   # tracks current animated position
            widget._cur_y  = tile_geo.y
            widget._tile_w = tile_geo.w
            widget._tile_h = tile_geo.h

            # Blurred drop shadow: Cairo DrawingArea placed behind tile
            shadow = self._make_shadow(int(tile_geo.w), int(tile_geo.h))
            sx = tile_geo.x - _SHADOW_PAD
            sy = tile_geo.y - _SHADOW_PAD
            self._fixed.put(shadow, sx, sy)
            widget._shadow    = shadow
            widget._shadow_dx = -_SHADOW_PAD
            widget._shadow_dy = -_SHADOW_PAD

            self._fixed.put(widget, tile_geo.x, tile_geo.y)
            self._tiles.append(widget)

            # For colour-fill tiles: place icon+label directly in _fixed
            # at the tile's center — bypasses GTK layout entirely for perfect centering
            if thumbnails.get(addr) is None:
                center_widget = self._make_tile_center(
                    cls, _display_name(cls),
                    int(tile_geo.w), int(tile_geo.h),
                )
                # Measure natural size once — used every animation frame
                nat = center_widget.get_preferred_size()[1]
                cw_nat = nat.width
                ch_nat = nat.height
                cx = tile_geo.x + tile_geo.w / 2 - cw_nat / 2
                cy = tile_geo.y + tile_geo.h / 2 - ch_nat / 2
                self._fixed.put(center_widget, cx, cy)
                widget._center_widget  = center_widget
                widget._center_tile_w  = tile_geo.w
                widget._center_tile_h  = tile_geo.h
                widget._center_nat_w   = cw_nat   # cached — avoids per-frame measure
                widget._center_nat_h   = ch_nat
            else:
                widget._center_widget = None

            cls = tile_geo.client.get("class") or "unknown"
            tile_widgets[cls].append(widget)
            by_class[cls].append(tile_geo)

        # Build one Stack per app class
        for cls, geo_list in by_class.items():
            widgets = tile_widgets[cls]

            # Cell bounds from tile positions
            cell_x = min(g.x for g in geo_list)
            cell_y = min(g.y for g in geo_list)
            cell_r = max(g.x + g.w for g in geo_list)
            cell_b = max(g.y + g.h for g in geo_list)
            cell_w = cell_r - cell_x
            cell_h = cell_b - cell_y

            # Icon widget — placed on top of stack center
            icon_widget = self._make_stack_icon(cls)
            icon_x = cell_x + cell_w / 2 - _ICON_SIZE / 2
            icon_y = cell_y + cell_h / 2 - _ICON_SIZE / 2
            self._fixed.put(icon_widget, icon_x, icon_y)

            # Label centered below icon
            label = Gtk.Label(label=_display_name(cls))
            label.add_css_class("group-label")
            label.set_halign(Gtk.Align.CENTER)
            label.set_max_width_chars(20)
            label.set_ellipsize(0)   # no ellipsis — names are short
            label_w = 140
            self._fixed.put(
                label,
                icon_x + _ICON_SIZE / 2 - label_w / 2,
                icon_y + _ICON_SIZE + 5,
            )

            # TODO 6: window title label removed — tiles already carry their name
            # in the title bar; the stack icon label shows the app name.

            stack = Stack(
                app_class=cls,
                widgets=widgets,
                icon_widget=icon_widget,
                label_widget=label,
                cell_x=cell_x, cell_y=cell_y,
                cell_w=cell_w, cell_h=cell_h,
                screen_w=screen_w, screen_h=screen_h,
            )
            self._stacks.append(stack)

            # Hover on any tile in this stack
            for w in widgets:
                motion = Gtk.EventControllerMotion()
                motion.connect("enter", lambda *_, s=stack: self._on_stack_enter(s))
                motion.connect("leave", lambda *_, s=stack: self._on_stack_leave(s))
                w.add_controller(motion)

            # Also hover on icon
            icon_motion = Gtk.EventControllerMotion()
            icon_motion.connect("enter", lambda *_, s=stack: self._on_stack_enter(s))
            icon_motion.connect("leave", lambda *_, s=stack: self._on_stack_leave(s))
            icon_widget.add_controller(icon_motion)

            # Also hover on label (sits below icon, in the gap between icon and tiles)
            label_motion = Gtk.EventControllerMotion()
            label_motion.connect("enter", lambda *_, s=stack: self._on_stack_enter(s))
            label_motion.connect("leave", lambda *_, s=stack: self._on_stack_leave(s))
            label.add_controller(label_motion)

            # Transparent hit-area covering the full cell to eliminate flicker gaps.
            hit = Gtk.Box()
            hit.set_size_request(int(cell_w), int(cell_h))
            hit.add_css_class("hit-area")
            self._fixed.put(hit, cell_x, cell_y)
            hit_motion = Gtk.EventControllerMotion()
            hit_motion.connect("enter", lambda *_, s=stack: self._on_stack_enter(s))
            hit_motion.connect("leave", lambda *_, s=stack: self._on_stack_leave(s))
            hit.add_controller(hit_motion)
            # Keep reference so it's not GC'd
            stack._hit_widget = hit

    def _make_tile_center(
        self, app_class: str, app_name: str, tile_w: int, tile_h: int
    ) -> Gtk.Box:
        """
        Icon + pill label for a colour-fill tile.
        Placed directly in _fixed at exact center coords — no GTK layout dependency.
        """
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_halign(Gtk.Align.CENTER)

        icon = self._make_stack_icon(app_class, size=32)
        icon.set_halign(Gtk.Align.CENTER)
        col.append(icon)

        pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        pill.set_halign(Gtk.Align.CENTER)
        pill.add_css_class("name-pill")

        lbl = Gtk.Label(label=app_name)
        lbl.add_css_class("name-pill-text")
        pill.append(lbl)
        col.append(pill)

        return col

    def _make_stack_icon(self, app_class: str, size: int = _ICON_SIZE) -> Gtk.Widget:
        """Create the icon widget shown at the stack center."""
        icon_name = resolve_icon_name(app_class)
        if icon_name:
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(size)
        else:
            img = Gtk.Label(label=(app_class[:2]).upper())
            img.set_size_request(size, size)
            img.add_css_class("tile-initials")
        img.add_css_class("stack-icon")
        return img

    def _show_empty(self, message: str) -> None:
        label = Gtk.Label(label=message)
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        label.set_hexpand(True)
        label.set_vexpand(True)
        label.add_css_class("mc-empty")
        self._root.append(label)

    # ── Stack hover ───────────────────────────────────────────────────────────

    def _on_stack_enter(self, stack: Stack) -> None:
        """Called when mouse enters any widget belonging to `stack`."""
        stack._hover_count += 1
        if self._active_stack is stack:
            return  # already exploded, nothing to do
        # Collapse previous stack immediately (cancel any pending collapse)
        if self._active_stack is not None:
            if self._active_stack._collapse_id:
                GLib.source_remove(self._active_stack._collapse_id)
                self._active_stack._collapse_id = 0
            self._animate_stack(self._active_stack, explode=False)
        self._active_stack = stack
        # TODO 7: raise stack tiles to top z-order before animating
        self._raise_stack(stack)
        self._animate_stack(stack, explode=True)

    def _raise_stack(self, stack: Stack) -> None:
        """Bring all tiles (shadows, center widgets) to the top of the z-order."""
        for w in stack.widgets:
            if hasattr(w, "_shadow"):
                self._fixed.remove(w._shadow)
                self._fixed.put(w._shadow, w._cur_x + w._shadow_dx, w._cur_y + w._shadow_dy)
            cx = w._cur_x
            cy = w._cur_y
            self._fixed.remove(w)
            self._fixed.put(w, cx, cy)
            if getattr(w, "_center_widget", None) is not None:
                ccx = cx + w._center_tile_w / 2 - w._center_nat_w / 2
                ccy = cy + w._center_tile_h / 2 - w._center_nat_h / 2
                self._fixed.remove(w._center_widget)
                self._fixed.put(w._center_widget, ccx, ccy)
        # Also raise icon and label
        icon = stack.icon_widget
        icon_x = stack.cell_x + stack.cell_w / 2 - _ICON_SIZE / 2
        icon_y = stack.cell_y + stack.cell_h / 2 - _ICON_SIZE / 2
        self._fixed.remove(icon)
        self._fixed.put(icon, icon_x, icon_y)
        label = stack.label_widget
        label_w = 140
        label_x = icon_x + _ICON_SIZE / 2 - label_w / 2
        label_y = icon_y + _ICON_SIZE + 5
        self._fixed.remove(label)
        self._fixed.put(label, label_x, label_y)

    def _on_stack_leave(self, stack: Stack) -> None:
        """Called when mouse leaves any widget belonging to `stack`."""
        stack._hover_count = max(0, stack._hover_count - 1)
        if stack._hover_count > 0:
            return  # mouse moved to another widget in same stack
        # Debounce: collapse only if mouse hasn't re-entered within 250ms.
        # This prevents flicker when cursor crosses the gap between the icon
        # and exploded tiles (both belong to the same stack but GTK fires
        # leave+enter for each widget crossing).
        if stack._collapse_id:
            GLib.source_remove(stack._collapse_id)

        def do_collapse():
            stack._collapse_id = 0
            if stack._hover_count == 0 and self._active_stack is stack:
                self._animate_stack(stack, explode=False)
                self._active_stack = None
            return False

        stack._collapse_id = GLib.timeout_add(250, do_collapse)

    # ── Animation ─────────────────────────────────────────────────────────────

    def _animate_stack(self, stack: Stack, explode: bool) -> None:
        """
        Animate stack tiles using spring physics.

        Explode: stiff spring with slight overshoot — tiles pop out naturally.
        Collapse: overdamped spring — quick clean snap-back, no bounce.

        Velocities are preserved across mid-animation reversals so the motion
        is always continuous (no jarring direction jump).
        """
        if stack._anim_id:
            GLib.source_remove(stack._anim_id)
            stack._anim_id = 0

        to_pos = (
            stack.exploded_pos if explode
            else [(w._orig_x, w._orig_y) for w in stack.widgets]
        )

        stiffness = _SPRING_EXPLODE_STIFFNESS if explode else _SPRING_COLLAPSE_STIFFNESS
        damping   = _SPRING_EXPLODE_DAMPING   if explode else _SPRING_COLLAPSE_DAMPING
        dt        = _ANIM_MS / 1000.0

        # On direction reversal, inherit current velocity (continuous motion).
        # On fresh start (vel was [0,0]), spring launches from rest.

        def tick():
            all_settled = True
            for i, (w, (tx, ty)) in enumerate(zip(stack.widgets, to_pos)):
                vx, vy = stack._vel[i]

                nx, vx = _spring_tick(w._cur_x, vx, tx, stiffness, damping, dt)
                ny, vy = _spring_tick(w._cur_y, vy, ty, stiffness, damping, dt)

                stack._vel[i] = [vx, vy]
                self._fixed.move(w, nx, ny)
                if hasattr(w, "_shadow"):
                    self._fixed.move(w._shadow, nx + w._shadow_dx, ny + w._shadow_dy)
                if getattr(w, "_center_widget", None) is not None:
                    cx = nx + w._center_tile_w / 2 - w._center_nat_w / 2
                    cy = ny + w._center_tile_h / 2 - w._center_nat_h / 2
                    self._fixed.move(w._center_widget, cx, cy)
                w._cur_x = nx
                w._cur_y = ny

                if (abs(nx - tx) > _SPRING_THRESHOLD or
                        abs(ny - ty) > _SPRING_THRESHOLD or
                        abs(vx) > _SPRING_THRESHOLD or
                        abs(vy) > _SPRING_THRESHOLD):
                    all_settled = False

            if all_settled:
                for i, (w, (tx, ty)) in enumerate(zip(stack.widgets, to_pos)):
                    self._fixed.move(w, tx, ty)
                    if hasattr(w, "_shadow"):
                        self._fixed.move(w._shadow, tx + w._shadow_dx, ty + w._shadow_dy)
                    if getattr(w, "_center_widget", None) is not None:
                        cx = tx + w._center_tile_w / 2 - w._center_nat_w / 2
                        cy = ty + w._center_tile_h / 2 - w._center_nat_h / 2
                        self._fixed.move(w._center_widget, cx, cy)
                    w._cur_x = tx
                    w._cur_y = ty
                    stack._vel[i] = [0.0, 0.0]
                stack._anim_id = 0
                stack.exploded = explode
                return False

            stack._anim_id = GLib.timeout_add(_ANIM_MS, tick)
            return False

        stack._anim_id = GLib.timeout_add(_ANIM_MS, tick)

    # ── Keyboard navigation ───────────────────────────────────────────────────

    def _set_focus(self, idx: int) -> None:
        if self._tiles:
            for t in self._tiles:
                t.set_focused(False)
            idx = idx % len(self._tiles)
            self._tiles[idx].set_focused(True)

    def _on_key_pressed(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.cancel_all_animations()
            self.close()
            return True
        if not self._tiles:
            return False
        focused = next((i for i, t in enumerate(self._tiles)
                        if t.has_css_class("tile-focused")), -1)
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and focused >= 0:
            self._on_tile_click(self._tiles[focused]._client.get("address", ""))
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_Tab, Gdk.KEY_l, Gdk.KEY_Down, Gdk.KEY_j):
            self._set_focus(focused + 1)
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_h, Gdk.KEY_Up, Gdk.KEY_k):
            self._set_focus(focused - 1)
            return True
        return False

    # ── Event handlers ────────────────────────────────────────────────────────

    def cancel_all_animations(self) -> None:
        """Cancel all pending GLib timers before the overlay is destroyed."""
        for stack in self._stacks:
            if stack._anim_id:
                GLib.source_remove(stack._anim_id)
                stack._anim_id = 0
            if stack._collapse_id:
                GLib.source_remove(stack._collapse_id)
                stack._collapse_id = 0

    def _on_tile_click(self, address: str) -> None:
        """Focus the clicked window and close the overlay (without quitting the daemon)."""
        client = next(
            (t._client for t in self._tiles if t._client.get("address") == address),
            None,
        )
        batch = ""
        if client:
            at = client.get("at", [0, 0])
            sz = client.get("size", [100, 100])
            cx = at[0] + sz[0] // 2
            cy = at[1] + sz[1] // 2
            batch = f"dispatch movecursor {cx} {cy} ; "
        batch += f"dispatch focuswindow address:{address}"
        self.set_visible(False)
        self.cancel_all_animations()
        subprocess.run(["hyprctl", "--batch", batch], capture_output=True)
        self.close()

    def _on_bg_click(self, gesture, n_press, x, y) -> None:
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is self._root or widget is self._fixed:
            self.cancel_all_animations()
            self.close()
