"""
src/layout.py — Stack-based layout. No GTK, fully unit-testable.

Algorithm — macOS Mission Control style
========================================

Each app class becomes a "stack" — a cluster of windows fanned slightly so
all are visible and clearly grouped.  Stacks are placed across the screen
in roughly equal regions (squarified treemap), each occupying similar area
regardless of window count.

Steps
-----
1.  Group clients by app class → N stacks.
2.  Divide the available area into N cells using a squarified treemap.
    All cells have equal weight (equal area), maximising squareness.
3.  Within each cell, choose a scale for the stack's "hero" window
    (largest window) that fills ~80% of the cell.
4.  Fan remaining windows of the same app behind the hero with a small
    x/y offset per window so they're all visible.
5.  Return one TileGeometry per window, hero last (drawn on top).

Fan layout (3 windows in a stack):
    window[0]  offset (-2*fan, -2*fan)   ← furthest back
    window[1]  offset (-1*fan, -1*fan)
    window[2]  offset (0, 0)             ← hero, on top
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# Maximum tile size as fraction of monitor dimensions.
# Prevents tiles being absurdly large when there are few stacks.
MAX_TILE_W_RATIO = 0.55   # max 55% of monitor width
MAX_TILE_H_RATIO = 0.48   # max 48% of monitor height

# Fan offset per window step (px in overlay space).
# FAN_STEP_Y must be >= the title bar height (28px) so the bar of the tile
# beneath is never covered by the tile stacked on top of it.
FAN_STEP_X = 20
FAN_STEP_Y = 30
# Hero window fills this fraction of its cell
HERO_FILL = 0.78
# Minimum tile dimensions
MIN_TILE_W = 100
MIN_TILE_H = 70


@dataclass
class TileGeometry:
    x: float
    y: float
    w: float
    h: float
    client: dict[str, Any]
    title_at_top: bool = True   # True → title bar on top of tile; False → bottom
    is_hero: bool = True        # True for the frontmost tile in each stack


def group_by_class(clients: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group clients by their wm_class, preserving insertion order."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in clients:
        cls = c.get("class") or c.get("initialClass") or "unknown"
        groups.setdefault(cls, []).append(c)
    return groups


def _window_size(client: dict[str, Any]) -> tuple[float, float]:
    """Return (w, h) falling back to 16:9 at 800×450."""
    size = client.get("size", [0, 0])
    w, h = float(size[0]), float(size[1])
    if w <= 0 or h <= 0:
        return 800.0, 450.0
    return w, h


def _largest_first(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort group so the largest window (by area) is last (hero on top)."""
    return sorted(group, key=lambda c: _window_size(c)[0] * _window_size(c)[1])


# ── Squarified treemap ────────────────────────────────────────────────────────

