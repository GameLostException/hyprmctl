"""
src/tiles.py — GTK4 tile widget for a single window.

Two render modes:
  Screenshot: pixbuf pre-scaled to exact tile_w × tile_h, rendered via
              Gtk.Image (reliable in Gtk.Fixed). Dark title bar.
  Colour-fill: app HSL colour background + centered icon + app name + full title.
               Used when no pixbuf available.
"""

from __future__ import annotations

import math
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
    """Muted dark tint of the app's hue — used as colour-fill background."""
    hue = _class_to_hue(app_class)
    # Keep saturation low and lightness dark so it doesn't look like a coloured border
    r, g, b = _hsl_to_rgb(hue, 0.25, 0.18)
    return f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha})"


class TileWidget(Gtk.Box):
    """
    Single window tile.

    Parameters
    ----------
    client:        hyprctl client dict
    on_click:      called with address string on click
    pixbuf:        GdkPixbuf screenshot — enables screenshot mode
    tile_w:        allocated tile width (required for screenshot scaling)
    tile_h:        allocated tile height (required for screenshot scaling)
    title_at_top:  if True, title bar at top; False = bottom.
                   Derived from fan direction so the bar is always on the
                   exposed edge, not covered by the tile stacked above.
    display_name:  human-readable app name (e.g. "Thunar", "PulseAudio")
                   shown in colour-fill mode. Passed from overlay so the
                   same _display_name() lookup is used everywhere.
    """

    def __init__(
        self,
        client: dict,
        on_click=None,
        pixbuf: GdkPixbuf.Pixbuf | None = None,
        tile_w: int = 0,
        tile_h: int = 0,
        title_at_top: bool = True,
        display_name: str = "",
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._client = client
        # Never expand beyond set_size_request — prevents allocation drift in Gtk.Fixed
        self.set_hexpand(False)
        self.set_vexpand(False)

        app_class = client.get("class") or client.get("initialClass") or "unknown"
        title     = client.get("title") or "(no title)"
        address   = client.get("address", "")
        # Fall back to title-cased class if caller didn't supply a display name
        app_name  = display_name or app_class.replace("-", " ").title()

        self._css_class = f"tile-addr-{address.replace('0x', '')}"
        self.add_css_class("tile")
        self.add_css_class("card")          # Adwaita .card gives drop shadow
        self.add_css_class(self._css_class)

        if pixbuf is not None and tile_w > 0 and tile_h > 0:
            self.add_css_class("tile-screenshot")
            self._build_screenshot(pixbuf, app_class, app_name, title, tile_w, tile_h, title_at_top)
            self._css_provider = None
        else:
            self._build_colour_fill(app_class, app_name)
            self._css_provider = self._inject_border_css(app_class, address)

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
        app_name: str,
        title: str,
        tile_w: int,
        tile_h: int,
        title_at_top: bool,
    ) -> None:
        img_h = max(tile_h - _BAR_H, 1)

        scaled = pixbuf.scale_simple(tile_w, img_h, 2)  # BILINEAR

        # Draw the screenshot with Cairo so we can clip to rounded bottom corners.
        # Gtk.Picture cannot be clipped to border-radius without overflow:hidden
        # (not supported in GTK CSS). DrawingArea + Cairo clip is the only reliable way.
        RADIUS = 8.0
        da = Gtk.DrawingArea()
        da.set_size_request(tile_w, img_h)
        da.set_hexpand(False)
        da.set_vexpand(False)

        _pb    = scaled
        _top   = title_at_top   # True → round bottom corners; False → round top corners
        _r     = RADIUS

        def draw_screenshot(widget, ctx, width, height):
            # Clip to rounded rect matching the tile corners
            if _top:
                # title bar at top → picture at bottom → round bottom corners only
                ctx.new_path()
                ctx.move_to(0, 0)
                ctx.line_to(width, 0)
                ctx.line_to(width, height - _r)
                ctx.arc(width - _r, height - _r, _r, 0, math.pi / 2)
                ctx.line_to(_r, height)
                ctx.arc(_r, height - _r, _r, math.pi / 2, math.pi)
                ctx.line_to(0, 0)
            else:
                # title bar at bottom → picture at top → round top corners only
                ctx.new_path()
                ctx.move_to(_r, 0)
                ctx.arc(_r, _r, _r, math.pi, 3 * math.pi / 2)
                ctx.line_to(width - _r, 0)
                ctx.arc(width - _r, _r, _r, 3 * math.pi / 2, 0)
                ctx.line_to(width, height)
                ctx.line_to(0, height)
                ctx.close_path()
            ctx.clip()
            # Paint the pixbuf
            Gdk.cairo_set_source_pixbuf(ctx, _pb, 0, 0)
            ctx.paint()

        da.set_draw_func(draw_screenshot)

        # Title bar: icon + FULL window title (no ellipsis, no class label)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bar.add_css_class("tile-bar")
        bar.add_css_class("tile-bar-top" if title_at_top else "tile-bar-bottom")
        bar.set_size_request(tile_w, _BAR_H)
        # No margin_start/end — margins add to natural width and cause the tile
        # Box to report a wider natural size than tile_w, shifting the shadow.
        bar.set_margin_start(0)
        bar.set_margin_end(0)
        bar.append(self._make_icon(app_class, size=18))

        lbl = Gtk.Label(label=title)
        lbl.set_ellipsize(0)       # no ellipsis — show full title
        lbl.set_hexpand(True)
        lbl.set_xalign(0.0)
        lbl.add_css_class("tile-bar-title")
        bar.append(lbl)

        if title_at_top:
            self.append(bar)
            self.append(da)
        else:
            self.append(da)
            self.append(bar)

    # ── Colour-fill mode ──────────────────────────────────────────────────────

    def _build_colour_fill(self, app_class: str, app_name: str) -> None:
        # Overlay ensures the icon+label column is always centered regardless
        # of how Gtk.Fixed allocates this box.
        overlay = Gtk.Overlay()
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)

        center_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        center_col.set_halign(Gtk.Align.CENTER)
        center_col.set_valign(Gtk.Align.CENTER)

        icon = self._make_icon(app_class, size=_ICON_SIZE)
        icon.set_halign(Gtk.Align.CENTER)
        center_col.append(icon)

        # App name in a semi-transparent pill — readable on any background colour
        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        pill_box.set_halign(Gtk.Align.CENTER)
        pill_box.add_css_class("name-pill")

        name_label = Gtk.Label(label=app_name)
        name_label.set_halign(Gtk.Align.CENTER)
        name_label.set_ellipsize(0)
        name_label.add_css_class("name-pill-text")
        pill_box.append(name_label)
        center_col.append(pill_box)

        overlay.set_child(center_col)
        self.append(overlay)

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

    def _inject_border_css(self, app_class: str, address: str) -> Gtk.CssProvider | None:
        """Inject per-tile CSS. Returns the provider so the overlay can remove it on close."""
        bg       = class_color_css(app_class, alpha=1.0)
        hover_bg = class_color_css(app_class, alpha=0.85)
        cls      = f"tile-addr-{address.replace('0x', '')}"
        css = f"""
        .{cls} {{
            background-color: {bg};
            border-radius: 8px;
        }}
        .{cls}.tile-focused {{
            background-color: {hover_bg};
            outline-width: 2px;
            outline-style: solid;
            outline-color: rgba(61, 174, 233, 1.0);
            outline-offset: -1px;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            return provider
        return None
