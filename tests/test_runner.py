from pathlib import Path
from unittest.mock import Mock

import pytest

import core.runner as runner_module
from core.runner import ScrapeRunner


class FakeLoader:
    def __init__(self, profile: dict):
        self.profile = profile

    def load(self, path: Path) -> dict:
        return self.profile


class FakeClient:
    def __init__(self, html_by_url: dict[str, str]):
        self.html_by_url = html_by_url
        self.calls: list[str] = []
        self.enter_count = 0
        self.exit_count = 0
        self.closed = False
        self.exit_exception: BaseException | None = None

    def __enter__(self):
        self.enter_count += 1
        self.closed = False
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.exit_count += 1
        self.exit_exception = exc_value
        self.close()

    def close(self):
        self.closed = True

    def fetch(self, url: str, wait_for: str | None = None) -> str:
        assert self.enter_count == 1 and self.exit_count == 0
        self.calls.append(url)
        return self.html_by_url[url]


class FakeParser:
    def __init__(self, records_by_url: dict[str, list[dict]]):
        self.records_by_url = records_by_url

    def extract(self, html: str, fields: dict[str, str], base_url: str) -> list[dict]:
        return self.records_by_url[base_url]


class FakePaginator:
    def __init__(self, next_urls: dict[str, str | None]):
        self.next_urls = next_urls

    def get_next_url(self, html: str, current_url: str, next_selector: str) -> str | None:
        return self.next_urls[current_url]


class FakeCache:
    def __init__(self, cached_urls: set[str] | None = None):
        self.cached_urls = set(cached_urls or set())
        self.marked: list[tuple[str, int]] = []
        self.cleared = False

    def is_cached(self, url: str) -> bool:
        return url in self.cached_urls

    def mark_done(self, url: str, record_count: int) -> None:
        self.cached_urls.add(url)
        self.marked.append((url, record_count))

    def clear(self) -> None:
        self.cached_urls.clear()
        self.cleared = True


class FakeTransformer:
    def transform(self, records: list[dict]) -> list[dict]:
        return records


