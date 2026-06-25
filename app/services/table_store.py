from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.models.schema import ANNOTATION_COLUMNS, AnnotationSchema, METADATA_COLUMNS, ROLE_COLUMNS
from app.services.annotation_datetime import format_annotation_date, format_annotation_time

_DATE_SHEET_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s|$)")
_US_DATE_SHEET_RE = re.compile(r"^\d{1,2}[-./]\d{1,2}[-./]\d{2,4}(?:\s|$)")
_EXCEL_SHEET_INVALID = re.compile(r"[:\\/?*\[\]]")
_ANNOTATION_HEADER_MARKERS = frozenset(
    {"date", "start_time", "end_time", "type", "location", "initiator", "victim", "event_id"}
)


class TableStore:
    def __init__(self) -> None:
        self.schema = AnnotationSchema()

    def load(self, table_path: str | Path) -> tuple[pd.DataFrame, list[str], str]:
        path = Path(table_path)
        suffix = path.suffix.lower()

        if suffix == ".csv":
            df = pd.read_csv(path)
            names = self._infer_animal_names(df)
            return self._normalize(df), names, ""

        if suffix in {".xlsx", ".xls"}:
            return self._load_xlsx(path)

        raise ValueError(f"Unsupported table extension: {suffix}")

    def create_empty(self, animal_names: list[str]) -> tuple[pd.DataFrame, list[str]]:
        df = pd.DataFrame(columns=ANNOTATION_COLUMNS)
        return df, animal_names

    def save(
        self,
        table_path: str | Path,
        annotations: pd.DataFrame,
        animal_names: list[str],
        id_images_dir: str = "",
    ) -> None:
        path = Path(table_path)
        suffix = path.suffix.lower()
        annotations = self._normalize(annotations)

        if suffix == ".csv":
            annotations.to_csv(path, index=False)
            return

        if suffix in {".xlsx", ".xls"}:
            self._save_xlsx(path, annotations, animal_names, id_images_dir)
            return

        raise ValueError(f"Unsupported table extension: {suffix}")

    def _load_xlsx(self, path: Path) -> tuple[pd.DataFrame, list[str], str]:
        xls = pd.ExcelFile(path)
        names, id_images_dir = self._metadata_from_sheet(xls)
        sheets_to_load = self._sheets_to_load(xls)

        frames: list[pd.DataFrame] = []
        for sheet in sheets_to_load:
            part = self._normalize(xls.parse(sheet))
            if part.empty and not self._sheet_has_annotation_headers(xls, sheet):
                continue
            date_str = self._date_from_sheet_name(sheet)
            if date_str:
                part = self._fill_date_column(part, date_str)
            frames.append(part)

        if frames:
            df = pd.concat(frames, ignore_index=True)
        else:
            df = pd.DataFrame(columns=ANNOTATION_COLUMNS)

        if not names:
            names = self._infer_animal_names(df)
        return df, names, id_images_dir

    def _sheets_to_load(self, xls: pd.ExcelFile) -> list[str]:
        """Choose workbook tabs to merge: all date-named and/or annotation data sheets."""
        reserved = {self.schema.metadata_sheet_name}
        non_metadata = [name for name in xls.sheet_names if name not in reserved]
        if not non_metadata:
            return list(xls.sheet_names)

        date_sheets = [name for name in non_metadata if self._is_date_sheet_name(name)]
        if date_sheets:
            return date_sheets

        annotation_like = [
            name for name in non_metadata if self._sheet_has_annotation_headers(xls, name)
        ]
        if len(annotation_like) >= 2:
            return annotation_like
        if len(annotation_like) == 1:
            return annotation_like

        if len(non_metadata) > 1:
            return non_metadata

        return non_metadata

    def _sheet_has_annotation_headers(self, xls: pd.ExcelFile, sheet: str) -> bool:
        try:
            header = xls.parse(sheet, nrows=0)
        except Exception:
            return False
        columns = {str(col).strip().lower() for col in header.columns}
        return len(columns & _ANNOTATION_HEADER_MARKERS) >= 2

    def _save_xlsx(
        self,
        path: Path,
        annotations: pd.DataFrame,
        animal_names: list[str],
        id_images_dir: str = "",
    ) -> None:
        metadata = pd.DataFrame(
            [{"animal_names": ",".join(animal_names), "id_images_dir": (id_images_dir or "").strip()}],
            columns=METADATA_COLUMNS,
        )
        buckets = self._split_by_date(annotations)

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            if not buckets:
                annotations.to_excel(writer, sheet_name=self.schema.annotation_sheet_name, index=False)
            else:
                for date_key in sorted(buckets.keys(), key=lambda key: (key == "", key)):
                    chunk = buckets[date_key]
                    sheet_name = (
                        self._sheet_name_for_date(date_key)
                        if date_key
                        else self.schema.annotation_sheet_name
                    )
                    chunk.to_excel(writer, sheet_name=sheet_name, index=False)
            metadata.to_excel(writer, sheet_name=self.schema.metadata_sheet_name, index=False)

    def _metadata_from_sheet(self, xls: pd.ExcelFile) -> tuple[list[str], str]:
        if self.schema.metadata_sheet_name not in xls.sheet_names:
            return [], ""
        metadata = xls.parse(self.schema.metadata_sheet_name)
        names: list[str] = []
        id_images_dir = ""
        if not metadata.empty:
            if "animal_names" in metadata.columns:
                raw = str(metadata.loc[0, "animal_names"])
                names = [value.strip() for value in raw.split(",") if value.strip()]
            if "id_images_dir" in metadata.columns:
                raw_dir = metadata.loc[0, "id_images_dir"]
                if raw_dir is not None and str(raw_dir).strip().lower() not in ("", "nan", "none"):
                    id_images_dir = str(raw_dir).strip()
        return names, id_images_dir

    def _animal_names_from_metadata(self, xls: pd.ExcelFile) -> list[str]:
        names, _id_images_dir = self._metadata_from_sheet(xls)
        return names

    def _is_date_sheet_name(self, name: str) -> bool:
        if name in {self.schema.annotation_sheet_name, self.schema.metadata_sheet_name}:
            return False
        return self._date_from_sheet_name(name) is not None

    def _date_from_sheet_name(self, name: str) -> str | None:
        text = str(name).strip()
        if not text:
            return None
        if _DATE_SHEET_RE.match(text) or _US_DATE_SHEET_RE.match(text):
            ts = pd.to_datetime(text.split()[0], errors="coerce")
        else:
            ts = pd.to_datetime(text, errors="coerce")
        if ts is None or pd.isna(ts):
            return None
        if int(ts.year) < 1990:
            return None
        return ts.strftime("%Y-%m-%d")

    def _sheet_name_for_date(self, date_key: str) -> str:
        safe = _EXCEL_SHEET_INVALID.sub("-", date_key.replace("/", "-"))
        return safe[:31]

    def _fill_date_column(self, frame: pd.DataFrame, date_str: str) -> pd.DataFrame:
        df = frame.copy()
        if "date" not in df.columns:
            df["date"] = date_str
            return df
        missing = df["date"].isna()
        if missing.any():
            as_text = df["date"].astype(str).str.strip()
            missing = missing | as_text.isin(["", "nan", "NaT", "None"])
        df.loc[missing, "date"] = date_str
        return df

    def _split_by_date(self, frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
        df = self._normalize(frame)
        if df.empty:
            return {}
        keys = df["date"].map(self._date_key)
        buckets: dict[str, pd.DataFrame] = {}
        for key, group in df.groupby(keys, sort=False):
            date_key = "" if key is None or (isinstance(key, float) and pd.isna(key)) else str(key)
            buckets[date_key] = group.reset_index(drop=True)
        return buckets

    def _date_key(self, value: object) -> str:
        if value is None:
            return ""
        try:
            if isinstance(value, float) and pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d")
        text = str(value).strip()
        if not text or text.lower() in {"nan", "nat", "none"}:
            return ""
        ts = pd.to_datetime(text, errors="coerce")
        if ts is None or pd.isna(ts):
            return ""
        return ts.strftime("%Y-%m-%d")

    def _normalize(self, frame: pd.DataFrame) -> pd.DataFrame:
        df = frame.copy()
        for col in ANNOTATION_COLUMNS:
            if col not in df.columns:
                df[col] = None
        df = df[ANNOTATION_COLUMNS]
        return self._coerce_datetime_columns(df)

    def _coerce_datetime_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Excel/CSV often yield midnight datetimes for ``date`` and timedelta-like ``start_time``."""
        if frame.empty:
            return frame
        df = frame.copy()
        if "date" in df.columns:
            df["date"] = df["date"].map(format_annotation_date)
        for col in ("start_time", "end_time"):
            if col in df.columns:
                df[col] = df[col].map(format_annotation_time)
        return df

    def _infer_animal_names(self, frame: pd.DataFrame) -> list[str]:
        names: set[str] = set()
        for role in ROLE_COLUMNS:
            if role not in frame.columns:
                continue
            series = frame[role].dropna().astype(str)
            for value in series.tolist():
                for token in value.split(","):
                    name = token.strip()
                    if name:
                        names.add(name)
        return sorted(names)
