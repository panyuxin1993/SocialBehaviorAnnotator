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
            self._unix_timestamps = [float(v) for v in values.tolist()]
            return

        if suffix == ".json":
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._unix_timestamps = self._parse_json(payload)
            return

        raise ValueError(f"Unsupported timestamp file type: {path.suffix}")

    def _parse_json(self, payload: object) -> list[float]:
        if isinstance(payload, list):
            return [float(v) for v in payload]

        if isinstance(payload, dict):
            if "timestamps" in payload and isinstance(payload["timestamps"], list):
                return [float(v) for v in payload["timestamps"]]
            if "unix_timestamps" in payload and isinstance(payload["unix_timestamps"], list):
                return [float(v) for v in payload["unix_timestamps"]]

        raise ValueError("Unsupported json timestamp format. Expected list or {timestamps: [...]} payload.")

    def timestamp_for_frame(self, frame_index: int) -> tuple[str, float]:
        if not self._unix_timestamps:
            return "", 0.0
        idx = max(0, min(frame_index, len(self._unix_timestamps) - 1))
        unix_value = float(self._unix_timestamps[idx])
        dt_value = datetime.fromtimestamp(unix_value).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        return dt_value, unix_value

    @property
    def timestamps(self) -> list[float]:
        return self._unix_timestamps

