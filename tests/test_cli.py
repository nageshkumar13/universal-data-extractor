from copy import deepcopy
import os
import subprocess
import sys

import yaml

from core.quality import QualityProcessor
from core.http_client import HTTPStatusError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

import cli


def sample_summary(skipped=False):
    return {
        "site_name": "Example", "pages_scraped": 0 if skipped else 3,
        "records_extracted": 0 if skipped else 4, "records_transformed": 0 if skipped else 4,
        "cached_skips": 3 if skipped else 0, "robots_blocked": 0,
        "cache_only_run": skipped, "csv_path": Path("data/example.csv"),
        "json_path": Path("data/example.json"), "xlsx_path": Path("data/example.xlsx"),
    }


@pytest.mark.parametrize("skipped", [False, True])
def test_cli_distinguishes_completed_from_cached_skip_regression(monkeypatch, skipped):
    runner = SimpleNamespace(run=Mock(return_value=sample_summary(skipped)),
                             last_quality_result=None, last_quality_enabled=False)
    monkeypatch.setattr(cli, "ScrapeRunner", lambda: runner)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    result = CliRunner().invoke(cli.main, ["--profile", "unused.yaml"])
    assert result.exit_code == 0
    assert result.stdout.splitlines()[0] == ("Status: skipped" if skipped else "Status: completed")



def quality_result(records):
    return QualityProcessor().process(records, {
        "data_quality": True, "fields": {"id": {"selector": "article::text", "type": "int", "required": True}},
        "unique_key": ["id"], "duplicate_policy": "keep_first", "include_provenance": False,
    })


@pytest.mark.parametrize("quality, records, exported, rejected", [
    (False, [{"id": "1"}], 1, 0),
    (True, [{"id": "1"}, {"id": "bad"}, {"id": "1"}], 1, 1),
    (True, [{"id": "1"}], 1, 0),
    (True, [{"id": "bad"}], 0, 1),
    (False, [], 0, 0), (True, [], 0, 0),
])
def test_fresh_summary_exact_counts_order_and_pure_formatting(monkeypatch, quality, records, exported, rejected):
    summary = sample_summary()
    summary.update(records_extracted=len(records), records_transformed=len(records))
    result = quality_result(records) if quality else None
    before = deepcopy((summary, result))
    expected = ["Status: completed", "Pages scraped: 3", f"Records extracted: {len(records)}",
                f"Records transformed: {len(records)}"]
    expected += ([f"Clean records exported: {exported}", f"Records rejected: {rejected}"] if quality
                 else [f"Records exported: {exported}"])
    expected += ["Cached skips: 0", "Robots blocked: 0", "Data quality: " + ("enabled" if quality else "disabled"),
                 "CSV: data/example.csv", "JSON: data/example.json", "XLSX: data/example.xlsx"]
    if quality:
        expected += ["Quality report: data/example.quality.json", "Rejected records: data/example.rejected.json"]
    with monkeypatch.context() as patch:
        for method in ("open", "stat", "mkdir", "resolve", "exists"):
            patch.setattr(Path, method, Mock(side_effect=AssertionError("Formatter must not access filesystem")))
        text = cli.format_summary(summary, quality_enabled=quality, quality_result=result)
        assert text == "\n".join(expected)
        assert cli.format_summary(summary, quality_enabled=quality, quality_result=result) == text
    assert (summary, result) == before


@pytest.mark.parametrize("quality", [False, True])
def test_skip_summary_omits_unavailable_counts_and_reports_expected_paths(quality):
    expected = ["Status: skipped", "Reason: completed output already exists", "Pages scraped: 0",
                "Cached skips: 3", "Robots blocked: 0",
                "Data quality: " + ("enabled (not run; cached skip)" if quality else "disabled"),
                "CSV: data/example.csv", "JSON: data/example.json", "XLSX: data/example.xlsx"]
    if quality:
        expected += ["Quality report: data/example.quality.json", "Rejected records: data/example.rejected.json"]
    assert cli.format_summary(sample_summary(True), quality_enabled=quality) == "\n".join(expected)


