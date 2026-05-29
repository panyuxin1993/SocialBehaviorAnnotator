from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.timestamp_service import TimestampService


_SUBJECT_XY_RE = re.compile(r"^(.+)_center_x$", re.IGNORECASE)
_SUBJECT_Y_RE = re.compile(r"^(.+)_center_y$", re.IGNORECASE)
_SUBJECT_AREA_RE = re.compile(r"^(.+)_area$", re.IGNORECASE)
_SUBJECT_PERIMETER_RE = re.compile(r"^(.+)_perimeter$", re.IGNORECASE)


@dataclass(frozen=True)
class SubjectFrame:
    x: float
    y: float
    area: float | None = None
    perimeter: float | None = None


class TrackingService:
    """Per-frame animal center positions from a tracking CSV (e.g. ``TQT.csv``)."""

    def __init__(self) -> None:
        self.source_path: Path | None = None
        self.subjects: list[str] = []
        self._unix_times: list[float] = []
        self._frames: list[dict[str, SubjectFrame]] = []
        self._clip_ids: list[str] = []
        #: Max |video_ts - tracking_ts| for a row to count as available (derived on load).
        self._max_match_delta: float = 0.1

    @property
    def is_loaded(self) -> bool:
        return bool(self._unix_times)

    @property
    def row_count(self) -> int:
        return len(self._unix_times)

    def clear(self) -> None:
        self.source_path = None
        self.subjects = []
        self._unix_times = []
        self._frames = []
        self._clip_ids = []
        self._max_match_delta = 0.1

    def load_file(self, tracking_path: str | Path) -> None:
        path = Path(tracking_path)
        if not path.is_file():
            raise FileNotFoundError(f"Tracking file not found: {path}")

        df = pd.read_csv(path, encoding="utf-8-sig")
        if df.empty:
            raise ValueError(f"Tracking file is empty: {path}")

        columns = [str(c).strip() for c in df.columns]
        df.columns = columns

        subject_cols = _subject_column_map(columns)
        area_cols = _subject_scalar_column_map(columns, _SUBJECT_AREA_RE)
        perimeter_cols = _subject_scalar_column_map(columns, _SUBJECT_PERIMETER_RE)
        if not subject_cols:
            raise ValueError(
                "No tracking position columns found. Expected pairs like "
                "'rat003_center_x' and 'rat003_center_y'."
            )

        time_col = _pick_column(columns, ("timestamp", "unix_timestamp", "time", "cam_frame_time"))
        if time_col is None:
            raise ValueError("Tracking CSV must include a 'timestamp' column.")

        clip_col = _pick_column(columns, ("clip", "clip_id", "video_id"))

        subjects = sorted(subject_cols.keys())
        unix_times: list[float] = []
        frames: list[dict[str, SubjectFrame]] = []
        clip_ids: list[str] = []

        for _, row in df.iterrows():
            raw_ts = row.get(time_col)
            if pd.isna(raw_ts):
                continue
            try:
                unix_times.append(TimestampService._normalize_unix_seconds(float(raw_ts)))
            except (TypeError, ValueError):
                continue

            frame_data: dict[str, SubjectFrame] = {}
            for subject_id, (x_col, y_col) in subject_cols.items():
                xy = _read_xy(row.get(x_col), row.get(y_col))
                if xy is None:
                    continue
                area_col = area_cols.get(subject_id)
                perim_col = perimeter_cols.get(subject_id)
                area = _read_positive_scalar(row.get(area_col)) if area_col else None
                perimeter = _read_positive_scalar(row.get(perim_col)) if perim_col else None
                frame_data[subject_id] = SubjectFrame(
                    x=xy[0], y=xy[1], area=area, perimeter=perimeter
                )
            frames.append(frame_data)
            if clip_col is not None:
                clip_ids.append(str(row.get(clip_col, "")).strip())
            else:
                clip_ids.append("")

        if not unix_times:
            raise ValueError(f"No valid timestamps parsed from {path}")

        self.source_path = path
        self.subjects = subjects
        self._unix_times = unix_times
        self._frames = frames
        self._clip_ids = clip_ids
        self._max_match_delta = _median_step_seconds(unix_times) * 2.0

    def poses_for_frame(
        self,
        frame_index: int,
        video_timestamps: list[float],
    ) -> dict[str, tuple[float, float]]:
        """Return subject_id → (pixel x, pixel y) for the closest tracking row to this video frame."""
        if not self.is_loaded:
            return {}

        if video_timestamps:
            idx = max(0, min(int(frame_index), len(video_timestamps) - 1))
            target_unix = float(video_timestamps[idx])
            if not self._unix_times:
                return {}
            if not self._timestamp_in_range(target_unix):
                return {}
            row_idx = self._nearest_row_index(target_unix)
            if abs(self._unix_times[row_idx] - target_unix) > self._max_match_delta:
                return {}
        else:
            row_idx = int(frame_index)
            if row_idx < 0 or row_idx >= len(self._frames):
                return {}

        if row_idx < 0 or row_idx >= len(self._frames):
            return {}
        return self._poses_at_row(row_idx)

    def poses_for_unix(self, target_unix: float) -> dict[str, tuple[float, float]]:
        """Return subject_id → (pixel x, pixel y) for the closest tracking row to ``target_unix``."""
        if not self.is_loaded:
            return {}
        if not self._timestamp_in_range(target_unix):
            return {}
        row_idx = self._nearest_row_index(target_unix)
        if abs(self._unix_times[row_idx] - target_unix) > self._max_match_delta:
            return {}
        return self._poses_at_row(row_idx)

    def _poses_at_row(self, row_idx: int) -> dict[str, tuple[float, float]]:
        if row_idx < 0 or row_idx >= len(self._frames):
            return {}
        frame = self._frames[row_idx]
        if not frame:
            return {}
        return {sid: (f.x, f.y) for sid, f in frame.items()}

    def _timestamp_in_range(self, target_unix: float) -> bool:
        times = self._unix_times
        margin = self._max_match_delta
        return (times[0] - margin) <= target_unix <= (times[-1] + margin)

    def samples_in_unix_range(
        self,
        t_min: float,
        t_max: float,
    ) -> list[tuple[float, dict[str, SubjectFrame]]]:
        """Return ``(unix_time, subject frames)`` for rows in ``[t_min, t_max]``."""
        if not self.is_loaded or t_max < t_min:
            return []
        out: list[tuple[float, dict[str, SubjectFrame]]] = []
        for t, frame in zip(self._unix_times, self._frames):
            if t < t_min or t > t_max:
                continue
            if frame:
                out.append((t, dict(frame)))
        return out

    def _nearest_row_index(self, target_unix: float) -> int:
        times = self._unix_times
        pos = bisect.bisect_left(times, target_unix)
        if pos <= 0:
            return 0
        if pos >= len(times):
            return len(times) - 1
        before = pos - 1
        if abs(times[before] - target_unix) <= abs(times[pos] - target_unix):
            return before
        return pos


