import pytest

from core.browser_client import BrowserClient
from core.client_factory import create_client
from core.http_client import HttpClient


def test_factory_creates_static_http_client() -> None:
    client = create_client("static")
    try:
        assert isinstance(client, HttpClient)
    finally:
        client.close()


def test_factory_creates_browser_client() -> None:
    assert isinstance(create_client("browser"), BrowserClient)


def test_factory_rejects_unknown_engine() -> None:
    with pytest.raises(ValueError, match="Unsupported engine"):
        create_client("unknown")


@pytest.mark.parametrize("engine", ["static", "browser"])
def test_factory_clients_provide_shared_lifecycle(engine):
    client = create_client(engine)
    try:
        for method in ("__enter__", "__exit__", "close", "fetch"):
            assert callable(getattr(client, method, None)), f"{engine} lacks {method}"
    finally:
        client.close()