def test_paths_with_spaces_unicode_and_markup_are_printed_literally(monkeypatch):
    summary = sample_summary()
    for extension, key in (("csv", "csv_path"), ("json", "json_path"), ("xlsx", "xlsx_path")):
        summary[key] = Path("client files") / f"caf\u00e9 [menu].{extension}"
    runner = SimpleNamespace(run=Mock(return_value=summary), last_quality_enabled=True,
                             last_quality_result=quality_result([{"id": "1"}]))
    monkeypatch.setattr(cli, "ScrapeRunner", lambda: runner)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    result = CliRunner(mix_stderr=False).invoke(cli.main, ["-p", "profile with spaces.yaml", "--clear-cache"])
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout.splitlines()[-5:] == [
        "CSV: client files/caf\u00e9 [menu].csv", "JSON: client files/caf\u00e9 [menu].json",
        "XLSX: client files/caf\u00e9 [menu].xlsx", "Quality report: client files/caf\u00e9 [menu].quality.json",
        "Rejected records: client files/caf\u00e9 [menu].rejected.json",
    ]
    runner.run.assert_called_once_with(profile_path=Path("profile with spaces.yaml"), output_dir=Path("data"), clear_cache=True)
    assert "\x1b" not in result.stdout


@pytest.fixture
def cli_job(tmp_path, monkeypatch):
    import core.runner as runner_module
    from core.cache import URLCache

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    cache = URLCache(str(tmp_path / "cache.db"))
    monkeypatch.setattr(runner_module, "URLCache", lambda: cache)

    class FakeClient:
        def __init__(self, pages):
            self.pages, self.calls = pages, []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def fetch(self, url, wait_for=None):
            self.calls.append(url)
            return self.pages[url]

    class Robots:
        def is_allowed(self, url):
            return url not in blocked

    blocked = set()
    monkeypatch.setattr(runner_module, "RobotsChecker", lambda url: Robots())
    urls = ["https://example.com/page-1", "https://example.com/page-2"]

    def make(quality, empty=False):
        profile = {"site_name": "Example", "engine": "static", "start_url": urls[0],
                   "record_selector": "article", "fields": {"id": "article::attr(data-id)"},
                   "data_quality": quality, "max_pages": 2, "pagination": {"next_button": "a.next"}}
        if quality:
            profile["fields"]["id"] = {"selector": "article::attr(data-id)", "type": "int", "required": True}
        path = tmp_path / "profile.yaml"
        path.write_text(yaml.safe_dump(profile), encoding="utf-8")
        pages = {urls[0]: ('<article data-id="1"></article><article data-id="bad"></article>' if not empty else '')
                 + '<a class="next" href="/page-2">Next</a>',
                 urls[1]: '<article data-id="2"></article>' if not empty else ''}
        client = FakeClient(pages)
        runner = runner_module.ScrapeRunner(client=client)
        monkeypatch.setattr(cli, "ScrapeRunner", lambda: runner)
        return SimpleNamespace(runner=runner, client=client, profile=profile, path=path, cache=cache,
                               blocked=blocked, urls=urls, pages=pages, new_client=lambda: FakeClient(pages))
    return make


