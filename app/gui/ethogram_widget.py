from __future__ import annotations

import bisect
import math
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

# Max horizontal resolution for pre-rendered timeline (memory vs sharpness).
_MAX_TIMELINE_CACHE_WIDTH = 12000

from app.services.annotation_service import annotation_datetime_to_unix, looks_like_full_datetime

_NY = ZoneInfo("America/New_York")

# Default event-type colors (aligned with rat_city ethogram style: distinct hues).
_DEFAULT_TYPE_COLORS: dict[str, str] = {
    "fighting": "#E53935",
    "fight": "#E53935",
    "chasing": "#FB8C00",
    "chase": "#FB8C00",
    "mounting": "#8E24AA",
    "push": "#1E88E5",
    "defend": "#43A047",
    "rob": "#6D4C41",
    "other": "#78909C",
}


def parse_event_color_hex(s: str) -> str | None:
    """Return ``#RRGGBB`` for user/CSV input: ``#hex``, bare 6-digit hex, 3-digit, or QColor names."""
    t = (s or "").strip()
    if not t:
        return None
    tl = t.lower()
    if re.fullmatch(r"[0-9a-f]{6}", tl):
        t = "#" + tl
    elif re.fullmatch(r"[0-9a-f]{3}", tl):
        t = "#" + "".join(ch * 2 for ch in tl)
    c = QColor(t)
    if not c.isValid():
        return None
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


def fallback_event_type_hex(event_type: str) -> str:
    """Stable default ``#RRGGBB`` for a type when the project has no custom color."""
    key = event_type.strip().lower()
    hex_color = _DEFAULT_TYPE_COLORS.get(key)
    if hex_color is not None:
        return hex_color
    h = (hash(key) % 360 + 360) % 360
    c = QColor.fromHsl(h, 160, 150)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"


