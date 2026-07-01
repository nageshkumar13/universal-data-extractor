from pathlib import Path
from typing import Any
import time

from core.cache import URLCache
from core.config import ProfileLoader
from core.exporter import Exporter
from core.http_client import HttpClient
from core.pagination import Paginator
from core.parser import HTMLParser
from core.robots import RobotsChecker
from core.transformers import Transformer


class ScrapeRunner:
    def __init__(self) -> None:
        self.loader = ProfileLoader()
        self.client = HttpClient()
        self.parser = HTMLParser()
        self.paginator = Paginator()
        self.cache = URLCache()
        self.transformer = Transformer()
        self.exporter = Exporter()

    def run(
        self,
        profile_path: Path,
        output_dir: Path,
        clear_cache: bool = False,
    ) -> dict[str, Any]:
        profile = self.loader.load(profile_path)
        robots = RobotsChecker(profile["start_url"])

        if clear_cache:
            self.cache.clear()

        current_url = profile["start_url"]
        max_pages = profile.get("max_pages", 1)
        next_selector = profile.get("pagination", {}).get("next_button", "")
        delay = float(profile.get("delay", 0) or 0)
        processed_pages = 0
        pages_scraped = 0
        cached_skips = 0
        robots_blocked = 0
        request_count = 0
        all_records: list[dict[str, Any]] = []

        while current_url and processed_pages < max_pages:
            if not robots.is_allowed(current_url):
                robots_blocked += 1
                processed_pages += 1
                current_url = None
                continue

            if self.cache.is_cached(current_url):
                cached_skips += 1
                if next_selector:
                    html, request_count = self._fetch_page(
                        current_url,
                        delay,
                        request_count,
                    )
                    current_url = self.paginator.get_next_url(html, current_url, next_selector)
                else:
                    current_url = None

                processed_pages += 1
                continue

            html, request_count = self._fetch_page(
                current_url,
                delay,
                request_count,
            )
            records = self.parser.extract(html, profile["fields"], current_url)
            all_records.extend(records)
            self.cache.mark_done(current_url, len(records))

            current_url = (
                self.paginator.get_next_url(html, current_url, next_selector)
                if next_selector
                else None
            )
            pages_scraped += 1
            processed_pages += 1

        transformed_records = self.transformer.transform(all_records)
        csv_path, json_path, xlsx_path = self._build_output_paths(
            profile["site_name"],
            output_dir,
        )
        cache_only_run = pages_scraped == 0 and cached_skips > 0 and not transformed_records

        if transformed_records:
            csv_path = self.exporter.to_csv(transformed_records, csv_path)
            json_path = self.exporter.to_json(transformed_records, json_path)
            xlsx_path = self.exporter.to_excel(transformed_records, xlsx_path)
        elif not cache_only_run and (
            not csv_path.exists() or not json_path.exists() or not xlsx_path.exists()
        ):
            csv_path = self.exporter.to_csv(transformed_records, csv_path)
            json_path = self.exporter.to_json(transformed_records, json_path)
            xlsx_path = self.exporter.to_excel(transformed_records, xlsx_path)

        return {
            "site_name": profile["site_name"],
            "pages_scraped": pages_scraped,
            "records_extracted": len(all_records),
            "records_transformed": len(transformed_records),
            "cached_skips": cached_skips,
            "robots_blocked": robots_blocked,
            "cache_only_run": cache_only_run,
            "csv_path": csv_path,
            "json_path": json_path,
            "xlsx_path": xlsx_path,
        }

    def _fetch_page(
        self,
        url: str,
        delay: float,
        request_count: int,
    ) -> tuple[str, int]:
        if request_count > 0 and delay > 0:
            time.sleep(delay)

        html = self.client.fetch(url)
        return html, request_count + 1

    def _build_output_paths(self, site_name: str, output_dir: Path) -> tuple[Path, Path, Path]:
        slug = "".join(character.lower() if character.isalnum() else " " for character in site_name)
        slug = "_".join(slug.split())
        return (
            output_dir / f"{slug}.csv",
            output_dir / f"{slug}.json",
            output_dir / f"{slug}.xlsx",
        )
