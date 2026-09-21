import csv
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from core.quality import QualityResult

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

try:
    import pandas as pd
except ImportError:
    pd = None


class Exporter:
    def to_csv(self, records: list[dict], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if pd is not None:
            dataframe = pd.DataFrame(records)
            dataframe.to_csv(output_path, index=False)
            return output_path

        fieldnames = list(records[0].keys()) if records else []
        with output_path.open("w", encoding="utf-8", newline="") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

        return output_path

    def to_json(self, records: list[dict], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if pd is not None:
            dataframe = pd.DataFrame(records)
            dataframe.to_json(
                output_path,
                orient="records",
                indent=4,
                force_ascii=False,
            )
            return output_path

        with output_path.open("w", encoding="utf-8") as file_handle:
            json.dump(records, file_handle, indent=4, ensure_ascii=False)

        return output_path

    def to_excel(self, records: list[dict], output_path: Path) -> Path:
        """Export records to an Excel .xlsx file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Data"
        worksheet.freeze_panes = "A2"

        headers = list(records[0].keys()) if records else []
        if headers:
            worksheet.append(headers)
            for cell in worksheet[1]:
                cell.font = Font(bold=True)

            for record in records:
                worksheet.append([record.get(header, "") for header in headers])

            for index, header in enumerate(headers, start=1):
                values = [header]
                values.extend("" if record.get(header) is None else str(record.get(header)) for record in records)
                width = min(max(len(value) for value in values) + 2, 50)
                worksheet.column_dimensions[get_column_letter(index)].width = width

        workbook.save(output_path)
        return output_path

    def write_quality_artifacts(
        self, result: QualityResult, output_path: Path
    ) -> tuple[Path, Path]:
        """Write audit sidecars using an existing normal export path as the anchor.

        Each file is atomic independently; a failed second write leaves the
        successfully replaced report and the previous rejected file intact.
        """
        quality_path = output_path.with_suffix(".quality.json")
        rejected_path = output_path.with_suffix(".rejected.json")
        self._write_audit_json(asdict(result.report), quality_path)
        self._write_audit_json(result.rejected_records, rejected_path)
        return quality_path, rejected_path

    @staticmethod
    def _write_audit_json(data: object, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            file_handle = NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=output_path.parent,
                prefix=f".{output_path.name}.", suffix=".tmp", delete=False,
            )
            temporary_path = Path(file_handle.name)
            try:
                json.dump(
                    data, file_handle, indent=4, ensure_ascii=False,
                    allow_nan=False, default=Exporter._audit_json_default,
                )
                file_handle.write("\n")
            except BaseException:
                try:
                    file_handle.close()
                except BaseException:
                    # Preserve the original write/interruption error.
                    pass
                raise
            file_handle.close()
            temporary_path.replace(output_path)
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    # Best effort only: never mask the write/replace exception.
                    pass

    @staticmethod
    def _audit_json_default(value: object) -> str:
        # Raw rejected values may contain native dates accepted by the processor.
        if isinstance(value, date):
            return value.isoformat()
        raise TypeError(f"Unsupported audit JSON value: {type(value).__name__}")
