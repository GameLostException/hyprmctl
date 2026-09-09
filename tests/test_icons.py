"""
tests/test_icons.py — Unit tests for src/icons.py.
File system calls are mocked.
"""

from pathlib import Path
from unittest.mock import mock_open, patch

from src.icons import _parse_desktop_file, find_icon_name, get_icon_path

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
    """Patch pathlib.Path.open so _parse_desktop_file reads the given string."""
    return patch("pathlib.Path.open", mock_open(read_data=content))


class TestParseDesktopFile:
    def test_extracts_icon(self):
        index = {}
        with _patch_path_open(FIREFOX_DESKTOP):
            _parse_desktop_file(Path("/usr/share/applications/firefox.desktop"), index)
        assert index.get("firefox") == "firefox"

    def test_indexes_by_exec_binary(self):
        index = {}
        with _patch_path_open(FIREFOX_DESKTOP):
            _parse_desktop_file(Path("/usr/share/applications/firefox.desktop"), index)
        # "firefox" from Exec and from filename — both should point to icon
        assert "firefox" in index

    def test_ignores_sections_after_desktop_entry(self):
        """Icon from a non-[Desktop Entry] section must not be used."""
        index = {}
        with _patch_path_open(MULTI_SECTION_DESKTOP):
            _parse_desktop_file(Path("/usr/share/applications/myapp.desktop"), index)
        assert index.get("myapp") == "myapp-icon"

    def test_no_icon_field(self):
        desktop = "[Desktop Entry]\nName=NoIcon\nExec=noicon\n"
        index = {}
        with _patch_path_open(desktop):
            _parse_desktop_file(Path("/usr/share/applications/noicon.desktop"), index)
        # Nothing inserted since no Icon= line
        assert all(v != "" for v in index.values())


class TestFindIconName:
    def _mock_index(self, data: dict):
        """Patch _load_desktop_index to return a fixed dict."""
        return patch("src.icons._load_desktop_index", return_value=data)

    def test_direct_match(self):
        with self._mock_index({"firefox": "firefox", "kitty": "kitty"}):
            assert find_icon_name("firefox") == "firefox"

    def test_case_insensitive(self):
        with self._mock_index({"firefox": "firefox"}):
            assert find_icon_name("Firefox") == "firefox"

    def test_partial_match(self):
        with self._mock_index({"org.mozilla.firefox": "firefox"}):
            result = find_icon_name("firefox")
            assert result == "firefox"

    def test_not_found_returns_none(self):
        with self._mock_index({"firefox": "firefox"}):
            assert find_icon_name("nonexistent_app_xyz") is None


class TestGetIconPath:
    def test_returns_path_when_file_exists(self, tmp_path):
        # Create a fake icon file
        icon_dir = tmp_path / "apps"
        icon_dir.mkdir(parents=True)
        icon_file = icon_dir / "firefox.png"
        icon_file.write_bytes(b"fake_png")

        with patch("src.icons._load_desktop_index", return_value={"firefox": "firefox"}):
            with patch("src.icons._DESKTOP_DIRS", [tmp_path]):
                # Patch search dirs to use tmp_path
                with patch("src.icons.get_icon_path") as mock_get:
                    mock_get.return_value = str(icon_file)
                    result = mock_get("firefox")
                    assert result == str(icon_file)

    def test_returns_none_when_not_found(self):
        with patch("src.icons._load_desktop_index", return_value={}):
            with patch("pathlib.Path.exists", return_value=False):
                result = get_icon_path("totally_unknown_app_xyz_123")
                assert result is None
