"""
src/app.py — Gtk.Application subclass for hyprmctl.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from src.overlay import MissionControlOverlay  # noqa: E402


class MissionControlApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.boris.hyprmctl")
        self.connect("activate", self._on_activate)

    def _on_activate(self, app: Gtk.Application) -> None:
        win = MissionControlOverlay(app)
        win.present()
