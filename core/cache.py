import sqlite3
from pathlib import Path


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
            connection.commit()

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
            connection.commit()
