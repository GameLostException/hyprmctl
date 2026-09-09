#!/usr/bin/env python3
"""
hyprmctl — Mission Control for Hyprland
Entry point. Re-execs itself with LD_PRELOAD if needed, then delegates to src.app.
"""

import os
import sys

# gtk4-layer-shell must be preloaded before libwayland-client.
# Re-exec with LD_PRELOAD injected so callers don't need to set it manually.
_LAYER_SHELL_SO = "/usr/lib/libgtk4-layer-shell.so"
if os.path.exists(_LAYER_SHELL_SO) and _LAYER_SHELL_SO not in os.environ.get("LD_PRELOAD", ""):
    os.environ["LD_PRELOAD"] = _LAYER_SHELL_SO
    os.execv(sys.executable, [sys.executable] + sys.argv)

from src.app import MissionControlApp  # noqa: E402 (import after sys.path setup)


def main() -> None:
    app = MissionControlApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
