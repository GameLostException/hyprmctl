"""
src/overlay.py — MissionControlOverlay window.

Phase 3 additions:
- Keyboard navigation: arrow keys cycle tiles, Enter focuses, Escape closes
- Group labels: app name rendered above each group's first tile
- Hover: delegated to CSS (.tile:hover defined in tiles.py)
- Background click: only closes when clicking the dim, not a tile
"""

from __future__ import annotations

import subprocess

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from src.hypr import get_active_monitor, get_active_workspace_clients  # noqa: E402
from src.layout import compute_layout  # noqa: E402
from src.tiles import TileWidget  # noqa: E402

_BASE_CSS = """
.mc-root {
    background-color: rgba(0, 0, 0, 0.72);
}
.group-label {
    color: rgba(255, 255, 255, 0.45);
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
.mc-empty {
    color: rgba(255, 255, 255, 0.4);
    font-size: 18px;
}
/* Open animation: tiles fade + scale in */
.tile-animate {
    opacity: 0;
    transition: opacity 140ms ease, transform 140ms ease;
}
.tile-animate-in {
    opacity: 1;
}
"""

# Vertical offset for group label below the hero tile
_GROUP_LABEL_OFFSET = 6


class MissionControlOverlay(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)

        # Layer shell
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.ON_DEMAND)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self, edge, True)

        self.set_decorated(False)

        # Root box + fixed layout
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._root.set_hexpand(True)
        self._root.set_vexpand(True)
        self._root.add_css_class("mc-root")
        self.set_child(self._root)

        self._fixed = Gtk.Fixed()
        self._fixed.set_hexpand(True)
        self._fixed.set_vexpand(True)
        self._root.append(self._fixed)

        # Keyboard nav state
        self._tiles: list[TileWidget] = []
        self._focus_idx: int = -1

        # Key handler
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Background click
        bg_click = Gtk.GestureClick()
        bg_click.connect("pressed", self._on_bg_click)
        self._root.add_controller(bg_click)

        # Shared CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(_BASE_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self.connect("map", self._on_mapped)

    # ── Tile population ──────────────────────────────────────────────────────

    def _on_mapped(self, _widget) -> None:
        monitor = get_active_monitor()
        if monitor is None:
            self._show_empty("No monitor detected")
            return

        # Pin overlay to the active monitor
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

        tiles = compute_layout(clients, log_w, log_h, padding=52, gap=14)
        self._place_tiles(tiles)

    def _place_tiles(self, tiles) -> None:
        from collections import defaultdict
        by_class: dict = defaultdict(list)
        for tile_geo in tiles:
            cls = tile_geo.client.get("class") or "unknown"
            by_class[cls].append(tile_geo)

        # Track heroes for label placement
        heroes: dict = {}
        for cls, group_tiles in by_class.items():
            heroes[cls] = group_tiles[-1]

        # Place tiles — hero last per group so it's on top in z-order
        for tile_geo in tiles:
            widget = TileWidget(tile_geo.client, on_click=self._on_tile_click)
            widget.set_size_request(int(tile_geo.w), int(tile_geo.h))
            widget.add_css_class("tile-animate")
            widget._geo = tile_geo  # store for expand/collapse
            self._fixed.put(widget, tile_geo.x, tile_geo.y)
            self._tiles.append(widget)

            delay = 20 + len(self._tiles) * 15
            GLib.timeout_add(delay, self._animate_in, widget)

        # Attach hover-expand to each stack group
        for cls, group_tiles in by_class.items():
            widgets = [t for t in self._tiles if t._geo in group_tiles]
            self._attach_stack_hover(widgets)

        # Label below each hero
        for cls, hero in heroes.items():
            label = Gtk.Label(label=cls.upper())
            label.add_css_class("group-label")
            label.set_halign(Gtk.Align.CENTER)
            self._fixed.put(label, hero.x, hero.y + hero.h + 6)

    def _attach_stack_hover(self, widgets: list) -> None:
        """
        On hover-enter any tile in the stack: fan all tiles out so each has
        a clearly clickable region. On hover-leave: collapse back.
        """
        if len(widgets) <= 1:
            return

        # Compute expanded positions: spread tiles horizontally with overlap
        # Each tile shifts right by ~60% of its width so titles are visible
        def expand():
            for i, w in enumerate(widgets):
                geo = w._geo
                shift = i * int(geo.w * 0.28)
                self._fixed.move(w, geo.x + shift, geo.y)

        def collapse():
            for w in widgets:
                geo = w._geo
                self._fixed.move(w, geo.x, geo.y)

        for w in widgets:
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda *_: expand())
            motion.connect("leave", lambda *_: GLib.timeout_add(300, lambda: collapse() or False))
            w.add_controller(motion)

    @staticmethod
    def _animate_in(widget: Gtk.Widget) -> bool:
        widget.add_css_class("tile-animate-in")
        return False  # don't repeat

    def _show_empty(self, message: str) -> None:
        label = Gtk.Label(label=message)
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        label.set_hexpand(True)
        label.set_vexpand(True)
        label.add_css_class("mc-empty")
        self._root.append(label)

    # ── Keyboard navigation ──────────────────────────────────────────────────

    def _set_focus(self, idx: int) -> None:
        """Move keyboard focus to tile at idx, clearing previous."""
        if self._focus_idx >= 0 and self._focus_idx < len(self._tiles):
            self._tiles[self._focus_idx].set_focused(False)
        self._focus_idx = idx % len(self._tiles) if self._tiles else -1
        if self._focus_idx >= 0:
            self._tiles[self._focus_idx].set_focused(True)

    def _on_key_pressed(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True

        if not self._tiles:
            return False

        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if self._focus_idx >= 0:
                addr = self._tiles[self._focus_idx]._client.get("address", "")
                self._on_tile_click(addr)
            return True

        # Arrow keys: move focus
        if keyval in (Gdk.KEY_Right, Gdk.KEY_Tab, Gdk.KEY_l):
            self._set_focus(self._focus_idx + 1)
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_h):
            self._set_focus(self._focus_idx - 1)
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_j):
            self._set_focus(self._focus_idx + 1)
            return True
        if keyval in (Gdk.KEY_Up, Gdk.KEY_k):
            self._set_focus(self._focus_idx - 1)
            return True

        return False

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_tile_click(self, address: str) -> None:
        # follow_mouse=1 means when this overlay surface is destroyed, Hyprland
        # re-focuses whatever window is under the cursor. In monocle all windows
        # are stacked at the same position so the previously-focused one always
        # wins unless we move the cursor into the target window first.
        #
        # Fix: warp cursor to target window's center, then focuswindow.
        # When the overlay closes, follow_mouse re-evaluates at the new cursor
        # position which is now over the target window — focus sticks.
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
        subprocess.run(["hyprctl", "--batch", batch], capture_output=True)
        self.get_application().quit()

    def _on_bg_click(self, gesture, n_press, x, y) -> None:
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is self._root or widget is self._fixed:
            self.close()
