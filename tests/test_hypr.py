"""
tests/test_hypr.py — Unit tests for src/hypr.py.
All subprocess calls are mocked; no real hyprctl needed.
"""

import json
from pathlib import Path

from src.hypr import (
    get_active_monitor,
    get_active_workspace_clients,
    get_clients,
    get_monitors,
)

# Load real-world fixtures
FIXTURE_DIR = Path(__file__).parent / "fixtures"
CLIENTS_JSON = (FIXTURE_DIR / "clients.json").read_text()
MONITORS_JSON = (FIXTURE_DIR / "monitors.json").read_text()


def make_runner(responses: dict[tuple, str]):
    """Return a runner function that maps command tuples to fixture strings."""
    def runner(cmd):
        key = tuple(cmd)
        for k, v in responses.items():
            if key == k:
                return v
        raise RuntimeError(f"Unexpected command: {cmd}")
    return runner


class TestGetClients:
    def test_returns_list(self):
        runner = make_runner({("hyprctl", "clients", "-j"): CLIENTS_JSON})
        result = get_clients(runner)
        assert isinstance(result, list)

    def test_each_client_has_address(self):
        runner = make_runner({("hyprctl", "clients", "-j"): CLIENTS_JSON})
        result = get_clients(runner)
        for client in result:
            assert "address" in client

    def test_empty_workspace(self):
        runner = make_runner({("hyprctl", "clients", "-j"): "[]"})
        result = get_clients(runner)
        assert result == []


class TestGetMonitors:
    def test_returns_list(self):
        runner = make_runner({("hyprctl", "monitors", "-j"): MONITORS_JSON})
        result = get_monitors(runner)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_monitor_has_geometry(self):
        runner = make_runner({("hyprctl", "monitors", "-j"): MONITORS_JSON})
        result = get_monitors(runner)
        for m in result:
            assert "width" in m
            assert "height" in m


class TestGetActiveMonitor:
    def test_returns_focused_monitor(self):
        monitors = json.loads(MONITORS_JSON)
        # Ensure at least one is focused
        if not any(m.get("focused") for m in monitors):
            monitors[0]["focused"] = True
        data = json.dumps(monitors)
        runner = make_runner({("hyprctl", "monitors", "-j"): data})
        result = get_active_monitor(runner)
        assert result is not None
        assert result.get("focused") is True

    def test_falls_back_to_first_if_none_focused(self):
        monitors = json.loads(MONITORS_JSON)
        for m in monitors:
            m["focused"] = False
        data = json.dumps(monitors)
        runner = make_runner({("hyprctl", "monitors", "-j"): data})
        result = get_active_monitor(runner)
        assert result == monitors[0]

    def test_returns_none_on_empty(self):
        runner = make_runner({("hyprctl", "monitors", "-j"): "[]"})
        result = get_active_monitor(runner)
        assert result is None


class TestGetActiveWorkspaceClients:
    def _make_runner(self, clients, monitors):
        return make_runner({
            ("hyprctl", "clients", "-j"): json.dumps(clients),
            ("hyprctl", "monitors", "-j"): json.dumps(monitors),
        })

    def test_filters_by_active_workspace(self):
        monitors = [{"focused": True, "activeWorkspace": {"id": 1}, "width": 1920, "height": 1080}]
        clients = [
            {"address": "0x1", "workspace": {"id": 1}, "class": "firefox", "title": "t", "hidden": False, "size": [800, 600], "at": [0, 0]},
            {"address": "0x2", "workspace": {"id": 2}, "class": "kitty",   "title": "t", "hidden": False, "size": [800, 600], "at": [0, 0]},
        ]
        runner = self._make_runner(clients, monitors)
        result = get_active_workspace_clients(runner)
        assert len(result) == 1
        assert result[0]["address"] == "0x1"

    def test_excludes_hidden_clients(self):
        monitors = [{"focused": True, "activeWorkspace": {"id": 1}, "width": 1920, "height": 1080}]
        clients = [
            {"address": "0x1", "workspace": {"id": 1}, "class": "firefox", "title": "t", "hidden": True,  "size": [800, 600], "at": [0, 0]},
            {"address": "0x2", "workspace": {"id": 1}, "class": "kitty",   "title": "t", "hidden": False, "size": [800, 600], "at": [0, 0]},
        ]
        runner = self._make_runner(clients, monitors)
        result = get_active_workspace_clients(runner)
        assert len(result) == 1
        assert result[0]["address"] == "0x2"

    def test_returns_empty_when_no_monitor(self):
        runner = make_runner({
            ("hyprctl", "clients", "-j"): "[]",
            ("hyprctl", "monitors", "-j"): "[]",
        })
        result = get_active_workspace_clients(runner)
        assert result == []