@pytest.mark.parametrize("quality", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_real_run_then_skip_reports_existing_paths_without_writing_or_reading_audits(cli_job, monkeypatch, quality, empty):
    import core.cache as cache_module

    job = cli_job(quality, empty)
    commands = CliRunner(mix_stderr=False)
    first = commands.invoke(cli.main, ["-p", str(job.path)])
    assert first.exit_code == 0, first.exception
    assert first.stderr == ""
    extracted = 0 if empty else 3
    rejected = 0 if empty or not quality else 1
    expected = ["Status: completed", "Pages scraped: 2", f"Records extracted: {extracted}",
                f"Records transformed: {extracted}"]
    expected += ([f"Clean records exported: {extracted - rejected}", f"Records rejected: {rejected}"] if quality
                 else [f"Records exported: {extracted}"])
    expected += ["Cached skips: 0", "Robots blocked: 0", "Data quality: " + ("enabled" if quality else "disabled"),
                 "CSV: data/example.csv", "JSON: data/example.json", "XLSX: data/example.xlsx"]
    artifacts = [Path("data/example.csv"), Path("data/example.json"), Path("data/example.xlsx")]
    if quality:
        expected += ["Quality report: data/example.quality.json", "Rejected records: data/example.rejected.json"]
        artifacts += [Path("data/example.quality.json"), Path("data/example.rejected.json")]
    assert first.stdout == "\n".join(expected) + "\n"
    assert job.client.calls == job.urls
    assert job.runner.last_quality_enabled is quality
    assert all(path.is_file() and path.stat().st_size > 0 for path in artifacts)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in artifacts + [job.cache.db_path]}
    sidecars = [Path(str(job.cache.db_path) + suffix) for suffix in ("-journal", "-wal", "-shm")]
    before_sidecars = {path: path.read_bytes() for path in sidecars if path.exists()}
    for target, names in ((job.runner.quality_processor, ("process",)),
                          (job.runner.exporter, ("to_csv", "to_json", "to_excel", "write_quality_artifacts")),
                          (job.cache, ("mark_complete", "invalidate_run", "clear"))):
        for name in names:
            monkeypatch.setattr(target, name, Mock(side_effect=AssertionError("Skip must not process or write")))
    original_open = Path.open
    targets = {path.absolute() for path in artifacts}

    def open_without_artifacts(path, *args, **kwargs):
        assert path.absolute() not in targets, "CLI must not open existing exports or audits"
        return original_open(path, *args, **kwargs)

    statements = []
    original_connect = cache_module.sqlite3.connect

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    job.runner.client = job.new_client()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_without_artifacts)
        patch.setattr(cache_module.sqlite3, "connect", connect)
        second = commands.invoke(cli.main, ["--profile", str(job.path)])
    assert second.exit_code == 0, second.exception
    assert second.stderr == ""
    expected_skip = ["Status: skipped", "Reason: completed output already exists", "Pages scraped: 0",
                     "Cached skips: 2", "Robots blocked: 0",
                     "Data quality: " + ("enabled (not run; cached skip)" if quality else "disabled"),
                     "CSV: data/example.csv", "JSON: data/example.json", "XLSX: data/example.xlsx"]
    if quality:
        expected_skip += ["Quality report: data/example.quality.json", "Rejected records: data/example.rejected.json"]
    assert second.stdout == "\n".join(expected_skip) + "\n"
    assert first.stdout != second.stdout
    assert job.runner.client.calls == []
    assert job.runner.last_quality_result is None
    assert job.runner.last_quality_enabled is quality
    assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before} == before
    assert {path: path.read_bytes() for path in sidecars if path.exists()} == before_sidecars


@pytest.mark.parametrize("quality", [False, True])
@pytest.mark.parametrize("block_first", [False, True])
def test_robots_restrictions_report_partial_success_without_completion(cli_job, quality, block_first):
    from contextlib import closing
    import sqlite3

    job = cli_job(quality)
    job.blocked.add(job.urls[0 if block_first else 1])
    result = CliRunner(mix_stderr=False).invoke(cli.main, ["-p", str(job.path)])
    assert result.exit_code == 0, result.exception
    assert result.stderr == ""
    pages = 0 if block_first else 1
    records = 0 if block_first else 2
    expected = ["Status: completed", "Coverage: partial (robots restrictions)", f"Pages scraped: {pages}",
                f"Records extracted: {records}", f"Records transformed: {records}"]
    expected += ([f"Clean records exported: {0 if block_first else 1}", f"Records rejected: {0 if block_first else 1}"]
                 if quality else [f"Records exported: {records}"])
    expected += ["Cached skips: 0", "Robots blocked: 1", "Data quality: " + ("enabled" if quality else "disabled"),
                 "CSV: data/example.csv", "JSON: data/example.json", "XLSX: data/example.xlsx"]
    if quality:
        expected += ["Quality report: data/example.quality.json", "Rejected records: data/example.rejected.json"]
    assert result.stdout == "\n".join(expected) + "\n"
    assert job.client.calls == job.urls[:pages]
    with closing(sqlite3.connect(job.cache.db_path)) as connection:
        assert connection.execute("SELECT * FROM run_completions").fetchall() == []


