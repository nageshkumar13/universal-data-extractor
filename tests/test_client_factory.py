import pytest

from core.browser_client import BrowserClient
from core.client_factory import create_client
from core.http_client import HttpClient


def test_factory_creates_static_http_client() -> None:
    assert isinstance(create_client("static"), HttpClient)


def test_factory_creates_browser_client() -> None:
    assert isinstance(create_client("browser"), BrowserClient)


def test_factory_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="Unsupported engine"):
        create_client("unknown")
