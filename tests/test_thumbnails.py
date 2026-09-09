"""
tests/test_thumbnails.py — Unit tests for src/thumbnails.py (ThumbnailCache).
"""

from unittest.mock import MagicMock, patch

from src.thumbnails import ThumbnailCache, _capture_now, _tmp_path


def make_client(addr="0xabc", x=0, y=0, w=800, h=600):
    return {"address": addr, "at": [x, y], "size": [w, h], "class": "app"}


class TestTmpPath:
    def test_no_0x_prefix(self):
        assert "0x" not in _tmp_path("0xdeadbeef")

    def test_contains_address(self):
        assert "deadbeef" in _tmp_path("0xdeadbeef")

    def test_is_png(self):
        assert _tmp_path("0x1").endswith(".png")


class TestCaptureNow:
    def test_returns_none_on_grim_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert _capture_now(make_client()) is None

    def test_returns_none_on_zero_size(self):
        assert _capture_now(make_client(w=0, h=0)) is None

    def test_returns_none_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("boom")):
            assert _capture_now(make_client()) is None

    def test_calls_grim_with_correct_geometry(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=1)

        with patch("subprocess.run", side_effect=fake_run):
            _capture_now(make_client(addr="0x1", x=100, y=200, w=800, h=600))

        assert calls[0][0] == "grim"
        assert calls[0][2] == "100,200 800x600"


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
        pb1 = MagicMock()
        pb2 = MagicMock()
        cache._store("0xabc", pb1)
        cache._store("0xabc", pb2)
        assert cache.get("0xabc") is pb2
        assert cache._order.count("0xabc") == 1  # no duplicate in order list

    def test_thread_safe_get(self):
        """get() must not raise under concurrent access."""
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
