import pytest

from core.config import InvalidProfileError
from core.config import ProfileLoader


def test_profile_loader_accepts_browser_engine() -> None:
    loader = ProfileLoader()

    loader.validate(
        {
            "site_name": "Example",
            "engine": "browser",
            "start_url": "https://example.com",
            "wait_for": "article.result",
            "fields": {"title": "h1::text"},
        }
    )


def test_profile_loader_rejects_empty_wait_for_selector() -> None:
    loader = ProfileLoader()

    with pytest.raises(InvalidProfileError, match="Invalid wait_for"):
        loader.validate(
            {
                "site_name": "Example",
                "engine": "browser",
                "start_url": "https://example.com",
                "wait_for": "  ",
                "fields": {"title": "h1::text"},
            }
        )
