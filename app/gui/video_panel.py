from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget


ROLE_COLORS = {
    "initiator": QColor("#d62728"),
    "victim": QColor("#1f77b4"),
    "intervenor": QColor("#2ca02c"),
    "observer": QColor("#9467bd"),
    "winner": QColor("#ff7f0e"),
    "loser": QColor("#8c564b"),
}


class ClickableFrameLabel(QLabel):
    clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(800, 500)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._display_pixmap: QPixmap | None = None

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self._display_pixmap is None or self._display_pixmap.isNull():
            return
        label_w = self.width()
        label_h = self.height()
        pix_w = self._display_pixmap.width()
        pix_h = self._display_pixmap.height()
        offset_x = (label_w - pix_w) / 2
        offset_y = (label_h - pix_h) / 2
        x = event.position().x()
        y = event.position().y()
        if x < offset_x or y < offset_y or x > offset_x + pix_w or y > offset_y + pix_h:
            return
        rel_x = (x - offset_x) / pix_w
        rel_y = (y - offset_y) / pix_h
        self.clicked.emit(float(rel_x), float(rel_y))

    def set_display_pixmap(self, pixmap: QPixmap) -> None:
        self._display_pixmap = pixmap
        self.setPixmap(pixmap)


class VideoPanel(QWidget):
    frame_clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.current_frame: np.ndarray | None = None
        self.current_frame_index = 0
        self.role_markers: Dict[str, Tuple[float, float]] = {}

        self.status_label = QLabel("datetime: -, unix: -, frame: -")
        self.frame_label = ClickableFrameLabel()

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.frame_label)

        self.frame_label.clicked.connect(self._emit_frame_click)

    def _emit_frame_click(self, x: float, y: float) -> None:
        self.frame_clicked.emit(x, y)

    def set_frame(self, frame: np.ndarray, frame_index: int, dt_value: str, unix_value: float) -> None:
        self.current_frame = frame
        self.current_frame_index = frame_index
        self.status_label.setText(f"datetime: {dt_value or '-'} | unix: {unix_value:.6f} | frame: {frame_index}")
        self._render()

    def set_role_markers(self, markers: Dict[str, Tuple[float, float]]) -> None:
        self.role_markers = markers
        self._render()

    def _render(self) -> None:
        if self.current_frame is None:
            return
        frame = self.current_frame
        height, width, _ = frame.shape
        image = QImage(frame.data, width, height, 3 * width, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image.copy())
        if self.role_markers:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            for role, (rx, ry) in self.role_markers.items():
                color = ROLE_COLORS.get(role, QColor("yellow"))
                painter.setPen(QPen(color, 2))
                cx = int(max(0.0, min(1.0, rx)) * width)
                cy = int(max(0.0, min(1.0, ry)) * height)
                painter.drawEllipse(QPoint(cx, cy), 8, 8)
                painter.drawText(cx + 10, cy - 10, role)
            painter.end()

        scaled = pixmap.scaled(self.frame_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.frame_label.set_display_pixmap(scaled)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._render()

