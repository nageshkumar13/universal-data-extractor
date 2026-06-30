from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from core.cache import URLCache
from core.config import ProfileLoader
from core.exporter import Exporter
from core.http_client import HttpClient
from core.pagination import Paginator
from core.parser import HTMLParser
from core.robots import RobotsChecker


console = Console()


@click.command()
@click.option("--profile", "-p", required=True, help="Path to YAML extraction profile")
@click.option("--clear-cache", is_flag=True, help="Clear cached URLs before running")
def main(profile: str, clear_cache: bool) -> None:
    """Universal Data Extractor CLI."""
    load_dotenv()

    loader = ProfileLoader()
    loaded_profile = loader.load(Path(profile))

    client = HttpClient()
    parser = HTMLParser()
    paginator = Paginator()
    cache = URLCache()
    robots = RobotsChecker(loaded_profile["start_url"])

    if clear_cache:
        cache.clear()

    current_url = loaded_profile["start_url"]
    max_pages = loaded_profile.get("max_pages", 1)
    next_selector = loaded_profile.get("pagination", {}).get("next_button", "")
    processed_pages = 0
    pages_scraped = 0
    cached_skips = 0
    robots_blocked = 0
    all_records: list[dict] = []

    while current_url and processed_pages < max_pages:
        if not robots.is_allowed(current_url):
            robots_blocked += 1
            processed_pages += 1
            current_url = None
            continue

        if cache.is_cached(current_url):
            cached_skips += 1
            if next_selector:
                html = client.fetch(current_url)
                current_url = paginator.get_next_url(html, current_url, next_selector)
            else:
                current_url = None

            processed_pages += 1
            continue

        html = client.fetch(current_url)
        records = parser.extract(html, loaded_profile["fields"], current_url)
        all_records.extend(records)
        cache.mark_done(current_url, len(records))

        current_url = (
            paginator.get_next_url(html, current_url, next_selector)
            if next_selector
            else None
        )
        pages_scraped += 1
        processed_pages += 1

    exporter = Exporter()
    csv_path = Path("data/books.csv")
    json_path = Path("data/books.json")

    if all_records or not csv_path.exists() or not json_path.exists():
        csv_path = exporter.to_csv(all_records, csv_path)
        json_path = exporter.to_json(all_records, json_path)

    console.print(f"Pages scraped: {pages_scraped}")
    console.print(f"Records extracted: {len(all_records)}")
    console.print(f"Cached skips: {cached_skips}")
    console.print(f"Robots blocked: {robots_blocked}")
    console.print(f"CSV: {csv_path.as_posix()}")
    console.print(f"JSON: {json_path.as_posix()}")


if __name__ == "__main__":
    main()