@pytest.mark.parametrize("failure", ["profile", "selector", "http"])
def test_cli_failures_propagate_without_exports_or_completion(cli_job, monkeypatch, failure):
    from contextlib import closing
    import sqlite3
    from soupsieve import SelectorSyntaxError
    import core.runner as runner_module

    job = cli_job(True)
    if failure == "profile":
        job.profile["record_selector"] = None
        job.path.write_text(yaml.safe_dump(job.profile), encoding="utf-8")
        monkeypatch.setattr(runner_module, "create_client", Mock(side_effect=AssertionError("No client creation")))
        monkeypatch.setattr(runner_module, "RobotsChecker", Mock(side_effect=AssertionError("No robots request")))
        error_type = ValueError
    elif failure == "selector":
        job.profile["record_selector"] = "["
        job.path.write_text(yaml.safe_dump(job.profile), encoding="utf-8")
        error_type = SelectorSyntaxError
    else:
        error = HTTPStatusError(job.urls[0], 429, job.urls[0])
        job.client.fetch = Mock(side_effect=error)
        error_type = HTTPStatusError
    result = CliRunner(mix_stderr=False).invoke(cli.main, ["-p", str(job.path)])
    assert result.exit_code == 1
    assert isinstance(result.exception, error_type)
    if failure == "http":
        assert result.exception is error
    assert result.stdout == ""
    assert job.runner.last_quality_result is None
    assert not Path("data").exists()
    with closing(sqlite3.connect(job.cache.db_path)) as connection:
        assert connection.execute("SELECT * FROM run_completions").fetchall() == []



ENTRYPOINT_SCRIPT = r"""
import runpy
import sys
from pathlib import Path
from unittest.mock import patch
from requests.exceptions import Timeout, ConnectionError
from soupsieve import SelectorSyntaxError
from core.config import InvalidProfileError
from core.http_client import HTTPStatusError

case = sys.argv[1]
entrypoint = sys.argv[2]
errors = {
    "http": HTTPStatusError("https://example.com/start", 429, "https://example.com/final"),
    "profile": InvalidProfileError("Invalid record_selector. Expected a non-empty CSS selector."),
    "selector": SelectorSyntaxError("Malformed selector example"),
    "timeout": Timeout("Timed out fetching example page"),
    "connection": ConnectionError("Connection failed for example page"),
    "interrupt": KeyboardInterrupt(), "exit": SystemExit(7),
}
class FakeRunner:
    last_quality_enabled = False
    last_quality_result = None
    def run(self, **kwargs):
        if case in errors:
            raise errors[case]
        skip = case == "skipped"
        return {"site_name":"Example", "pages_scraped":0 if skip else 2,
                "records_extracted":0 if skip else 3, "records_transformed":0 if skip else 3,
                "cached_skips":2 if skip else 0, "robots_blocked":0, "cache_only_run":skip,
                "csv_path":Path("data/example.csv"), "json_path":Path("data/example.json"),
                "xlsx_path":Path("data/example.xlsx")}
sys.argv = [entrypoint, "--profile", "unused.yaml"]
with patch("core.runner.ScrapeRunner", FakeRunner), patch("dotenv.load_dotenv"):
    runpy.run_path(entrypoint, run_name="__main__")
"""


def run_entrypoint(case, tmp_path):
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(repo), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-c", ENTRYPOINT_SCRIPT, case, str(repo / "cli.py")],
                          cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)


