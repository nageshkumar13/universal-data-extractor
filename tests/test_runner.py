from copy import deepcopy
import json

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from openpyxl import load_workbook

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


@pytest.fixture
def make_quality_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "URLCache", FakeCache)
    monkeypatch.setattr(runner_module, "RobotsChecker", AllowAllRobots)

    def make(quality=True, html_by_url=None):
        start_url = "https://example.com/page-1.html"
        selectors = {
            "id": "article::attr(data-id)",
            "title": "article h2::text",
            "price": "article .price::text",
        }
        profile = {
            "site_name": "Quality Example",
            "engine": "static",
            "start_url": start_url,
            "fields": selectors,
            "max_pages": 2,
            "delay": 0,
            "pagination": {"next_button": "a.next"},
        }
        if quality is not None:
            profile["data_quality"] = quality
        if quality is True:
            profile.update({
                "fields": {
                    "id": {"selector": selectors["id"], "required": True, "type": "int"},
                    "title": selectors["title"],
                    "price": {"selector": selectors["price"], "type": "float"},
                },
                "unique_key": ["id"],
            })
        profile_path = tmp_path / "integration.yaml"
        profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
        if html_by_url is None:
            html_by_url = {
                start_url: '<article data-id="1"><h2>One</h2><p class="price">12.50</p></article>',
            }
        runner = ScrapeRunner(client=FakeClient(html_by_url))
        runner.exporter = FakeExporter()
        return runner, profile_path

    return make


@pytest.mark.parametrize("quality", [None, False])
def test_legacy_run_skips_quality_and_preserves_export_and_return_contract(
    tmp_path, make_quality_runner, quality,
):
    runner, path = make_quality_runner(quality=quality)
    runner.quality_processor = Mock()
    assert runner.last_quality_result is None

    summary = runner.run(path, tmp_path)

    runner.quality_processor.process.assert_not_called()
    assert runner.last_quality_result is None
    expected_records = [{"id": "1", "title": "One", "price": 12.5}]
    assert [call[0] for call in runner.exporter.calls] == ["csv", "json", "xlsx"]
    assert all(call[1] == expected_records for call in runner.exporter.calls)
    assert summary == {
        "site_name": "Quality Example", "pages_scraped": 1,
        "records_extracted": 1, "records_transformed": 1,
        "cached_skips": 0, "robots_blocked": 0, "cache_only_run": False,
        "csv_path": tmp_path / "quality_example.csv",
        "json_path": tmp_path / "quality_example.json",
        "xlsx_path": tmp_path / "quality_example.xlsx",
    }


