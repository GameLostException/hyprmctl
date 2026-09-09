"""
src/thumbnails.py — Rolling window capture daemon.

Continuously cycles through ALL visible windows, capturing one every
_ROLL_INTERVAL seconds.  With 20 windows at 0.5s intervals, every window
is refreshed approximately every 10s.

No burst load — one grim call at a time, evenly spread.
All pixbufs stored in RAM only (no disk writes).
Captures are downscaled to _THUMB_MAX_W × _THUMB_MAX_H to save RAM.

Effective RAM: ~30MB for 20 windows.
Effective CPU: one screencopy call per ~1.1s (0.5s sleep + 0.6s grim).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from typing import Any

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

_TIMEOUT       = 2.0   # grim per-capture timeout (seconds)
_CACHE_MAX     = 128   # max cached entries (evict oldest beyond this)
_ROLL_INTERVAL = 0.5   # sleep between captures (effective interval = this + capture time)
_THUMB_MAX_W   = 800   # max width of stored pixbuf
_THUMB_MAX_H   = 500   # max height of stored pixbuf


# ── Capture ───────────────────────────────────────────────────────────────────

def _capture_now(client: dict[str, Any]) -> GdkPixbuf.Pixbuf | None:
    """
    Capture a window via grim, entirely in RAM.
    grim writes PNG to stdout → PixbufLoader → downscaled pixbuf.
    No temp files. Works for any window regardless of Z-order.
    Returns None on any failure.
    """
    at   = client.get("at",   [0, 0])
    size = client.get("size", [0, 0])
    w, h = int(size[0]), int(size[1])
    if w <= 0 or h <= 0:
        return None

    geo = f"{int(at[0])},{int(at[1])} {w}x{h}"
    try:
        r = subprocess.run(
            ["grim", "-g", geo, "-"],
            capture_output=True,
            timeout=_TIMEOUT,
        )
        if r.returncode != 0 or not r.stdout:
            return None
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(r.stdout)
        loader.close()
        pb = loader.get_pixbuf()
        if pb is None:
            return None
        # Downscale to save RAM (5× reduction, negligible quality loss at tile size)
        scale = min(_THUMB_MAX_W / pb.get_width(), _THUMB_MAX_H / pb.get_height(), 1.0)
        if scale < 1.0:
            nw = max(1, int(pb.get_width()  * scale))
            nh = max(1, int(pb.get_height() * scale))
            pb = pb.scale_simple(nw, nh, 2)  # GdkPixbuf.InterpType.BILINEAR
        return pb
    except Exception:
        return None


# ── Cache ─────────────────────────────────────────────────────────────────────

class ThumbnailCache:
    """
    Rolling capture daemon.

    Cycles through all visible windows, capturing one per _ROLL_INTERVAL.
    The client list is refreshed at the start of each full cycle so new
    or closed windows are picked up automatically.
    """

    def __init__(self) -> None:
        self._cache: dict[str, GdkPixbuf.Pixbuf] = {}
        self._order: list[str] = []
        self._lock  = threading.Lock()
        self._stop  = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._roll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get(self, address: str) -> GdkPixbuf.Pixbuf | None:
        with self._lock:
            return self._cache.get(address)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _store(self, address: str, pixbuf: GdkPixbuf.Pixbuf) -> None:
        with self._lock:
            if address not in self._cache:
                self._order.append(address)
            self._cache[address] = pixbuf
            while len(self._order) > _CACHE_MAX:
                self._cache.pop(self._order.pop(0), None)

    def warm(self, priority_addrs: list[str] | None = None) -> None:
        """
        Immediately capture a set of priority windows in a background thread.
        Called when the overlay is about to open so the active WS is ready fast.
        """
        if not priority_addrs:
            return
        threading.Thread(
            target=self._warm_batch, args=(priority_addrs,), daemon=True
        ).start()

    def _warm_batch(self, addrs: list[str]) -> None:
        try:
            r = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            all_clients = {c["address"]: c for c in json.loads(r.stdout)}
        except Exception:
            return
        for addr in addrs:
            if addr not in self._cache and addr in all_clients:
                pb = _capture_now(all_clients[addr])
                if pb is not None:
                    self._store(addr, pb)

    def _all_clients(self) -> list[dict]:
        """
        All visible, non-hidden clients across all workspaces.
        Active workspace clients come first so they're captured earliest.
        """
        try:
            r = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            all_clients = [
                c for c in json.loads(r.stdout)
                if not c.get("hidden") and c.get("size", [0, 0])[0] > 0
            ]
            # Get active workspace id
            r2 = subprocess.run(
                ["hyprctl", "activeworkspace", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            active_ws_id = json.loads(r2.stdout).get("id", -1)
            # Sort: active WS first, then rest
            all_clients.sort(
                key=lambda c: 0 if c.get("workspace", {}).get("id") == active_ws_id else 1
            )
            return all_clients
        except Exception:
            return []

    def _roll(self) -> None:
        """
        Main loop: two concurrent tasks in one thread:
        1. Subscribe to Hyprland openwindow events → capture new windows immediately
        2. Rolling refresh — cycle through all windows, one per _ROLL_INTERVAL

        Both run in the same thread to keep the implementation simple.
        The socket uses a 1s timeout so the roll tick fires regularly.
        """
        instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        uid = os.getuid()
        sock_dir = f"/run/user/{uid}/hypr"

        if not instance:
            try:
                entries = [e for e in os.listdir(sock_dir)
                           if not e.endswith(".log") and not e.endswith(".log.old")]
                if entries:
                    instance = sorted(entries)[-1]
            except OSError:
                pass

        sock_path = f"{sock_dir}/{instance}/.socket2.sock" if instance else ""

        # Rolling state
        clients: list[dict] = []
        idx = 0
        last_roll = 0.0

        import time

        def try_connect():
            if not sock_path:
                return None
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(sock_path)
                return s
            except Exception:
                return None

        sock = try_connect()
        buf = ""

        while not self._stop.is_set():
            # ── Event handling ──────────────────────────────────────────────
            if sock is not None:
                try:
                    data = sock.recv(4096).decode("utf-8", errors="replace")
                    buf += data
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._handle_event(line.strip())
                except TimeoutError:
                    pass
                except Exception:
                    sock = None  # reconnect next iteration

            # ── Rolling capture tick ─────────────────────────────────────────
            now = time.monotonic()
            if now - last_roll >= _ROLL_INTERVAL:
                last_roll = now
                if idx >= len(clients):
                    clients = self._all_clients()
                    idx = 0
                if clients:
                    pb = _capture_now(clients[idx])
                    if pb is not None:
                        self._store(clients[idx]["address"], pb)
                    idx += 1

        if sock:
            sock.close()

    def _handle_event(self, line: str) -> None:
        """Handle Hyprland socket2 events."""
        if ">>" not in line:
            return
        event, _, payload = line.partition(">>")

        if event == "openwindow":
            # openwindow>>addr,ws,class,title — capture new window immediately
            addr = f"0x{payload.split(',')[0]}" if payload else ""
            if addr:
                threading.Thread(
                    target=self._capture_addr, args=(addr,), daemon=True
                ).start()

    def _capture_addr(self, address: str) -> None:
        """Fetch client by address and capture it."""
        try:
            r = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            client = next(
                (c for c in json.loads(r.stdout) if c.get("address") == address),
                None,
            )
            if client:
                pb = _capture_now(client)
                if pb is not None:
                    self._store(address, pb)
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_cache: ThumbnailCache | None = None


def get_cache() -> ThumbnailCache:
    """Return (and lazily start) the module-level singleton cache."""
    global _cache
    if _cache is None:
        _cache = ThumbnailCache()
        _cache.start()
    return _cache
