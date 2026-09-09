"""
tests/test_thumbnails.py — Unit tests for src/thumbnails.py (ThumbnailCache).
"""

from unittest.mock import MagicMock, patch

from src.thumbnails import ThumbnailCache, _capture_now


def make_client(addr="0xabc", x=0, y=0, w=800, h=600):
    return {"address": addr, "at": [x, y], "size": [w, h], "class": "app"}


class TestCaptureNow:
    def test_returns_none_on_grim_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=b"")
            assert _capture_now(make_client()) is None

    def test_returns_none_on_zero_size(self):
        assert _capture_now(make_client(w=0, h=0)) is None

    def test_returns_none_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("boom")):
            assert _capture_now(make_client()) is None

    def test_calls_grim_with_stdout_pipe(self):
        """grim must be called with '-' as output (stdout pipe, no disk write)."""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=1, stdout=b"")

        with patch("subprocess.run", side_effect=fake_run):
            _capture_now(make_client(x=100, y=200, w=800, h=600))

        assert calls[0][-1] == "-", "grim must output to stdout ('-'), not a file"

    def test_correct_geometry_string(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=1, stdout=b"")

        with patch("subprocess.run", side_effect=fake_run):
            _capture_now(make_client(x=100, y=200, w=800, h=600))

        assert "100,200 800x600" in calls[0]

    def test_no_temp_files_created(self):
        """Capture must not write any files to disk."""
        import os
        import tempfile
        tmp_before = set(os.listdir(tempfile.gettempdir()))

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=b"")
            _capture_now(make_client())

        tmp_after = set(os.listdir(tempfile.gettempdir()))
        new_files = tmp_after - tmp_before
        hyprmctl_files = [f for f in new_files if "hyprmctl" in f]
        assert hyprmctl_files == [], f"Unexpected temp files: {hyprmctl_files}"


class TestThumbnailCache:
    def test_get_returns_none_for_unknown(self):
        cache = ThumbnailCache()
        assert cache.get("0xunknown") is None

    def test_store_and_retrieve(self):
        cache = ThumbnailCache()
        fake_pixbuf = MagicMock()
        cache._store("0xabc", fake_pixbuf)
        assert cache.get("0xabc") is fake_pixbuf

    def test_evicts_oldest_when_over_limit(self):
        from src.thumbnails import _CACHE_MAX
        cache = ThumbnailCache()
        for i in range(_CACHE_MAX + 5):
            cache._store(f"0x{i}", MagicMock())
        assert len(cache._cache) <= _CACHE_MAX

    def test_store_updates_existing(self):
        cache = ThumbnailCache()
        pb1, pb2 = MagicMock(), MagicMock()
        cache._store("0xabc", pb1)
        cache._store("0xabc", pb2)
        assert cache.get("0xabc") is pb2
        assert cache._order.count("0xabc") == 1

    def test_thread_safe_get(self):
        import threading
        cache = ThumbnailCache()
        for i in range(20):
            cache._store(f"0x{i}", MagicMock())

        errors = []

        def reader():
            for i in range(50):
                try:
                    cache.get(f"0x{i % 20}")
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
