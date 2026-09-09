"""
src/overlay.py — MissionControlOverlay window.

Phase 2: fetches live window data, computes layout, renders TileWidgets.
"""

from __future__ import annotations

import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gdk, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from src.hypr import get_active_monitor, get_active_workspace_clients  # noqa: E402
from src.layout import compute_layout  # noqa: E402
from src.tiles import TileWidget  # noqa: E402

_BASE_CSS = """
/* Root overlay */
.mc-root {
    background-color: rgba(0, 0, 0, 0.72);
}

/* App group label */
.group-label {
    color: rgba(255, 255, 255, 0.45);
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
}

/* Tile shared styles */
.tile {
    padding: 8px;
    border-radius: 8px;
    transition: background-color 80ms ease;
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

/* Empty state */
.mc-empty {
    color: rgba(255, 255, 255, 0.4);
    font-size: 18px;
}
"""


class MissionControlOverlay(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)

        # ── Layer shell ──────────────────────────────────────────────────────
        LayerShell.init_for_window(self)
        LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
        LayerShell.set_exclusive_zone(self, -1)
        LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(self, edge, True)

        self.set_decorated(False)

        # ── Root: fixed layout container ─────────────────────────────────────
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._root.set_hexpand(True)
        self._root.set_vexpand(True)
        self._root.add_css_class("mc-root")
        self.set_child(self._root)

        self._fixed = Gtk.Fixed()
        self._fixed.set_hexpand(True)
        self._fixed.set_vexpand(True)
        self._root.append(self._fixed)

        # ── Keyboard: Escape closes ──────────────────────────────────────────
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # ── Background click closes ──────────────────────────────────────────
        bg_click = Gtk.GestureClick()
        bg_click.connect("pressed", self._on_bg_click)
        self._root.add_controller(bg_click)

        # ── Load shared CSS ──────────────────────────────────────────────────
        provider = Gtk.CssProvider()
        provider.load_from_data(_BASE_CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Tiles are built after the window is mapped (we need the real size)
        self.connect("map", self._on_mapped)

    # ── Tile population ──────────────────────────────────────────────────────

    def _on_mapped(self, _widget) -> None:
        """Called once the window is on screen and has a real size."""
        monitor = get_active_monitor()
        if monitor is None:
            self._show_empty("No monitor detected")
            return

        mon_w = monitor.get("width", 1920)
        mon_h = monitor.get("height", 1080)
        scale = monitor.get("scale", 1.0)
        # Logical pixels = physical / scale
        log_w = int(mon_w / scale)
        log_h = int(mon_h / scale)

        clients = get_active_workspace_clients()
        if not clients:
            self._show_empty("No windows on this workspace")
            return

        tiles = compute_layout(clients, log_w, log_h, padding=48, gap=14)
        self._place_tiles(tiles)

    def _place_tiles(self, tiles) -> None:
        for tile_geo in tiles:
            widget = TileWidget(tile_geo.client, on_click=self._on_tile_click)
            widget.set_size_request(int(tile_geo.w), int(tile_geo.h))
            self._fixed.put(widget, tile_geo.x, tile_geo.y)

    def _show_empty(self, message: str) -> None:
        label = Gtk.Label(label=message)
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        label.set_hexpand(True)
        label.set_vexpand(True)
        label.add_css_class("mc-empty")
        self._root.append(label)

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_tile_click(self, address: str) -> None:
        subprocess.run(
            ["hyprctl", "dispatch", "focuswindow", f"address:{address}"],
            capture_output=True,
        )
        self.close()

    def _on_key_pressed(self, ctrl, keyval, keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_bg_click(self, gesture, n_press, x, y) -> None:
        # Only close if click landed on the background (root box), not a tile
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        if widget is self._root or widget is self._fixed:
            self.close()
