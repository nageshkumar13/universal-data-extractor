from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from core.runner import ScrapeRunner


console = Console()


@click.command()
@click.option("--profile", "-p", required=True, help="Path to YAML extraction profile")
@click.option("--clear-cache", is_flag=True, help="Clear cached URLs before running")
def main(profile: str, clear_cache: bool) -> None:
    """Universal Data Extractor CLI."""
    load_dotenv()

    runner = ScrapeRunner()
    summary = runner.run(
        profile_path=Path(profile),
        output_dir=Path("data"),
        clear_cache=clear_cache,
    )

    console.print(f"Pages scraped: {summary['pages_scraped']}")
    console.print(f"Records extracted: {summary['records_extracted']}")
    console.print(f"Records transformed: {summary['records_transformed']}")
    console.print(f"Cached skips: {summary['cached_skips']}")
    console.print(f"Robots blocked: {summary['robots_blocked']}")

    if summary["cache_only_run"]:
        console.print("No new records extracted. Existing cache skipped all pages.")
        console.print("Use --clear-cache to regenerate outputs.")
        return

    console.print(f"CSV: {summary['csv_path'].as_posix()}")
    console.print(f"JSON: {summary['json_path'].as_posix()}")
    console.print(f"XLSX: {summary['xlsx_path'].as_posix()}")


if __name__ == "__main__":
    main()
