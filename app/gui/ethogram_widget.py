from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class EthogramWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(90)
        self.events = pd.DataFrame()
        self.current_frame = 0
        self.total_frames = 1

    def set_data(self, events: pd.DataFrame, current_frame: int, total_frames: int) -> None:
        self.events = events
        self.current_frame = current_frame
        self.total_frames = max(total_frames, 1)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())
        width = max(1, self.width())
        height = self.height()

        painter.setPen(QPen(QColor("#909090"), 1))
        painter.drawRect(0, 0, width - 1, height - 1)

        if not self.events.empty and "start_frame" in self.events.columns:
            unique_events = self.events.drop_duplicates(subset=["event_id"])
            for _, row in unique_events.iterrows():
                start = int(row.get("start_frame", 0) or 0)
                end = int(row.get("end_frame", start) or start)
                x1 = int(start / self.total_frames * width)
                x2 = int(max(start + 1, end) / self.total_frames * width)
                event_type = str(row.get("event_type", "other"))
                color = QColor("#4CAF50" if event_type == "fighting" else "#42A5F5")
                painter.fillRect(x1, 15, max(2, x2 - x1), height - 30, color)

        cursor_x = int(self.current_frame / self.total_frames * width)
        painter.setPen(QPen(QColor("#E53935"), 2))
        painter.drawLine(cursor_x, 0, cursor_x, height)
        painter.end()

