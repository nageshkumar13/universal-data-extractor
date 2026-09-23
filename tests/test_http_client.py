from unittest.mock import Mock

import pytest

from core import http_client as http_client_module
from core.http_client import HttpClient


@pytest.fixture(autouse=True)
def no_status_wait(monkeypatch):
    sleeper = Mock()
    monkeypatch.setattr(http_client_module, "sleep_seconds", sleeper)
    return sleeper


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
    response._content_consumed = True
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
    response.raw = Mock()  # Allow close() without reading the guarded body.
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
    assert calls == [requested, intermediate, final] * (4 if final_status == 503 else 1)


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


@pytest.fixture
def wire_client(monkeypatch):
    """Real Requests adapter + urllib3 retry loop; only socket I/O is faked."""
    from io import BytesIO
    from types import SimpleNamespace
    from urllib3 import HTTPConnectionPool
    from urllib3.response import HTTPResponse
    from urllib3.util.retry import Retry

    sleeps, transport_sleeps, calls = [], [], []
    client = HttpClient(sleep=sleeps.append, clock=lambda: 0)
    client.session.trust_env = False
    pool = HTTPConnectionPool("example.com")
    adapter = client.session.get_adapter("http://example.com")
    monkeypatch.setattr(adapter, "get_connection_with_tls_context", lambda *args, **kwargs: pool)
    # Observe urllib3's own transport backoff without patching global time.sleep.
    def backoff(retry):
        delay = retry.get_backoff_time()
        if delay:
            transport_sleeps.append(delay)
    monkeypatch.setattr(Retry, "_sleep_backoff", backoff)
    monkeypatch.setattr(Retry, "sleep_for_retry", Mock(side_effect=AssertionError("Adapter must not honor Retry-After")))
    state = SimpleNamespace(client=client, pool=pool, calls=calls, sleeps=sleeps,
                            transport_sleeps=transport_sleeps, outcomes=[])

    def request(conn, method, url, **kwargs):
        calls.append((method, url))
        outcome = state.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        status, headers = outcome
        return HTTPResponse(body=BytesIO(b"" if status in (204, 304) else b"<article>data</article>"), status=status,
                            headers=headers, preload_content=False)
    monkeypatch.setattr(pool, "_make_request", request)
    yield state
    client.close()
    pool.close()


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
@pytest.mark.parametrize("recover", [False, True])
def test_status_loop_is_the_only_status_retry_layer(wire_client, status, recover):
    from core.http_client import HTTPStatusError

    job = wire_client
    job.outcomes = [(status, {})] * 3 + [(200 if recover else status, {})]
    if recover:
        assert job.client.fetch("http://example.com/page") == "<article>data</article>"
    else:
        with pytest.raises(HTTPStatusError) as caught:
            job.client.fetch("http://example.com/page")
        assert caught.value.status_code == status
        assert caught.value.requested_url == caught.value.final_url == "http://example.com/page"
    assert job.calls == [("GET", "/page")] * 4
    assert job.sleeps == [1, 2, 4]
    assert job.transport_sleeps == []
    assert job.outcomes == []


@pytest.mark.parametrize("status", [301, 302, 307, 308, 304, 400, 401, 403, 404, 408, 409, 413, 425, 501])
def test_adapter_and_project_never_retry_other_statuses(wire_client, status):
    from core.http_client import HTTPStatusError

    job = wire_client
    job.outcomes = [(status, {"Retry-After": "60"})]
    with pytest.raises(HTTPStatusError) as caught:
        job.client.fetch("http://example.com/page")
    assert caught.value.status_code == status
    assert len(job.calls) == 1
    assert job.sleeps == job.transport_sleeps == []


