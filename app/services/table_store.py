from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.models.schema import ANNOTATION_COLUMNS, AnnotationSchema, METADATA_COLUMNS


class TableStore:
    def __init__(self) -> None:
        self.schema = AnnotationSchema()

    def load(self, table_path: str | Path) -> tuple[pd.DataFrame, list[str]]:
        path = Path(table_path)
        suffix = path.suffix.lower()

        if suffix == ".csv":
            df = pd.read_csv(path)
            names = sorted([str(v) for v in df.get("animal_name", pd.Series(dtype=object)).dropna().unique().tolist()])
            return self._normalize(df), names

        if suffix in {".xlsx", ".xls"}:
            xls = pd.ExcelFile(path)
            if self.schema.annotation_sheet_name in xls.sheet_names:
                df = xls.parse(self.schema.annotation_sheet_name)
            else:
                df = xls.parse(xls.sheet_names[0])

            names = sorted([str(v) for v in df.get("animal_name", pd.Series(dtype=object)).dropna().unique().tolist()])
            if self.schema.metadata_sheet_name in xls.sheet_names:
                metadata = xls.parse(self.schema.metadata_sheet_name)
                if "animal_names" in metadata.columns and not metadata.empty:
                    raw = str(metadata.loc[0, "animal_names"])
                    names = [v.strip() for v in raw.split(",") if v.strip()]
            return self._normalize(df), names

        raise ValueError(f"Unsupported table extension: {suffix}")

    def create_empty(self, animal_names: list[str]) -> tuple[pd.DataFrame, list[str]]:
        df = pd.DataFrame(columns=ANNOTATION_COLUMNS)
        return df, animal_names

    def save(self, table_path: str | Path, annotations: pd.DataFrame, animal_names: list[str]) -> None:
        path = Path(table_path)
        suffix = path.suffix.lower()
        annotations = self._normalize(annotations)

        if suffix == ".csv":
            annotations.to_csv(path, index=False)
            return

        if suffix in {".xlsx", ".xls"}:
            metadata = pd.DataFrame([{"animal_names": ",".join(animal_names)}], columns=METADATA_COLUMNS)
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                annotations.to_excel(writer, sheet_name=self.schema.annotation_sheet_name, index=False)
                metadata.to_excel(writer, sheet_name=self.schema.metadata_sheet_name, index=False)
            return

        raise ValueError(f"Unsupported table extension: {suffix}")

    def _normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        df = frame.copy()
        for col in ANNOTATION_COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[ANNOTATION_COLUMNS]

