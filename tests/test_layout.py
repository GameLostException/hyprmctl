"""
tests/test_layout.py — Unit tests for src/layout.py.
Pure functions; no mocking needed.
"""

import pytest
from src.layout import (
    TileGeometry,
    group_by_class,
    compute_layout,
    _fit_in_cell,
    _best_column_count,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_client(addr, cls, title="window", w=800, h=600):
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
        groups = group_by_class(clients)
        assert list(groups.keys()) == ["firefox"]
        assert len(groups["firefox"]) == 2

    def test_multiple_groups(self):
        clients = [
            make_client("0x1", "firefox"),
            make_client("0x2", "kitty"),
            make_client("0x3", "firefox"),
        ]
        groups = group_by_class(clients)
        assert set(groups.keys()) == {"firefox", "kitty"}
        assert len(groups["firefox"]) == 2
        assert len(groups["kitty"]) == 1

    def test_empty(self):
        assert group_by_class([]) == {}

    def test_missing_class_uses_unknown(self):
        clients = [{"address": "0x1", "title": "t", "size": [800, 600], "at": [0, 0]}]
        groups = group_by_class(clients)
        assert "unknown" in groups


# ── _fit_in_cell ───────────────────────────────────────────────────────────────

class TestFitInCell:
    def test_wide_content_in_square_cell(self):
        """16:9 content in a 200×200 cell → constrained by width."""
        w, h = _fit_in_cell(200, 200, 16 / 9)
        assert abs(w - 200) < 0.01
        assert abs(h - 200 * 9 / 16) < 0.01

    def test_tall_content_in_wide_cell(self):
        """9:16 content in a 400×200 cell → constrained by height."""
        w, h = _fit_in_cell(400, 200, 9 / 16)
        assert abs(h - 200) < 0.01
        assert abs(w - 200 * 9 / 16) < 0.01

    def test_exact_fit(self):
        w, h = _fit_in_cell(160, 90, 16 / 9)
        assert abs(w - 160) < 0.01
        assert abs(h - 90) < 0.01


# ── compute_layout ─────────────────────────────────────────────────────────────

class TestComputeLayout:
    W, H = 1920, 1080

    def test_empty_returns_empty(self):
        assert compute_layout([], self.W, self.H) == []

    def test_single_tile_fills_most_of_screen(self):
        clients = [make_client("0x1", "firefox")]
        tiles = compute_layout(clients, self.W, self.H, padding=40, gap=12)
        assert len(tiles) == 1
        t = tiles[0]
        # Tile should be large (at least 60% of available area)
        avail_w = self.W - 80
        avail_h = self.H - 80
        assert t.w > avail_w * 0.6
        assert t.h > avail_h * 0.6

    def test_tiles_within_bounds(self):
        clients = [make_client(f"0x{i}", "firefox") for i in range(6)]
        tiles = compute_layout(clients, self.W, self.H, padding=40, gap=12)
        for t in tiles:
            assert t.x >= 40, f"tile x={t.x} too small"
            assert t.y >= 40, f"tile y={t.y} too small"
            assert t.x + t.w <= self.W - 40 + 1, f"tile right edge out of bounds"
            assert t.y + t.h <= self.H - 40 + 1, f"tile bottom edge out of bounds"

    def test_one_tile_per_client(self):
        clients = [make_client(f"0x{i}", f"app{i}") for i in range(5)]
        tiles = compute_layout(clients, self.W, self.H)
        assert len(tiles) == len(clients)

    def test_groups_are_adjacent(self):
        """Windows of the same app class should appear consecutively."""
        clients = [
            make_client("0x1", "firefox", "Tab 1"),
            make_client("0x2", "kitty",   "term 1"),
            make_client("0x3", "firefox", "Tab 2"),
        ]
        tiles = compute_layout(clients, self.W, self.H)
        classes = [t.client["class"] for t in tiles]
        # firefox has 2 windows → should be sorted first (larger group)
        # then kitty
        assert classes[0] == "firefox"
        assert classes[1] == "firefox"
        assert classes[2] == "kitty"

    def test_aspect_ratio_preserved(self):
        clients = [make_client("0x1", "firefox", w=1600, h=900)]  # 16:9
        tiles = compute_layout(clients, self.W, self.H, padding=40, gap=12)
        t = tiles[0]
        actual_aspect = t.w / t.h
        assert abs(actual_aspect - 16 / 9) < 0.05

    def test_no_overlapping_tiles(self):
        clients = [make_client(f"0x{i}", f"app{i%3}") for i in range(9)]
        tiles = compute_layout(clients, self.W, self.H, padding=40, gap=12)
        for i, a in enumerate(tiles):
            for j, b in enumerate(tiles):
                if i >= j:
                    continue
                overlap_x = a.x < b.x + b.w and a.x + a.w > b.x
                overlap_y = a.y < b.y + b.h and a.y + a.h > b.y
                assert not (overlap_x and overlap_y), (
                    f"Tiles {i} and {j} overlap: "
                    f"({a.x:.0f},{a.y:.0f},{a.w:.0f},{a.h:.0f}) vs "
                    f"({b.x:.0f},{b.y:.0f},{b.w:.0f},{b.h:.0f})"
                )