@pytest.mark.parametrize("case, error_line", [
    ("http", "core.http_client.HTTPStatusError: Fetch failed with HTTP 429 for https://example.com/final"),
    ("profile", "ValueError: Invalid record_selector. Expected a non-empty CSS selector."),
    ("selector", "soupsieve.util.SelectorSyntaxError: Malformed selector example"),
    ("timeout", "requests.exceptions.Timeout: Timed out fetching example page"),
    ("connection", "requests.exceptions.ConnectionError: Connection failed for example page"),
])
def test_actual_entrypoint_preserves_traceback_type_message_and_failure_exit(tmp_path, case, error_line):
    result = run_entrypoint(case, tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("Traceback (most recent call last):")
    assert result.stderr.splitlines()[-1] == error_line
    assert "Status: completed" not in result.stderr
    assert "Status: skipped" not in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("case, code, stderr", [("interrupt", 1, "\nAborted!\n"), ("exit", 7, "")])
def test_actual_entrypoint_preserves_special_exit_behavior(tmp_path, case, code, stderr):
    result = run_entrypoint(case, tmp_path)
    assert result.returncode == code
    assert result.stdout == ""
    assert result.stderr == stderr


@pytest.mark.parametrize("skipped", [False, True])
def test_actual_entrypoint_success_exit_and_exact_streams(tmp_path, skipped):
    result = run_entrypoint("skipped" if skipped else "fresh", tmp_path)
    lines = (["Status: skipped", "Reason: completed output already exists", "Pages scraped: 0", "Cached skips: 2"]
             if skipped else ["Status: completed", "Pages scraped: 2", "Records extracted: 3",
                              "Records transformed: 3", "Records exported: 3", "Cached skips: 0"])
    lines += ["Robots blocked: 0", "Data quality: disabled", "CSV: data/example.csv",
              "JSON: data/example.json", "XLSX: data/example.xlsx"]
    assert result.returncode == 0
    assert result.stdout == "\n".join(lines) + "\n"
    assert result.stderr == ""


def test_required_profile_argument_and_help_are_preserved(monkeypatch):
    factory = Mock(side_effect=AssertionError("No runner for usage errors"))
    monkeypatch.setattr(cli, "ScrapeRunner", factory)
    commands = CliRunner(mix_stderr=False)
    invalid = commands.invoke(cli.main, [])
    assert invalid.exit_code == 2
    assert invalid.stdout == ""
    assert "Missing option '--profile' / '-p'" in invalid.stderr
    help_result = commands.invoke(cli.main, ["--help"])
    assert help_result.exit_code == 0
    assert "--profile" in help_result.stdout and "--clear-cache" in help_result.stdout
    factory.assert_not_called()



def test_quality_enabled_run_with_no_rejections_reports_zero(cli_job):
    job = cli_job(True)
    job.pages[job.urls[0]] = job.pages[job.urls[0]].replace('<article data-id="bad"></article>', '')
    result = CliRunner(mix_stderr=False).invoke(cli.main, ["-p", str(job.path)])
    assert result.exit_code == 0, result.exception
    assert result.stderr == ""
    assert result.stdout == (
        "Status: completed\nPages scraped: 2\nRecords extracted: 2\nRecords transformed: 2\n"
        "Clean records exported: 2\nRecords rejected: 0\nCached skips: 0\nRobots blocked: 0\n"
        "Data quality: enabled\nCSV: data/example.csv\nJSON: data/example.json\nXLSX: data/example.xlsx\n"
        "Quality report: data/example.quality.json\nRejected records: data/example.rejected.json\n"
    )
    assert Path("data/example.rejected.json").read_text(encoding="utf-8").strip() == "[]"


def test_fresh_quality_summary_requires_completed_result_without_printing_success(monkeypatch):
    runner = SimpleNamespace(run=Mock(return_value=sample_summary()), last_quality_enabled=True,
                             last_quality_result=None)
    monkeypatch.setattr(cli, "ScrapeRunner", lambda: runner)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    result = CliRunner(mix_stderr=False).invoke(cli.main, ["-p", "unused.yaml"])
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)
    assert str(result.exception) == "Completed quality run has no quality result."
    assert result.stdout == ""


@pytest.mark.parametrize("blocked", [0, 1])
def test_cached_skip_coverage_preserves_skip_status(monkeypatch, blocked):
    summary = sample_summary(True)
    summary["robots_blocked"] = blocked
    runner = SimpleNamespace(run=Mock(return_value=summary), last_quality_enabled=False,
                             last_quality_result=None)
    monkeypatch.setattr(cli, "ScrapeRunner", lambda: runner)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    result = CliRunner(mix_stderr=False).invoke(cli.main, ["-p", "unused.yaml"])
    expected = ["Status: skipped", "Reason: completed output already exists"]
    if blocked > 0:
        expected.append("Coverage: partial (robots restrictions)")
    expected += ["Pages scraped: 0", "Cached skips: 3", f"Robots blocked: {blocked}",
                 "Data quality: disabled", "CSV: data/example.csv", "JSON: data/example.json",
                 "XLSX: data/example.xlsx"]
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout == "\n".join(expected) + "\n"
