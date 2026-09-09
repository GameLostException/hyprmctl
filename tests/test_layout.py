"""
tests/test_layout.py — Unit tests for the zone-based layout engine.
Pure functions; no mocking needed.
"""



from src.layout import (
    _best_grid,
    _fit_in_cell,
    _tile_zone,
    compute_layout,
    group_by_class,
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

    def test_empty(self):
        assert group_by_class([]) == {}

    def test_missing_class_uses_unknown(self):
        clients = [{"address": "0x1", "title": "t", "size": [800, 600], "at": [0, 0]}]
        groups = group_by_class(clients)
        assert "unknown" in groups


# ── _fit_in_cell ───────────────────────────────────────────────────────────────

class TestFitInCell:
    def test_wide_content_in_square_cell(self):
        w, h = _fit_in_cell(200, 200, 16 / 9)
        assert abs(w - 200) < 0.01
        assert abs(h - 200 * 9 / 16) < 0.01

    def test_tall_content_in_wide_cell(self):
        w, h = _fit_in_cell(400, 200, 9 / 16)
        assert abs(h - 200) < 0.01
        assert abs(w - 200 * 9 / 16) < 0.01

    def test_exact_fit(self):
        w, h = _fit_in_cell(160, 90, 16 / 9)
        assert abs(w - 160) < 0.01
        assert abs(h - 90) < 0.01


# ── _best_grid ─────────────────────────────────────────────────────────────────

class TestBestGrid:
    def test_single_window_is_1x1(self):
        cols, rows = _best_grid(1, 800, 600, 12)
        assert cols == 1 and rows == 1

    def test_two_windows_wider_than_tall_prefers_2cols(self):
        # Wide zone → 2 columns fits better than 1col×2rows
        cols, rows = _best_grid(2, 800, 200, 12)
        assert cols == 2

    def test_four_windows_square_zone_prefers_2x2(self):
        cols, rows = _best_grid(4, 800, 800, 12)
        assert cols * rows >= 4

    def test_never_exceeds_window_count(self):
        for n in range(1, 10):
            cols, rows = _best_grid(n, 1600, 900, 12)
            assert cols <= n
            assert cols * rows >= n


# ── _tile_zone ─────────────────────────────────────────────────────────────────

class TestTileZone:
    def test_empty_returns_empty(self):
        assert _tile_zone([], 0, 0, 800, 600, 12) == []

    def test_tiles_within_zone(self):
        clients = [make_client(f"0x{i}", "kitty") for i in range(4)]
        tiles = _tile_zone(clients, 100, 50, 600, 400, 12)
        for t in tiles:
            assert t.x >= 100, f"x={t.x} < zone_x=100"
            assert t.y >= 50, f"y={t.y} < zone_y=50"
            assert t.x + t.w <= 100 + 600 + 1
            assert t.y + t.h <= 50 + 400 + 1

    def test_one_tile_per_client(self):
        clients = [make_client(f"0x{i}", "app") for i in range(5)]
        tiles = _tile_zone(clients, 0, 0, 1000, 800, 12)
        assert len(tiles) == 5

    def test_aspect_ratio_preserved(self):
        clients = [make_client("0x1", "app", w=1600, h=900)]
        tiles = _tile_zone(clients, 0, 0, 800, 600, 12)
        t = tiles[0]
        assert abs(t.w / t.h - 16 / 9) < 0.05


# ── compute_layout (zone-based) ───────────────────────────────────────────────

class TestComputeLayout:
    W, H = 1920, 1080

    def test_empty_returns_empty(self):
        assert compute_layout([], self.W, self.H) == []

    def test_one_tile_per_client(self):
        clients = [make_client(f"0x{i}", f"app{i}") for i in range(5)]
        tiles = compute_layout(clients, self.W, self.H)
        assert len(tiles) == len(clients)

    def test_all_tiles_within_screen(self):
        clients = [make_client(f"0x{i}", f"app{i % 3}") for i in range(6)]
        tiles = compute_layout(clients, self.W, self.H, padding=40)
        for t in tiles:
            assert t.x >= 40, f"x={t.x:.0f} too small"
            assert t.y >= 40, f"y={t.y:.0f} too small"
            assert t.x + t.w <= self.W - 40 + 1, "right edge out of bounds"
            assert t.y + t.h <= self.H - 40 + 1, "bottom edge out of bounds"

    def test_zones_are_horizontally_separated(self):
        """Windows of different apps must not share the same x-range."""
        clients = (
            [make_client(f"0x{i}", "firefox") for i in range(3)] +
            [make_client(f"0x{i+3}", "kitty") for i in range(3)]
        )
        tiles = compute_layout(clients, self.W, self.H, padding=40, zone_gap=20)
        firefox_tiles = [t for t in tiles if t.client["class"] == "firefox"]
        kitty_tiles = [t for t in tiles if t.client["class"] == "kitty"]

        firefox_max_x = max(t.x + t.w for t in firefox_tiles)
        kitty_min_x = min(t.x for t in kitty_tiles)
        # kitty zone starts after firefox zone (with gap)
        assert kitty_min_x > firefox_max_x - 1

    def test_larger_group_gets_more_width(self):
        """A group with 4 windows must occupy more width than one with 1."""
        clients = (
            [make_client(f"0x{i}", "big") for i in range(4)] +
            [make_client("0x10", "small")]
        )
        tiles = compute_layout(clients, self.W, self.H, padding=40)
        big_xs = [t.x for t in tiles if t.client["class"] == "big"]
        small_xs = [t.x for t in tiles if t.client["class"] == "small"]

        big_span = max(t.x + t.w for t in tiles if t.client["class"] == "big") - min(big_xs)
        small_span = max(t.x + t.w for t in tiles if t.client["class"] == "small") - min(small_xs)
        assert big_span > small_span

    def test_proportional_zones_sum_to_available_width(self):
        """Zone widths should sum to available width (minus gaps)."""
        clients = (
            [make_client(f"0x{i}", "firefox") for i in range(4)] +
            [make_client(f"0x{i+4}", "kitty") for i in range(2)]
        )
        padding, zone_gap = 40, 20
        tiles = compute_layout(clients, self.W, self.H, padding=padding, zone_gap=zone_gap)
        # firefox gets 4/6 of strip pool, kitty gets 2/6
        # Total zone spans + 1 gap should equal avail_w
        ff = [t for t in tiles if t.client["class"] == "firefox"]
        kt = [t for t in tiles if t.client["class"] == "kitty"]
        ff_span = max(t.x + t.w for t in ff) - min(t.x for t in ff)
        kt_span = max(t.x + t.w for t in kt) - min(t.x for t in kt)
        # Ratio should be close to 4:2 = 2:1
        assert abs(ff_span / kt_span - 2.0) < 0.5

    def test_no_overlapping_tiles(self):
        clients = [make_client(f"0x{i}", f"app{i % 3}") for i in range(9)]
        tiles = compute_layout(clients, self.W, self.H, padding=40, gap=12)
        for i, a in enumerate(tiles):
            for j, b in enumerate(tiles):
                if i >= j:
                    continue
                overlap_x = a.x < b.x + b.w - 1 and a.x + a.w > b.x + 1
                overlap_y = a.y < b.y + b.h - 1 and a.y + a.h > b.y + 1
                assert not (overlap_x and overlap_y), (
                    f"Tiles {i}({a.client['class']}) and {j}({b.client['class']}) overlap"
                )

    def test_single_app_fills_full_width(self):
        """One app group should span the full available width."""
        clients = [make_client(f"0x{i}", "kitty") for i in range(4)]
        padding = 40
        tiles = compute_layout(clients, self.W, self.H, padding=padding)
        min_x = min(t.x for t in tiles)
        max_x = max(t.x + t.w for t in tiles)
        # Should use most of the available width
        assert min_x >= padding - 1
        assert max_x <= self.W - padding + 1
        assert (max_x - min_x) > (self.W - 2 * padding) * 0.7
