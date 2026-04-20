from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional, Tuple

from app.models.schema import ROLE_COLUMNS


Point = Tuple[float, float]


@dataclass
class AnimalRoleSelection:
    animal_name: str
    roles: Dict[str, bool] = field(default_factory=dict)
    role_points: Dict[str, Optional[Point]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for role in ROLE_COLUMNS:
            self.roles.setdefault(role, False)
            self.role_points.setdefault(role, None)


@dataclass
class EventRecord:
    event_id: str
    event_type: str
    start_frame: int
    end_frame: Optional[int]
    start_datetime: datetime
    end_datetime: Optional[datetime]
    start_unix: float
    end_unix: Optional[float]
    #: Arena / site: ``left``, ``right``, or ``door`` (stored in ``location`` column).
    event_location: str = "left"
    notes: str = ""
    animals: list[AnimalRoleSelection] = field(default_factory=list)
    #: When set, ``submit`` updates this dataframe row (positional index) instead of appending.
    editing_iloc: Optional[int] = None

