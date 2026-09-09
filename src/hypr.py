"""
src/hypr.py — Hyprland data fetching via hyprctl.
All functions return parsed Python objects; subprocess is injected for testability.
"""

import json
import subprocess
from typing import Any


def _run(cmd: list[str], runner=None) -> str:
    """Run a command and return stdout. Uses subprocess by default; injectable for tests."""
    if runner is None:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    return runner(cmd)


def get_clients(runner=None) -> list[dict[str, Any]]:
    """Return all open clients from hyprctl clients -j."""
    raw = _run(["hyprctl", "clients", "-j"], runner)
    return json.loads(raw)


def get_monitors(runner=None) -> list[dict[str, Any]]:
    """Return all monitors from hyprctl monitors -j."""
    raw = _run(["hyprctl", "monitors", "-j"], runner)
    return json.loads(raw)


def get_active_monitor(runner=None) -> dict[str, Any] | None:
    """Return the monitor that has the focused workspace."""
    monitors = get_monitors(runner)
    for m in monitors:
        if m.get("focused"):
            return m
    # Fallback: first monitor
    return monitors[0] if monitors else None


def get_active_workspace_clients(runner=None) -> list[dict[str, Any]]:
    """
    Return clients that belong to the active monitor's active workspace,
    excluding special/scratchpad workspaces (id < 0).
    """
    monitor = get_active_monitor(runner)
    if monitor is None:
        return []

    active_workspace_id = monitor.get("activeWorkspace", {}).get("id")
    if active_workspace_id is None:
        return []

    clients = get_clients(runner)
    return [
        c for c in clients
        if c.get("workspace", {}).get("id") == active_workspace_id
        and not c.get("hidden", False)
    ]
