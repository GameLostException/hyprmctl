"""
src/tiles.py — GTK4 tile widget for a single window.

Each tile shows:
  - A coloured border derived from the app class name
  - The app class as a small header label
  - The window title as the main label
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402


def _class_to_hue(app_class: str) -> float:
    """Deterministic hue (0–360) from app class string."""
    h = 0
    for c in app_class:
        h = (h * 31 + ord(c)) & 0xFFFFFF
    return (h % 360)


def _hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[float, float, float]:
    """Convert HSL (h 0-360, s 0-1, lightness 0-1) to RGB (each 0-1)."""
    h /= 360.0
    if s == 0:
        return lightness, lightness, lightness

    def hue2rgb(p: float, q: float, t: float) -> float:
        t %= 1.0
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = lightness * (1 + s) if lightness < 0.5 else lightness + s - lightness * s
    p = 2 * lightness - q
    return hue2rgb(p, q, h + 1 / 3), hue2rgb(p, q, h), hue2rgb(p, q, h - 1 / 3)


def class_color_css(app_class: str, alpha: float = 0.25) -> str:
    """Return a CSS rgba() string for the tile background of an app class."""
    hue = _class_to_hue(app_class)
    r, g, b = _hsl_to_rgb(hue, 0.55, 0.45)
    return f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, {alpha})"


def class_border_css(app_class: str) -> str:
    """Return a CSS rgba() string for the tile border (more opaque)."""
    hue = _class_to_hue(app_class)
    r, g, b = _hsl_to_rgb(hue, 0.7, 0.55)
    return f"rgba({int(r*255)}, {int(g*255)}, {int(b*255)}, 0.85)"


class TileWidget(Gtk.Box):
    """
    A single window tile. Displays app class + title inside a coloured box.

    Parameters
    ----------
    client : dict
        A hyprctl client dict with at least 'class', 'title', 'address'.
    on_click : callable(address: str) | None
        Called when the tile is clicked. Receives the window address string.
    """

    def __init__(self, client: dict, on_click=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._client = client
        self._on_click_cb = on_click

        app_class = client.get("class") or client.get("initialClass") or "unknown"
        title = client.get("title") or "(no title)"
        address = client.get("address", "")

        # --- CSS classes ---
        self.add_css_class("tile")
        self.add_css_class(f"tile-{app_class.lower().replace(' ', '-')}")

        # Inline CSS for per-app color (dynamic, can't be in static sheet)
        bg = class_color_css(app_class)
        border = class_border_css(app_class)
        self._inject_css(address, bg, border)
        self.add_css_class(f"tile-addr-{address.replace('0x', '')}")

        # --- App class label (small header) ---
        cls_label = Gtk.Label(label=app_class)
        cls_label.set_halign(Gtk.Align.START)
        cls_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        cls_label.add_css_class("tile-class")
        self.append(cls_label)

        # --- Window title ---
        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.set_valign(Gtk.Align.START)
        title_label.set_wrap(True)
        title_label.set_wrap_mode(2)  # PANGO_WRAP_WORD_CHAR
        title_label.set_max_width_chars(30)
        title_label.set_ellipsize(3)
        title_label.add_css_class("tile-title")
        self.append(title_label)

        # Fill remaining space so labels sit at top
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.append(spacer)

        # --- Click handler ---
        if on_click is not None:
            click_ctrl = Gtk.GestureClick()
            click_ctrl.connect("pressed", lambda g, n, x, y: on_click(address))
            self.add_controller(click_ctrl)
            self.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(8)
        self.set_margin_end(8)

    def _inject_css(self, address: str, bg: str, border: str) -> None:
        css_class = f"tile-addr-{address.replace('0x', '')}"
        css = f"""
        .{css_class} {{
            background-color: {bg};
            border: 2px solid {border};
            border-radius: 8px;
        }}
        .{css_class}:hover {{
            background-color: {bg.replace(', 0.25)', ', 0.38)')};
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
