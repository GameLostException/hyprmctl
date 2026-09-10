"""
src/tiles.py — GTK4 tile widget for a single window.

Two render modes:
  Screenshot: pixbuf pre-scaled to exact tile_w × tile_h, rendered via
              Gtk.Image (reliable in Gtk.Fixed). Dark title bar below image.
  Colour-fill: app HSL colour background + icon + class + title.
               Used when no pixbuf available.
"""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GdkPixbuf, Gtk  # noqa: E402

from src.icons import resolve_icon_name  # noqa: E402

_ICON_SIZE = 32
_BAR_H     = 28   # height of title bar in screenshot mode


def _class_to_hue(app_class: str) -> float:
    h = 0
    for c in app_class:
        h = (h * 31 + ord(c)) & 0xFFFFFF
    return h % 360


def _hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[float, float, float]:
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
    hue = _class_to_hue(app_class)
    r, g, b = _hsl_to_rgb(hue, 0.55, 0.45)
    return f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"


class TileWidget(Gtk.Box):
    """
    Single window tile.

    Parameters
    ----------
    client:       hyprctl client dict
    on_click:     called with address string on click
    pixbuf:       GdkPixbuf screenshot — enables screenshot mode
    tile_w:       allocated tile width (required for screenshot scaling)
    tile_h:       allocated tile height (required for screenshot scaling)
    title_at_top: if True, title bar is placed at top of tile;
                  if False, at bottom. Determined by fan direction so the
                  title always sticks out from under the next stacked tile.
    """

    def __init__(
        self,
        client: dict,
        on_click=None,
        pixbuf: GdkPixbuf.Pixbuf | None = None,
        tile_w: int = 0,
        tile_h: int = 0,
        title_at_top: bool = True,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._client = client
        self._on_click_cb = on_click

        app_class = client.get("class") or client.get("initialClass") or "unknown"
        title     = client.get("title") or "(no title)"
        address   = client.get("address", "")

        self._css_class = f"tile-addr-{address.replace('0x', '')}"
        self.add_css_class("tile")
        self.add_css_class(self._css_class)

        if pixbuf is not None and tile_w > 0 and tile_h > 0:
            self.add_css_class("tile-screenshot")
            self._build_screenshot(pixbuf, app_class, title, tile_w, tile_h, title_at_top)
        else:
            self._build_colour_fill(app_class, title, title_at_top)
            self._inject_border_css(app_class, address)

        if on_click is not None:
            click_ctrl = Gtk.GestureClick()
            click_ctrl.connect("pressed", lambda g, n, x, y: on_click(address))
            self.add_controller(click_ctrl)
            self.set_cursor(Gdk.Cursor.new_from_name("pointer", None))

    # ── Screenshot mode ───────────────────────────────────────────────────────

    def _build_screenshot(
        self,
        pixbuf: GdkPixbuf.Pixbuf,
        app_class: str,
        title: str,
        tile_w: int,
        tile_h: int,
        title_at_top: bool,
    ) -> None:
        img_h = max(tile_h - _BAR_H, 1)

        # Pre-scale to exact tile dimensions
        scaled = pixbuf.scale_simple(tile_w, img_h, 2)  # BILINEAR

        # Gdk.Texture → Gtk.Picture with can_shrink=False is the only
        # approach that reliably renders in Gtk.Fixed under GTK4.14+
        tex = Gdk.Texture.new_for_pixbuf(scaled)
        pic = Gtk.Picture.new_for_paintable(tex)
        pic.set_can_shrink(False)
        pic.set_size_request(tile_w, img_h)

        # Title bar: icon + window title
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("tile-bar")
        # Rounded corners follow bar position: top bar → top radius, bottom → bottom
        bar.add_css_class("tile-bar-top" if title_at_top else "tile-bar-bottom")
        bar.set_size_request(tile_w, _BAR_H)
        bar.set_margin_start(4)
        bar.set_margin_end(4)
        bar.append(self._make_icon(app_class, size=18))

        lbl = Gtk.Label(label=title)
        lbl.set_ellipsize(3)
        lbl.set_hexpand(True)
        lbl.set_xalign(0.0)
        lbl.add_css_class("tile-bar-title")
        bar.append(lbl)

        # Order: bar first = top; pic first = bottom bar
        if title_at_top:
            self.append(bar)
            self.append(pic)
        else:
            self.append(pic)
            self.append(bar)

    # ── Colour-fill mode ──────────────────────────────────────────────────────

    def _build_colour_fill(self, app_class: str, title: str, title_at_top: bool) -> None:
        self.set_spacing(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(8)
        self.set_margin_end(8)

        # Icon + class label row
        icon_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon_row.set_halign(Gtk.Align.START)
        icon_row.append(self._make_icon(app_class, size=_ICON_SIZE))

        cls_label = Gtk.Label(label=app_class)
        cls_label.set_halign(Gtk.Align.START)
        cls_label.set_valign(Gtk.Align.CENTER)
        cls_label.set_ellipsize(3)
        cls_label.add_css_class("tile-class")
        icon_row.append(cls_label)

        title_label = Gtk.Label(label=title)
        title_label.set_halign(Gtk.Align.START)
        title_label.set_wrap(True)
        title_label.set_wrap_mode(2)
        title_label.set_max_width_chars(30)
        title_label.set_ellipsize(3)
        title_label.add_css_class("tile-title")

        spacer = Gtk.Box()
        spacer.set_vexpand(True)

        # Stack order: title at top → title row, then icon+spacer at bottom
        #              title at bottom → icon row, spacer, then title at bottom
        if title_at_top:
            self.append(title_label)
            self.append(icon_row)
            self.append(spacer)
        else:
            self.append(icon_row)
            self.append(spacer)
            self.append(title_label)

    # ── Shared ────────────────────────────────────────────────────────────────

    def _make_icon(self, app_class: str, size: int = _ICON_SIZE) -> Gtk.Widget:
        icon_name = resolve_icon_name(app_class)
        if icon_name:
            img = Gtk.Image.new_from_icon_name(icon_name)
            img.set_pixel_size(size)
            img.set_valign(Gtk.Align.CENTER)
            return img
        lbl = Gtk.Label(label=(app_class[:2]).upper())
        lbl.set_size_request(size, size)
        lbl.set_valign(Gtk.Align.CENTER)
        lbl.add_css_class("tile-initials")
        return lbl

    def set_focused(self, focused: bool) -> None:
        if focused:
            self.add_css_class("tile-focused")
        else:
            self.remove_css_class("tile-focused")

    def _inject_border_css(self, app_class: str, address: str) -> None:
        bg       = class_color_css(app_class, alpha=1.0)
        hover_bg = class_color_css(app_class, alpha=0.85)
        cls      = f"tile-addr-{address.replace('0x', '')}"
        css = f"""
        .{cls} {{
            background-color: {bg};
            border-width: 1px;
            border-style: solid;
            border-color: rgba(61, 174, 233, 0.35);
            border-radius: 8px;
        }}
        .{cls}:hover {{
            background-color: {hover_bg};
            border-color: rgba(61, 174, 233, 0.9);
        }}
        .{cls}.tile-focused {{
            border-width: 2px;
            border-color: rgba(61, 174, 233, 1.0);
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
