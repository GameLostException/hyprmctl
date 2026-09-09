"""
src/icons.py — App icon resolution from .desktop files and GTK icon theme.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

# Directories to scan for .desktop files (in priority order)
_DESKTOP_DIRS = [
    Path.home() / ".local/share/applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
]


@lru_cache(maxsize=256)
def _load_desktop_index() -> dict[str, str]:
    """
    Build a mapping of { app_class_lower -> icon_name } by scanning
    all .desktop files. Cached after first call.
    """
    index: dict[str, str] = {}
    for desktop_dir in _DESKTOP_DIRS:
        if not desktop_dir.exists():
            continue
        for path in desktop_dir.glob("*.desktop"):
            try:
                _parse_desktop_file(path, index)
            except (OSError, UnicodeDecodeError):
                pass
    return index


def _parse_desktop_file(path: Path, index: dict[str, str]) -> None:
    """Extract Name, Exec, and Icon from a .desktop file and populate index."""
    icon_name: str | None = None
    names: list[str] = []

    with path.open(encoding="utf-8", errors="replace") as f:
        in_desktop_entry = False
        for line in f:
            line = line.strip()
            if line == "[Desktop Entry]":
                in_desktop_entry = True
                continue
            if line.startswith("[") and line != "[Desktop Entry]":
                in_desktop_entry = False
                continue
            if not in_desktop_entry:
                continue

            if line.startswith("Icon="):
                icon_name = line[5:].strip()
            elif line.startswith("Name="):
                names.append(line[5:].strip().lower())
            elif line.startswith("Exec="):
                # Extract binary name from Exec= (strip args and path)
                exec_val = line[5:].strip().split()[0] if line[5:].strip() else ""
                exec_base = os.path.basename(exec_val).lower()
                if exec_base:
                    names.append(exec_base)

    # Also index by filename stem (e.g. "firefox.desktop" → "firefox")
    names.append(path.stem.lower())

    if icon_name:
        for name in names:
            if name and name not in index:
                index[name] = icon_name


def find_icon_name(app_class: str) -> str | None:
    """
    Resolve an app_class string to a GTK icon name by consulting .desktop files.
    Returns None if not found.
    """
    index = _load_desktop_index()
    key = app_class.lower()
    # Direct match
    if key in index:
        return index[key]
    # Partial match: first entry whose key contains app_class
    for k, v in index.items():
        if key in k or k in key:
            return v
    return None


def get_icon_path(app_class: str, size: int = 48) -> str | None:
    """
    Resolve app_class to an icon file path on disk.
    Returns an absolute path string or None.
    Searches common icon theme directories.
    """
    icon_name = find_icon_name(app_class)
    if icon_name is None:
        # Try app_class itself as icon name
        icon_name = app_class.lower()

    # Try to find in standard icon dirs
    search_dirs = [
        Path.home() / ".local/share/icons",
        Path("/usr/share/icons/hicolor"),
        Path("/usr/share/icons/Papirus"),
        Path("/usr/share/pixmaps"),
    ]
    size_dir = f"{size}x{size}"
    extensions = [".png", ".svg", ".xpm"]

    for base in search_dirs:
        # Search recursively for size-specific dir first, then any
        candidates = [
            base / "apps" / f"{icon_name}{ext}"
            for ext in extensions
        ] + [
            base / size_dir / "apps" / f"{icon_name}{ext}"
            for ext in extensions
        ]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    # Last resort: pixmaps flat dir
    for ext in extensions:
        p = Path("/usr/share/pixmaps") / f"{icon_name}{ext}"
        if p.exists():
            return str(p)

    return None
