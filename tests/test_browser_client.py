from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from core import browser_client as browser_client_module
from core.browser_client import BrowserClient


@pytest.fixture
def playwright_mock(monkeypatch):
    manager = Mock(spec=["start"])
    playwright = Mock(spec=["chromium", "stop"])
    browser = Mock(spec=["new_context", "close"])
    context = Mock(spec=[
        "new_page", "set_default_timeout", "set_default_navigation_timeout", "close",
    ])
    manager.start.return_value = playwright
    playwright.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    pages = []

    def new_page():
        page = Mock(spec=["goto", "wait_for_selector", "content", "close"])
        page.goto.return_value = SimpleNamespace(status=200)
        page.content.return_value = "<html><article>Rendered</article></html>"
        pages.append(page)
        return page

    context.new_page.side_effect = new_page
    cleanup = Mock()
    cleanup.attach_mock(context.close, "context")
    cleanup.attach_mock(browser.close, "browser")
    cleanup.attach_mock(playwright.stop, "playwright")
    start = Mock(return_value=manager)
    monkeypatch.setattr(browser_client_module, "sync_playwright", start)
    return SimpleNamespace(
        start=start, manager=manager, playwright=playwright, browser=browser,
        context=context, pages=pages, cleanup=cleanup,
    )


def test_browser_client_waits_for_selector_and_returns_rendered_html(playwright_mock):
    resources = playwright_mock
    client = BrowserClient(timeout=12.0)
    with client as opened:
        assert opened is client
        for index in range(3):
            url = f"https://example.com/page-{index}"
            html = client.fetch(url, wait_for="article.result")
            assert html == "<html><article>Rendered</article></html>"
            assert client.last_status_code == 200
            page = resources.pages[index]
            page.goto.assert_called_once_with(url, wait_until="domcontentloaded")
            page.wait_for_selector.assert_called_once_with("article.result")
            page.close.assert_called_once_with()
            assert resources.cleanup.mock_calls == []

        resources.start.assert_called_once_with()
        resources.manager.start.assert_called_once_with()
        resources.playwright.chromium.launch.assert_called_once_with(headless=True)
        resources.browser.new_context.assert_called_once_with()
        resources.context.set_default_timeout.assert_called_once_with(12000.0)
        resources.context.set_default_navigation_timeout.assert_called_once_with(12000.0)
        assert resources.context.new_page.call_count == 3
        assert len({id(page) for page in resources.pages}) == 3

    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


def test_browser_client_requires_enter_before_fetch(playwright_mock):
    with pytest.raises(RuntimeError, match="must be opened"):
        BrowserClient().fetch("https://example.com")
    playwright_mock.start.assert_not_called()


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_browser_client_cleans_up_when_with_block_raises(playwright_mock, error_type):
    error = error_type("with block failed")
    with pytest.raises(error_type) as caught:
        with BrowserClient():
            raise error
    assert caught.value is error
    assert playwright_mock.cleanup.mock_calls == [
        call.context(), call.browser(), call.playwright(),
    ]


@pytest.mark.parametrize("operation", ["goto", "wait_for_selector", "content"])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize("close_fails", [False, True])
def test_browser_client_closes_page_when_fetch_raises(
    playwright_mock, operation, error_type, close_fails, caplog,
):
    resources = playwright_mock
    page = resources.context.new_page.side_effect()
    resources.context.new_page.side_effect = None
    resources.context.new_page.return_value = page
    error = error_type("page operation failed")
    getattr(page, operation).side_effect = error
    close_error = RuntimeError("page close failed")
    if close_fails:
        page.close.side_effect = close_error

    with pytest.raises(error_type) as caught:
        with BrowserClient() as client:
            client.fetch("https://example.com", wait_for="article")
    assert caught.value is error
    page.close.assert_called_once_with()
    if close_fails:
        assert any(
            record.name == "core.browser_client"
            and record.levelname == "ERROR"
            and record.getMessage() == "Failed to close page while handling a fetch error"
            and record.exc_info is not None
            and record.exc_info[1] is close_error
            for record in caplog.records
        )
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


@pytest.mark.parametrize("stage, expected_cleanup", [
    ("start", []),
    ("launch", [call.playwright()]),
    ("context", [call.browser(), call.playwright()]),
    ("selector_timeout", [call.context(), call.browser(), call.playwright()]),
    ("navigation_timeout", [call.context(), call.browser(), call.playwright()]),
])
@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_browser_client_cleans_up_partial_startup(
    playwright_mock, stage, expected_cleanup, error_type,
):
    resources = playwright_mock
    operations = {
        "start": resources.manager.start,
        "launch": resources.playwright.chromium.launch,
        "context": resources.browser.new_context,
        "selector_timeout": resources.context.set_default_timeout,
        "navigation_timeout": resources.context.set_default_navigation_timeout,
    }
    error = error_type("startup failed")
    operations[stage].side_effect = error
    client = BrowserClient()
    with pytest.raises(error_type) as caught:
        with client:
            pytest.fail("Startup should not succeed")
    assert caught.value is error
    assert resources.cleanup.mock_calls == expected_cleanup
    client.close()
    assert resources.cleanup.mock_calls == expected_cleanup
    with pytest.raises(RuntimeError, match="must be opened"):
        client.fetch("https://example.com")


