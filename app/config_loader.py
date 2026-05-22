from __future__ import annotations

import csv
import json
from pathlib import Path

from app.color_utils import parse_event_color_hex

_REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = _REPO_ROOT / "config"

_BUILTIN_EVENT_TYPE_SPECS: list[tuple[str, str, str]] = [
    ("FT", "fight", "#E53935"),
    ("CH", "chase", "#FB8C00"),
    ("PU", "push", "#1E88E5"),
    ("DF", "defend", "#43A047"),
    ("RB", "rob", "#6D4C41"),
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
    for _abbr, t, hx in _BUILTIN_EVENT_TYPE_SPECS:
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


def parse_event_types_csv(path: Path) -> list[tuple[str, str, str]]:
    """Parse ``abbr,type,color`` rows from a CSV file."""
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

    out: list[tuple[str, str, str]] = []
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
        out.append((abbr, type_name, color_hex))
    return out


def load_event_type_specs(path: Path | None = None) -> list[tuple[str, str, str]]:
    """Load ``(abbr, type, #RRGGBB)`` from *path* or ``config/event_types.csv``."""
    csv_path = path if path is not None else default_event_types_csv_path()
    if csv_path.is_file():
        specs = parse_event_types_csv(csv_path)
        if specs:
            return specs
    return list(_BUILTIN_EVENT_TYPE_SPECS)


def _specs_to_color_map(specs: list[tuple[str, str, str]]) -> dict[str, str]:
    m: dict[str, str] = dict(_TYPE_COLOR_ALIASES)
    for abbr, type_name, color_hex in specs:
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
