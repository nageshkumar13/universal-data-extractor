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
