"""
src/layout.py — Proportional row-packing layout. No GTK, fully unit-testable.

Algorithm — macOS Mission Control style
========================================

Goal: fill the available screen area with scaled-down window thumbnails that
preserve each window's real aspect ratio and relative size.

Steps
-----
1.  Collect real window sizes. If a window has no meaningful size, use 16:9.
2.  Binary-search for a scale factor S (0 < S ≤ 1) such that:
      - Every window is scaled by S.
      - Windows are packed left-to-right into rows (greedy, no sorting by app).
      - The total height of all rows + gaps fits within avail_h.
3.  Once S is found, repack windows into rows and compute final (x, y) for each.
4.  Distribute rows vertically so they fill avail_h evenly.

No grouping by app class — windows are ordered by their original position in the
input list (caller decides order).  The overlay passes clients in the order
returned by hyprctl (roughly Z-order / creation order) which is fine.

Minimum tile size
-----------------
A window is never scaled below MIN_TILE_W × MIN_TILE_H regardless of how many
windows are open.  When there are many small windows the layout may exceed the
screen height slightly — this is preferable to unreadably tiny tiles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MIN_TILE_W = 160   # px — never scale a tile narrower than this
MIN_TILE_H = 100   # px — never scale a tile shorter than this


@dataclass
class TileGeometry:
    x: float
    y: float
    w: float
    h: float
    client: dict[str, Any]


def group_by_class(clients: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group clients by their wm_class (kept for overlay group-label usage)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in clients:
        cls = c.get("class") or c.get("initialClass") or "unknown"
        groups.setdefault(cls, []).append(c)
    return groups


def _window_size(client: dict[str, Any]) -> tuple[float, float]:
    """Return (w, h) for a client, falling back to 16:9 at 800×450."""
    size = client.get("size", [0, 0])
    w, h = float(size[0]), float(size[1])
    if w <= 0 or h <= 0:
        return 800.0, 450.0
    return w, h


def _pack_rows(
    clients: list[dict[str, Any]],
    scale: float,
    avail_w: float,
    gap: float,
) -> list[list[dict[str, Any]]]:
    """
    Greedily pack clients into rows at the given scale.
    Each row is as wide as avail_w allows.
    """
    rows: list[list[dict[str, Any]]] = []
    current_row: list[dict[str, Any]] = []
    current_w = 0.0

    for client in clients:
        w, _ = _window_size(client)
        tw = max(w * scale, MIN_TILE_W)

        if current_row and current_w + gap + tw > avail_w + 0.5:
            rows.append(current_row)
            current_row = [client]
            current_w = tw
        else:
            current_row.append(client)
            current_w += (gap if current_row else 0) + tw

    if current_row:
        rows.append(current_row)

    return rows


def _row_height(row: list[dict[str, Any]], scale: float) -> float:
    """Return the height of a row = max scaled window height in that row."""
    return max(max(_window_size(c)[1] * scale, MIN_TILE_H) for c in row)


def _total_height(
    rows: list[list[dict[str, Any]]],
    scale: float,
    row_gap: float,
) -> float:
    """Total height consumed by all rows at this scale."""
    if not rows:
        return 0.0
    h = sum(_row_height(r, scale) for r in rows)
    h += row_gap * (len(rows) - 1)
    return h


def _find_scale(
    clients: list[dict[str, Any]],
    avail_w: float,
    avail_h: float,
    gap: float,
    row_gap: float,
) -> float:
    """
    Binary search for the largest scale S such that all windows packed into
    rows fit within avail_h.  Clamps to MIN_TILE constraints.
    """
    lo, hi = 0.001, 1.0

    # Quick check: if even scale=1.0 fits, return 1.0
    rows = _pack_rows(clients, 1.0, avail_w, gap)
    if _total_height(rows, 1.0, row_gap) <= avail_h:
        return 1.0

    for _ in range(48):          # 48 iterations → sub-pixel precision
        mid = (lo + hi) / 2
        rows = _pack_rows(clients, mid, avail_w, gap)
        if _total_height(rows, mid, row_gap) <= avail_h:
            lo = mid
        else:
            hi = mid

    return lo


def compute_layout(
    clients: list[dict[str, Any]],
    monitor_w: int,
    monitor_h: int,
    padding: int = 48,
    gap: int = 16,
    row_gap: int = 24,
) -> list[TileGeometry]:
    """
    Compute tile positions using proportional row-packing (macOS style).

    Windows keep their real aspect ratios and relative sizes.
    No grouping — windows are laid out in input order.

    Parameters
    ----------
    clients:    All clients to lay out.
    monitor_w:  Monitor logical width in pixels.
    monitor_h:  Monitor logical height in pixels.
    padding:    Margin around the whole screen (px).
    gap:        Horizontal gap between tiles in a row (px).
    row_gap:    Vertical gap between rows (px).
    """
    if not clients:
        return []

    avail_w = monitor_w - 2 * padding
    avail_h = monitor_h - 2 * padding

    scale = _find_scale(clients, avail_w, avail_h, gap, row_gap)
    rows = _pack_rows(clients, scale, avail_w, gap)

    if not rows:
        return []

    # Distribute rows vertically to fill avail_h
    n_rows = len(rows)
    total_rows_h = sum(_row_height(r, scale) for r in rows)
    total_gap_h = row_gap * (n_rows - 1)
    extra_v = max(0.0, avail_h - total_rows_h - total_gap_h)
    # Spread extra space: half at top, half at bottom, equal between rows
    v_padding = extra_v / (n_rows + 1) if n_rows > 0 else 0.0

    tiles: list[TileGeometry] = []
    y = padding + v_padding

    for row in rows:
        row_h = _row_height(row, scale)

        # Distribute windows horizontally within the row
        # Compute total row width then centre it
        scaled_widths = [max(_window_size(c)[0] * scale, MIN_TILE_W) for c in row]
        total_row_w = sum(scaled_widths) + gap * (len(row) - 1)
        x = padding + (avail_w - total_row_w) / 2   # centre each row

        for client, tw in zip(row, scaled_widths):
            _, ch = _window_size(client)
            th = max(ch * scale, MIN_TILE_H)
            # Align window to bottom of row (tallest window sits flush at row bottom)
            ty = y + (row_h - th)
            tiles.append(TileGeometry(x=x, y=ty, w=tw, h=th, client=client))
            x += tw + gap

        y += row_h + row_gap + v_padding

    return tiles
