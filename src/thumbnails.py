"""
src/thumbnails.py — Non-disruptive window capture daemon.

Design principles:
  - NEVER focus or move windows
  - NEVER disrupt the user's GUI
  - Capture only when a window is already on top (active)
  - Light on CPU: one capture per event, no polling loops

How it works:
  1. activewindowv2 event  → capture the newly active window immediately
                             (it's already on top, grim gets correct content)
  2. openwindow event      → schedule capture of the new window
                             (it just opened, likely on top)
  3. 10s refresh timer     → re-capture the currently active window only
                             (keeps the active window fresh, zero disruption)

Monocle windows not yet visited: colour-fill tile — acceptable, correct.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from typing import Any

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

_TIMEOUT      = 2.0    # grim capture timeout (seconds)
_CACHE_MAX    = 128    # max cached pixbufs in RAM
_THUMB_MAX_W  = 800    # downscale max width
_THUMB_MAX_H  = 500    # downscale max height
_REFRESH_S    = 10     # seconds between full re-capture cycles
_ROLL_INTERVAL = 0.5   # sleep between individual window captures
_HYPRSHOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hyprshot", "hyprshot")


# ── Capture ───────────────────────────────────────────────────────────────────

def _capture_now(client: dict[str, Any]) -> GdkPixbuf.Pixbuf | None:
    """
    Capture any window via hyprland-toplevel-export-v1 regardless of Z-order.
    hyprshot reads the window's framebuffer directly from the compositor.
    No focus changes, no disruption. Works for hidden/monocle windows.
    Returns a downscaled pixbuf or None on failure.
    """
    addr = client.get("address", "")
    if not addr:
        return None

    try:
        r = subprocess.run(
            [_HYPRSHOT, addr],
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
        scale = min(_THUMB_MAX_W / pb.get_width(), _THUMB_MAX_H / pb.get_height(), 1.0)
        if scale < 1.0:
            nw = max(1, int(pb.get_width()  * scale))
            nh = max(1, int(pb.get_height() * scale))
            pb = pb.scale_simple(nw, nh, 2)  # BILINEAR
        return pb
    except Exception:
        return None


# ── Cache ─────────────────────────────────────────────────────────────────────

class ThumbnailCache:
    """
    Event-driven capture cache. Never focuses or moves windows.

    Captures:
      - On activewindowv2: the window that just became active
      - On openwindow: the window that just opened
      - On 10s timer: the currently active window (refresh)
    """

    def __init__(self) -> None:
        self._cache: dict[str, GdkPixbuf.Pixbuf] = {}
        self._order: list[str] = []
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def get(self, address: str) -> GdkPixbuf.Pixbuf | None:
        with self._lock:
            return self._cache.get(address)

    def _store(self, address: str, pixbuf: GdkPixbuf.Pixbuf) -> None:
        with self._lock:
            if address not in self._cache:
                self._order.append(address)
            self._cache[address] = pixbuf
            while len(self._order) > _CACHE_MAX:
                self._cache.pop(self._order.pop(0), None)

    # ── Capture helpers ───────────────────────────────────────────────────────

    def _capture_client(self, client: dict) -> None:
        """Capture a single client and store in cache."""
        addr = client.get("address", "")
        if not addr:
            return
        pb = _capture_now(client)
        if pb is not None:
            self._store(addr, pb)

    def _all_clients(self) -> list[dict]:
        """All visible non-hidden clients, active workspace first."""
        try:
            r = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            all_clients = [
                c for c in json.loads(r.stdout)
                if not c.get("hidden") and c.get("size", [0, 0])[0] > 0
            ]
            r2 = subprocess.run(
                ["hyprctl", "activeworkspace", "-j"],
                capture_output=True, text=True, timeout=2.0,
            )
            active_ws = json.loads(r2.stdout).get("id", -1)
            all_clients.sort(
                key=lambda c: 0 if c.get("workspace", {}).get("id") == active_ws else 1
            )
            return all_clients
        except Exception:
            return []

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """
        Rolling capture loop + Hyprland event listener.

        Now that hyprshot can capture any window regardless of Z-order,
        the rolling loop captures all windows one by one.
        Active workspace windows are prioritised (sorted first).
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
        buf = ""
        clients: list[dict] = []
        idx = 0
        last_tick = time.monotonic()

        def connect():
            if not sock_path:
                return None
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect(sock_path)
                return s
            except Exception:
                return None

        sock = connect()

        while not self._stop.is_set():
            # ── Event handling ────────────────────────────────────────────────
            if sock is not None:
                try:
                    data = sock.recv(4096).decode("utf-8", errors="replace")
                    if not data:
                        sock = None
                    else:
                        buf += data
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            self._handle_event(line.strip())
                except TimeoutError:
                    pass
                except Exception:
                    sock = None

            # ── Rolling capture tick ──────────────────────────────────────────
            now = time.monotonic()
            if now - last_tick >= _ROLL_INTERVAL:
                last_tick = now
                if idx >= len(clients):
                    clients = self._all_clients()
                    idx = 0
                if clients:
                    threading.Thread(
                        target=self._capture_client,
                        args=(clients[idx],),
                        daemon=True,
                    ).start()
                    idx += 1

        if sock:
            try:
                sock.close()
            except Exception:
                pass

    def _handle_event(self, line: str) -> None:
        if ">>" not in line:
            return
        event, _, payload = line.partition(">>")

        if event in ("activewindowv2", "openwindow"):
            # Capture immediately — hyprshot works for any window
            addr = f"0x{payload.split(',')[0].strip()}" if payload.strip() else ""
            if not addr or addr == "0x":
                return
            def capture(a=addr):
                if event == "openwindow":
                    time.sleep(0.3)  # let new window render first
                try:
                    r = subprocess.run(
                        ["hyprctl", "clients", "-j"],
                        capture_output=True, text=True, timeout=2.0,
                    )
                    client = next(
                        (c for c in json.loads(r.stdout) if c.get("address") == a),
                        None,
                    )
                    if client:
                        self._capture_client(client)
                except Exception:
                    pass
            threading.Thread(target=capture, daemon=True).start()


# ── Singleton ─────────────────────────────────────────────────────────────────

_cache: ThumbnailCache | None = None


def get_cache() -> ThumbnailCache:
    global _cache
    if _cache is None:
        _cache = ThumbnailCache()
        _cache.start()
    return _cache
