"""
tests/test_layout.py — Tests for the stack-based layout engine.
"""

from src.layout import (
    _squarify,
    _window_size,
    compute_layout,
    group_by_class,
)


def make_client(addr, cls="app", title="window", w=800, h=600):
    return {
        "address": addr, "class": cls, "title": title,
        "size": [w, h], "at": [0, 0],
        "workspace": {"id": 1}, "hidden": False,
    }


class TestGroupByClass:
    def test_groups_correctly(self):
        clients = [make_client("0x1", "a"), make_client("0x2", "b"), make_client("0x3", "a")]
        g = group_by_class(clients)
        assert len(g["a"]) == 2 and len(g["b"]) == 1

    def test_empty(self):
        assert group_by_class([]) == {}

    def test_missing_class_unknown(self):
        assert "unknown" in group_by_class([{"address": "0x1"}])


class TestWindowSize:
    def test_normal(self):
        assert _window_size(make_client("0x1", w=1280, h=720)) == (1280.0, 720.0)

    def test_zero_fallback(self):
        w, h = _window_size(make_client("0x1", w=0, h=0))
        assert w > 0 and h > 0


class TestSquarify:
    def test_single_cell_fills_area(self):
        cells = _squarify(1, 1000, 800)
        assert len(cells) == 1
        assert cells[0] == (0.0, 0.0, 1000, 800)

    def test_n_cells_returned(self):
        for n in range(1, 9):
            assert len(_squarify(n, 1920, 1080)) == n

    def test_cells_cover_area(self):
        """All cells must be within the bounding rectangle."""
        for n in [2, 3, 4, 6]:
            cells = _squarify(n, 1920, 1080)
            for x, y, cw, ch in cells:
                assert x >= 0 and y >= 0
                assert x + cw <= 1920 + 0.1
                assert y + ch <= 1080 + 0.1

    def test_four_cells_roughly_square(self):
        cells = _squarify(4, 1920, 1080)
        for _, _, cw, ch in cells:
            ratio = max(cw, ch) / min(cw, ch)
            assert ratio < 3.0  # not wildly elongated


class TestComputeLayout:
    W, H = 1920, 1080

    def test_empty(self):
        assert compute_layout([], self.W, self.H) == []

    def test_one_tile_per_client(self):
        clients = [make_client(f"0x{i}", f"app{i}") for i in range(5)]
        assert len(compute_layout(clients, self.W, self.H)) == 5

    def test_stacks_in_separate_regions(self):
        """Hero tiles of different apps should not share the same cell centre."""
        clients = (
            [make_client(f"0x{i}", "chrome") for i in range(3)] +
            [make_client(f"0x{i+3}", "kitty") for i in range(2)]
        )
        tiles = compute_layout(clients, self.W, self.H)
        chrome = [t for t in tiles if t.client["class"] == "chrome"]
        kitty  = [t for t in tiles if t.client["class"] == "kitty"]
        # Hero of chrome and hero of kitty should be in different screen regions
        cx = sum(t.x for t in chrome) / len(chrome)
        kx = sum(t.x for t in kitty) / len(kitty)
        assert abs(cx - kx) > 100  # clearly different horizontal positions

    def test_fanned_windows_offset(self):
        """Multiple windows in same app must have different positions."""
        clients = [make_client(f"0x{i}", "chrome") for i in range(3)]
        tiles = compute_layout(clients, self.W, self.H)
        positions = [(t.x, t.y) for t in tiles]
        assert len(set(positions)) == 3  # all different

    def test_single_app_no_fan(self):
        """One window per app = no fanning needed, tile within screen."""
        clients = [make_client("0x1", "kitty")]
        tiles = compute_layout(clients, self.W, self.H)
        t = tiles[0]
        assert 0 <= t.x and t.x + t.w <= self.W + 1
        assert 0 <= t.y and t.y + t.h <= self.H + 1

    def test_aspect_ratio_preserved(self):
        clients = [make_client("0x1", "app", w=1920, h=1080)]
        tiles = compute_layout(clients, self.W, self.H)
        t = tiles[0]
        assert abs(t.w / t.h - 16 / 9) < 0.1

    def test_tiles_mostly_within_screen(self):
        """All tiles should be within screen bounds (fanning may push edge tiles slightly)."""
        clients = [make_client(f"0x{i}", f"app{i % 4}") for i in range(8)]
        tiles = compute_layout(clients, self.W, self.H, padding=48)
        for t in tiles:
            # Allow small overshoot from fanning
            assert t.x > -50
            assert t.y > -50
            assert t.x + t.w < self.W + 50
            assert t.y + t.h < self.H + 50
