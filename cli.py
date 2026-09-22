from pathlib import Path
from typing import Any

import click
from dotenv import load_dotenv

from core.exporter import quality_artifact_paths
from core.quality import QualityResult
from core.runner import ScrapeRunner


def format_summary(
    summary: dict[str, Any], *, quality_enabled: bool,
    quality_result: QualityResult | None = None,
) -> str:
    """Format successful run information without reading or writing files."""
    skipped = summary["cache_only_run"]
    lines = ["Status: skipped" if skipped else "Status: completed"]
    if skipped:
        lines.append("Reason: completed output already exists")
    if summary["robots_blocked"] > 0:
        lines.append("Coverage: partial (robots restrictions)")
    lines.append(f"Pages scraped: {summary['pages_scraped']}")
    if not skipped:
        lines.extend([
            f"Records extracted: {summary['records_extracted']}",
            f"Records transformed: {summary['records_transformed']}",
        ])
        if quality_enabled:
            if quality_result is None:
                raise ValueError("Completed quality run has no quality result.")
            lines.extend([
                f"Clean records exported: {quality_result.report.exported}",
                f"Records rejected: {quality_result.report.rejected}",
            ])
        else:
            lines.append(f"Records exported: {summary['records_transformed']}")
    lines.extend([
        f"Cached skips: {summary['cached_skips']}",
        f"Robots blocked: {summary['robots_blocked']}",
        "Data quality: " + (
            "enabled (not run; cached skip)" if quality_enabled and skipped
            else "enabled" if quality_enabled else "disabled"
        ),
    ])
    for label, key in (("CSV", "csv_path"), ("JSON", "json_path"), ("XLSX", "xlsx_path")):
        lines.append(f"{label}: {summary[key].as_posix()}")
    if quality_enabled:
        quality_path, rejected_path = quality_artifact_paths(summary["csv_path"])
        lines.extend([
            f"Quality report: {quality_path.as_posix()}",
            f"Rejected records: {rejected_path.as_posix()}",
        ])
    return "\n".join(lines)


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
    click.echo(format_summary(
        summary, quality_enabled=runner.last_quality_enabled,
        quality_result=runner.last_quality_result,
    ))


if __name__ == "__main__":
    main()
