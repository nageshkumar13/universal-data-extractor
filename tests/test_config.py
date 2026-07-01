import pytest

from core.config import InvalidProfileError
from core.config import ProfileLoader


def test_profile_loader_rejects_browser_engine() -> None:
    loader = ProfileLoader()

    with pytest.raises(InvalidProfileError, match="Invalid engine"):
        loader.validate(
            {
                "site_name": "Example",
                "engine": "browser",
                "start_url": "https://example.com",
                "fields": {"title": "h1::text"},
            }
        )
