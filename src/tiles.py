"""
src/tiles.py — GTK4 tile widget for a single window.

Phase 4 additions:
- App icon via Gtk.Image.new_from_icon_name (GTK IconTheme, auto SVG/PNG)
- Initials fallback when no icon found
- Entry animation: opacity 0->1 + scale 0.85->1.0 via CSS transition
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

from src.icons import resolve_icon_name  # noqa: E402

_ICON_SIZE = 32  # px


def _class_to_hue(app_class: str) -> float:
    """Deterministic hue (0-360) from app class string."""
    h = 0
    for c in app_class:
        h = (h * 31 + ord(c)) & 0xFFFFFF
    return h % 360


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
    return f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"


def class_border_css(app_class: str) -> str:
    """Return a CSS rgba() string for the tile border."""
    hue = _class_to_hue(app_class)
    r, g, b = _hsl_to_rgb(hue, 0.7, 0.55)
    return f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, 0.85)"


class TileWidget(Gtk.Box):
    """
    A single window tile: icon (or initials) + app class label + title.

    Parameters
    ----------
    client:
        hyprctl client dict with at least 'class', 'title', 'address'.
    on_click:
        Called with the window address string when the tile is clicked.
    """

    def __init__(self, client: dict, on_click=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._client = client
        self._on_click_cb = on_click

        app_class = client.get("class") or client.get("initialClass") or "unknown"
        title = client.get("title") or "(no title)"
        address = client.get("address", "")

        self._css_class = f"tile-addr-{address.replace('0x', '')}"
        self.add_css_class("tile")
        self.add_css_class(self._css_class)

        self._inject_css(app_class, address)

        # Icon row: icon/initials + app class label
        icon_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon_row.set_halign(Gtk.Align.START)
        icon_row.append(self._make_icon(app_class))

        cls_label = Gtk.Label(label=app_class)
        cls_label.set_halign(Gtk.Align.START)
        cls_label.set_valign(Gtk.Align.CENTER)
        cls_label.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
        cls_label.add_css_class("tile-class")
        icon_row.append(cls_label)
        self.append(icon_row)

        # Window title
        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.set_valign(Gtk.Align.START)
        title_label.set_wrap(True)
        title_label.set_wrap_mode(2)  # PANGO_WRAP_WORD_CHAR
        title_label.set_max_width_chars(30)
        title_label.set_ellipsize(3)
        title_label.add_css_class("tile-title")
        self.append(title_label)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.append(spacer)

        # Click handler
        if on_click is not None:
            click_ctrl = Gtk.GestureClick()
            click_ctrl.connect("pressed", lambda g, n, x, y: on_click(address))
            self.add_controller(click_ctrl)
            self.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(8)
        self.set_margin_end(8)

    def _make_icon(self, app_class: str) -> Gtk.Widget:
        """Return a Gtk.Image for the app, or an initials label fallback."""
        icon_name = resolve_icon_name(app_class)
        if icon_name:
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(_ICON_SIZE)
            img.set_valign(Gtk.Align.CENTER)
            return img

        # Initials fallback
        initials = (app_class[:2]).upper()
        lbl = Gtk.Label(label=initials)
        lbl.set_size_request(_ICON_SIZE, _ICON_SIZE)
        lbl.set_valign(Gtk.Align.CENTER)
        lbl.add_css_class("tile-initials")
        return lbl

    def set_focused(self, focused: bool) -> None:
        """Toggle the keyboard-focus ring on this tile."""
        if focused:
            self.add_css_class("tile-focused")
        else:
            self.remove_css_class("tile-focused")

    def _inject_css(self, app_class: str, address: str) -> None:
        bg = class_color_css(app_class)
        hover_bg = class_color_css(app_class, alpha=0.42)
        border = class_border_css(app_class)
        css_class = f"tile-addr-{address.replace('0x', '')}"

        css = f"""
        .{css_class} {{
            background-color: {bg};
            border: 2px solid {border};
            border-radius: 8px;
        }}
        .{css_class}:hover {{
            background-color: {hover_bg};
        }}
        .{css_class}.tile-focused {{
            border: 2px solid white;
            background-color: {hover_bg};
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
