"""
src/app.py — hyprmctl application + Unix socket IPC.

hyprmctl runs as a persistent daemon:
  - Keeps the thumbnail cache warm in the background
  - Listens on a Unix socket for commands
  - On 'show': displays the Mission Control overlay
  - On 'hide'/'toggle': hides it

Hyprland keybind sends 'show' via: python3 hyprmctl.py --show
If no daemon is running, --show starts one.
"""

from __future__ import annotations

import os
import socket
import threading

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk  # noqa: E402

from src.overlay import MissionControlOverlay  # noqa: E402
from src.thumbnails import get_cache  # noqa: E402

_UID      = os.getuid()
_SOCK     = f"/tmp/hyprmctl-{_UID}.sock"


class MissionControlApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.boris.hyprmctl")
        self._overlay: MissionControlOverlay | None = None
        self.connect("activate", self._on_activate)
        self.connect("startup", self._on_startup)

    def _on_startup(self, app: Gtk.Application) -> None:
        # Start thumbnail cache
        get_cache()
        # Start IPC socket listener
        threading.Thread(target=self._serve, daemon=True).start()

    def _on_activate(self, app: Gtk.Application) -> None:
        self._show_overlay()

    # ── IPC socket ────────────────────────────────────────────────────────────

    def _serve(self) -> None:
        """Listen on Unix socket for show/hide/toggle commands."""
        try:
            os.unlink(_SOCK)
        except OSError:
            pass
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
            srv.bind(_SOCK)
            srv.listen(4)
            srv.settimeout(1.0)
            while True:
                try:
                    conn, _ = srv.accept()
                except TimeoutError:
                    continue
                try:
                    cmd = conn.recv(64).decode().strip()
                    conn.close()
                    GLib.idle_add(self._handle_cmd, cmd)
                except Exception:
                    pass

    def _handle_cmd(self, cmd: str) -> bool:
        if cmd == "show":
            self._show_overlay()
        elif cmd == "hide":
            self._hide_overlay()
        elif cmd == "toggle":
            if self._overlay and self._overlay.get_visible():
                self._hide_overlay()
            else:
                self._show_overlay()
        return False

    # ── Overlay lifecycle ─────────────────────────────────────────────────────

    def _show_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        self._overlay = MissionControlOverlay(self)
        self._overlay.present()

    def _hide_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
