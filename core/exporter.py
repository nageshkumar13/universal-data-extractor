import csv
import json
from pathlib import Path

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
