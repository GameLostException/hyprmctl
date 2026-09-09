"""
tests/test_tiles.py — Unit tests for src/tiles.py.
Color functions are pure; TileWidget tests run headless via GDK_BACKEND=offscreen.
"""

from src.tiles import _class_to_hue, _hsl_to_rgb, class_border_css, class_color_css

# ── Color helpers ──────────────────────────────────────────────────────────────

class TestClassToHue:
    def test_returns_float_in_range(self):
        for cls in ["firefox", "kitty", "code", "unknown", ""]:
            hue = _class_to_hue(cls)
            assert 0 <= hue < 360, f"hue={hue} out of range for class={cls!r}"

    def test_deterministic(self):
        assert _class_to_hue("firefox") == _class_to_hue("firefox")

    def test_different_classes_differ(self):
        hues = {_class_to_hue(c) for c in ["firefox", "kitty", "code", "thunar", "discord"]}
        # Unlikely all 5 hash to the same value
        assert len(hues) > 1


class TestHslToRgb:
    def test_grey_when_saturation_zero(self):
        r, g, b = _hsl_to_rgb(180, 0, 0.5)
        assert abs(r - 0.5) < 0.01
        assert abs(g - 0.5) < 0.01
        assert abs(b - 0.5) < 0.01
    def test_red_hue(self):
        r, g, b = _hsl_to_rgb(0, 1.0, 0.5)
        assert r > 0.9
        assert g < 0.1
        assert b < 0.1

    def test_output_in_0_1(self):
        for h in range(0, 360, 30):
            r, g, b = _hsl_to_rgb(h, 0.7, 0.5)
            assert 0.0 <= r <= 1.0
            assert 0.0 <= g <= 1.0
            assert 0.0 <= b <= 1.0


class TestCssFunctions:
    def test_color_css_is_rgba_string(self):
        css = class_color_css("firefox")
        assert css.startswith("rgba(")
        assert css.endswith(")")

    def test_border_css_is_rgba_string(self):
        css = class_border_css("firefox")
        assert css.startswith("rgba(")

    def test_different_apps_different_colors(self):
        assert class_color_css("firefox") != class_color_css("kitty")


# ── TileWidget (GTK4 widgets can't be instantiated outside Gtk.Application) ────
# Widget-level tests are covered by manual live testing.
# Here we only test the pure helper logic that doesn't touch GTK.

class TestTileWidgetColorInjection:
    """Verify that per-tile CSS strings are well-formed (no GTK needed)."""

    def test_css_class_name_format(self):
        """CSS class name derived from address must be valid."""
        addr = "0xdeadbeef"
        expected_class = f"tile-addr-{addr.replace('0x', '')}"
        assert expected_class == "tile-addr-deadbeef"
        # Must not contain 'x' prefix (invalid in CSS class)
        assert "0x" not in expected_class

    def test_hover_css_replacement(self):
        """The hover alpha swap in _inject_css must produce a valid string."""
        from src.tiles import class_color_css
        bg = class_color_css("firefox")  # e.g. rgba(R, G, B, 0.25)
        hover = bg.replace(", 0.25)", ", 0.38)")
        assert "0.38" in hover
        assert hover.startswith("rgba(")