def test_quality_runs_once_after_transform_across_pages_before_all_exports(
    tmp_path, make_quality_runner,
):
    page_one = "https://example.com/page-1.html"
    page_two = "https://example.com/page-2.html"
    html_by_url = {
        page_one: (
            '<article data-id="01"><h2>First</h2><p class="price">12.50</p></article>'
            '<article data-id="bad"><h2>Rejected</h2><p class="price">1.00</p></article>'
            '<a class="next" href="page-2.html">Next</a>'
        ),
        page_two: (
            '<article data-id="1"><h2>Duplicate</h2><p class="price">15.50</p></article>'
            '<article data-id="2"><h2>Second</h2><p class="price">20.00</p></article>'
        ),
    }
    runner, path = make_quality_runner(html_by_url=html_by_url)
    expected_profile = runner.loader.load(path)
    runner.loader.load = Mock(return_value=expected_profile)
    original_profile = deepcopy(expected_profile)
    stages, parser_batches, original_batches = [], [], []
    original_extract = runner.parser.extract

    def extract(html, fields, base_url):
        assert fields == {
            name: definition["selector"]
            for name, definition in expected_profile["fields"].items()
        }
        records = original_extract(html, fields, base_url)
        parser_batches.append(records)
        original_batches.append(deepcopy(records))
        return records

    runner.parser.extract = Mock(side_effect=extract)
    original_transform = runner.transformer.transform

    def transform(records):
        assert runner.client.closed
        assert records == [record for batch in original_batches for record in batch]
        stages.append("transform")
        return original_transform(records)

    runner.transformer.transform = Mock(side_effect=transform)
    original_process = runner.quality_processor.process
    transformed_snapshots = []

    def process(records, profile):
        assert stages == ["transform"]
        assert runner.client.closed
        assert profile is expected_profile
        assert all(isinstance(record["price"], float) for record in records)
        transformed_snapshots.append(deepcopy(records))
        stages.append("quality")
        return original_process(records, profile)

    runner.quality_processor.process = Mock(side_effect=process)

    def observe_export(method, stage):
        def export(records, output_path):
            assert "quality" in stages
            assert records is runner.last_quality_result.clean_records
            stages.append(stage)
            return method(records, output_path)
        return export

    for name in ("to_csv", "to_json", "to_excel"):
        setattr(runner.exporter, name, observe_export(getattr(runner.exporter, name), name))

    summary = runner.run(path, tmp_path)

    runner.quality_processor.process.assert_called_once()
    result = runner.last_quality_result
    assert result is not None
    assert result.clean_records == [
        {"id": 1, "title": "First", "price": 12.5},
        {"id": 2, "title": "Second", "price": 20.0},
    ]
    assert result.rejected_records[0]["normalized"]["title"] == "Rejected"
    assert result.report.extracted == result.report.valid_before_deduplication + result.report.rejected == 4
    assert result.report.exported == result.report.valid_before_deduplication - result.report.duplicates_removed == 2
    assert stages == ["transform", "quality", "to_csv", "to_json", "to_excel"]
    assert all(call[1] == result.clean_records for call in runner.exporter.calls)
    assert summary["records_extracted"] == summary["records_transformed"] == 4
    assert summary["pages_scraped"] == 2
    assert summary["cached_skips"] == summary["robots_blocked"] == 0
    assert runner.client.calls == [page_one, page_two]
    assert runner.cache.marked == [(page_one, 2), (page_two, 2)]
    assert runner.client.enter_count == runner.client.exit_count == 1
    assert expected_profile == original_profile
    assert parser_batches == original_batches
    assert runner.quality_processor.process.call_args.args[0] == transformed_snapshots[0]
    assert html_by_url == runner.client.html_by_url


@pytest.mark.parametrize("preexisting", [False, True])
def test_all_rejected_records_export_empty_clean_lists(tmp_path, make_quality_runner, preexisting):
    runner, path = make_quality_runner(html_by_url={
        "https://example.com/page-1.html": (
            '<article data-id="bad"><h2>Rejected</h2><p class="price">1.00</p></article>'
        ),
    })
    if preexisting:
        for extension in ("csv", "json", "xlsx"):
            (tmp_path / f"quality_example.{extension}").write_text("previous", encoding="utf-8")
    runner.quality_processor.process = Mock(wraps=runner.quality_processor.process)

    summary = runner.run(path, tmp_path)

    runner.quality_processor.process.assert_called_once()
    assert [call[0] for call in runner.exporter.calls] == ["csv", "json", "xlsx"]
    assert all(call[1] == [] for call in runner.exporter.calls)
    assert runner.last_quality_result.report.rejected == 1
    assert runner.last_quality_result.report.exported == 0
    assert summary["records_transformed"] == 1
    assert summary["cache_only_run"] is False


def test_existing_exporters_accept_empty_quality_output(tmp_path, make_quality_runner):
    runner, path = make_quality_runner(html_by_url={
        "https://example.com/page-1.html": '<article data-id="bad"><h2>Rejected</h2></article>',
    })
    runner.exporter = runner_module.Exporter()

    summary = runner.run(path, tmp_path)

    assert runner.last_quality_result.clean_records == []
    assert summary["csv_path"].read_text(encoding="utf-8").strip() == ""
    assert json.loads(summary["json_path"].read_text(encoding="utf-8")) == []
    workbook = load_workbook(summary["xlsx_path"])
    try:
        assert list(workbook.active.values) == []
    finally:
        workbook.close()


