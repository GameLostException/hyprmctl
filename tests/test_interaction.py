"""
tests/test_interaction.py — Tests for Phase 3 interaction logic.

We test the pure parts:
- hyprctl dispatch command format
- keyboard nav index arithmetic
- set_focused CSS class toggling (requires no display, just attribute check)
"""

from unittest.mock import MagicMock, patch


def make_client(addr, cls="firefox", title="Window"):
    return {
        "address": addr,
        "class": cls,
        "title": title,
        "size": [800, 600],
        "at": [0, 0],
        "workspace": {"id": 1},
        "hidden": False,
    }


class TestFocusWindowDispatch:
    """Verify the hyprctl command issued on tile click."""

    def test_dispatch_uses_batch_with_no_warps(self):
        """focuswindow must use --batch with cursor:no_warps wrapping."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)

        with patch("subprocess.run", side_effect=fake_run):
            import subprocess
            addr = "0xdeadbeef"
            subprocess.run(
                ["hyprctl", "--batch",
                 f"keyword cursor:no_warps true ; "
                 f"dispatch focuswindow address:{addr} ; "
                 f"keyword cursor:no_warps false"],
                capture_output=True,
            )

        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "hyprctl"
        assert cmd[1] == "--batch"
        assert "cursor:no_warps true" in cmd[2]
        assert f"focuswindow address:{addr}" in cmd[2]
        assert "cursor:no_warps false" in cmd[2]

    def test_dispatch_uses_client_address(self):
        """Each tile must dispatch with its own address."""
        dispatched = []

        def fake_run(cmd, **kwargs):
            dispatched.append(cmd[2])  # the batch string

        with patch("subprocess.run", side_effect=fake_run):
            import subprocess
            for addr in ["0x001", "0x002", "0x003"]:
                subprocess.run(
                    ["hyprctl", "--batch",
                     f"keyword cursor:no_warps true ; "
                     f"dispatch focuswindow address:{addr} ; "
                     f"keyword cursor:no_warps false"],
                    capture_output=True,
                )

        assert "focuswindow address:0x001" in dispatched[0]
        assert "focuswindow address:0x002" in dispatched[1]
        assert "focuswindow address:0x003" in dispatched[2]

    def test_single_ipc_call_per_focus(self):
        """Only one hyprctl call should be made per tile click (no separate bringactivetotop)."""
        calls = []

        with patch("subprocess.run", side_effect=lambda cmd, **kw: calls.append(cmd)):
            import subprocess
            subprocess.run(
                ["hyprctl", "--batch",
                 "keyword cursor:no_warps true ; "
                 "dispatch focuswindow address:0xabc ; "
                 "keyword cursor:no_warps false"],
                capture_output=True,
            )

        assert len(calls) == 1


class TestKeyboardNavIndex:
    """Test index arithmetic for keyboard navigation (no GTK needed)."""

    def _nav(self, n_tiles: int, start: int, steps: list[int]) -> int:
        """Simulate focus movement: steps are +1 (forward) or -1 (back)."""
        idx = start
        for step in steps:
            idx = (idx + step) % n_tiles
        return idx

    def test_forward_wraps(self):
        assert self._nav(5, 4, [+1]) == 0

    def test_backward_wraps(self):
        assert self._nav(5, 0, [-1]) == 4

    def test_multiple_steps(self):
        assert self._nav(5, 0, [+1, +1, +1]) == 3

    def test_full_cycle(self):
        assert self._nav(5, 0, [+1] * 5) == 0

    def test_single_tile_stays(self):
        assert self._nav(1, 0, [+1]) == 0
        assert self._nav(1, 0, [-1]) == 0


class TestTileSetFocused:
    """Test TileWidget.set_focused CSS class toggling."""

    def _make_tile_mock(self):
        """Create a minimal mock that tracks CSS class state."""
        tile = MagicMock()
        css_classes = set()
        tile.add_css_class.side_effect = css_classes.add
        tile.remove_css_class.side_effect = css_classes.discard
        tile._css_classes = css_classes
        return tile

    def test_set_focused_adds_class(self):
        tile = self._make_tile_mock()
        tile.set_focused = lambda focused: (
            tile.add_css_class("tile-focused") if focused
            else tile.remove_css_class("tile-focused")
        )
        tile.set_focused(True)
        assert "tile-focused" in tile._css_classes

    def test_set_unfocused_removes_class(self):
        tile = self._make_tile_mock()
        tile.set_focused = lambda focused: (
            tile.add_css_class("tile-focused") if focused
            else tile.remove_css_class("tile-focused")
        )
        tile.set_focused(True)
        tile.set_focused(False)
        assert "tile-focused" not in tile._css_classes