class FakeExporter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict], Path]] = []

    def to_csv(self, records: list[dict], output_path: Path) -> Path:
        self.calls.append(("csv", list(records), output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("csv", encoding="utf-8")
        return output_path

    def to_json(self, records: list[dict], output_path: Path) -> Path:
        self.calls.append(("json", list(records), output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("json", encoding="utf-8")
        return output_path

    def to_excel(self, records: list[dict], output_path: Path) -> Path:
        self.calls.append(("xlsx", list(records), output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("xlsx", encoding="utf-8")
        return output_path


class AllowAllRobots:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        return True


def test_runner_does_not_export_empty_files_when_all_pages_are_cached(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "site_name": "Cached Example",
        "engine": "static",
        "start_url": "https://example.com/page-1.html",
        "fields": {"title": "article h2::text"},
        "max_pages": 1,
        "delay": 0,
    }

    runner = ScrapeRunner()
    runner.loader = FakeLoader(profile)
    runner.client = FakeClient({})
    runner.parser = FakeParser({})
    runner.paginator = FakePaginator({})
    runner.cache = FakeCache({profile["start_url"]})
    runner.transformer = FakeTransformer()
    runner.exporter = FakeExporter()
    monkeypatch.setattr(runner_module, "RobotsChecker", AllowAllRobots)

    summary = runner.run(Path("profiles/example.yaml"), tmp_path)

    assert summary["cache_only_run"] is True
    assert summary["pages_scraped"] == 0
    assert summary["cached_skips"] == 1
    assert runner.client.enter_count == runner.client.exit_count == 1
    assert runner.client.closed is True
    assert runner.exporter.calls == []
    assert summary["csv_path"].exists() is False
    assert summary["json_path"].exists() is False
    assert summary["xlsx_path"].exists() is False


def test_runner_respects_profile_delay_between_requests(tmp_path, monkeypatch) -> None:
    page_one = "https://example.com/page-1.html"
    page_two = "https://example.com/page-2.html"
    profile = {
        "site_name": "Delayed Example",
        "engine": "static",
        "start_url": page_one,
        "fields": {"title": "article h2::text"},
        "max_pages": 2,
        "delay": 1.0,
        "pagination": {"next_button": "a.next"},
    }
    sleeps: list[float] = []

    runner = ScrapeRunner()
    runner.loader = FakeLoader(profile)
    runner.client = FakeClient(
        {
            page_one: "<html>page one</html>",
            page_two: "<html>page two</html>",
        }
    )
    runner.parser = FakeParser(
        {
            page_one: [{"title": "One"}],
            page_two: [{"title": "Two"}],
        }
    )
    runner.paginator = FakePaginator(
        {
            page_one: page_two,
            page_two: None,
        }
    )
    runner.cache = FakeCache()
    runner.transformer = FakeTransformer()
    runner.exporter = FakeExporter()

    monkeypatch.setattr(runner_module, "RobotsChecker", AllowAllRobots)
    monkeypatch.setattr(runner_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    stages = []
    original_transform = runner.transformer.transform

    def transform_after_exit(records):
        assert runner.client.exit_count == 1
        assert runner.client.closed is True
        stages.append("transform")
        return original_transform(records)

    monkeypatch.setattr(runner.transformer, "transform", transform_after_exit)

    def check_export_after_exit(method, stage):
        def export(records, output_path):
            assert runner.client.exit_count == 1
            assert runner.client.closed is True
            stages.append(stage)
            return method(records, output_path)
        return export

    for method_name in ("to_csv", "to_json", "to_excel"):
        method = getattr(runner.exporter, method_name)
        monkeypatch.setattr(
            runner.exporter, method_name, check_export_after_exit(method, method_name),
        )

    summary = runner.run(Path("profiles/example.yaml"), tmp_path)

    assert summary["pages_scraped"] == 2
    assert runner.client.calls == [page_one, page_two]
    assert sleeps == [1.0]
    assert runner.client.enter_count == runner.client.exit_count == 1
    assert runner.client.exit_exception is None
    assert stages == ["transform", "to_csv", "to_json", "to_excel"]
    assert summary["records_extracted"] == summary["records_transformed"] == 2
    assert summary["cached_skips"] == summary["robots_blocked"] == 0
    assert runner.cache.marked == [(page_one, 1), (page_two, 1)]


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
@pytest.mark.parametrize("client_source", ["injected", "factory"])
def test_runner_exits_client_when_fetch_raises(
    tmp_path, monkeypatch, error_type, client_source,
):
    profile = {
        "site_name": "Failing Example",
        "engine": "browser",
        "start_url": "https://example.com/page-1.html",
        "fields": {"title": "article h2::text"},
        "max_pages": 1,
        "delay": 0,
    }
    client = FakeClient({})
    error = error_type("fetch failed")

    def failing_fetch(url, wait_for=None):
        assert client.enter_count == 1 and client.exit_count == 0
        raise error

    monkeypatch.setattr(client, "fetch", failing_fetch)
    factory = Mock(return_value=client)
    monkeypatch.setattr(runner_module, "create_client", factory)
    monkeypatch.setattr(runner_module, "RobotsChecker", AllowAllRobots)
    runner = ScrapeRunner(client=client if client_source == "injected" else None)
    runner.loader = FakeLoader(profile)
    runner.cache = FakeCache()
    runner.transformer = Mock(spec=["transform"])
    runner.exporter = FakeExporter()

    with pytest.raises(error_type) as caught:
        runner.run(Path("profiles/example.yaml"), tmp_path)

    assert caught.value is error
    assert client.enter_count == client.exit_count == 1
    assert client.exit_exception is error
    assert client.closed is True
    runner.transformer.transform.assert_not_called()
    assert runner.exporter.calls == []
    if client_source == "factory":
        factory.assert_called_once_with("browser")
    else:
        factory.assert_not_called()