@pytest.mark.parametrize("failing_resource", ["context", "browser", "playwright", "all"])
def test_browser_client_attempts_all_cleanup_after_close_failure(
    playwright_mock, failing_resource,
):
    resources = playwright_mock
    errors = []
    for name, operation in (
        ("context", resources.context.close),
        ("browser", resources.browser.close),
        ("playwright", resources.playwright.stop),
    ):
        if failing_resource in (name, "all"):
            error = RuntimeError(f"{name} cleanup failed")
            errors.append(error)
            operation.side_effect = error

    client = BrowserClient()
    with pytest.raises(RuntimeError) as caught:
        with client:
            pass
    assert caught.value is errors[0]
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]
    client.close()
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


def test_browser_client_close_is_idempotent(playwright_mock):
    client = BrowserClient()
    client.close()
    assert playwright_mock.cleanup.mock_calls == []
    with client:
        client.close()
        client.close()
    client.close()
    assert playwright_mock.cleanup.mock_calls == [
        call.context(), call.browser(), call.playwright(),
    ]
    with pytest.raises(RuntimeError, match="must be opened"):
        client.fetch("https://example.com")


@pytest.mark.parametrize("during_startup", [False, True])
def test_browser_client_preserves_original_error_if_cleanup_fails(
    playwright_mock, during_startup,
):
    resources = playwright_mock
    error = RuntimeError("original failure")
    resources.context.close.side_effect = RuntimeError("cleanup failure")
    if during_startup:
        resources.context.set_default_navigation_timeout.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        with BrowserClient():
            raise error
    assert caught.value is error
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_browser_client_propagates_close_error_after_successful_fetch(
    playwright_mock, error_type,
):
    resources = playwright_mock
    page = resources.context.new_page.side_effect()
    resources.context.new_page.side_effect = None
    resources.context.new_page.return_value = page
    error = error_type("page close failed")
    page.close.side_effect = error

    with pytest.raises(error_type) as caught:
        with BrowserClient() as client:
            client.fetch("https://example.com", wait_for="article")

    assert caught.value is error
    page.goto.assert_called_once_with("https://example.com", wait_until="domcontentloaded")
    page.wait_for_selector.assert_called_once_with("article")
    page.content.assert_called_once_with()
    page.close.assert_called_once_with()
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


@pytest.mark.parametrize("status", [302, 307, 304, 403, 404, 429, 500, 503])
def test_browser_failed_main_response_is_not_usable_html_regression(playwright_mock, status):
    from requests import HTTPError

    resources = playwright_mock
    page = resources.context.new_page.side_effect()
    resources.context.new_page.side_effect = None
    resources.context.new_page.return_value = page
    page.goto.return_value = SimpleNamespace(status=status, url="https://example.com/final")
    page.content.return_value = "<article>HTTP error page</article>"

    with pytest.raises(HTTPError):
        with BrowserClient() as client:
            client.fetch("https://example.com/requested")


@pytest.mark.parametrize("status", [200, 201, 204, 206, 299])
def test_browser_accepts_other_successful_main_statuses(playwright_mock, status):
    page = playwright_mock.context.new_page.side_effect()
    playwright_mock.context.new_page.side_effect = None
    playwright_mock.context.new_page.return_value = page
    page.goto.return_value = SimpleNamespace(status=status, url="https://example.com/final")
    with BrowserClient() as client:
        assert client.fetch("https://example.com/requested", wait_for="article") == page.content.return_value
        assert client.last_status_code == status
    page.wait_for_selector.assert_called_once_with("article")
    page.content.assert_called_once_with()
    page.close.assert_called_once_with()


@pytest.mark.parametrize("status", [199, 302, 307, 304, 403, 404, 429, 500, 503, 600])
def test_browser_failed_status_exposes_urls_and_never_reads_error_html(playwright_mock, status):
    from core.http_client import HTTPStatusError

    page = playwright_mock.context.new_page.side_effect()
    playwright_mock.context.new_page.side_effect = None
    playwright_mock.context.new_page.return_value = page
    page.goto.return_value = SimpleNamespace(status=status, url="https://example.com/final")
    with pytest.raises(HTTPStatusError) as caught:
        with BrowserClient() as client:
            client.fetch("https://example.com/requested", wait_for="article")
    assert caught.value.status_code == status
    assert caught.value.requested_url == "https://example.com/requested"
    assert caught.value.final_url == "https://example.com/final"
    assert str(caught.value) == f"Fetch failed with HTTP {status} for https://example.com/final"
    page.wait_for_selector.assert_not_called()
    page.content.assert_not_called()
    page.close.assert_called_once_with()
    assert playwright_mock.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


