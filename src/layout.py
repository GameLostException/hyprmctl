"""
src/layout.py — Pure tile geometry calculation. No GTK, fully unit-testable.

Zone-based layout algorithm
============================

Step 1 — Group & sort
    Group clients by app class. Sort groups by window count descending
    (most windows = most screen real estate).

Step 2 — Partition the screen into zones
    Divide the available area into vertical strips, one per group.
    Each strip's width is proportional to the group's window count
    (so a group with 4 windows gets twice the width of one with 2).

    For a single group the strip is the whole screen.

Step 3 — Tile within each zone
    Inside each strip, find the grid layout (cols × rows) that maximises
    tile area. Each window gets one cell; tiles are aspect-ratio-preserved
    and centred in their cell.

Visual example — 4 × thunar + 2 × kitty on 1920×1080:

    ┌──────────────────────────┬────────────────┐
    │  THUNAR (4)  2/3 width   │ KITTY (2) 1/3  │
    │  ┌────┐ ┌────┐           │  ┌────┐        │
    │  │    │ │    │           │  │    │        │
    │  └────┘ └────┘           │  └────┘        │
    │  ┌────┐ ┌────┐           │  ┌────┐        │
    │  │    │ │    │           │  │    │        │
    │  └────┘ └────┘           │  └────┘        │
    └──────────────────────────┴────────────────┘

Group label is placed above each zone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class TileGeometry:
    x: float
    y: float
    w: float
    h: float
    client: dict[str, Any]


def group_by_class(clients: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group clients by their wm_class, preserving insertion order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in clients:
        cls = c.get("class") or c.get("initialClass") or "unknown"
        groups.setdefault(cls, []).append(c)
    return groups


def _sort_groups(groups: dict[str, list]) -> list[list[dict[str, Any]]]:
    """Return groups sorted by descending window count."""
    return sorted(groups.values(), key=lambda g: len(g), reverse=True)


def _client_aspect(client: dict[str, Any]) -> float:
    """Return width/height aspect ratio, defaulting to 16/9."""
    size = client.get("size", [0, 0])
    w, h = size[0], size[1]
    if h == 0:
        return 16 / 9
    return w / h


def _fit_in_cell(cell_w: float, cell_h: float, aspect: float) -> tuple[float, float]:
    """Scale a rectangle with the given aspect ratio to fit cell_w × cell_h."""
    if cell_w / cell_h >= aspect:
        h = cell_h
        w = h * aspect
    else:
        w = cell_w
        h = w / aspect
    return w, h


def _best_grid(n: int, zone_w: float, zone_h: float, gap: int) -> tuple[int, int]:
    """
    Return (cols, rows) that maximises tile area for n windows in zone_w × zone_h.
    """
    best_cols, best_rows, best_area = 1, n, 0.0
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cell_w = (zone_w - gap * (cols - 1)) / cols
        cell_h = (zone_h - gap * (rows - 1)) / rows
        if cell_w <= 0 or cell_h <= 0:
            break
        area = cell_w * cell_h
        if area > best_area:
            best_area = area
            best_cols, best_rows = cols, rows
    return best_cols, best_rows


def _tile_zone(
    clients: list[dict[str, Any]],
    zone_x: float,
    zone_y: float,
    zone_w: float,
    zone_h: float,
    gap: int,
) -> list[TileGeometry]:
    """Tile `clients` inside a rectangular zone, returning TileGeometry list."""
    n = len(clients)
    if n == 0:
        return []

    cols, rows = _best_grid(n, zone_w, zone_h, gap)
    cell_w = (zone_w - gap * (cols - 1)) / cols
    cell_h = (zone_h - gap * (rows - 1)) / rows

    tiles = []
    for i, client in enumerate(clients):
        col = i % cols
        row = i // cols

        cx = zone_x + col * (cell_w + gap)
        cy = zone_y + row * (cell_h + gap)

        aspect = _client_aspect(client)
        tw, th = _fit_in_cell(cell_w, cell_h, aspect)

        # Centre within cell
        tx = cx + (cell_w - tw) / 2
        ty = cy + (cell_h - th) / 2

        tiles.append(TileGeometry(x=tx, y=ty, w=tw, h=th, client=client))

    return tiles


def compute_layout(
    clients: list[dict[str, Any]],
    monitor_w: int,
    monitor_h: int,
    padding: int = 40,
    gap: int = 12,
    zone_gap: int = 20,
) -> list[TileGeometry]:
    """
    Compute tile positions for all clients using zone-based layout.

    Each app class gets a vertical strip proportional to its window count.
    Within each strip, windows are laid out in the best-fit grid.

    Parameters
    ----------
    clients:    All clients to lay out (will be grouped internally).
    monitor_w:  Monitor logical width in pixels.
    monitor_h:  Monitor logical height in pixels.
    padding:    Margin around the whole screen (px).
    gap:        Gap between tiles within a zone (px).
    zone_gap:   Gap between zone strips (px).
    """
    if not clients:
        return []

    groups = group_by_class(clients)
    sorted_groups = _sort_groups(groups)

    avail_w = monitor_w - 2 * padding
    avail_h = monitor_h - 2 * padding

    # Total window count (denominator for proportional widths)
    total = sum(len(g) for g in sorted_groups)
    n_groups = len(sorted_groups)

    # Total horizontal space consumed by zone gaps
    gap_total = zone_gap * (n_groups - 1)
    strip_pool = avail_w - gap_total  # pixels available for actual zone content

    tiles: list[TileGeometry] = []
    x_cursor = float(padding)

    for group in sorted_groups:
        # Zone width proportional to window count
        zone_w = strip_pool * len(group) / total
        zone_h = float(avail_h)
        zone_x = x_cursor
        zone_y = float(padding)

        # Sort windows within group by title for stable ordering
        sorted_clients = sorted(group, key=lambda c: c.get("title", ""))

        tiles.extend(_tile_zone(sorted_clients, zone_x, zone_y, zone_w, zone_h, gap))
        x_cursor += zone_w + zone_gap

    return tiles
