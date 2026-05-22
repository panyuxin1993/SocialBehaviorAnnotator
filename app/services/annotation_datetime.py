from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

_ANNOTATION_TZ = ZoneInfo("America/New_York")
_DATE_ONLY_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_ONLY_US_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$")


def looks_like_full_datetime(s: str) -> bool:
    """True if string encodes calendar date and clock time (not date-only or time-only)."""
    s = s.strip()
    if not s:
        return False
    if _DATE_ONLY_ISO_RE.match(s) or _DATE_ONLY_US_RE.match(s):
        return False
    if _TIME_ONLY_RE.match(s):
        return False
    has_calendar = bool(re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", s))
    has_clock = bool(re.search(r"\d{1,2}:\d{2}", s))
    return has_calendar and has_clock


def format_annotation_date(value: object) -> str | None:
    """Normalize a table ``date`` cell to ``YYYY-MM-DD`` (Excel often yields midnight datetimes)."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    ts = pd.to_datetime(text, errors="coerce")
    if ts is None or pd.isna(ts):
        return text
    return ts.strftime("%Y-%m-%d")


def format_annotation_time(value: object) -> str | None:
    """Normalize a table ``start_time`` / ``end_time`` cell to wall-clock ``HH:MM:SS[.mmm]``."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, time):
        return _timestamp_to_time_str(pd.Timestamp.combine(pd.Timestamp("1970-01-01"), value))
    if isinstance(value, timedelta):
        return _seconds_to_time_str(value.total_seconds())
    if isinstance(value, pd.Timestamp):
        return _timestamp_to_time_str(value)
    if isinstance(value, datetime):
        return _timestamp_to_time_str(pd.Timestamp(value))
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    if looks_like_full_datetime(text):
        ts = pd.to_datetime(text, errors="coerce")
        if ts is not None and not pd.isna(ts):
            return _timestamp_to_time_str(ts)
    ts = pd.to_datetime(text, errors="coerce")
    if ts is not None and not pd.isna(ts):
        return _timestamp_to_time_str(ts)
    return text


def annotation_datetime_to_unix(*parts: str | None) -> float | None:
    """Parse annotation date/time text to Unix seconds for matching video timestamps.

    - Strings with timezone or offset are interpreted accordingly.
    - **Naive** strings are treated as **America/New_York** (lab collection timezone),
      not UTC — so they align with ``pd.to_datetime(..., utc=True)`` on naive input,
      which would incorrectly assume UTC.
    - When two parts are given and the second is **time-only** (typical Excel split:
      ``2025-12-16`` + ``09:00:45.7``), the calendar day is taken from the first value
      and the clock from the second.
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

        if ts.tzinfo is not None:
            return float(ts.timestamp())

        py_dt = ts.to_pydatetime()
        if py_dt.tzinfo is not None:
            py_dt = py_dt.replace(tzinfo=None)
        aware = py_dt.replace(tzinfo=_ANNOTATION_TZ)
        return float(aware.timestamp())
    except Exception:
        return None


def _timestamp_to_time_str(ts: pd.Timestamp) -> str:
    ms = int(ts.microsecond // 1000)
    base = ts.strftime("%H:%M:%S")
    if ms:
        return f"{base}.{ms:03d}"
    return base


def _seconds_to_time_str(total_seconds: float) -> str:
    if total_seconds < 0:
        total_seconds = total_seconds % 86400
    whole = int(total_seconds)
    frac = total_seconds - whole
    hours = (whole // 3600) % 24
    minutes = (whole % 3600) // 60
    seconds = whole % 60
    ms = int(round(frac * 1000))
    base = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if ms:
        return f"{base}.{ms:03d}"
    return base
