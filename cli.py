from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from core.config import ProfileLoader


console = Console()


@click.command()
@click.option("--profile", "-p", required=True, help="Path to YAML extraction profile")
def main(profile: str) -> None:
    """Universal Data Extractor CLI."""
    load_dotenv()

    loader = ProfileLoader()
    loaded_profile = loader.load(Path(profile))

    console.print(
        Panel.fit(
            f"[bold]Site:[/bold] {loaded_profile['site_name']}\n"
            f"[bold]Engine:[/bold] {loaded_profile['engine']}\n"
            f"[bold]Start URL:[/bold] {loaded_profile['start_url']}\n"
            f"[bold]Fields:[/bold] {len(loaded_profile['fields'])}",
            title="Profile Loaded",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
