"""
src/thumbnails.py — Background window capture daemon.

Subscribes to Hyprland's activewindow events. Each time a window becomes
active (= it's visually on top), captures it immediately via grim and
caches the pixbuf.  At overlay open time, the cache is served instantly
with no delay.

Usage
-----
    from src.thumbnails import ThumbnailCache
    cache = ThumbnailCache()
    cache.start()          # launch background thread
    ...
    pixbuf = cache.get("0xdeadbeef")   # None if not captured yet
    cache.stop()
"""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import threading
from typing import Any

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

_TMP_DIR    = tempfile.gettempdir()
_TIMEOUT    = 2.0   # grim per-capture timeout (seconds)
_CACHE_MAX  = 64    # max cached entries (evict oldest)


def _tmp_path(address: str) -> str:
    return os.path.join(_TMP_DIR, f"hyprmctl-{address.replace('0x','')}.png")


def _capture_now(client: dict[str, Any]) -> GdkPixbuf.Pixbuf | None:
    """
    Capture the window described by `client` via grim.
    The window MUST be visually on top when this is called.
    Returns a GdkPixbuf or None on any failure.
    """
    at   = client.get("at",   [0, 0])
    size = client.get("size", [0, 0])
    addr = client.get("address", "unknown")
    w, h = int(size[0]), int(size[1])
    if w <= 0 or h <= 0:
        return None

    out = _tmp_path(addr)
    geo = f"{int(at[0])},{int(at[1])} {w}x{h}"
    try:
        r = subprocess.run(
            ["grim", "-g", geo, out],
            capture_output=True, timeout=_TIMEOUT,
        )
        if r.returncode != 0 or not os.path.exists(out):
            return None
        return GdkPixbuf.Pixbuf.new_from_file(out)
    except Exception:
        return None
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


class ThumbnailCache:
    """
    Background daemon: listens to Hyprland activewindow events,
    captures each newly focused window, stores pixbufs in a dict.
    """

    def __init__(self) -> None:
        self._cache: dict[str, GdkPixbuf.Pixbuf] = {}
        self._order: list[str] = []   # insertion order for LRU eviction
        self._lock  = threading.Lock()
        self._stop  = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background capture thread. Captures the active window immediately."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get(self, address: str) -> GdkPixbuf.Pixbuf | None:
        with self._lock:
            return self._cache.get(address)

    def capture_active_now(self) -> None:
        """Capture the currently active window immediately (call at startup)."""
        threading.Thread(target=self._capture_active, daemon=True).start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _store(self, address: str, pixbuf: GdkPixbuf.Pixbuf) -> None:
        with self._lock:
            if address not in self._cache:
                self._order.append(address)
            self._cache[address] = pixbuf
            # Evict oldest if over limit
            while len(self._order) > _CACHE_MAX:
                evict = self._order.pop(0)
                self._cache.pop(evict, None)

    def _capture_active(self) -> None:
        """Fetch the active window from hyprctl and capture it."""
        try:
            r = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            import json
            client = json.loads(r.stdout)
            addr = client.get("address")
            if not addr:
                return
            pixbuf = _capture_now(client)
            if pixbuf is not None:
                self._store(addr, pixbuf)
        except Exception:
            pass

    def _run(self) -> None:
        """Main loop: subscribe to Hyprland socket2 and handle events."""
        instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        uid      = os.getuid()

        # Find the active socket
        sock_dir = f"/run/user/{uid}/hypr"
        if not instance:
            try:
                entries = [e for e in os.listdir(sock_dir) if not e.endswith(".log")]
                if entries:
                    instance = sorted(entries)[-1]
            except OSError:
                return

        sock_path = f"{sock_dir}/{instance}/.socket2.sock"

        # Capture current active window before subscribing
        self._capture_active()

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(sock_path)
                buf = ""
                while not self._stop.is_set():
                    try:
                        data = s.recv(4096).decode("utf-8", errors="replace")
                    except TimeoutError:
                        continue
                    if not data:
                        break
                    buf += data
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._handle_event(line.strip())
        except Exception:
            pass

    def _handle_event(self, line: str) -> None:
        if ">>" not in line:
            return
        event, _, payload = line.partition(">>")
        if event != "activewindow":
            return

        # activewindow payload is "class,title" — we need the address
        # Use a quick hyprctl call to get the full client dict
        threading.Thread(
            target=self._capture_active, daemon=True
        ).start()


# ── Module-level singleton ────────────────────────────────────────────────────

_cache: ThumbnailCache | None = None


def get_cache() -> ThumbnailCache:
    """Return (and lazily start) the module-level singleton cache."""
    global _cache
    if _cache is None:
        _cache = ThumbnailCache()
        _cache.start()
    return _cache