class EthogramWidget(QWidget):
    """Timeline of events over a sliding frame window (see rat_city ethogram_view layering)."""

    #: Emitted when ``set_data`` loads annotations — ``list[tuple[str, str]]`` of (type label, ``#RRGGBB``).
    legend_items_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(90)
        self.events = pd.DataFrame()
        self.current_frame = 0
        self.total_frames = 1
        self.video_timestamps: list[float] = []
        self.animal_names: list[str] = []
        #: Half-width of the visible timeline in **seconds** (± around playhead).
        self.window_radius_seconds: float = 60.0
        #: Video FPS from project (used only when there is no per-frame timestamp list).
        self._video_fps: float = 0.0
        #: Full-video timeline raster; rebuilt only in ``set_data`` (not on every seek).
        self._timeline_cache: QImage | None = None
        self._cache_w: int = 0
        self._cache_h: int = 0
        #: Lowercased event ``type`` string → ``#RRGGBB`` from Annotation → Event types…
        self._type_color_overrides: dict[str, str] = {}
        #: Lowercased stored ``type`` cell (often abbr) → legend label (usually full type name).
        self._type_legend_labels: dict[str, str] = {}

    @staticmethod
    def _color_hex(c: QColor) -> str:
        return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

    def set_playhead(self, frame: int) -> None:
        """Update current frame for drawing without rebuilding the timeline cache."""
        self.current_frame = int(frame)
        self.update()

    def set_window_radius_seconds(self, seconds: float) -> None:
        """Set ethogram half-window in seconds (± around current time) and repaint."""
        s = float(seconds)
        if s < 0.5:
            s = 0.5
        if s > 86400.0:
            s = 86400.0
        self.window_radius_seconds = s
        self.update()

    def set_type_color_overrides(self, mapping: dict[str, str] | None) -> None:
        """Set per-type ethogram colors (keys matched case-insensitively on ``type``)."""
        self._type_color_overrides = {}
        if not mapping:
            return
        for k, v in mapping.items():
            key = str(k).strip().lower()
            if not key:
                continue
            raw = str(v).strip() if v is not None else ""
            nh = parse_event_color_hex(raw) if raw else None
            if not nh and raw:
                c = QColor(raw)
                if c.isValid():
                    nh = f"#{c.red():02x}{c.green():02x}{c.blue():02x}"
            if nh:
                self._type_color_overrides[key] = nh

    def apply_type_color_map(self, mapping: dict[str, str] | None) -> None:
        """Update colors only (e.g. after Event types…); rebuilds the timeline raster."""
        self.set_type_color_overrides(mapping)
        self._timeline_cache = None
        self._emit_legend_items()
        self.update()
        self.repaint()

    def set_data(
        self,
        events: pd.DataFrame,
        current_frame: int,
        total_frames: int,
        video_timestamps: list[float] | None = None,
        animal_names: list[str] | None = None,
        fps: float | None = None,
        type_colors: dict[str, str] | None = None,
        type_legend_labels: dict[str, str] | None = None,
    ) -> None:
        # Annotation / video metadata changed — drop cached bitmap (expensive rebuild once).
        self._timeline_cache = None
        self.events = events
        self.current_frame = current_frame
        self.total_frames = max(total_frames, 1)
        self.video_timestamps = video_timestamps or []
        self.animal_names = list(animal_names or [])
        if fps is not None and fps > 0:
            self._video_fps = float(fps)
        if type_colors is not None:
            self.set_type_color_overrides(type_colors)
        if type_legend_labels is not None:
            self._type_legend_labels = {
                str(k).strip().lower(): str(v).strip()
                for k, v in type_legend_labels.items()
                if str(k).strip() and str(v).strip()
            }
        else:
            self._type_legend_labels = {}
        n_lanes = max(1, len(self.animal_names))
        self.setMinimumHeight(max(90, min(22 * n_lanes + 24, 400)))
        self._emit_legend_items()
        self.update()

    def _emit_legend_items(self) -> None:
        """Publish unique event types and colors for the navigator legend."""
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()
        df = self._unique_events_df()
        if not df.empty and "type" in df.columns:
            for _, row in df.iterrows():
                t = str(row.get("type", "")).strip()
                if not t or t.lower() == "nan":
                    continue
                key = t.lower()
                if key in seen:
                    continue
                seen.add(key)
                c = self._color_for_event_type(t)
                label = self._type_legend_labels.get(key, t)
                pairs.append((label, self._color_hex(c)))
        if not pairs:
            for t in ("fight", "chase", "push", "defend", "rob", "other"):
                c = self._color_for_event_type(t)
                pairs.append((t, self._color_hex(c)))
        self.legend_items_changed.emit(pairs)

    def refresh_legend(self) -> None:
        """Recompute legend entries from current events (call after wiring ``legend_items_changed``)."""
        self._emit_legend_items()

    @staticmethod
    def _to_int_or_none(value) -> int | None:
        if value is None:
            return None
        try:
            if isinstance(value, float) and math.isnan(value):
                return None
            if pd.isna(value):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _names_in_cell(value) -> set[str]:
        if value is None:
            return set()
        try:
            if isinstance(value, float) and math.isnan(value):
                return set()
            if pd.isna(value):
                return set()
        except (TypeError, ValueError):
            return set()
        s = str(value).strip()
        if not s or s.lower() == "nan":
            return set()
        return {p.strip() for p in s.split(",") if p.strip()}

    def _color_for_event_type(self, event_type: str) -> QColor:
        key = event_type.strip().lower()
        ov = self._type_color_overrides.get(key)
        if ov:
            c = QColor(ov)
            if c.isValid():
                return c
        hex_color = _DEFAULT_TYPE_COLORS.get(key)
        if hex_color is None:
            h = (hash(key) % 360 + 360) % 360
            return QColor.fromHsl(h, 160, 150)
        c = QColor(hex_color)
        if not c.isValid():
            return QColor("#78909C")
        return c

    def _infer_fps(self) -> float:
        """Average frames-per-second from timestamps, else a safe default."""
        ts = self.video_timestamps
        tf = self.total_frames
        n = min(len(ts), tf) if ts and tf else 0
        if n >= 2:
            span = float(ts[n - 1]) - float(ts[0])
            if span > 0:
                return (n - 1) / span
        return 30.0

    def _radius_frames(self) -> int:
        """±window in frames when timestamps are unavailable (fps × seconds)."""
        fps = float(self._video_fps) if self._video_fps > 0 else self._infer_fps()
        return max(1, int(self.window_radius_seconds * fps))

    def _frame_window(self) -> tuple[int, int]:
        """[start, end] frame indices visible in the ethogram (inclusive)."""
        tf = max(0, self.total_frames - 1)
        current = max(0, min(self.current_frame, tf))
        ts = self.video_timestamps
        half_sec = max(0.001, float(self.window_radius_seconds))

        if len(ts) >= 2:
            n = min(len(ts), self.total_frames)
            if n <= 1:
                return 0, tf
            fi = min(current, n - 1)
            u = float(ts[fi])
            arr = [float(ts[i]) for i in range(n)]
            lo = bisect.bisect_left(arr, u - half_sec)
            hi = bisect.bisect_right(arr, u + half_sec) - 1
            lo = max(0, lo)
            hi = max(lo, hi)
            hi = min(hi, tf)
            return lo, hi

        radius = self._radius_frames()
        start = max(0, current - radius)
        end = min(tf, current + radius)
        target_span = min(tf, 2 * radius) if tf > 0 else 0
        actual_span = end - start
        if target_span > 0 and actual_span < target_span:
            missing = target_span - actual_span
            shift_left = min(start, missing)
            start -= shift_left
            end = min(tf, end + (missing - shift_left))
        return start, end

    def _unix_for_frame(self, frame_index: int) -> float | None:
        ts = self.video_timestamps
        if not ts:
            return None
        fi = max(0, min(int(frame_index), len(ts) - 1))
        return float(ts[fi])

    def _frame_from_unix(self, target_unix: float) -> int | None:
        ts = self.video_timestamps
        if not ts:
            return None
        return int(min(range(len(ts)), key=lambda i: abs(float(ts[i]) - target_unix)))

    def _daytime_unix_segments(self, unix_lo: float, unix_hi: float) -> list[tuple[float, float]]:
        """9:00–21:00 America/New_York per calendar day, intersected with [unix_lo, unix_hi]."""
        if unix_hi <= unix_lo:
            return []
        start_dt = datetime.fromtimestamp(unix_lo, tz=_NY)
        end_dt = datetime.fromtimestamp(unix_hi, tz=_NY)
        out: list[tuple[float, float]] = []
        day = start_dt.date()
        end_day = end_dt.date()
        while day <= end_day:
            t0 = datetime.combine(day, time(9, 0, 0), tzinfo=_NY).timestamp()
            t1 = datetime.combine(day, time(21, 0, 0), tzinfo=_NY).timestamp()
            lo = max(t0, unix_lo)
            hi = min(t1, unix_hi)
            if lo < hi:
                out.append((lo, hi))
            day += timedelta(days=1)
        return out

    def _event_frame_span(self, row) -> tuple[int | None, int | None]:
        start = self._to_int_or_none(row.get("start_frame", None))
        if start is None:
            start = self._frame_from_datetime_str(row.get("date", None), row.get("start_time", None))
        end = self._to_int_or_none(row.get("end_frame", None))
        if end is None:
            end = self._frame_from_datetime_str(row.get("date", None), row.get("end_time", None))
        if end is None:
            end = start
        if start is None:
            return None, None
        end = max(end, start)
        return start, end

    def _unique_events_df(self) -> pd.DataFrame:
        if self.events.empty:
            return self.events
        if "start_time" in self.events.columns:
            dedupe_cols = [c for c in ["start_time", "type", "other_notes"] if c in self.events.columns]
            if dedupe_cols:
                return self.events.drop_duplicates(subset=dedupe_cols)
        if "start_frame" in self.events.columns and "event_id" in self.events.columns:
            return self.events.drop_duplicates(subset=["event_id"])
        return self.events

    @staticmethod
    def _frame_to_cache_x(frame_index: int, cache_w: int, last_frame_index: int) -> int:
        if cache_w <= 1 or last_frame_index <= 0:
            return 0
        f = max(0, min(int(frame_index), last_frame_index))
        return int(f * (cache_w - 1) / last_frame_index)

    def _ensure_timeline_cache(self) -> None:
        if self._timeline_cache is not None and not self._timeline_cache.isNull():
            return
        self._build_timeline_cache()

    def _build_timeline_cache(self) -> None:
        """Rasterize the full timeline once (rest, daytime, events) for fast pan/zoom in paintEvent."""
        tf = max(1, self.total_frames)
        last_f = max(0, tf - 1)
        cache_w = min(_MAX_TIMELINE_CACHE_WIDTH, max(1, tf))
        animals = self.animal_names
        n_lanes = max(1, len(animals))
        cache_h = max(48, int(18 * n_lanes + 20))

        img = QImage(cache_w, cache_h, QImage.Format_RGB32)
        img.fill(QColor(245, 245, 245))
        p = QPainter(img)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            lane_h = max(14.0, (cache_h - 4) / n_lanes)
            ts = self.video_timestamps
            n_ts = min(len(ts), tf) if ts else 0
            arr = [float(ts[i]) for i in range(n_ts)] if n_ts >= 2 else []

            for lane in range(n_lanes):
                y0 = int(2 + lane * lane_h)
                y1 = int(min(cache_h - 2, y0 + int(lane_h) - 2))
                rh = max(1, y1 - y0)

                p.fillRect(0, y0, cache_w, rh, QColor(255, 255, 255))
                p.setPen(QPen(QColor(0, 0, 0, 50), 1))
                p.drawRect(0, y0, cache_w - 1, rh - 1)

                if len(arr) >= 2:
                    u0, u1 = arr[0], arr[-1]
                    for lo_u, hi_u in self._daytime_unix_segments(u0, u1):
                        fa = bisect.bisect_left(arr, lo_u)
                        fb = bisect.bisect_right(arr, hi_u) - 1
                        fa = max(0, min(fa, last_f))
                        fb = max(0, min(fb, last_f))
                        xa = self._frame_to_cache_x(fa, cache_w, last_f)
                        xb = self._frame_to_cache_x(fb, cache_w, last_f)
                        p.fillRect(xa, y0, max(1, xb - xa + 1), rh, QColor(218, 218, 218))

            unique_events = self._unique_events_df()
            if not unique_events.empty:
                for _, row in unique_events.iterrows():
                    start_f, end_f = self._event_frame_span(row)
                    if start_f is None or end_f is None:
                        continue

                    event_type = str(row.get("type", row.get("event_type", "other")))
                    base_color = self._color_for_event_type(event_type)
                    initiators = self._names_in_cell(row.get("initiator", ""))
                    victims = self._names_in_cell(row.get("victim", ""))

                    if animals:
                        for lane, name in enumerate(animals):
                            y0 = int(2 + lane * lane_h)
                            y1 = int(min(cache_h - 2, y0 + int(lane_h) - 2))
                            rh = max(1, y1 - y0)
                            draw_init = name in initiators
                            draw_vict = name in victims
                            if not draw_init and not draw_vict:
                                continue
                            xa = self._frame_to_cache_x(start_f, cache_w, last_f)
                            xb = self._frame_to_cache_x(end_f, cache_w, last_f) + 1
                            if xb <= xa:
                                xb = min(cache_w - 1, xa + 1)
                            if draw_init:
                                c = QColor(base_color)
                                c.setAlpha(255)
                                p.fillRect(xa, y0, max(2, xb - xa), rh, c)
                            if draw_vict:
                                c = QColor(base_color)
                                c.setAlpha(128)
                                p.fillRect(xa, y0, max(2, xb - xa), rh, c)
                    else:
                        y0 = 2
                        y1 = cache_h - 2
                        rh = max(1, y1 - y0)
                        xa = self._frame_to_cache_x(start_f, cache_w, last_f)
                        xb = self._frame_to_cache_x(end_f, cache_w, last_f) + 1
                        if xb <= xa:
                            xb = min(cache_w - 1, xa + 1)
                        c = QColor(base_color)
                        c.setAlpha(230)
                        p.fillRect(xa, y0, max(2, xb - xa), rh, c)
        finally:
            if p.isActive():
                p.end()

        self._timeline_cache = img
        self._cache_w = cache_w
        self._cache_h = cache_h

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            width = max(1, self.width())
            height = self.height()

            painter.fillRect(self.rect(), self.palette().window())
            painter.setPen(QPen(QColor("#909090"), 1))
            painter.drawRect(0, 0, width - 1, height - 1)

            margin = 6
            animals = self.animal_names
            n_lanes = max(1, len(animals))
            label_w = min(120, width // 4) if animals else 0
            plot_x0 = margin + label_w
            plot_w = max(1, width - plot_x0 - margin)
            lane_h = max(14.0, (height - 2 * margin) / n_lanes)

            for lane in range(n_lanes):
                y0 = int(margin + lane * lane_h)
                y1 = int(min(height - margin, y0 + lane_h - 2))
                if y1 <= y0:
                    continue
                if animals and lane < len(animals):
                    painter.setPen(QColor("#404040"))
                    painter.drawText(
                        margin,
                        y0,
                        label_w - 4,
                        y1 - y0,
                        Qt.AlignRight | Qt.AlignVCenter,
                        animals[lane],
                    )

            window_start, window_end = self._frame_window()
            window_span = max(1, window_end - window_start)
            last_f = max(0, self.total_frames - 1)

            self._ensure_timeline_cache()
            plot_rect_h = max(1, height - 2 * margin)
            if self._timeline_cache is not None and not self._timeline_cache.isNull() and self._cache_w > 0:
                sx0 = self._frame_to_cache_x(window_start, self._cache_w, last_f)
                sx1 = self._frame_to_cache_x(window_end, self._cache_w, last_f) + 1
                sw = max(1, min(self._cache_w - sx0, sx1 - sx0))
                painter.drawImage(
                    QRect(int(plot_x0), margin, int(plot_w), int(plot_rect_h)),
                    self._timeline_cache,
                    QRect(int(sx0), 0, int(sw), int(self._timeline_cache.height())),
                )
            else:
                # Fallback if cache failed
                painter.fillRect(plot_x0, margin, plot_w, plot_rect_h, QColor(250, 250, 250))

            cursor_x = plot_x0 + int((self.current_frame - window_start) / window_span * plot_w)
            cursor_x = max(plot_x0, min(plot_x0 + plot_w - 1, cursor_x))
            painter.setPen(QPen(QColor("#E53935"), 2))
            painter.drawLine(cursor_x, margin, cursor_x, height - margin)
        finally:
            if painter.isActive():
                painter.end()

    def _frame_from_datetime_str(self, date_value, time_value) -> int | None:
        """Map ``date`` + ``start_time`` / ``end_time`` cells to a frame index."""
        if not self.video_timestamps:
            return None
        if time_value is None:
            return None
        try:
            if isinstance(time_value, float) and math.isnan(time_value):
                return None
            if pd.isna(time_value):
                return None
        except (TypeError, ValueError):
            return None

        t = str(time_value).strip()
        if not t or t.lower() == "nan":
            return None

        date_str: str | None = None
        if date_value is not None:
            try:
                if isinstance(date_value, float) and math.isnan(date_value):
                    date_str = None
                elif pd.isna(date_value):
                    date_str = None
                else:
                    ds = str(date_value).strip()
                    date_str = ds if ds and ds.lower() != "nan" else None
            except (TypeError, ValueError):
                date_str = None

        if looks_like_full_datetime(t):
            target_unix = annotation_datetime_to_unix(t)
        elif date_str:
            target_unix = annotation_datetime_to_unix(date_str, t)
        else:
            target_unix = annotation_datetime_to_unix(t)

        if target_unix is None:
            return None
        try:
            return self._frame_from_unix(target_unix)
        except Exception:
            return None