def _pick_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lower_map = {c.lower(): c for c in columns}
    for name in candidates:
        if name in lower_map:
            return lower_map[name]
    return None


def _subject_scalar_column_map(columns: list[str], pattern: re.Pattern[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in columns:
        m = pattern.match(col)
        if m:
            out[m.group(1)] = col
    return out


def _read_positive_scalar(value: object) -> float | None:
    if pd.isna(value):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v) or v < 0:
        return None
    return v


def _subject_column_map(columns: list[str]) -> dict[str, tuple[str, str]]:
    x_cols: dict[str, str] = {}
    y_cols: dict[str, str] = {}
    for col in columns:
        mx = _SUBJECT_XY_RE.match(col)
        if mx:
            x_cols[mx.group(1)] = col
            continue
        my = _SUBJECT_Y_RE.match(col)
        if my:
            y_cols[my.group(1)] = col

    out: dict[str, tuple[str, str]] = {}
    for subject_id in sorted(set(x_cols) | set(y_cols)):
        if subject_id in x_cols and subject_id in y_cols:
            out[subject_id] = (x_cols[subject_id], y_cols[subject_id])
    return out


def _median_step_seconds(times: list[float]) -> float:
    if len(times) < 2:
        return 0.1
    diffs = [times[i + 1] - times[i] for i in range(len(times) - 1) if times[i + 1] > times[i]]
    if not diffs:
        return 0.1
    diffs.sort()
    median = diffs[len(diffs) // 2]
    return max(0.05, float(median))


def _read_xy(x_val: object, y_val: object) -> tuple[float, float] | None:
    if pd.isna(x_val) or pd.isna(y_val):
        return None
    try:
        x = float(x_val)
        y = float(y_val)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(x) or not np.isfinite(y):
        return None
    if x < 0 or y < 0:
        return None
    return (x, y)
