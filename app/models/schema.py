from __future__ import annotations

from dataclasses import dataclass


ROLE_COLUMNS = [
    "initiator",
    "victim",
    "winner",
    "loser",
    "intervenor",
    "observer",
]

ANNOTATION_COLUMNS = [
    "event_id",
    "date",
    "start_time",
    "end_time",
    "start_frame",
    "end_frame",
    "type",
    "location",
    *ROLE_COLUMNS,
    "other_notes",
]

METADATA_COLUMNS = ["animal_names"]


@dataclass(frozen=True)
class AnnotationSchema:
    annotation_sheet_name: str = "annotations"
    metadata_sheet_name: str = "metadata"

