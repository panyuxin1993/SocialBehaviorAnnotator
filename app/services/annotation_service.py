from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import pandas as pd

from app.models.event import EventRecord
from app.services.table_store import TableStore


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
        rows: list[dict] = []
        for animal in event.animals:
            row = {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "start_frame": event.start_frame,
                "end_frame": event.end_frame,
                "start_datetime": event.start_datetime.isoformat(),
                "end_datetime": event.end_datetime.isoformat() if event.end_datetime else None,
                "start_unix": event.start_unix,
                "end_unix": event.end_unix,
                "notes": event.notes,
                "animal_name": animal.animal_name,
            }
            row.update(animal.roles)
            for role, point in animal.role_points.items():
                row[f"{role}_point_xy"] = None if point is None else f"{point[0]:.2f},{point[1]:.2f}"
            rows.append(row)
        self.annotations = pd.concat([self.annotations, pd.DataFrame(rows)], ignore_index=True)

    def generate_event_id(self) -> str:
        return uuid4().hex[:10]

    def save(self) -> None:
        if self.table_path is None:
            raise ValueError("No table path configured.")
        self.table_store.save(self.table_path, self.annotations, self.animal_names)

    def start_frames(self) -> list[int]:
        if self.annotations.empty:
            return []
        starts = self.annotations["start_frame"].dropna().astype(int).unique().tolist()
        return sorted(starts)

    def next_event_start_frame(self, current_frame: int) -> int | None:
        starts = self.start_frames()
        for frame in starts:
            if frame > current_frame:
                return frame
        return None

    def previous_event_start_frame(self, current_frame: int) -> int | None:
        starts = self.start_frames()
        prev = [frame for frame in starts if frame < current_frame]
        return prev[-1] if prev else None

    def find_event_by_start_frame(self, start_frame: int) -> dict | None:
        if self.annotations.empty:
            return None
        df = self.annotations[self.annotations["start_frame"].fillna(-1).astype(int) == int(start_frame)]
        if df.empty:
            return None
        return df.to_dict(orient="records")[0]

