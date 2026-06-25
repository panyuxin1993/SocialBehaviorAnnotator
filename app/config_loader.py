from __future__ import annotations

import csv
import json
from pathlib import Path

from app.color_utils import parse_event_color_hex

_REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = _REPO_ROOT / "config"

# (abbr, type, color, environmental)
EventTypeSpec = tuple[str, str, str, bool]

_BUILTIN_EVENT_TYPE_SPECS: list[EventTypeSpec] = [
    ("FT", "fight", "#E53935", False),
    ("CH", "chase", "#FB8C00", False),
    ("PU", "push", "#1E88E5", False),
    ("DF", "defend", "#43A047", False),
    ("RB", "rob", "#6D4C41", False),
]

# Extra lookup keys for ethogram fallbacks (synonyms not listed as separate CSV rows).
_TYPE_COLOR_ALIASES: dict[str, str] = {
    "fighting": "#E53935",
    "chasing": "#FB8C00",
    "mounting": "#8E24AA",
    "other": "#78909C",
}

_cached_type_colors: dict[str, str] | None = None


def _builtin_hex_for_type(type_name: str) -> str:
    key = type_name.strip().lower()
    for _abbr, t, hx, _environmental in _BUILTIN_EVENT_TYPE_SPECS:
        if t.lower() == key:
            return hx
    return "#78909C"


def repo_config_dir() -> Path:
    """Directory containing shipped default/example configuration files."""
    return CONFIG_DIR


def default_event_types_csv_path() -> Path:
    return CONFIG_DIR / "event_types.csv"


def example_event_types_csv_path() -> Path:
    return CONFIG_DIR / "event_types.example.csv"


def _parse_environmental_cell(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "env", "environmental"}


def parse_event_types_csv(path: Path) -> list[EventTypeSpec]:
    """Parse ``abbr,type,color[,environmental]`` rows from a CSV file."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return []

    headers = [h.strip().lower() for h in rows[0]]
    data_rows = rows[1:]
    abbr_idx = headers.index("abbr") if "abbr" in headers else 0
    type_idx = headers.index("type") if "type" in headers else min(1, len(headers) - 1)
    color_idx = headers.index("color") if "color" in headers else None
    env_idx = headers.index("environmental") if "environmental" in headers else None

    out: list[EventTypeSpec] = []
    seen: set[str] = set()
    for raw in data_rows:
        if not raw:
            continue
        abbr = raw[abbr_idx].strip() if abbr_idx < len(raw) else ""
        type_name = raw[type_idx].strip() if type_idx < len(raw) else ""
        if not type_name:
            continue
        kl = type_name.lower()
        if kl in seen:
            continue
        seen.add(kl)
        color_cell = ""
        if color_idx is not None and color_idx < len(raw):
            color_cell = raw[color_idx].strip()
        parsed = parse_event_color_hex(color_cell)
        color_hex = parsed if parsed else _builtin_hex_for_type(type_name)
        environmental = False
        if env_idx is not None and env_idx < len(raw):
            environmental = _parse_environmental_cell(raw[env_idx])
        out.append((abbr, type_name, color_hex, environmental))
    return out


def load_event_type_specs(path: Path | None = None) -> list[EventTypeSpec]:
    """Load ``(abbr, type, #RRGGBB)`` from *path* or ``config/event_types.csv``."""
    csv_path = path if path is not None else default_event_types_csv_path()
    if csv_path.is_file():
        specs = parse_event_types_csv(csv_path)
        if specs:
            return specs
    return list(_BUILTIN_EVENT_TYPE_SPECS)


def environmental_type_keys(specs: list[EventTypeSpec]) -> set[str]:
    """Lowercase ``type`` and ``abbr`` tokens marked environmental in event-type specs."""
    keys: set[str] = set()
    for abbr, type_name, _color_hex, environmental in specs:
        if not environmental:
            continue
        keys.add(type_name.strip().lower())
        a = (abbr or "").strip()
        if a:
            keys.add(a.lower())
    return keys


def _specs_to_color_map(specs: list[EventTypeSpec]) -> dict[str, str]:
    m: dict[str, str] = dict(_TYPE_COLOR_ALIASES)
    for abbr, type_name, color_hex, _environmental in specs:
        m[type_name.strip().lower()] = color_hex
        a = (abbr or "").strip()
        if a:
            m[a.lower()] = color_hex
    return m


def default_type_color_map(*, reload: bool = False) -> dict[str, str]:
    """Lowercase type/abbr → ``#RRGGBB`` for ethogram fallbacks."""
    global _cached_type_colors
    if _cached_type_colors is None or reload:
        _cached_type_colors = _specs_to_color_map(load_event_type_specs())
    return _cached_type_colors


def load_animal_colors_example() -> list[str] | None:
    """Read example animal palette from ``config/animal_colors.example.json``."""
    path = CONFIG_DIR / "animal_colors.example.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    colors = data.get("colors")
    if not isinstance(colors, list):
        return None
    out: list[str] = []
    for c in colors:
        hx = parse_event_color_hex(str(c))
        if hx:
            out.append(hx)
    return out or None


_ANIMAL_NAME_HEADER_LABELS = frozenset(
    {"rat", "name", "animal", "animal_name", "rat_id", "id", "subject", "subject_id"}
)
_ANIMAL_NAME_SKIP_LABELS = frozenset({"sum", "total", "mean", "average", "avg"})


def parse_animal_names_xlsx(path: Path) -> list[str]:
    """Read animal names from the first column of the first worksheet."""
    import pandas as pd

    df = pd.read_excel(path, sheet_name=0)
    if df.empty:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for idx, raw in enumerate(df.iloc[:, 0]):
        if pd.isna(raw):
            continue
        text = str(raw).strip()
        if not text or text.lower() == "nan":
            continue
        key = text.lower()
        if idx == 0 and key in _ANIMAL_NAME_HEADER_LABELS:
            continue
        if key in _ANIMAL_NAME_SKIP_LABELS:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