def _squarify(n: int, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """
    Divide a w×h rectangle into n equal-area cells arranged to be as square
    as possible.  Returns list of (x, y, cell_w, cell_h) for each cell.

    Uses a simple grid approach: find cols×rows such that cols*rows >= n and
    aspect ratio of each cell is as close to 1:1 as possible.
    """
    if n <= 0:
        return []
    if n == 1:
        return [(0.0, 0.0, w, h)]

    best_cols = 1
    best_score = float("inf")
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cell_w = w / cols
        cell_h = h / rows
        # Score: deviation from square aspect ratio
        ratio = max(cell_w, cell_h) / min(cell_w, cell_h) if min(cell_w, cell_h) > 0 else 999
        if ratio < best_score:
            best_score = ratio
            best_cols = cols

    rows = math.ceil(n / best_cols)
    cell_w = w / best_cols
    cell_h = h / rows

    cells = []
    for i in range(n):
        col = i % best_cols
        row = i // best_cols
        cells.append((col * cell_w, row * cell_h, cell_w, cell_h))
    return cells


# ── Stack placement ───────────────────────────────────────────────────────────

def _place_stack(
    group: list[dict[str, Any]],
    cell_x: float,
    cell_y: float,
    cell_w: float,
    cell_h: float,
    padding: float,
    max_tile_w: float = 9999.0,
    max_tile_h: float = 9999.0,
) -> list[TileGeometry]:
    """
    Place all windows in a group as a fanned stack within a cell.
    max_tile_w / max_tile_h cap the hero tile size regardless of cell size.
    title_at_top is derived from FAN_STEP_Y sign (positive = fan SE = title at top).
    """
    inner_w = cell_w - 2 * padding
    inner_h = cell_h - 2 * padding
    if inner_w <= 0 or inner_h <= 0:
        inner_w = max(inner_w, MIN_TILE_W)
        inner_h = max(inner_h, MIN_TILE_H)

    ordered = _largest_first(group)
    n = len(ordered)
    fan_reach_x = FAN_STEP_X * (n - 1)
    fan_reach_y = FAN_STEP_Y * (n - 1)

    # Hero fits in (inner_w - fan_reach) × (inner_h - fan_reach) * HERO_FILL
    hero_avail_w = (inner_w - fan_reach_x) * HERO_FILL
    hero_avail_h = (inner_h - fan_reach_y) * HERO_FILL
    hero_avail_w = max(hero_avail_w, MIN_TILE_W)
    hero_avail_h = max(hero_avail_h, MIN_TILE_H)

    # Scale hero preserving aspect ratio, capped by max tile dimensions
    hw, hh = _window_size(ordered[-1])
    scale = min(hero_avail_w / hw, hero_avail_h / hh)
    # Apply absolute max size cap (prevents oversized tiles with few stacks)
    scale = min(scale, max_tile_w / hw, max_tile_h / hh)
    hero_w = max(hw * scale, MIN_TILE_W)
    hero_h = max(hh * scale, MIN_TILE_H)

    # Centre the whole stack (hero position) in the cell
    hero_x = cell_x + padding + (inner_w - hero_w - fan_reach_x) / 2 + fan_reach_x
    hero_y = cell_y + padding + (inner_h - hero_h - fan_reach_y) / 2 + fan_reach_y

    # Determine title bar placement from fan direction.
    # Back tiles are shifted by (-FAN_STEP_X * back, -FAN_STEP_Y * back) relative
    # to the hero. The exposed edge is the one *opposite* to the fan direction:
    #   fan_dy > 0 → back tiles are above hero → their TOP edge sticks out
    #   fan_dy < 0 → back tiles are below hero → their BOTTOM edge sticks out
    # (FAN_STEP_Y is always ≥ 0 in the current config, so default is top.)
    title_at_top = FAN_STEP_Y >= 0

    tiles = []
    for i, client in enumerate(ordered):
        # i=0 furthest back, i=n-1 is hero (no offset)
        back = (n - 1 - i)
        ox = -back * FAN_STEP_X
        oy = -back * FAN_STEP_Y

        cw, ch = _window_size(client)
        # Scale each window the same as the hero
        tw = max(cw * scale, MIN_TILE_W)
        th = max(ch * scale, MIN_TILE_H)

        tiles.append(TileGeometry(
            x=hero_x + ox,
            y=hero_y + oy,
            w=tw,
            h=th,
            client=client,
            title_at_top=title_at_top,
            is_hero=(i == n - 1),
        ))

    return tiles


# ── Public API ────────────────────────────────────────────────────────────────

def compute_layout(
    clients: list[dict[str, Any]],
    monitor_w: int,
    monitor_h: int,
    padding: int = 48,
    gap: int = 20,
) -> list[TileGeometry]:
    """
    Compute tile positions using stack-based layout.

    Each app class gets one roughly equal cell.  Within each cell, windows
    are fanned so all are visible and clearly grouped.

    Parameters
    ----------
    clients:    All clients to lay out.
    monitor_w:  Monitor logical width in pixels.
    monitor_h:  Monitor logical height in pixels.
    padding:    Margin around the whole screen (px).
    gap:        Gap between cells (px).
    """
    if not clients:
        return []

    groups = group_by_class(clients)
    # Sort: largest group first
    sorted_groups = sorted(groups.values(), key=lambda g: -len(g))
    n = len(sorted_groups)

    avail_w = float(monitor_w - 2 * padding)
    avail_h = float(monitor_h - 2 * padding)

    # Max tile size: hard cap as fraction of monitor regardless of stack count.
    # Prevents single-stack tiles from filling the entire screen.
    max_tile_w = monitor_w * MAX_TILE_W_RATIO
    max_tile_h = monitor_h * MAX_TILE_H_RATIO

    # Squarify into n equal cells, then shrink each by gap/2
    raw_cells = _squarify(n, avail_w, avail_h)
    half_gap = gap / 2

    tiles: list[TileGeometry] = []
    for group, (cx, cy, cw, ch) in zip(sorted_groups, raw_cells):
        # Inset cell by gap
        cell_x = padding + cx + half_gap
        cell_y = padding + cy + half_gap
        cell_w = cw - gap
        cell_h = ch - gap
        tiles.extend(_place_stack(
            group, cell_x, cell_y, cell_w, cell_h, padding=8,
            max_tile_w=max_tile_w, max_tile_h=max_tile_h,
        ))

    return tiles
