from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from core.config import ProfileLoader
from core.exporter import Exporter
from core.http_client import HttpClient
from core.pagination import Paginator
from core.parser import HTMLParser


console = Console()


@click.command()
@click.option("--profile", "-p", required=True, help="Path to YAML extraction profile")
def main(profile: str) -> None:
    """Universal Data Extractor CLI."""
    load_dotenv()

    loader = ProfileLoader()
    loaded_profile = loader.load(Path(profile))

    client = HttpClient()
    parser = HTMLParser()
    paginator = Paginator()

    current_url = loaded_profile["start_url"]
    max_pages = loaded_profile.get("max_pages", 1)
    next_selector = loaded_profile.get("pagination", {}).get("next_button", "")
    page_count = 0
    all_records: list[dict] = []

    while current_url and page_count < max_pages:
        html = client.fetch(current_url)
        records = parser.extract(html, loaded_profile["fields"], current_url)
        all_records.extend(records)

        current_url = (
            paginator.get_next_url(html, current_url, next_selector)
            if next_selector
            else None
        )
        page_count += 1

    exporter = Exporter()
    csv_path = exporter.to_csv(all_records, Path("data/books.csv"))
    json_path = exporter.to_json(all_records, Path("data/books.json"))

    console.print(f"Pages scraped: {page_count}")
    console.print(f"Records extracted: {len(all_records)}")
    console.print(f"CSV: {csv_path.as_posix()}")
    console.print(f"JSON: {json_path.as_posix()}")


if __name__ == "__main__":
    main()
