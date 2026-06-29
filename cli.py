from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from core.config import ProfileLoader
from core.exporter import Exporter
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
    records = parser.extract(html, loaded_profile["fields"], loaded_profile["start_url"])

    exporter = Exporter()
    csv_path = exporter.to_csv(records, Path("data/books.csv"))
    json_path = exporter.to_json(records, Path("data/books.json"))

    summary = Table(show_header=False)
    summary.add_row("Records", str(len(records)))
    summary.add_row("CSV Export", "OK")
    summary.add_row("JSON Export", "OK")

    console.print(f"Extracted {len(records)} records")
    console.print()
    console.print("Saved:")
    console.print(csv_path.as_posix())
    console.print(json_path.as_posix())
    console.print()
    console.print(summary)


if __name__ == "__main__":
    main()
