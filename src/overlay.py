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

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from src.hypr import get_active_monitor, get_active_workspace_clients  # noqa: E402
from src.icons import resolve_icon_name  # noqa: E402
from src.layout import compute_layout  # noqa: E402
from src.tiles import TileWidget  # noqa: E402

_ANIM_FPS = 60
_ANIM_MS = 1000 // _ANIM_FPS
_ANIM_DURATION = 220          # ms total animation duration
_ANIM_STEPS = _ANIM_DURATION // _ANIM_MS
_ICON_SIZE = 56               # app icon px at stack center

_BASE_CSS = """
.mc-root {
    background-color: rgba(0, 0, 0, 0.55);
}
.group-label {
    color: rgba(255, 255, 255, 0.55);
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
}
.tile {
    padding: 8px;
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
    background-color: rgba(0, 0, 0, 0.55);
    border-radius: 0 0 8px 8px;
    padding: 4px 6px;
}
.tile-bar-title {
    color: rgba(255, 255, 255, 0.92);
    font-size: 11px;
}
.mc-empty {
    color: rgba(255, 255, 255, 0.4);
    font-size: 18px;
}
.stack-icon {
    border-radius: 8px;
}
"""

# ── Easing ────────────────────────────────────────────────────────────────────

def _ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def _ease_in_cubic(t: float) -> float:
    return t ** 3


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
        # Convert center positions to top-left
        self.exploded_pos = [
            (px - tw / 2, py - th / 2)
            for px, py in raw_positions
        ]

        self.exploded = False
        self._anim_id = 0
        self._hover_count = 0   # widgets in this stack currently under cursor
        self._collapse_id = 0   # pending collapse GLib source id


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
            widget = TileWidget(
                tile_geo.client,
                on_click=self._on_tile_click,
                pixbuf=pixbuf,
                tile_w=int(tile_geo.w),
                tile_h=int(tile_geo.h),
            )
            widget.set_size_request(int(tile_geo.w), int(tile_geo.h))
            widget._orig_x = tile_geo.x
            widget._orig_y = tile_geo.y
            widget._cur_x  = tile_geo.x   # tracks current animated position
            widget._cur_y  = tile_geo.y
            widget._tile_w = tile_geo.w
            widget._tile_h = tile_geo.h
            self._fixed.put(widget, tile_geo.x, tile_geo.y)
            self._tiles.append(widget)

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
            label = Gtk.Label(label=cls)
            label.add_css_class("group-label")
            label.set_halign(Gtk.Align.CENTER)
            label.set_max_width_chars(16)
            label.set_ellipsize(3)
            label_w = 120
            self._fixed.put(
                label,
                icon_x + _ICON_SIZE / 2 - label_w / 2,
                icon_y + _ICON_SIZE + 5,
            )

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

    def _make_stack_icon(self, app_class: str) -> Gtk.Widget:
        """Create the icon widget shown at the stack center."""
        icon_name = resolve_icon_name(app_class)
        if icon_name:
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(_ICON_SIZE)
        else:
            img = Gtk.Label(label=(app_class[:2]).upper())
            img.set_size_request(_ICON_SIZE, _ICON_SIZE)
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
        self._animate_stack(stack, explode=True)

    def _on_stack_leave(self, stack: Stack) -> None:
        """Called when mouse leaves any widget belonging to `stack`."""
        stack._hover_count = max(0, stack._hover_count - 1)
        if stack._hover_count > 0:
            return  # mouse moved to another widget in same stack
        # Debounce: collapse only if mouse hasn't re-entered within 200ms
        if stack._collapse_id:
            GLib.source_remove(stack._collapse_id)

        def do_collapse():
            stack._collapse_id = 0
            if stack._hover_count == 0 and self._active_stack is stack:
                self._animate_stack(stack, explode=False)
                self._active_stack = None
            return False

        stack._collapse_id = GLib.timeout_add(200, do_collapse)

    # ── Animation ─────────────────────────────────────────────────────────────

    def _animate_stack(self, stack: Stack, explode: bool) -> None:
        """Start a smooth position animation for the stack."""
        if stack._anim_id:
            GLib.source_remove(stack._anim_id)
            stack._anim_id = 0

        # Always animate FROM current widget positions (handles mid-anim reversal)
        from_pos = [(w._cur_x, w._cur_y) for w in stack.widgets]
        to_pos   = stack.exploded_pos if explode else \
                   [(w._orig_x, w._orig_y) for w in stack.widgets]

        step = [0]
        ease = _ease_out_cubic if explode else _ease_in_cubic

        def tick():
            step[0] += 1
            t = min(step[0] / _ANIM_STEPS, 1.0)
            et = ease(t)

            for w, (fx, fy), (tx, ty) in zip(stack.widgets, from_pos, to_pos):
                nx = fx + (tx - fx) * et
                ny = fy + (ty - fy) * et
                self._fixed.move(w, nx, ny)
                w._cur_x = nx
                w._cur_y = ny

            if t < 1.0:
                stack._anim_id = GLib.timeout_add(_ANIM_MS, tick)
            else:
                stack._anim_id = 0
                stack.exploded = explode
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

    def _on_tile_click(self, address: str) -> None:
        """Focus the clicked window and close the overlay (without quitting the daemon)."""
        client = next(
            (t._client for t in self._tiles if t._client.get("address") == address),
            None,
        )
        # Warp cursor to target window center so follow_mouse refocuses correctly
        batch = ""
        if client:
            at = client.get("at", [0, 0])
            sz = client.get("size", [100, 100])
            cx = at[0] + sz[0] // 2
            cy = at[1] + sz[1] // 2
            batch = f"dispatch movecursor {cx} {cy} ; "
        batch += f"dispatch focuswindow address:{address}"
        self.set_visible(False)
        subprocess.run(["hyprctl", "--batch", batch], capture_output=True)
        self.close()  # close overlay only — daemon stays alive via hold()

    def _on_bg_click(self, gesture, n_press, x, y) -> None:
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is self._root or widget is self._fixed:
            self.close()