@pytest.mark.parametrize("header, delays", [
    ("10", [10, 10, 10]), ("1", [1, 2, 4]), ("60", [60, 60, 60]),
    ("61", []), ("bad", [1, 2, 4]), ("-1", [1, 2, 4]), ("0", [1, 2, 4]),
    ("Wed, 31 Dec 1969 23:59:59 GMT", [1, 2, 4]),
    ("Thu, 01 Jan 1970 00:00:10 GMT", [10, 10, 10]),
])
def test_requests_retry_after_is_controlled_by_shared_policy(wire_client, header, delays):
    from core.http_client import HTTPStatusError

    job = wire_client
    job.outcomes = [(503, {"Retry-After": header})] * (len(delays) + 1)
    with pytest.raises(HTTPStatusError):
        job.client.fetch("http://example.com/page")
    assert job.sleeps == delays
    assert len(job.calls) == len(delays) + 1
    assert job.transport_sleeps == []


@pytest.mark.parametrize("kind, final_type", [
    ("connect", "ConnectTimeout"), ("refused", "ConnectionError"),
    ("dns", "ConnectionError"), ("tls", "SSLError"),
    ("read", "ConnectionError"), ("protocol", "ConnectionError"),
])
@pytest.mark.parametrize("recover", [False, True])
def test_real_adapter_preserves_transport_retries_and_exceptions(wire_client, kind, final_type, recover):
    import socket
    from requests import exceptions as requests_errors
    from urllib3 import exceptions as errors

    job = wire_client
    failures = {
        "connect": errors.ConnectTimeoutError("connect timed out"),
        "refused": errors.NewConnectionError(None, "connection refused"),
        "dns": errors.NameResolutionError("example.com", None, socket.gaierror("name resolution failed")),
        "tls": errors.SSLError("TLS handshake failed"),
        "read": errors.ReadTimeoutError(job.pool, "/page", "read timed out"),
        "protocol": errors.ProtocolError("connection reset"),
    }
    error = failures[kind]
    job.outcomes = [error] * 3 + ([(200, {})] if recover else [error])
    if recover:
        assert job.client.fetch("http://example.com/page") == "<article>data</article>"
    else:
        with pytest.raises(getattr(requests_errors, final_type)) as caught:
            job.client.fetch("http://example.com/page")
        assert type(caught.value) is getattr(requests_errors, final_type)
        assert caught.value.args[0].reason is error
    assert len(job.calls) == 4
    assert job.transport_sleeps == [2, 4]
    assert job.sleeps == []


def test_mixed_transport_and_status_attempt_bound_is_sixteen(wire_client):
    from urllib3.exceptions import ConnectTimeoutError
    from core.http_client import HTTPStatusError

    job = wire_client
    job.outcomes = ([ConnectTimeoutError("timeout")] * 3 + [(503, {})]) * 4
    with pytest.raises(HTTPStatusError) as caught:
        job.client.fetch("http://example.com/page")
    assert caught.value.status_code == 503
    assert len(job.calls) == 16
    assert job.sleeps == [1, 2, 4]
    assert job.transport_sleeps == [2, 4] * 4
    assert job.outcomes == []


@pytest.mark.parametrize("final_status", [200, 429, 503, 404])
def test_status_attempts_restart_original_redirect_chain(wire_client, final_status):
    from core.http_client import HTTPStatusError

    job = wire_client
    chain = [(302, {"Location": "/final"}), (final_status, {})]
    attempts = 4 if final_status in (429, 503) else 1
    job.outcomes = chain * attempts
    if final_status == 200:
        assert job.client.fetch("http://example.com/start") == "<article>data</article>"
    else:
        with pytest.raises(HTTPStatusError) as caught:
            job.client.fetch("http://example.com/start")
        assert caught.value.requested_url == "http://example.com/start"
        assert caught.value.final_url == "http://example.com/final"
        assert caught.value.status_code == final_status
    assert job.calls == [("GET", "/start"), ("GET", "/final")] * attempts
    assert job.sleeps == ([1, 2, 4] if attempts == 4 else [])
    assert job.transport_sleeps == []


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_adapter_configuration_keeps_get_transport_budget_only(scheme):
    with HttpClient() as client:
        policy = client.session.get_adapter(f"{scheme}://example.com").max_retries
        assert policy.total == 3
        assert policy.connect is policy.read is policy.other is None
        assert policy.allowed_methods == frozenset({"GET"})
        assert policy.status == 0
        assert not policy.status_forcelist
        assert policy.respect_retry_after_header is False


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_requests_interruption_during_retry_wait_does_not_retry(monkeypatch, error_type):
    from requests import Response

    response = Response()
    response.status_code = 503
    response.url = "https://example.com/final"
    response._content_consumed = True
    response.close = Mock()
    error = error_type()
    def sleep(delay):
        assert delay == 1
        response.close.assert_called_once_with()
        raise error
    with HttpClient(sleep=sleep) as client:
        get = Mock(return_value=response)
        monkeypatch.setattr(client.session, "get", get)
        with pytest.raises(error_type) as caught:
            client.fetch("https://example.com/start")
        assert caught.value is error
        get.assert_called_once_with("https://example.com/start", timeout=10)


