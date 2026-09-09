"""
tests/test_layout.py — Tests for the proportional row-packing layout engine.
"""

from src.layout import (
    _find_scale,
    _pack_rows,
    _window_size,
    compute_layout,
    group_by_class,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_client(addr, cls="app", title="window", w=800, h=600):
    return {
        "address": addr,
        "class": cls,
        "title": title,
        "size": [w, h],
        "at": [0, 0],
        "workspace": {"id": 1},
        "hidden": False,
    }


# ── group_by_class ─────────────────────────────────────────────────────────────

class TestGroupByClass:
    def test_single_group(self):
        clients = [make_client("0x1", "firefox"), make_client("0x2", "firefox")]
        assert len(group_by_class(clients)["firefox"]) == 2

    def test_multiple_groups(self):
        clients = [make_client("0x1", "a"), make_client("0x2", "b")]
        assert set(group_by_class(clients).keys()) == {"a", "b"}

    def test_empty(self):
        assert group_by_class([]) == {}

    def test_missing_class_falls_back(self):
        assert "unknown" in group_by_class([{"address": "0x1"}])


# ── _window_size ───────────────────────────────────────────────────────────────

class TestWindowSize:
    def test_normal_size(self):
        c = make_client("0x1", w=1280, h=720)
        assert _window_size(c) == (1280.0, 720.0)

    def test_zero_size_fallback(self):
        c = make_client("0x1", w=0, h=0)
        w, h = _window_size(c)
        assert w > 0 and h > 0

    def test_missing_size_fallback(self):
        w, h = _window_size({"address": "0x1"})
        assert w > 0 and h > 0


# ── _pack_rows ─────────────────────────────────────────────────────────────────

class TestPackRows:
    def test_single_window_one_row(self):
        clients = [make_client("0x1", w=800, h=600)]
        rows = _pack_rows(clients, 0.5, 1000, 16)
        assert len(rows) == 1

    def test_too_wide_wraps_to_next_row(self):
        # Two 800px windows at scale 1.0 with gap 16 need 1616px → won't fit in 1200
        clients = [make_client("0x1", w=800), make_client("0x2", w=800)]
        rows = _pack_rows(clients, 1.0, 1200, 16)
        assert len(rows) == 2

    def test_fits_in_one_row_when_scaled(self):
        clients = [make_client("0x1", w=800), make_client("0x2", w=800)]
        rows = _pack_rows(clients, 0.5, 1000, 16)
        assert len(rows) == 1

    def test_preserves_order(self):
        clients = [make_client(f"0x{i}") for i in range(4)]
        rows = _pack_rows(clients, 0.3, 1920, 16)
        flat = [c for row in rows for c in row]
        assert flat == clients


# ── _find_scale ────────────────────────────────────────────────────────────────

class TestFindScale:
    def test_single_window_fills_screen(self):
        clients = [make_client("0x1", w=1920, h=1080)]
        s = _find_scale(clients, 1820, 980, 16, 24)
        assert 0.9 < s <= 1.0

    def test_many_windows_smaller_scale(self):
        clients = [make_client(f"0x{i}", w=800, h=600) for i in range(12)]
        s = _find_scale(clients, 1820, 980, 16, 24)
        assert s < 0.6   # needs significant scaling for 12 windows

    def test_scale_positive(self):
        clients = [make_client(f"0x{i}") for i in range(6)]
        s = _find_scale(clients, 1820, 980, 16, 24)
        assert s > 0

    def test_layout_fits_after_scale(self):
        """Tiles at the found scale must fit in avail_h."""
        from src.layout import _pack_rows, _total_height
        clients = [make_client(f"0x{i}", w=800, h=600) for i in range(8)]
        avail_w, avail_h, gap, row_gap = 1820.0, 980.0, 16, 24
        s = _find_scale(clients, avail_w, avail_h, gap, row_gap)
        rows = _pack_rows(clients, s, avail_w, gap)
        total_h = _total_height(rows, s, row_gap)
        assert total_h <= avail_h + 1.0   # +1 for float rounding


# ── compute_layout ─────────────────────────────────────────────────────────────

class TestComputeLayout:
    W, H = 1920, 1080

    def test_empty_returns_empty(self):
        assert compute_layout([], self.W, self.H) == []

    def test_one_tile_per_client(self):
        clients = [make_client(f"0x{i}") for i in range(6)]
        assert len(compute_layout(clients, self.W, self.H)) == 6

    def test_all_tiles_within_screen(self):
        clients = [make_client(f"0x{i}", w=800, h=600) for i in range(8)]
        tiles = compute_layout(clients, self.W, self.H, padding=48)
        for t in tiles:
            assert t.x >= 0, f"x={t.x:.0f} negative"
            assert t.y >= 0, f"y={t.y:.0f} negative"
            assert t.x + t.w <= self.W + 1, f"right edge out: x={t.x:.0f} w={t.w:.0f}"
            assert t.y + t.h <= self.H + 1, f"bottom edge out: y={t.y:.0f} h={t.h:.0f}"

    def test_aspect_ratios_preserved(self):
        """Each tile's aspect ratio must match the source window's."""
        clients = [
            make_client("0x1", w=1920, h=1080),  # 16:9
            make_client("0x2", w=1080, h=1920),  # 9:16 portrait
            make_client("0x3", w=800,  h=600),   # 4:3
        ]
        tiles = compute_layout(clients, self.W, self.H)
        src_aspects = [c["size"][0] / c["size"][1] for c in clients]
        for t, expected_aspect in zip(tiles, src_aspects):
            actual = t.w / t.h
            assert abs(actual - expected_aspect) < 0.05, (
                f"aspect mismatch: got {actual:.3f} expected {expected_aspect:.3f}"
            )

    def test_relative_sizes_preserved(self):
        """A window twice as wide as another should produce a tile twice as wide."""
        clients = [
            make_client("0x1", w=1600, h=900),
            make_client("0x2", w=800,  h=900),
        ]
        tiles = compute_layout(clients, self.W, self.H)
        ratio = tiles[0].w / tiles[1].w
        assert abs(ratio - 2.0) < 0.1, f"expected 2:1 width ratio, got {ratio:.2f}"

    def test_no_overlapping_tiles(self):
        clients = [make_client(f"0x{i}", w=800, h=600) for i in range(9)]
        tiles = compute_layout(clients, self.W, self.H, padding=48)
        for i, a in enumerate(tiles):
            for j, b in enumerate(tiles):
                if i >= j:
                    continue
                ox = a.x < b.x + b.w - 1 and a.x + a.w > b.x + 1
                oy = a.y < b.y + b.h - 1 and a.y + a.h > b.y + 1
                assert not (ox and oy), f"tiles {i} and {j} overlap"

    def test_single_window_large(self):
        """One window should fill most of the available area."""
        clients = [make_client("0x1", w=1920, h=1080)]
        tiles = compute_layout(clients, self.W, self.H, padding=48)
        avail_w = self.W - 96
        avail_h = self.H - 96
        assert tiles[0].w > avail_w * 0.7
        assert tiles[0].h > avail_h * 0.7

    def test_order_preserved(self):
        """Tiles must appear in input order (row-major)."""
        clients = [make_client(f"0x{i}") for i in range(5)]
        tiles = compute_layout(clients, self.W, self.H)
        for i, (t, c) in enumerate(zip(tiles, clients)):
            assert t.client["address"] == c["address"], f"order mismatch at {i}"
