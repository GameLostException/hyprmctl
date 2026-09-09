"""
tests/test_thumbnails.py — Unit tests for src/thumbnails.py (ThumbnailCache).
"""

from unittest.mock import MagicMock, patch

from src.thumbnails import ThumbnailCache, _capture_now


def make_client(addr="0xabc", x=0, y=0, w=800, h=600):
    return {"address": addr, "at": [x, y], "size": [w, h], "class": "app"}


class TestCaptureNow:
    def _fake_run(self, calls, returncode=1, stdout=b""):
        def fake(cmd, **kwargs):
            calls.append(list(cmd))
            m = MagicMock()
            m.returncode = returncode
            m.stdout = stdout
            m.stderr = b""
            return m
        return fake

    def test_returns_none_on_failure(self):
        with patch("subprocess.run", side_effect=self._fake_run([], returncode=1)):
            assert _capture_now(make_client()) is None

    def test_returns_none_on_missing_address(self):
        assert _capture_now({"size": [800, 600], "at": [0, 0]}) is None

    def test_returns_none_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("boom")):
            assert _capture_now(make_client()) is None

    def test_calls_hyprshot_with_address(self):
        """hyprshot must be called with the window address."""
        calls = []
        with patch("subprocess.run", side_effect=self._fake_run(calls, returncode=1)):
            _capture_now(make_client(addr="0xdeadbeef"))
        assert calls, "no subprocess call made"
        first_call = calls[0]
        assert "hyprshot" in first_call[0], f"expected hyprshot, got {first_call[0]}"
        assert "0xdeadbeef" in first_call[1], "address not passed to hyprshot"

    def test_no_temp_files_created(self):
        import os
        import tempfile
        tmp_before = set(os.listdir(tempfile.gettempdir()))
        with patch("subprocess.run", side_effect=self._fake_run([], returncode=1)):
            _capture_now(make_client())
        tmp_after = set(os.listdir(tempfile.gettempdir()))
        assert not [f for f in tmp_after - tmp_before if "hyprmctl" in f]


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