@pytest.mark.parametrize("statuses, retry_after, delays", [
    ([503, 429, 200], None, [1, 2]),
    ([503, 503, 503, 503], None, [1, 2, 4]),
    ([503], "61", []),
    ([404], "60", []),
])
def test_discarded_responses_close_before_sleep_next_attempt_and_exit(monkeypatch, statuses, retry_after, delays):
    from requests import Response
    from core.http_client import HTTPStatusError

    events = []
    responses = []

    class ObservedResponse(Response):
        def __init__(self, index, status):
            super().__init__()
            self.index = index
            self.status_code = status
            self.url = f"https://example.com/final-{index}"
            self._content = b"rendered success"
            self._content_consumed = True  # Session.get buffers the body before returning.
            if retry_after is not None:
                self.headers["Retry-After"] = retry_after
            self.closed = False

        @property
        def content(self):
            assert 200 <= self.status_code < 300, "Failed response body must not be decoded"
            events.append(("content", self.index))
            return self._content

        def close(self):
            assert not self.closed
            self.closed = True
            events.append(("close", self.index))

    def get(url, **kwargs):
        assert url == "https://example.com/start"
        index = len(responses)
        if index:
            assert responses[-1].closed
        events.append(("get", index))
        response = ObservedResponse(index, statuses[index])
        responses.append(response)
        return response

    def sleep(delay):
        assert responses[-1].closed
        events.append(("sleep", delay))

    with HttpClient(sleep=sleep, clock=lambda: 0) as client:
        monkeypatch.setattr(client.session, "get", get)
        if statuses[-1] == 200:
            assert client.fetch("https://example.com/start") == "rendered success"
        else:
            with pytest.raises(HTTPStatusError) as caught:
                client.fetch("https://example.com/start")
            assert caught.value.response is responses[-1]
            assert caught.value.requested_url == "https://example.com/start"
            assert caught.value.final_url == responses[-1].url
            assert caught.value.status_code == statuses[-1]
    expected = []
    for index, status in enumerate(statuses):
        expected += [("get", index), ("content" if status == 200 else "close", index)]
        if index < len(delays):
            expected.append(("sleep", delays[index]))
    assert events == expected
    assert all(response.closed for response in responses if response.status_code != 200)


def test_response_cleanup_failure_preserves_status_and_prevents_retry(monkeypatch, caplog):
    from requests import Response
    from core.http_client import HTTPStatusError

    response = Response()
    response.status_code = 503
    response.url = "https://example.com/final"
    close_error = RuntimeError("response close failed")
    response.close = Mock(side_effect=close_error)
    sleeper = Mock()
    with HttpClient(sleep=sleeper) as client:
        get = Mock(return_value=response)
        monkeypatch.setattr(client.session, "get", get)
        with pytest.raises(HTTPStatusError) as caught:
            client.fetch("https://example.com/start")
    assert caught.value.status_code == 503
    assert caught.value.requested_url == "https://example.com/start"
    assert caught.value.final_url == response.url
    assert caught.value.response is response
    response.close.assert_called_once_with()
    get.assert_called_once_with("https://example.com/start", timeout=10)
    sleeper.assert_not_called()
    assert any(record.exc_info and record.exc_info[1] is close_error for record in caplog.records)
