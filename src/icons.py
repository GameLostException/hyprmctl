"""
src/icons.py — App icon resolution via GTK4 IconTheme + .desktop file index.

Strategy (in order):
1. Look up app_class directly in the GTK icon theme (handles most apps).
2. Check .desktop files to get the declared Icon= name, then look that up.
3. Try common fallback icon names (app-related generic icons).
4. Return None — caller shows initials fallback.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk  # noqa: E402

# Directories to scan for .desktop files
_DESKTOP_DIRS = [
    Path.home() / ".local/share/applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
]


@lru_cache(maxsize=1)
def _get_theme() -> Gtk.IconTheme | None:
    """Return the GTK icon theme for the default display."""
    try:
        display = Gdk.Display.get_default()
        if display is None:
            return None
        return Gtk.IconTheme.get_for_display(display)
    except Exception:
        return None


def _theme_has(name: str) -> bool:
    theme = _get_theme()
    if theme is None:
        return False
    return theme.has_icon(name)


@lru_cache(maxsize=256)
def _build_desktop_index() -> dict[str, str]:
    """Map app_class_lower -> icon_name from .desktop files."""
    index: dict[str, str] = {}
    for desktop_dir in _DESKTOP_DIRS:
        if not desktop_dir.exists():
            continue
        for path in desktop_dir.glob("*.desktop"):
            try:
                _parse_desktop(path, index)
            except (OSError, UnicodeDecodeError):
                pass
    return index


def _parse_desktop(path: Path, index: dict[str, str]) -> None:
    icon_name: str | None = None
    keys: list[str] = [path.stem.lower()]

    with path.open(encoding="utf-8", errors="replace") as f:
        in_entry = False
        for line in f:
            line = line.strip()
            if line == "[Desktop Entry]":
                in_entry = True
                continue
            if line.startswith("[") and line != "[Desktop Entry]":
                in_entry = False
                continue
            if not in_entry:
                continue
            if line.startswith("Icon="):
                icon_name = line[5:].strip()
            elif line.startswith("Name="):
                keys.append(line[5:].strip().lower())
            elif line.startswith("Exec="):
                exe = line[5:].strip().split()[0] if line[5:].strip() else ""
                base = os.path.basename(exe).lower()
                if base:
                    keys.append(base)

    if icon_name:
        for k in keys:
            if k and k not in index:
                index[k] = icon_name


def resolve_icon_name(app_class: str) -> str | None:
    """
    Return a GTK icon theme name for an app class, or None.

    Tries: direct class name, desktop file lookup, common fallbacks.
    """
    candidates = _candidates(app_class)
    theme = _get_theme()
    if theme is None:
        return None
    for name in candidates:
        if theme.has_icon(name):
            return name
    return None


def _candidates(app_class: str) -> list[str]:
    """Generate icon name candidates for an app class, best-first."""
    cls = app_class.lower()
    names: list[str] = [cls]

    # Desktop file lookup
    idx = _build_desktop_index()
    if cls in idx:
        names.append(idx[cls])
    # Partial match
    for k, v in idx.items():
        if (cls in k or k in cls) and v not in names:
            names.append(v)
            break

    # Common generic fallbacks
    names += ["application-x-executable", "application-default-icon"]
    return names
