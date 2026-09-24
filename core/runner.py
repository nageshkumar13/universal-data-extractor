from pathlib import Path
from typing import Any
import time

from core.cache import URLCache, run_identity
from core.client_factory import PageClient, create_client
from core.config import ProfileLoader
from core.exporter import Exporter, quality_artifact_paths
from core.pagination import Paginator
from core.parser import HTMLParser
from core.quality import QualityProcessor, QualityResult
from core.robots import RobotsChecker
from core.transformers import Transformer


class ScrapeRunner:
    def __init__(self, client: PageClient | None = None) -> None:
        self.loader = ProfileLoader()
        self.client = client
        self.parser = HTMLParser()
        self.paginator = Paginator()
        self.cache = URLCache()
        self.transformer = Transformer()
        self.exporter = Exporter()
        self.quality_processor = QualityProcessor()
        self.last_quality_result: QualityResult | None = None
        self._last_quality_enabled = False

    @property
    def last_quality_enabled(self) -> bool:
        """Whether the most recent run's validated profile enabled quality."""
        return self._last_quality_enabled

    def run(
        self,
        profile_path: Path,
        output_dir: Path,
        clear_cache: bool = False,
    ) -> dict[str, Any]:
        self.last_quality_result = None
        self._last_quality_enabled = False
        profile = self.loader.load(profile_path)
        quality_enabled = profile.get("data_quality") is True
        self._last_quality_enabled = quality_enabled
        parser_fields = profile["fields"]
        if quality_enabled:
            parser_fields = {
                name: definition["selector"]
                for name, definition in profile["fields"].items()
            }
        csv_path, json_path, xlsx_path = self._build_output_paths(profile["site_name"], output_dir)
        expected_outputs = [csv_path, json_path, xlsx_path]
        if quality_enabled:
            expected_outputs.extend(quality_artifact_paths(csv_path))
        output_key, fingerprint = run_identity(profile, csv_path)
        if clear_cache:
            self.cache.clear()
        completed_pages = self.cache.completed_pages(output_key, fingerprint)
        if completed_pages is not None and self._outputs_complete(expected_outputs):
            return {
                "site_name": profile["site_name"], "pages_scraped": 0,
                "records_extracted": 0, "records_transformed": 0,
                "cached_skips": completed_pages, "robots_blocked": 0, "cache_only_run": True,
                "csv_path": csv_path, "json_path": json_path, "xlsx_path": xlsx_path,
            }

        # Invalidate this destination even when its previous fingerprint differs.
        # A failed rebuild must never leave an older profile's marker usable.
        self.cache.invalidate_run(output_key)
        client = self.client if self.client is not None else create_client(profile["engine"])
        robots = RobotsChecker(profile["start_url"])

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

        # The runner owns both factory-created and injected clients.
        with client as client:
            while current_url and processed_pages < max_pages:
                if not robots.is_allowed(current_url):
                    robots_blocked += 1
                    processed_pages += 1
                    current_url = None
                    continue

                html, request_count = self._fetch_page(
                    client,
                    current_url,
                    delay,
                    request_count,
                    profile.get("wait_for"),
                )
                if "record_selector" in profile:
                    records = self.parser.extract(
                        html, parser_fields, current_url,
                        record_selector=profile["record_selector"],
                    )
                else:
                    records = self.parser.extract(html, parser_fields, current_url)
                all_records.extend(records)

                current_url = (
                    self.paginator.get_next_url(html, current_url, next_selector)
                    if next_selector
                    else None
                )
                pages_scraped += 1
                processed_pages += 1

        transformed_records = self.transformer.transform(all_records)
        export_records = transformed_records
        if quality_enabled:
            self.last_quality_result = self.quality_processor.process(
                transformed_records, profile,
            )
            export_records = self.last_quality_result.clean_records
        if self.last_quality_result is not None:
            self.exporter.write_quality_artifacts(self.last_quality_result, csv_path)

        csv_path = self.exporter.to_csv(export_records, csv_path)
        json_path = self.exporter.to_json(export_records, json_path)
        xlsx_path = self.exporter.to_excel(export_records, xlsx_path)

        if not self._outputs_complete(expected_outputs):
            raise RuntimeError("Required output files are missing or empty after export.")
        if not robots_blocked:
            # The last state-changing action, after every required output succeeds.
            self.cache.mark_complete(output_key, fingerprint, pages_scraped)

        return {
            "site_name": profile["site_name"],
            "pages_scraped": pages_scraped,
            "records_extracted": len(all_records),
            "records_transformed": len(transformed_records),
            "cached_skips": cached_skips,
            "robots_blocked": robots_blocked,
            "cache_only_run": False,
            "csv_path": csv_path,
            "json_path": json_path,
            "xlsx_path": xlsx_path,
        }

    @staticmethod
    def _outputs_complete(paths: list[Path]) -> bool:
        return all(path.is_file() and path.stat().st_size > 0 for path in paths)

    def _fetch_page(
        self,
        client: PageClient,
        url: str,
        delay: float,
        request_count: int,
        wait_for: str | None,
    ) -> tuple[str, int]:
        if request_count > 0 and delay > 0:
            time.sleep(delay)

        html = client.fetch(url, wait_for=wait_for)
        return html, request_count + 1

    def _build_output_paths(self, site_name: str, output_dir: Path) -> tuple[Path, Path, Path]:
        slug = "".join(character.lower() if character.isalnum() else " " for character in site_name)
        slug = "_".join(slug.split())
        return (
            output_dir / f"{slug}.csv",
            output_dir / f"{slug}.json",
            output_dir / f"{slug}.xlsx",
        )
