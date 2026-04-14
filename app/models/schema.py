from __future__ import annotations

from dataclasses import dataclass


ROLE_COLUMNS = [
    "initiator",
    "victim",
    "intervenor",
    "observer",
    "winner",
    "loser",
]

ROLE_POINT_COLUMNS = [f"{role}_point_xy" for role in ROLE_COLUMNS]

ANNOTATION_COLUMNS = [
    "event_id",
    "event_type",
    "start_frame",
    "end_frame",
    "start_datetime",
    "end_datetime",
    "start_unix",
    "end_unix",
    "notes",
    "animal_name",
    *ROLE_COLUMNS,
    *ROLE_POINT_COLUMNS,
]

METADATA_COLUMNS = ["animal_names"]


@dataclass(frozen=True)
class AnnotationSchema:
    annotation_sheet_name: str = "annotations"
    metadata_sheet_name: str = "metadata"