@pytest.mark.parametrize("error_type", [RuntimeError, KeyboardInterrupt])
def test_processor_failure_propagates_without_export_or_stale_result(
    tmp_path, make_quality_runner, error_type,
):
    runner, path = make_quality_runner()
    runner.run(path, tmp_path)
    assert runner.last_quality_result is not None
    runner.client = FakeClient(runner.client.html_by_url)
    runner.exporter.calls.clear()
    error = error_type("quality failed")

    def fail(records, profile):
        assert runner.last_quality_result is None
        assert runner.client.closed
        raise error

    runner.quality_processor.process = Mock(side_effect=fail)

    with pytest.raises(error_type) as caught:
        runner.run(path, tmp_path, clear_cache=True)

    assert caught.value is error
    runner.quality_processor.process.assert_called_once()
    assert runner.exporter.calls == []
    assert runner.last_quality_result is None


@pytest.mark.parametrize("stage", ["load", "fetch", "transform"])
def test_result_is_reset_before_failures_earlier_in_the_pipeline(
    tmp_path, make_quality_runner, stage,
):
    runner, path = make_quality_runner()
    runner.run(path, tmp_path)
    assert runner.last_quality_result is not None
    runner.client = FakeClient(runner.client.html_by_url)
    runner.exporter.calls.clear()
    runner.quality_processor.process = Mock()
    error = RuntimeError(f"{stage} failed")

    def fail(*args, **kwargs):
        assert runner.last_quality_result is None
        raise error

    target, method = {
        "load": (runner.loader, "load"),
        "fetch": (runner.client, "fetch"),
        "transform": (runner.transformer, "transform"),
    }[stage]
    setattr(target, method, Mock(side_effect=fail))

    with pytest.raises(RuntimeError) as caught:
        runner.run(path, tmp_path, clear_cache=True)

    assert caught.value is error
    assert runner.last_quality_result is None
    runner.quality_processor.process.assert_not_called()
    assert runner.exporter.calls == []


@pytest.mark.parametrize("quality", [None, False])
def test_later_legacy_run_clears_previous_quality_result(tmp_path, make_quality_runner, quality):
    runner, path = make_quality_runner()
    runner.run(path, tmp_path)
    assert runner.last_quality_result is not None
    legacy_runner, legacy_path = make_quality_runner(quality=quality)
    runner.client = legacy_runner.client
    runner.quality_processor.process = Mock()
    runner.exporter.calls.clear()
    original_load = runner.loader.load

    def load(profile_path):
        assert runner.last_quality_result is None
        return original_load(profile_path)

    runner.loader.load = Mock(side_effect=load)

    summary = runner.run(legacy_path, tmp_path, clear_cache=True)

    assert runner.last_quality_result is None
    runner.quality_processor.process.assert_not_called()
    assert all(call[1] == [{"id": "1", "title": "One", "price": 12.5}] for call in runner.exporter.calls)
    assert summary["records_transformed"] == 1


def test_quality_cache_only_run_preserves_existing_skip_behavior(tmp_path, make_quality_runner):
    runner, path = make_quality_runner()
    runner.run(path, tmp_path)
    previous_result = runner.last_quality_result
    runner.client = FakeClient({})
    runner.exporter.calls.clear()
    profile = runner.loader.load(path)
    profile.pop("pagination")
    runner.loader = FakeLoader(profile)
    runner.quality_processor.process = Mock(wraps=runner.quality_processor.process)

    summary = runner.run(path, tmp_path)

    runner.quality_processor.process.assert_called_once_with([], profile)
    assert runner.last_quality_result is not previous_result
    assert runner.last_quality_result.report.extracted == 0
    assert runner.last_quality_result.clean_records == []
    assert runner.exporter.calls == []
    assert runner.client.calls == []
    assert summary["cache_only_run"] is True
    assert summary["cached_skips"] == 1


