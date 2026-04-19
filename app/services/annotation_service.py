from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from uuid import uuid4

import pandas as pd

from app.models.event import EventRecord
from app.models.schema import ROLE_COLUMNS
from app.services.table_store import TableStore

_ANNOTATION_TZ = ZoneInfo("America/New_York")


def looks_like_full_datetime(s: str) -> bool:
    """True if string likely encodes calendar date + time (not time-only)."""
    s = s.strip()
    if len(s) < 10:
        return False
    return s[4] == "-" and s[7] == "-" and s[:4].isdigit()


def annotation_datetime_to_unix(*parts: str | None) -> float | None:
    """Parse annotation date/time text to Unix seconds for matching video timestamps.

    - Strings with timezone or offset are interpreted accordingly.
    - **Naive** strings are treated as **America/New_York** (lab collection timezone),
      not UTC — so they align with ``pd.to_datetime(..., utc=True)`` on naive input,
      which would incorrectly assume UTC.
    - When two parts are given and the second is **time-only** (typical Excel split:
      ``2025-12-16 00:00:00`` + ``09:00:45.7``), the calendar day is taken from the
      first value and the clock from the second — a naive string join would not parse.
    """
    texts: list[str] = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip()
        if not s or s.lower() == "nan":
            continue
        texts.append(s)
    if not texts:
        return None
    try:
        ts: pd.Timestamp | None = None
        if len(texts) == 2:
            a, b = texts[0], texts[1]
            ta = pd.to_datetime(a, errors="coerce", utc=False)
            tb = pd.to_datetime(b, errors="coerce", utc=False)
            # Second cell is wall-clock only, not a calendar datetime.
            if not looks_like_full_datetime(b) and not pd.isna(ta) and not pd.isna(tb):
                day = ta.normalize()
                ts = day.replace(
                    hour=int(tb.hour),
                    minute=int(tb.minute),
                    second=int(tb.second),
                    microsecond=int(tb.microsecond),
                    nanosecond=int(getattr(tb, "nanosecond", 0) or 0),
                )
            else:
                ts = pd.to_datetime(f"{a} {b}", errors="coerce", utc=False)
        else:
            joined = " ".join(texts)
            ts = pd.to_datetime(joined, errors="coerce", utc=False)

        if ts is None or pd.isna(ts):
            return None

        # Already has a zone (e.g. ISO with offset from this app): .timestamp() is correct.
        if ts.tzinfo is not None:
            return float(ts.timestamp())

        # Naive wall clock = lab time in America/New_York. Avoid pandas tz_localize here:
        # it can raise on ambiguous/nonexistent NY instants or on some pandas/ZoneInfo combos.
        py_dt = ts.to_pydatetime()
        if py_dt.tzinfo is not None:
            py_dt = py_dt.replace(tzinfo=None)
        aware = py_dt.replace(tzinfo=_ANNOTATION_TZ)
        return float(aware.timestamp())
    except Exception:
        return None


class AnnotationService:
    def __init__(self) -> None:
        self.table_store = TableStore()
        self.annotations = pd.DataFrame()
        self.animal_names: list[str] = []
        self.table_path: Path | None = None

    def load_or_create_table(self, table_path: str | Path, animal_names_if_new: list[str]) -> None:
        path = Path(table_path)
        self.table_path = path
        if path.exists():
            self.annotations, loaded_names = self.table_store.load(path)
            if loaded_names:
                self.animal_names = loaded_names
            elif animal_names_if_new:
                self.animal_names = animal_names_if_new
            return

        self.annotations, self.animal_names = self.table_store.create_empty(animal_names_if_new)
        self.table_store.save(path, self.annotations, self.animal_names)

    def append_event(self, event: EventRecord) -> None:
        ny_tz = ZoneInfo("America/New_York")
        start_dt = self._to_ny_datetime(event.start_datetime, ny_tz)
        end_dt = self._to_ny_datetime(event.end_datetime, ny_tz) if event.end_datetime else None

        role_to_animals: dict[str, list[str]] = {role: [] for role in ROLE_COLUMNS}
        role_to_points: dict[str, dict[str, tuple[float, float]]] = {role: {} for role in ROLE_COLUMNS}
        for animal in event.animals:
            for role in ROLE_COLUMNS:
                if animal.roles.get(role):
                    role_to_animals[role].append(animal.animal_name)
                    point = animal.role_points.get(role)
                    if point is not None:
                        role_to_points[role][animal.animal_name] = point

        location_payload = {
            role: {name: f"{point[0]:.3f},{point[1]:.3f}" for name, point in points.items()}
            for role, points in role_to_points.items()
            if points
        }

        row = {
            "date": start_dt.strftime("%Y-%m-%d"),
            "start_time": start_dt.isoformat(sep=" ", timespec="milliseconds"),
            "end_time": end_dt.isoformat(sep=" ", timespec="milliseconds") if end_dt else "",
            "type": event.event_type,
            "location": json.dumps(location_payload, ensure_ascii=True) if location_payload else "",
            "other_notes": event.notes,
        }
        for role in ROLE_COLUMNS:
            row[role] = ", ".join(role_to_animals[role])

        self.annotations = pd.concat([self.annotations, pd.DataFrame([row])], ignore_index=True)

    def generate_event_id(self) -> str:
        return uuid4().hex[:10]

    def save(self) -> None:
        if self.table_path is None:
            raise ValueError("No table path configured.")
        self.table_store.save(self.table_path, self.annotations, self.animal_names)

    def start_frames(
        self,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> list[int]:
        if self.annotations.empty or "start_time" not in self.annotations.columns:
            return []
        starts: list[int] = []
        for value in self.annotations["start_time"].dropna().astype(str).tolist():
            frame = self._frame_from_start_time(value, video_timestamps, max_frame_index=max_frame_index)
            if frame is not None:
                starts.append(frame)
        return sorted(set(starts))

    def next_event_start_frame(
        self,
        current_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        starts = self.start_frames(video_timestamps, max_frame_index=max_frame_index)
        for frame in starts:
            if frame > current_frame:
                return frame
        return None

    def previous_event_start_frame(
        self,
        current_frame: int,
        video_timestamps: list[float] | None = None,
        max_frame_index: int | None = None,
    ) -> int | None:
        starts = self.start_frames(video_timestamps, max_frame_index=max_frame_index)
        prev = [frame for frame in starts if frame < current_frame]
        return prev[-1] if prev else None

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
            value = row.get("start_time", None)
            if value is None:
                continue
            frame = self._frame_from_start_time(str(value), video_timestamps, max_frame_index=max_frame_index)
            if frame == int(start_frame):
                matched_row = row
                break
        if matched_row is None:
            return None
        return matched_row.to_dict()

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
        except Exception:
            return None

