"""
src/overlay.py — MissionControlOverlay window.

Phase 3 additions:
- Keyboard navigation: arrow keys cycle tiles, Enter focuses, Escape closes
- Group labels: app name rendered above each group's first tile
- Hover: delegated to CSS (.tile:hover defined in tiles.py)
- Background click: only closes when clicking the dim, not a tile
"""

from __future__ import annotations

import json
import subprocess

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from src.hypr import get_active_monitor, get_active_workspace_clients  # noqa: E402
from src.layout import compute_layout  # noqa: E402
from src.tiles import TileWidget  # noqa: E402


def _active_layout() -> str:
    """Return the current Hyprland layout name for the active workspace."""
    try:
        result = subprocess.run(
            ["hyprctl", "activeworkspace", "-j"],
            capture_output=True, text=True, check=True,
        )
        ws = json.loads(result.stdout)
        # tiledLayout reflects hawesome's general:layout setting
        return ws.get("tiledLayout", "dwindle")
    except Exception:
        return "dwindle"


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
.mc-empty {
    color: rgba(255, 255, 255, 0.4);
    font-size: 18px;
}
"""

# Vertical offset for group label above the first tile in a group
_GROUP_LABEL_H = 22


class MissionControlOverlay(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)

        # Layer shell
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
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

        mon_w = monitor.get("width", 1920)
        mon_h = monitor.get("height", 1080)
        scale = monitor.get("scale", 1.0)
        log_w = int(mon_w / scale)
        log_h = int(mon_h / scale)

        clients = get_active_workspace_clients()
        if not clients:
            self._show_empty("No windows on this workspace")
            return

        # Extra top padding to make room for group labels
        tiles = compute_layout(clients, log_w, log_h, padding=52, gap=14)
        self._place_tiles(tiles)

    def _place_tiles(self, tiles) -> None:
        # Track which app classes we've already placed a label for
        seen_classes: set[str] = set()

        for tile_geo in tiles:
            app_class = tile_geo.client.get("class") or "unknown"

            # Group label above the first tile of each app class
            if app_class not in seen_classes:
                seen_classes.add(app_class)
                label = Gtk.Label(label=app_class.upper())
                label.add_css_class("group-label")
                label.set_halign(Gtk.Align.START)
                self._fixed.put(label, tile_geo.x + 4, tile_geo.y - _GROUP_LABEL_H)

            widget = TileWidget(tile_geo.client, on_click=self._on_tile_click)
            widget.set_size_request(int(tile_geo.w), int(tile_geo.h))
            self._fixed.put(widget, tile_geo.x, tile_geo.y)
            self._tiles.append(widget)

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
        subprocess.run(
            ["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
            capture_output=True,
        )
        # In monocle layout, focuswindow alone doesn't visually bring the window
        # to the front of the Z-stack. bringactivetotop fixes this.
        if _active_layout() == "monocle":
            subprocess.run(
                ["hyprctl", "dispatch", "bringactivetotop"],
                capture_output=True,
            )
        self.close()

    def _on_bg_click(self, gesture, n_press, x, y) -> None:
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is self._root or widget is self._fixed:
            self.close()
