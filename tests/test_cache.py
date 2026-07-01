from core.cache import URLCache


def test_new_url_is_not_cached(tmp_path) -> None:
    cache = URLCache(str(tmp_path / "cache.db"))

    assert cache.is_cached("https://example.com/page-1.html") is False


def test_mark_done_makes_url_cached(tmp_path) -> None:
    cache = URLCache(str(tmp_path / "cache.db"))
    url = "https://example.com/page-1.html"

    cache.mark_done(url, 20)

    assert cache.is_cached(url) is True


def test_clear_removes_cached_urls(tmp_path) -> None:
    cache = URLCache(str(tmp_path / "cache.db"))
    url = "https://example.com/page-1.html"
    cache.mark_done(url, 20)

    cache.clear()

    assert cache.is_cached(url) is False
