from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from uuid import uuid4

import pandas as pd

from app.models.event import EventRecord
from app.models.schema import ROLE_COLUMNS
from app.services.annotation_datetime import (
    annotation_datetime_to_unix,
    annotation_ts_to_unix,
    annotation_unix_to_ts_nanos,
    format_annotation_date,
    format_annotation_time,
    looks_like_full_datetime,
)
from app.services.table_store import TableStore

__all__ = [
    "AnnotationService",
    "annotation_datetime_to_unix",
    "format_annotation_date",
    "format_annotation_time",
    "looks_like_full_datetime",
]


class AnnotationService:
    def __init__(self) -> None:
        self.table_store = TableStore()
        self.annotations = pd.DataFrame()
        self.animal_names: list[str] = []
        self.id_images_dir: str = ""
        self.table_path: Path | None = None

    @staticmethod
    def resolve_table_path(table_path: str | Path, *, video_path: str | Path | None = None) -> Path:
        """Return an absolute annotation table path.

        Relative paths are resolved against the video directory when provided,
        otherwise against the current working directory.
        """
        path = Path(table_path).expanduser()
        if not path.is_absolute():
            base = Path(video_path).expanduser().resolve().parent if video_path else Path.cwd()
            path = (base / path).resolve()
        else:
            path = path.resolve()
        return path

    def load_or_create_table(
        self,
        table_path: str | Path,
        animal_names_if_new: list[str],
        *,
        video_path: str | Path | None = None,
    ) -> None:
        path = self.resolve_table_path(table_path, video_path=video_path)
        self.table_path = path
        if path.exists():
            self.annotations, loaded_names, loaded_id_images_dir = self.table_store.load(path)
            if loaded_names:
                self.animal_names = loaded_names
            elif animal_names_if_new:
                self.animal_names = animal_names_if_new
            self.id_images_dir = loaded_id_images_dir
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        self.annotations, self.animal_names = self.table_store.create_empty(animal_names_if_new)
        self.id_images_dir = ""
        # Defer writing the file until the first event is saved.

    def _event_record_to_row(self, event: EventRecord) -> dict:
        ny_tz = ZoneInfo("America/New_York")
        start_dt = self._to_ny_datetime(event.start_datetime, ny_tz)
        end_dt = self._to_ny_datetime(event.end_datetime, ny_tz) if event.end_datetime else None

        role_to_animals: dict[str, list[str]] = {role: [] for role in ROLE_COLUMNS}
        for animal in event.animals:
            for role in ROLE_COLUMNS:
                if animal.roles.get(role):
                    role_to_animals[role].append(animal.animal_name)

        arena = (event.event_location or "left").strip() or "left"

        row: dict = {
            "event_id": (event.event_id or "").strip(),
            "date": start_dt.strftime("%Y-%m-%d"),
            "start_time": start_dt.isoformat(sep=" ", timespec="milliseconds"),
            "end_time": end_dt.isoformat(sep=" ", timespec="milliseconds") if end_dt else "",
            "ts_start": (event.start_ts_raw or "").strip()
            or annotation_unix_to_ts_nanos(event.start_unix),
            "ts_end": (event.end_ts_raw or "").strip()
            or annotation_unix_to_ts_nanos(event.end_unix),
            "type": event.event_type,
            "location": arena,
            "other_notes": event.notes,
        }
        for role in ROLE_COLUMNS:
            row[role] = ", ".join(role_to_animals[role])
        return row

    def append_event(self, event: EventRecord) -> None:
        row = self._event_record_to_row(event)
        new_row = self.table_store.normalize(pd.DataFrame([row]))
        if new_row.empty:
            raise RuntimeError("Failed to build annotation row for this event.")
        if self.annotations.empty:
            self.annotations = new_row.copy()
        else:
            self.annotations = self.table_store.normalize(
                pd.concat([self.annotations, new_row], ignore_index=True)
            )
        if len(self.annotations) <= 0:
            raise RuntimeError("Failed to append annotation row.")

    def update_event_at_iloc(self, iloc: int, event: EventRecord) -> None:
        n = len(self.annotations)
        if iloc < 0 or iloc >= n:
            raise ValueError(f"Invalid annotation row index: {iloc}")
        row = self._event_record_to_row(event)
        if not row.get("event_id"):
            prev = self.annotations.iloc[iloc].get("event_id")
            if prev is not None and not (isinstance(prev, float) and pd.isna(prev)):
                row["event_id"] = str(prev).strip()
        new_row = self.table_store.normalize(pd.DataFrame([row]))
        parts = [
            self.annotations.iloc[:iloc],
            new_row,
            self.annotations.iloc[iloc + 1 :],
        ]
        self.annotations = self.table_store.normalize(pd.concat(parts, ignore_index=True))

    def generate_event_id(self) -> str:
        return uuid4().hex[:10]

    def save(self) -> None:
        if self.table_path is None:
            raise ValueError("No table path configured.")
        path = Path(self.table_path).expanduser().resolve()
        self.table_path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.annotations = self.table_store.normalize(self.annotations)
        expected_rows = len(self.annotations)

        if expected_rows == 0 and path.exists() and path.suffix.lower() == ".csv":
            try:
                existing = pd.read_csv(path, encoding="utf-8-sig")
                if len(existing) > 0:
                    raise ValueError(
                        f"Refusing to overwrite {path.name} ({len(existing)} existing events) "
                        "with an empty in-memory table. Reload the project or use "
                        "Submit event before saving."
                    )
            except pd.errors.EmptyDataError:
                pass

        self.table_store.save(
            path,
            self.annotations,
            self.animal_names,
            self.id_images_dir,
        )

        if path.suffix.lower() == ".csv" and expected_rows > 0:
            written = pd.read_csv(path, encoding="utf-8-sig")
            if len(written) != expected_rows:
                raise OSError(
                    f"Wrote {expected_rows} event(s) to {path}, but the file now contains "
                    f"{len(written)} row(s). Close the file if it is open in Excel/Numbers "
                    "and try again."
                )

    def start_frames(
        self,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> list[int]:
        if self.annotations.empty or "start_time" not in self.annotations.columns:
            return []
        starts: list[int] = []
        for _, row in self.annotations.iterrows():
            frame = self._frame_from_row(row, video_timestamps, max_frame_index=max_frame_index)
            if frame is not None:
                starts.append(frame)
        return sorted(set(starts))

    def _sorted_event_starts(
        self,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> list[tuple[float, int, int, pd.Series]]:
        """Return ``(start_unix, iloc, start_frame, row)`` sorted by time then table order."""
        items: list[tuple[float, int, int, pd.Series]] = []
        for iloc in range(len(self.annotations)):
            row = self.annotations.iloc[iloc]
            eu = self._row_start_unix(row)
            if eu is None:
                continue
            frame = self._frame_from_row(row, video_timestamps, max_frame_index=max_frame_index)
            if frame is None:
                continue
            items.append((float(eu), iloc, int(frame), row))
        items.sort(key=lambda item: (item[0], item[1]))
        return items

    @staticmethod
    def _event_index_at_or_before(
        items: list[tuple[float, int, int, pd.Series]],
        cur_u: float,
    ) -> int | None:
        """Index of the last event whose start time is <= *cur_u*."""
        idx: int | None = None
        for i, (eu, _iloc, _frame, _row) in enumerate(items):
            if eu <= cur_u:
                idx = i
            else:
                break
        return idx

    def next_event_from_current_time(
        self,
        current_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
        *,
        current_iloc: int | None = None,
    ) -> tuple[int | None, dict | None, int | None]:
        """Jump target: next event by start time after the current frame timestamp."""
        items = self._sorted_event_starts(video_timestamps, max_frame_index=max_frame_index)
        if not items:
            return None, None, None

        if current_iloc is not None:
            for i, (_eu, iloc, frame, row) in enumerate(items):
                if iloc == current_iloc:
                    if i + 1 >= len(items):
                        return None, None, None
                    _eu, next_iloc, frame, row = items[i + 1]
                    return frame, row.to_dict(), next_iloc
            return None, None, None

        cur_u = self._unix_at_frame(current_frame, video_timestamps, max_frame_index)
        if cur_u is None:
            return None, None, None
        idx = self._event_index_at_or_before(items, float(cur_u))
        next_idx = 0 if idx is None else idx + 1
        if next_idx >= len(items):
            return None, None, None
        _eu, iloc, frame, row = items[next_idx]
        return frame, row.to_dict(), iloc

    def previous_event_from_current_time(
        self,
        current_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
        *,
        current_iloc: int | None = None,
    ) -> tuple[int | None, dict | None, int | None]:
        """Jump target: previous event by start time before the current frame timestamp."""
        items = self._sorted_event_starts(video_timestamps, max_frame_index=max_frame_index)
        if not items:
            return None, None, None

        if current_iloc is not None:
            for i, (_eu, iloc, frame, row) in enumerate(items):
                if iloc == current_iloc:
                    if i <= 0:
                        return None, None, None
                    _eu, prev_iloc, frame, row = items[i - 1]
                    return frame, row.to_dict(), prev_iloc
            return None, None, None

        cur_u = self._unix_at_frame(current_frame, video_timestamps, max_frame_index)
        if cur_u is None:
            return None, None, None
        idx = self._event_index_at_or_before(items, float(cur_u))
        if idx is None or idx <= 0:
            return None, None, None
        _eu, iloc, frame, row = items[idx - 1]
        return frame, row.to_dict(), iloc

    def next_event_start_frame(
        self,
        current_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        f, _, _ = self.next_event_from_current_time(
            current_frame, video_timestamps, max_frame_index=max_frame_index
        )
        return f

    def previous_event_start_frame(
        self,
        current_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        f, _, _ = self.previous_event_from_current_time(
            current_frame, video_timestamps, max_frame_index=max_frame_index
        )
        return f

    def find_event_by_start_frame(
        self,
        start_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> dict | None:
        if self.annotations.empty:
            return None
        matched_row = None
        for _, row in self.annotations.iterrows():
            frame = self._frame_from_row(row, video_timestamps, max_frame_index=max_frame_index)
            if frame == int(start_frame):
                matched_row = row
                break
        if matched_row is None:
            return None
        return matched_row.to_dict()

    @staticmethod
    def _unix_at_frame(
        current_frame: int,
        video_timestamps: list[float] | None,
        max_frame_index: int | None,
    ) -> float | None:
        if not video_timestamps:
            return None
        cap = len(video_timestamps) - 1
        if max_frame_index is not None and max_frame_index >= 0:
            cap = min(cap, max_frame_index)
        fi = max(0, min(int(current_frame), cap))
        return float(video_timestamps[fi])

    def _row_start_unix(self, row: pd.Series) -> float | None:
        """Parse this row's event start to Unix seconds (``ts_start`` or ``date`` + ``start_time``)."""
        u = annotation_ts_to_unix(row.get("ts_start"))
        if u is not None:
            return float(u)
        st = row.get("start_time")
        if st is None:
            return None
        try:
            if isinstance(st, float) and pd.isna(st):
                return None
        except (TypeError, ValueError):
            return None
        st_s = str(st).strip()
        if not st_s or st_s.lower() == "nan":
            return None
        date_v = row.get("date")
        try:
            if date_v is not None and not (isinstance(date_v, float) and pd.isna(date_v)):
                ds = str(date_v).strip()
                if ds and ds.lower() != "nan":
                    u = annotation_datetime_to_unix(ds, st_s)
                    if u is not None:
                        return float(u)
        except Exception:
            pass
        u = annotation_datetime_to_unix(st_s)
        return float(u) if u is not None else None

    def _frame_from_row(
        self,
        row: pd.Series,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        u = self._row_start_unix(row)
        if u is None:
            return None
        return self._frame_index_from_unix(u, video_timestamps, max_frame_index=max_frame_index)

    @staticmethod
    def _frame_index_from_unix(
        unix_value: float,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        if not video_timestamps:
            return None
        n = len(video_timestamps)
        if max_frame_index is not None and max_frame_index >= 0:
            n = min(n, max_frame_index + 1)
        if n <= 0:
            return None
        closest_idx = min(
            range(n),
            key=lambda idx: abs(float(video_timestamps[idx]) - unix_value),
        )
        return int(closest_idx)

    @staticmethod
    def _to_ny_datetime(value: datetime, ny_tz: ZoneInfo) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=ny_tz)
        return value.astimezone(ny_tz)

    @staticmethod
    def _frame_from_start_time(
        value: str,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        """Map an annotation start_time string to a video frame via timestamps.

        Uses :func:`annotation_datetime_to_unix` so naive times are NY-local and
        timezone-aware ISO strings (from this app) map correctly to Unix seconds.

        If ``max_frame_index`` is set (typically ``video.total_frames - 1``), only
        indices ``0 .. max_frame_index`` are considered. This avoids jumping past
        the end of the loaded video when the timestamp file has more rows than
        frames (OpenCV frame count vs. per-frame log length mismatch).
        """
        if not value:
            return None
        try:
            unix_value = annotation_datetime_to_unix(str(value).strip())
            if unix_value is None:
                return None
            return AnnotationService._frame_index_from_unix(
                float(unix_value), video_timestamps, max_frame_index=max_frame_index
            )
        except Exception:
            return None

