from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from core.config import ProfileLoader
from core.http_client import HttpClient
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
    html = client.fetch(loaded_profile["start_url"])

    parser = HTMLParser()
    records = parser.extract(html, loaded_profile["fields"])

    console.print(f"Records extracted: {len(records)}")
    console.print("First record:")
    if records:
        console.print(records[0])


if __name__ == "__main__":
    main()
