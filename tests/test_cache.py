from copy import deepcopy
import sqlite3

import pytest

import core.cache as cache_module
from core.cache import URLCache, run_identity
from core.config import ProfileLoader


def test_new_url_is_not_cached(tmp_path) -> None:
    cache = URLCache(str(tmp_path / "cache.db"))

    assert cache.is_cached("https://example.com/page-1.html") is False


def test_mark_done_makes_url_cached(tmp_path) -> None:
    cache = URLCache(str(tmp_path / "cache.db"))
    url = "https://example.com/page-1.html"

    cache.mark_done(url, 20)

    assert cache.is_cached(url) is True


def test_clear_removes_cached_urls(tmp_path) -> None:
    cache = URLCache(str(tmp_path / "cache.db"))
    url = "https://example.com/page-1.html"
    cache.mark_done(url, 20)

    cache.clear()

    assert cache.is_cached(url) is False

@pytest.fixture
def expanded_profile(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("""site_name: Identity
engine: static
start_url: https://example.com
max_pages: 3
pagination:
  next_button: a.next
data_quality: true
fields:
  title: h2::text
  date:
    selector: time::text
    type: date
    format: '%d/%m/%Y'
""", encoding="utf-8")
    return ProfileLoader().load(path)


def test_identity_uses_expanded_snapshot_and_is_independent_of_mapping_order(tmp_path, expanded_profile):
    def reverse(value):
        if isinstance(value, dict):
            return {key: reverse(item) for key, item in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reverse(item) for item in value]
        return value

    before = deepcopy(expanded_profile)
    first = run_identity(expanded_profile, tmp_path / "out.csv")
    assert first == run_identity(reverse(expanded_profile), tmp_path / "out.csv")
    assert expanded_profile == before
    assert all(len(digest) == 64 for digest in first)


@pytest.mark.parametrize("key, value", [
    ("site_name", "Other"), ("engine", "browser"), ("start_url", "https://example.com/other"),
    ("max_pages", 4), ("delay", 2), ("wait_for", "article"),
    ("pagination", {"next_button": "a.more"}), ("record_selector", "article"),
    ("transform", {"title": "strip"}), ("transformation", {"title": "strip"}),
    ("transformations", {"title": "strip"}), ("data_quality", False),
    ("unique_key", ["title"]), ("duplicate_policy", "report_only"),
    ("include_provenance", True),
])
def test_behavior_settings_change_fingerprint(tmp_path, expanded_profile, key, value):
    old = run_identity(expanded_profile, tmp_path / "out.csv")
    changed = deepcopy(expanded_profile)
    changed[key] = value
    new = run_identity(changed, tmp_path / "out.csv")
    assert new[0] == old[0]
    assert new[1] != old[1]


@pytest.mark.parametrize("property_name, value", [
    ("selector", "time::attr(datetime)"), ("required", True), ("type", "string"),
    ("format", "%Y-%m-%d"),
])
def test_field_rules_change_fingerprint(tmp_path, expanded_profile, property_name, value):
    old = run_identity(expanded_profile, tmp_path / "out.csv")
    changed = deepcopy(expanded_profile)
    changed["fields"]["date"][property_name] = value
    assert run_identity(changed, tmp_path / "out.csv")[1] != old[1]


def test_destination_and_stem_change_identity_but_equivalent_paths_do_not(tmp_path, expanded_profile):
    first = run_identity(expanded_profile, tmp_path / "out.csv")
    assert first == run_identity(expanded_profile, tmp_path / "nested" / ".." / "out.csv")
    for path in (tmp_path / "other" / "out.csv", tmp_path / "different.csv"):
        second = run_identity(expanded_profile, path)
        assert second[0] != first[0]
        assert second[1] != first[1]


def test_identity_excludes_unrelated_secrets_and_runtime_state(tmp_path, expanded_profile):
    old = run_identity(expanded_profile, tmp_path / "out.csv")
    changed = deepcopy(expanded_profile)
    changed.update({"password": "secret", "api_key": "secret", "headers": {"Authorization": "secret"},
                    "runtime": object(), "last_quality_result": object()})
    assert run_identity(changed, tmp_path / "out.csv") == old


def test_old_database_is_extended_without_altering_legacy_or_unrelated_data(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE url_cache (url TEXT PRIMARY KEY, record_count INTEGER NOT NULL,
                                    scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO url_cache VALUES ('https://example.com', 10, '2000-01-01');
            CREATE TABLE unrelated (value TEXT);
            INSERT INTO unrelated VALUES ('keep');
        """)
    cache = URLCache(str(path))
    assert cache.is_cached("https://example.com")
    assert cache.completed_pages("destination", "profile") is None
    cache.mark_complete("destination", "profile", 3)
    assert cache.completed_pages("destination", "profile") == 3
    assert cache.completed_pages("destination", "other") is None
    cache.clear_runs()
    assert cache.completed_pages("destination", "profile") is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT * FROM url_cache").fetchall() == [
            ("https://example.com", 10, "2000-01-01"),
        ]
        assert connection.execute("SELECT * FROM unrelated").fetchall() == [("keep",)]


def test_completion_and_invalidation_are_committed_and_one_profile_owns_each_output(tmp_path):
    cache = URLCache(str(tmp_path / "cache.db"))
    cache.mark_complete("destination", "a", 3)
    other = URLCache(str(cache.db_path))
    assert other.completed_pages("destination", "a") == 3
    cache.mark_complete("destination", "b", 2)
    assert other.completed_pages("destination", "a") is None
    assert other.completed_pages("destination", "b") == 2
    cache.invalidate_run("destination")
    assert other.completed_pages("destination", "b") is None
    cache.mark_complete("destination", "a", 0)
    assert other.completed_pages("destination", "a") == 0
    cache.clear()
    assert other.completed_pages("destination", "a") is None


def test_initialization_and_completion_read_do_not_write_existing_database(tmp_path, monkeypatch):
    cache = URLCache(str(tmp_path / "cache.db"))
    cache.mark_complete("destination", "a", 3)
    before = cache.db_path.read_bytes(), cache.db_path.stat().st_mtime_ns
    cache = URLCache(str(cache.db_path))
    original_connect = sqlite3.connect
    statements = []

    def connect(*args, **kwargs):
        assert args[0].endswith("?mode=ro") and kwargs["uri"] is True
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(cache_module.sqlite3, "connect", connect)
    assert cache.completed_pages("destination", "a") == 3
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert (cache.db_path.read_bytes(), cache.db_path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("operation", ["mark_complete", "invalidate_run", "clear_runs"])
def test_cache_commit_failure_rolls_back_and_preserves_original_error(tmp_path, monkeypatch, operation):
    cache = URLCache(str(tmp_path / "cache.db"))
    if operation != "mark_complete":
        cache.mark_complete("destination", "a", 3)
    original_connect = sqlite3.connect
    error = sqlite3.OperationalError("commit failed")

    class FailedCommit(sqlite3.Connection):
        def __exit__(self, exc_type, exc_value, traceback):
            if exc_type is None:
                self.rollback()
                raise error
            return super().__exit__(exc_type, exc_value, traceback)

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=FailedCommit)

    with monkeypatch.context() as patch:
        patch.setattr(cache_module.sqlite3, "connect", connect)
        with pytest.raises(sqlite3.OperationalError) as caught:
            if operation == "mark_complete":
                cache.mark_complete("destination", "a", 3)
            elif operation == "invalidate_run":
                cache.invalidate_run("destination")
            else:
                cache.clear_runs()
    assert caught.value is error
    expected = None if operation == "mark_complete" else 3
    assert cache.completed_pages("destination", "a") == expected



def test_public_clear_removes_both_tables_and_preserves_unrelated_data(tmp_path):
    cache = URLCache(str(tmp_path / "cache.db"))
    cache.mark_done("https://example.com", 3)
    cache.mark_complete("one", "profile-one", 3)
    cache.mark_complete("two", "profile-two", 2)
    with sqlite3.connect(cache.db_path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('retained')")

    cache.clear()

    assert not cache.is_cached("https://example.com")
    assert cache.completed_pages("one", "profile-one") is None
    assert cache.completed_pages("two", "profile-two") is None
    with sqlite3.connect(cache.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM url_cache").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM run_completions").fetchone() == (0,)
        assert connection.execute("SELECT * FROM unrelated").fetchall() == [("retained",)]


def test_targeted_invalidation_preserves_legacy_and_unrelated_completion(tmp_path):
    cache = URLCache(str(tmp_path / "cache.db"))
    cache.mark_done("https://example.com", 3)
    cache.mark_complete("one", "profile-one", 3)
    cache.mark_complete("two", "profile-two", 2)
    with sqlite3.connect(cache.db_path) as connection:
        legacy = connection.execute("SELECT * FROM url_cache").fetchall()
        other = connection.execute("SELECT * FROM run_completions WHERE output_key = 'two'").fetchall()

    cache.invalidate_run("one")

    assert cache.completed_pages("one", "profile-one") is None
    with sqlite3.connect(cache.db_path) as connection:
        assert connection.execute("SELECT * FROM url_cache").fetchall() == legacy
        assert connection.execute("SELECT * FROM run_completions WHERE output_key = 'two'").fetchall() == other



def test_reopening_initialized_database_has_zero_changes_and_preserves_sidecars(tmp_path, monkeypatch):
    from contextlib import closing

    path = tmp_path / "cache.db"
    cache = URLCache(str(path))
    cache.mark_complete("destination", "profile", 3)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT * FROM run_completions").fetchall()
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    paths = [path] + [type(path)(str(path) + suffix) for suffix in ("-journal", "-wal", "-shm")]
    before = {file: (file.read_bytes(), file.stat().st_size, file.stat().st_mtime_ns)
              for file in paths if file.exists()}
    original_connect = sqlite3.connect
    observed, statements = [], []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        observed.append(connection)
        connection.set_trace_callback(statements.append)
        return connection

    try:
        with monkeypatch.context() as patch:
            patch.setattr(cache_module.sqlite3, "connect", connect)
            URLCache(str(path))
        assert observed and all(connection.total_changes == 0 for connection in observed)
        assert not any(statement.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                       for statement in statements)
    finally:
        for connection in observed:
            connection.close()
    assert {file: (file.read_bytes(), file.stat().st_size, file.stat().st_mtime_ns)
            for file in paths if file.exists()} == before
    with closing(original_connect(path)) as connection:
        assert connection.execute("SELECT * FROM run_completions").fetchall() == rows
