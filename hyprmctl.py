#!/usr/bin/env python3
"""
hyprmctl — Mission Control for Hyprland
Phase 1: Overlay shell — full-screen dimmed overlay, closes on Escape or click outside.
"""

import os
import sys

# gtk4-layer-shell must be preloaded before libwayland-client.
# If not already set, re-exec this script with LD_PRELOAD injected.
_LAYER_SHELL_SO = "/usr/lib/libgtk4-layer-shell.so"
if os.path.exists(_LAYER_SHELL_SO) and _LAYER_SHELL_SO not in os.environ.get("LD_PRELOAD", ""):
    os.environ["LD_PRELOAD"] = _LAYER_SHELL_SO
    os.execv(sys.executable, [sys.executable] + sys.argv)
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")

from gi.repository import Gtk, Gdk, Gtk4LayerShell as GtkLayerShell, GLib


class MissionControlOverlay(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)

        # --- Layer shell setup ---
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_exclusive_zone(self, -1)           # don't push other surfaces
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        # Anchor to all four edges → full-screen
        for edge in (
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
            GtkLayerShell.Edge.RIGHT,
        ):
            GtkLayerShell.set_anchor(self, edge, True)

        # --- Window properties ---
        self.set_decorated(False)

        # --- Root widget: semi-transparent black overlay ---
        self.overlay_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay_box.set_halign(Gtk.Align.FILL)
        self.overlay_box.set_valign(Gtk.Align.FILL)
        self.overlay_box.add_css_class("mc-root")
        self.set_child(self.overlay_box)

        # --- Placeholder label (Phase 1) ---
        label = Gtk.Label(label="Mission Control — Phase 1\n\nPress Escape or click to close")
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        label.set_hexpand(True)
        label.set_vexpand(True)
        label.add_css_class("mc-hint")
        self.overlay_box.append(label)

        # --- Key handler: Escape closes ---
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        # --- Click handler: click on background closes ---
        click_ctrl = Gtk.GestureClick()
        click_ctrl.connect("pressed", self._on_click)
        self.overlay_box.add_controller(click_ctrl)

        # Load CSS
        self._load_css()

    def _load_css(self):
        css = b"""
        .mc-root {
            background-color: rgba(0, 0, 0, 0.75);
        }
        .mc-hint {
            color: rgba(255, 255, 255, 0.6);
            font-size: 18px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _on_key_pressed(self, ctrl, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _on_click(self, gesture, n_press, x, y):
        self.close()


class MissionControlApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.boris.hyprmctl")
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        win = MissionControlOverlay(app)
        win.present()


def main():
    app = MissionControlApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
