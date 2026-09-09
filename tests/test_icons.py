"""
tests/test_icons.py — Unit tests for src/icons.py.
GTK display calls are mocked; .desktop parsing is tested directly.
"""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from src.icons import _candidates, _parse_desktop

FIREFOX_DESKTOP = """\
[Desktop Entry]
Name=Firefox
Exec=/usr/bin/firefox %u
Icon=firefox
Type=Application
"""

KITTY_DESKTOP = """\
[Desktop Entry]
Name=kitty
Exec=kitty
Icon=kitty
Type=Application
"""

MULTI_SECTION_DESKTOP = """\
[Desktop Entry]
Name=MyApp
Icon=myapp-icon
Exec=myapp

[Desktop Action NewWindow]
Name=New Window
Exec=myapp --new-window
"""


def _patch_path_open(content: str):
    return patch("pathlib.Path.open", MagicMock(return_value=content.splitlines(keepends=True).__iter__()))


class TestParseDesktop:
    def test_extracts_icon(self):
        index = {}
        with patch("pathlib.Path.open", mock_open(read_data=FIREFOX_DESKTOP)):
            _parse_desktop(Path("/usr/share/applications/firefox.desktop"), index)
        assert index.get("firefox") == "firefox"

    def test_indexes_by_exec_binary(self):
        index = {}
        with patch("pathlib.Path.open", mock_open(read_data=FIREFOX_DESKTOP)):
            _parse_desktop(Path("/usr/share/applications/firefox.desktop"), index)
        assert "firefox" in index

    def test_ignores_sections_after_desktop_entry(self):
        index = {}
        with patch("pathlib.Path.open", mock_open(read_data=MULTI_SECTION_DESKTOP)):
            _parse_desktop(Path("/usr/share/applications/myapp.desktop"), index)
        assert index.get("myapp") == "myapp-icon"

    def test_no_icon_field_nothing_inserted(self):
        desktop = "[Desktop Entry]\nName=NoIcon\nExec=noicon\n"
        index = {}
        with patch("pathlib.Path.open", mock_open(read_data=desktop)):
            _parse_desktop(Path("/usr/share/applications/noicon.desktop"), index)
        assert all(v for v in index.values())


class TestCandidates:
    def test_includes_class_itself(self):
        with patch("src.icons._build_desktop_index", return_value={}):
            cands = _candidates("firefox")
        assert "firefox" in cands

    def test_includes_desktop_icon(self):
        with patch("src.icons._build_desktop_index", return_value={"firefox": "firefox-esr"}):
            cands = _candidates("firefox")
        assert "firefox-esr" in cands

    def test_includes_generic_fallbacks(self):
        with patch("src.icons._build_desktop_index", return_value={}):
            cands = _candidates("unknownapp")
        assert "application-x-executable" in cands

    def test_case_insensitive(self):
        with patch("src.icons._build_desktop_index", return_value={"firefox": "firefox"}):
            cands = _candidates("Firefox")
        assert "firefox" in cands


class TestResolveIconName:
    def _mock_theme(self, has: set[str]):
        theme = MagicMock()
        theme.has_icon.side_effect = lambda name: name in has
        return theme

    def test_returns_direct_match(self):
        from src.icons import resolve_icon_name
        theme = self._mock_theme({"firefox"})
        with patch("src.icons._get_theme", return_value=theme):
            with patch("src.icons._build_desktop_index", return_value={}):
                assert resolve_icon_name("firefox") == "firefox"

    def test_returns_desktop_icon_name(self):
        from src.icons import resolve_icon_name
        theme = self._mock_theme({"firefox-esr"})
        with patch("src.icons._get_theme", return_value=theme):
            with patch("src.icons._build_desktop_index", return_value={"firefox": "firefox-esr"}):
                assert resolve_icon_name("firefox") == "firefox-esr"

    def test_returns_none_when_no_match(self):
        from src.icons import resolve_icon_name
        theme = self._mock_theme(set())
        with patch("src.icons._get_theme", return_value=theme):
            with patch("src.icons._build_desktop_index", return_value={}):
                assert resolve_icon_name("totally_unknown_xyz") is None

    def test_returns_none_when_no_display(self):
        from src.icons import resolve_icon_name
        with patch("src.icons._get_theme", return_value=None):
            assert resolve_icon_name("firefox") is None
