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


@pytest.mark.parametrize("status", [302, 307, 304])
def test_http_final_redirect_status_is_not_usable_content_regression(monkeypatch, status):
    from requests import HTTPError, Response

    response = Response()
    response.status_code = status
    response.url = "https://example.com/final"
    response._content = b"<article>Not a successful page</article>"
    client = HttpClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=response))

    with pytest.raises(HTTPError):
        with client:
            client.fetch("https://example.com/requested")


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_http_already_rejects_returned_4xx_and_5xx_responses(monkeypatch, status):
    from requests import HTTPError, Response

    response = Response()
    response.status_code = status
    response.url = "https://example.com/error"
    response._content = b"<article>HTTP error page</article>"
    client = HttpClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=response))
    with pytest.raises(HTTPError) as caught:
        with client:
            client.fetch(response.url)
    assert caught.value.response is response
    assert client.last_status_code == status


@pytest.mark.parametrize("status", [200, 201, 204, 206, 299])
def test_http_accepts_successful_final_status_and_preserves_decoding(monkeypatch, status):
    from requests import Response

    response = Response()
    response.status_code = status
    response.url = "https://example.com/final"
    response._content = "<article>Caf\u00e9</article>".encode("utf-8")
    client = HttpClient(timeout=12)
    get = Mock(return_value=response)
    monkeypatch.setattr(client.session, "get", get)
    with client:
        assert client.fetch("https://example.com/requested") == "<article>Caf\u00e9</article>"
    assert client.last_status_code == status
    get.assert_called_once_with("https://example.com/requested", timeout=12)


@pytest.mark.parametrize("status", [199, 302, 307, 304, 403, 404, 429, 500, 503, 600])
@pytest.mark.parametrize("final_url", ["https://example.com/final", None])
def test_http_status_error_exposes_metadata_before_body_access(monkeypatch, status, final_url):
    from requests import HTTPError, Request, Response
    from core.http_client import HTTPStatusError

    class GuardedResponse(Response):
        @property
        def content(self):
            pytest.fail("Failed final response content must not be accessed")
        @property
        def text(self):
            pytest.fail("Failed final response text must not be accessed")

    requested = "https://example.com/requested"
    response = GuardedResponse()
    response.status_code = status
    response.url = final_url
    response.request = Request("GET", final_url or requested).prepare()
    client = HttpClient()
    monkeypatch.setattr(client.session, "get", Mock(return_value=response))
    close = Mock(wraps=client.session.close)
    monkeypatch.setattr(client.session, "close", close)
    with pytest.raises(HTTPStatusError) as caught:
        with client:
            client.fetch(requested)
    error = caught.value
    assert isinstance(error, HTTPError)
    assert error.requested_url == requested
    assert error.final_url == final_url
    assert error.status_code == status
    assert error.response is response
    assert error.request is response.request
    assert str(error) == f"Fetch failed with HTTP {status} for {final_url or requested}"
    assert client.last_status_code == status
    close.assert_called_once_with()


@pytest.mark.parametrize("final_status", [200, 206, 302, 307, 304, 404, 503])
def test_http_automatic_redirects_validate_only_final_response(final_status):
    from requests import Response
    from requests.adapters import BaseAdapter
    from core.http_client import HTTPStatusError

    requested, intermediate, final = [f"https://example.com/{part}" for part in ("requested", "intermediate", "final")]
    calls = []
    class RedirectAdapter(BaseAdapter):
        def send(self, request, **kwargs):
            calls.append(request.url)
            response = Response()
            response.request = request
            response.url = request.url
            response.status_code = {requested: 302, intermediate: 307, final: final_status}[request.url]
            response._content = b"<article>Final document</article>"
            if request.url != final:
                response.headers["Location"] = intermediate if request.url == requested else final
            return response
        def close(self):
            pass

    with HttpClient() as client:
        client.session.mount("https://", RedirectAdapter())
        if 200 <= final_status < 300:
            assert client.fetch(requested) == "<article>Final document</article>"
        else:
            with pytest.raises(HTTPStatusError) as caught:
                client.fetch(requested)
            assert caught.value.requested_url == requested
            assert caught.value.final_url == final
            assert caught.value.status_code == final_status
            assert [item.status_code for item in caught.value.response.history] == [302, 307]
    assert calls == [requested, intermediate, final]


@pytest.mark.parametrize("error_name", ["Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError", "SSLError",
                                       "RetryError", "TooManyRedirects", "KeyboardInterrupt"])
def test_http_transport_errors_propagate_original_type_object_and_traceback(monkeypatch, error_name):
    import traceback
    from requests import exceptions

    error_type = KeyboardInterrupt if error_name == "KeyboardInterrupt" else getattr(exceptions, error_name)
    error = error_type("transport failed")
    def fail_get(*args, **kwargs):
        raise error
    client = HttpClient()
    monkeypatch.setattr(client.session, "get", fail_get)
    close = Mock(wraps=client.session.close)
    monkeypatch.setattr(client.session, "close", close)
    with pytest.raises(error_type) as caught:
        with client:
            client.fetch("https://example.com")
    assert caught.value is error
    assert type(caught.value) is error_type
    assert traceback.extract_tb(caught.value.__traceback__)[-1].name == "fail_get"
    close.assert_called_once_with()