@pytest.mark.parametrize("final_status", [200, 206, 302, 307, 404, 503])
def test_browser_navigation_uses_final_response_after_redirects(playwright_mock, final_status):
    from core.http_client import HTTPStatusError

    page = playwright_mock.context.new_page.side_effect()
    playwright_mock.context.new_page.side_effect = None
    playwright_mock.context.new_page.return_value = page
    original_request = SimpleNamespace(url="https://example.com/requested", redirected_from=None)
    intermediate = SimpleNamespace(url="https://example.com/intermediate", redirected_from=original_request)
    final_request = SimpleNamespace(url="https://example.com/final", redirected_from=intermediate)
    page.goto.return_value = SimpleNamespace(status=final_status, url=final_request.url, request=final_request)
    with BrowserClient() as client:
        if final_status < 300:
            assert client.fetch(original_request.url) == page.content.return_value
        else:
            with pytest.raises(HTTPStatusError) as caught:
                client.fetch(original_request.url)
            assert caught.value.status_code == final_status
            assert caught.value.requested_url == original_request.url
            assert caught.value.final_url == final_request.url
            page.content.assert_not_called()
    page.goto.assert_called_once_with(original_request.url, wait_until="domcontentloaded")
    page.close.assert_called_once_with()


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("failure", ["no_response", "status"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_browser_validation_failure_closes_every_resource_and_preserves_primary_error(
    playwright_mock, scheme, failure, cleanup_fails, caplog,
):
    from core.http_client import HTTPStatusError

    resources = playwright_mock
    page = resources.context.new_page.side_effect()
    resources.context.new_page.side_effect = None
    resources.context.new_page.return_value = page
    url = f"{scheme}://example.com/page"
    page.goto.return_value = None if failure == "no_response" else SimpleNamespace(status=429, url=url)
    if cleanup_fails:
        page.close.side_effect = RuntimeError("page cleanup failed")
        resources.context.close.side_effect = RuntimeError("context cleanup failed")
        resources.browser.close.side_effect = RuntimeError("browser cleanup failed")
        resources.playwright.stop.side_effect = RuntimeError("playwright cleanup failed")
    error_type = RuntimeError if failure == "no_response" else HTTPStatusError
    original_errors = []
    with pytest.raises(error_type) as caught:
        with BrowserClient() as client:
            try:
                client.fetch(url, wait_for="article")
            except error_type as error:
                original_errors.append(error)
                raise
    assert caught.value is original_errors[0]
    if failure == "no_response":
        assert str(caught.value) == f"Browser navigation returned no main-document response for {url}"
        assert client.last_status_code is None
    else:
        assert caught.value.status_code == 429
    page.wait_for_selector.assert_not_called()
    page.content.assert_not_called()
    page.close.assert_called_once_with()
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]
    client.close()
    assert resources.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]
    if cleanup_fails:
        assert any(record.getMessage() == "Failed to close page while handling a fetch error" for record in caplog.records)
        assert any(record.getMessage() == "Failed to clean up browser resources while handling an error" for record in caplog.records)


@pytest.mark.parametrize("error_kind", ["timeout", "dns", "connection", "tls", "navigation", "interrupt"])
def test_browser_transport_errors_keep_original_type_object_and_traceback(playwright_mock, error_kind):
    import traceback
    from playwright.sync_api import Error, TimeoutError

    error_type = TimeoutError if error_kind == "timeout" else KeyboardInterrupt if error_kind == "interrupt" else Error
    error = error_type(f"{error_kind} failed")
    page = playwright_mock.context.new_page.side_effect()
    playwright_mock.context.new_page.side_effect = None
    playwright_mock.context.new_page.return_value = page
    def fail_navigation(*args, **kwargs):
        raise error
    page.goto.side_effect = fail_navigation
    with pytest.raises(error_type) as caught:
        with BrowserClient() as client:
            client.fetch("https://example.com")
    assert caught.value is error
    assert type(caught.value) is error_type
    assert traceback.extract_tb(caught.value.__traceback__)[-1].name == "fail_navigation"
    page.close.assert_called_once_with()
    assert playwright_mock.cleanup.mock_calls == [call.context(), call.browser(), call.playwright()]


def test_browser_ignores_secondary_404_when_main_document_succeeds(playwright_mock):
    handlers = []
    page = Mock(spec=["goto", "on", "wait_for_selector", "content", "close"])
    page.on.side_effect = lambda event, callback: handlers.append((event, callback))
    secondary = SimpleNamespace(status=404, url="https://example.com/image.png")
    main = SimpleNamespace(status=200, url="https://example.com/page")
    observed = []
    def goto(*args, **kwargs):
        for response in (main, secondary):
            observed.append(response.status)
            for event, callback in handlers:
                if event == "response":
                    callback(response)
        return main
    page.goto.side_effect = goto
    page.content.return_value = "<article>Main content</article>"
    playwright_mock.context.new_page.side_effect = None
    playwright_mock.context.new_page.return_value = page
    with BrowserClient() as client:
        assert client.fetch(main.url) == "<article>Main content</article>"
        assert client.last_status_code == 200
    assert observed == [200, 404]
    page.content.assert_called_once_with()
    page.close.assert_called_once_with()
