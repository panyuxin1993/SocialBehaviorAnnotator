from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np


class TimestampService:
    def __init__(self) -> None:
        self._unix_timestamps: list[float] = []

    def load_file(self, timestamp_path: str | Path) -> None:
        path = Path(timestamp_path)
        suffix = path.suffix.lower()

        if suffix == ".npy":
            values = np.load(path)
            if values.ndim > 1:
                values = values.reshape(-1)
            self._unix_timestamps = [self._normalize_unix_seconds(float(v)) for v in values.tolist()]
            return

        if suffix == ".json":
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._unix_timestamps = self._parse_json(payload)
            return

        raise ValueError(f"Unsupported timestamp file type: {path.suffix}")

    def _parse_json(self, payload: object) -> list[float]:
        if isinstance(payload, list):
            if not payload:
                raise ValueError("Timestamp json list is empty.")
            first = payload[0]
            if isinstance(first, dict):
                if "cam_frame_time" in first:
                    return [
                        self._normalize_unix_seconds(float(item["cam_frame_time"]))
                        for item in payload
                        if isinstance(item, dict) and "cam_frame_time" in item
                    ]
                if "timestamp" in first:
                    return [
                        self._normalize_unix_seconds(float(item["timestamp"]))
                        for item in payload
                        if isinstance(item, dict) and "timestamp" in item
                    ]
                raise ValueError(
                    "Unsupported json list[dict] timestamp format. "
                    "Expected key 'cam_frame_time' or 'timestamp'."
                )
            return [self._normalize_unix_seconds(float(v)) for v in payload]

        if isinstance(payload, dict):
            if "timestamps" in payload and isinstance(payload["timestamps"], list):
                return [self._normalize_unix_seconds(float(v)) for v in payload["timestamps"]]
            if "unix_timestamps" in payload and isinstance(payload["unix_timestamps"], list):
                return [self._normalize_unix_seconds(float(v)) for v in payload["unix_timestamps"]]

        raise ValueError(
            "Unsupported json timestamp format. Expected one of: "
            "list[number], list[{cam_frame_time|timestamp}], or {timestamps|unix_timestamps: [...]}"
        )

    @staticmethod
    def _normalize_unix_seconds(value: float) -> float:
        """
        Normalize unix timestamps to seconds.
        Accepts common units:
        - seconds (~1e9..1e10)
        - milliseconds (~1e12..1e13)
        - microseconds (~1e15..1e16)
        - nanoseconds (~1e18..1e19)
        """
        abs_value = abs(value)
        if abs_value >= 1e18:  # nanoseconds
            return value / 1e9
        if abs_value >= 1e15:  # microseconds
            return value / 1e6
        if abs_value >= 1e12:  # milliseconds
            return value / 1e3
        return value

    def timestamp_for_frame(self, frame_index: int) -> tuple[str, float]:
        if not self._unix_timestamps:
            return "", 0.0
        idx = max(0, min(frame_index, len(self._unix_timestamps) - 1))
        unix_value = float(self._unix_timestamps[idx])
        try:
            dt_value = datetime.fromtimestamp(unix_value).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        except (OverflowError, OSError, ValueError):
            dt_value = ""
        return dt_value, unix_value

    @property
    def timestamps(self) -> list[float]:
        return self._unix_timestamps

