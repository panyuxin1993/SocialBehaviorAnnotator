from __future__ import annotations

import re

from PySide6.QtGui import QColor


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
    from app.config_loader import default_type_color_map

    key = event_type.strip().lower()
    hex_color = default_type_color_map().get(key)
    if hex_color is not None:
        return hex_color
    h = (hash(key) % 360 + 360) % 360
    c = QColor.fromHsl(h, 160, 150)
    return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"
