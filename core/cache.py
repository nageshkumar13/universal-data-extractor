from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any


# Only configuration inputs belong in the fingerprint, never runtime state or
# unrelated authentication settings. The loader owns validation and defaults.
FINGERPRINT_FIELDS = (
    "site_name", "engine", "start_url", "max_pages", "delay", "wait_for",
    "pagination", "record_selector", "fields", "transform", "transformation",
    "transformations", "data_quality", "unique_key", "duplicate_policy",
    "include_provenance",
)


def run_identity(profile: dict[str, Any], csv_path: Path) -> tuple[str, str]:
    """Hash the loaded profile snapshot and canonical output destination.

    One output slot has only one completion marker: profile A must not reuse
    files overwritten by profile B. No plaintext profile is persisted.
    """
    output_path = os.path.normcase(str(csv_path.resolve()))
    output_key = hashlib.sha256(output_path.encode("utf-8")).hexdigest()
    payload = {
        "version": 1,
        "profile": {key: profile[key] for key in FINGERPRINT_FIELDS if key in profile},
        "output_csv": output_path,
    }
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )
    return output_key, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class URLCache:
    def __init__(self, db_path: str = "data/cache.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def is_cached(self, url: str) -> bool:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM url_cache WHERE url = ? LIMIT 1",
                (url,),
            ).fetchone()
        return row is not None

    def mark_done(self, url: str, record_count: int) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO url_cache (url, record_count)
                VALUES (?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    record_count = excluded.record_count,
                    scraped_at = CURRENT_TIMESTAMP
                """,
                (url, record_count),
            )
            connection.commit()

    def clear(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DELETE FROM url_cache")
            connection.execute("DELETE FROM run_completions")
            connection.commit()

    def completed_pages(self, output_key: str, fingerprint: str) -> int | None:
        # Opening read-only also makes accidental writes on the skip path fail.
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            row = connection.execute(
                "SELECT pages_scraped FROM run_completions "
                "WHERE output_key = ? AND fingerprint = ?",
                (output_key, fingerprint),
            ).fetchone()
        return row[0] if row is not None else None

    def invalidate_run(self, output_key: str) -> None:
        # Commit before any network activity or output replacement begins.
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DELETE FROM run_completions WHERE output_key = ?", (output_key,))

    def mark_complete(self, output_key: str, fingerprint: str, pages_scraped: int) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute(
                """
                INSERT INTO run_completions (output_key, fingerprint, pages_scraped)
                VALUES (?, ?, ?)
                ON CONFLICT(output_key) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    pages_scraped = excluded.pages_scraped,
                    completed_at = CURRENT_TIMESTAMP
                """,
                (output_key, fingerprint, pages_scraped),
            )

    def clear_runs(self) -> None:
        """Force rebuilds without deleting legacy callers' URL-cache rows."""
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("DELETE FROM run_completions")

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS url_cache (
                    url TEXT PRIMARY KEY,
                    record_count INTEGER NOT NULL,
                    scraped_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS run_completions (
                    output_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    pages_scraped INTEGER NOT NULL CHECK (pages_scraped >= 0),
                    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.commit()
