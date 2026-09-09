"""
src/layout.py — Pure tile geometry calculation. No GTK, fully unit-testable.

Algorithm:
  1. Group clients by wm_class.
  2. Sort groups by window count descending (largest app first).
  3. Flatten into a single ordered list of clients (within each group, sort by title).
  4. Compute a grid that fits all tiles into the monitor area.
  5. Scale each tile to its cell preserving the window's aspect ratio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    """Return groups as a list sorted by descending window count."""
    return sorted(groups.values(), key=lambda g: len(g), reverse=True)


def _client_aspect(client: dict[str, Any]) -> float:
    """Return width/height aspect ratio for a client, defaulting to 16/9."""
    size = client.get("size", [0, 0])
    w, h = size[0], size[1]
    if h == 0:
        return 16 / 9
    return w / h


def compute_layout(
    clients: list[dict[str, Any]],
    monitor_w: int,
    monitor_h: int,
    padding: int = 40,
    gap: int = 12,
) -> list[TileGeometry]:
    """
    Compute tile positions for all clients within the monitor bounds.

    Returns a list of TileGeometry objects, one per client, in the same order
    as the (grouped, sorted) input.
    """
    if not clients:
        return []

    groups = group_by_class(clients)
    ordered: list[dict[str, Any]] = []
    for group in _sort_groups(groups):
        ordered.extend(sorted(group, key=lambda c: c.get("title", "")))

    n = len(ordered)

    # Available area after padding
    avail_w = monitor_w - 2 * padding
    avail_h = monitor_h - 2 * padding

    # Find the best number of columns: minimise wasted space
    best_cols = _best_column_count(n, avail_w, avail_h, gap)
    rows = math.ceil(n / best_cols)

    cell_w = (avail_w - gap * (best_cols - 1)) / best_cols
    cell_h = (avail_h - gap * (rows - 1)) / rows

    tiles: list[TileGeometry] = []
    for i, client in enumerate(ordered):
        col = i % best_cols
        row = i // best_cols

        # Cell origin
        cx = padding + col * (cell_w + gap)
        cy = padding + row * (cell_h + gap)

        # Scale tile to fit cell preserving aspect ratio
        aspect = _client_aspect(client)
        tw, th = _fit_in_cell(cell_w, cell_h, aspect)

        # Centre within cell
        tx = cx + (cell_w - tw) / 2
        ty = cy + (cell_h - th) / 2

        tiles.append(TileGeometry(x=tx, y=ty, w=tw, h=th, client=client))

    return tiles


def _fit_in_cell(cell_w: float, cell_h: float, aspect: float) -> tuple[float, float]:
    """Scale a rectangle with the given aspect ratio to fit inside cell_w × cell_h."""
    if cell_w / cell_h >= aspect:
        # Cell is wider than content → constrained by height
        h = cell_h
        w = h * aspect
    else:
        # Cell is taller than content → constrained by width
        w = cell_w
        h = w / aspect
    return w, h


def _best_column_count(
    n: int, avail_w: float, avail_h: float, gap: int
) -> int:
    """Try all column counts and return the one with the largest minimum tile area."""
    best_cols = 1
    best_area = 0.0
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cell_w = (avail_w - gap * (cols - 1)) / cols
        cell_h = (avail_h - gap * (rows - 1)) / rows
        if cell_w <= 0 or cell_h <= 0:
            break
        area = cell_w * cell_h
        if area > best_area:
            best_area = area
            best_cols = cols
    return best_cols
