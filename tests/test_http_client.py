from unittest.mock import Mock

import pytest

from core import http_client as http_client_module
from core.http_client import HttpClient


@pytest.fixture
def session(monkeypatch):
    session = Mock(spec=["mount", "headers", "close"])
    monkeypatch.setattr(http_client_module, "Session", lambda: session)
    return session


def test_http_client_returns_self_and_closes_session_on_exit(session):
    client = HttpClient()
    with client as opened:
        assert opened is client
        session.close.assert_not_called()
    session.close.assert_called_once_with()


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_http_client_closes_session_without_suppressing_errors(session, error_type):
    error = error_type("request processing failed")
    with pytest.raises(error_type) as caught:
        with HttpClient():
            raise error
    assert caught.value is error
    session.close.assert_called_once_with()
