#!/usr/bin/env python3
"""
hyprmctl — Mission Control for Hyprland

Two modes:
  python3 hyprmctl.py          → start daemon (stays running, warms cache)
  python3 hyprmctl.py --show   → send 'show' to running daemon, or start one
  python3 hyprmctl.py --toggle → toggle overlay on running daemon

Hyprland keybind should use --show:
  bind = $mod, SPACE, exec, python3 /path/to/hyprmctl.py --show
"""

import os
import socket
import sys

_LAYER_SHELL_SO = "/usr/lib/libgtk4-layer-shell.so"
if os.path.exists(_LAYER_SHELL_SO) and _LAYER_SHELL_SO not in os.environ.get("LD_PRELOAD", ""):
    os.environ["LD_PRELOAD"] = _LAYER_SHELL_SO
    os.execv(sys.executable, [sys.executable] + sys.argv)

_UID  = os.getuid()
_SOCK = f"/tmp/hyprmctl-{_UID}.sock"

# ── Auto-build hyprshot if missing ────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_HYPRSHOT    = os.path.join(_SCRIPT_DIR, "hyprshot", "hyprshot")
if not os.path.exists(_HYPRSHOT):
    import subprocess
    _hyprshot_dir = os.path.join(_SCRIPT_DIR, "hyprshot")
    if os.path.exists(os.path.join(_hyprshot_dir, "Makefile")):
        print("hyprmctl: building hyprshot...", flush=True)
        r = subprocess.run(["make"], cwd=_hyprshot_dir, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"hyprmctl: hyprshot build failed:\n{r.stderr}", file=sys.stderr)


def _send(cmd: str) -> bool:
    """Send a command to the running daemon. Returns True if delivered."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(_SOCK)
            s.sendall(cmd.encode())
            return True
    except Exception:
        return False


def main() -> None:
    cmd = None
    if "--show"   in sys.argv: cmd = "show"
    if "--toggle" in sys.argv: cmd = "toggle"
    if "--hide"   in sys.argv: cmd = "hide"

    if cmd is not None:
        # Try to signal running daemon first
        if _send(cmd):
            return
        # No daemon running — start one and it will show the overlay on activate
        # (fall through to daemon start below)

    # Start daemon
    from src.app import MissionControlApp
    app = MissionControlApp()
    # If a command was requested, activate = show overlay on startup
    sys.exit(app.run(sys.argv[:1]))  # strip --show/--toggle from argv


if __name__ == "__main__":
    main()
