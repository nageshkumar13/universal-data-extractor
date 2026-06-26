from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from core.config import ProfileLoader
from core.http_client import HttpClient


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

    console.print("Fetched page successfully")
    console.print(f"Status: {client.last_status_code}")
    console.print(f"HTML size: {len(html)} characters")


if __name__ == "__main__":
    main()