def test_quality_run_preserves_robots_blocking(tmp_path, make_quality_runner, monkeypatch):
    runner, path = make_quality_runner()
    robots = Mock()
    robots.is_allowed.return_value = False
    monkeypatch.setattr(runner_module, "RobotsChecker", Mock(return_value=robots))
    runner.quality_processor.process = Mock(wraps=runner.quality_processor.process)

    summary = runner.run(path, tmp_path)

    assert summary["robots_blocked"] == 1
    assert summary["pages_scraped"] == summary["records_extracted"] == 0
    assert runner.client.calls == []
    assert runner.cache.marked == []
    runner.quality_processor.process.assert_called_once()
    assert runner.quality_processor.process.call_args.args[0] == []
    assert all(call[1] == [] for call in runner.exporter.calls)


@pytest.mark.parametrize("existing_formats", [(), ("csv",), ("csv", "json", "xlsx")])
def test_zero_extracted_records_produce_zero_quality_result_and_preserve_export_path(
    tmp_path, make_quality_runner, existing_formats,
):
    from dataclasses import asdict

    runner, path = make_quality_runner(html_by_url={
        "https://example.com/page-1.html": "<html><body>No listings</body></html>",
    })
    profile = runner.loader.load(path)
    runner.quality_processor.process = Mock(wraps=runner.quality_processor.process)
    for extension in existing_formats:
        (tmp_path / f"quality_example.{extension}").write_text("previous", encoding="utf-8")

    summary = runner.run(path, tmp_path)

    runner.quality_processor.process.assert_called_once_with([], profile)
    result = runner.last_quality_result
    assert result is not None
    assert result.clean_records == result.rejected_records == []
    assert all(count == 0 for count in asdict(result.report).values())
    result.report.enforce_invariants()
    assert summary["pages_scraped"] == 1
    assert summary["records_extracted"] == summary["records_transformed"] == 0
    assert summary["cache_only_run"] is False
    if len(existing_formats) == 3:
        assert runner.exporter.calls == []
        for extension in existing_formats:
            assert (tmp_path / f"quality_example.{extension}").read_text(encoding="utf-8") == "previous"
    else:
        assert [call[0] for call in runner.exporter.calls] == ["csv", "json", "xlsx"]
        assert all(call[1] == [] for call in runner.exporter.calls)
        assert all(summary[f"{extension}_path"].exists() for extension in ("csv", "json", "xlsx"))


@pytest.mark.parametrize("failing_method", ["to_csv", "to_json", "to_excel"])
def test_exporter_failure_retains_completed_quality_result(
    tmp_path, make_quality_runner, failing_method,
):
    runner, path = make_quality_runner()
    runner.run(path, tmp_path)
    previous_result = runner.last_quality_result
    assert previous_result is not None
    runner.client = FakeClient(runner.client.html_by_url)
    runner.exporter.calls.clear()
    completed_results = []
    original_process = runner.quality_processor.process

    def process(records, profile):
        assert runner.last_quality_result is None
        result = original_process(records, profile)
        completed_results.append(result)
        return result

    runner.quality_processor.process = Mock(side_effect=process)
    error = OSError(f"{failing_method} failed")

    def fail(records, output_path):
        assert runner.last_quality_result is completed_results[0]
        assert records is completed_results[0].clean_records
        raise error

    methods = ("to_csv", "to_json", "to_excel")
    for method in methods:
        original_export = getattr(runner.exporter, method)
        setattr(runner.exporter, method, Mock(wraps=original_export))
    getattr(runner.exporter, failing_method).side_effect = fail

    with pytest.raises(OSError) as caught:
        runner.run(path, tmp_path, clear_cache=True)

    assert caught.value is error
    runner.quality_processor.process.assert_called_once()
    assert runner.last_quality_result is completed_results[0]
    assert runner.last_quality_result is not previous_result
    assert runner.last_quality_result.clean_records == [{"id": 1, "title": "One", "price": 12.5}]
    assert runner.last_quality_result.rejected_records == []
    assert runner.last_quality_result.report.exported == 1
    runner.last_quality_result.report.enforce_invariants()
    failed_index = methods.index(failing_method)
    for index, method in enumerate(methods):
        if index <= failed_index:
            getattr(runner.exporter, method).assert_called_once()
        else:
            getattr(runner.exporter, method).assert_not_called()
