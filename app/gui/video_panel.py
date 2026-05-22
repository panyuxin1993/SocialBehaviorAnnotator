from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.gui.colors import ANIMAL_COLORS


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


def _subject_color(subject_id: str, subjects: list[str]) -> QColor:
    if subjects:
        try:
            idx = subjects.index(subject_id)
        except ValueError:
            idx = hash(subject_id) % len(ANIMAL_COLORS)
    else:
        idx = hash(subject_id) % len(ANIMAL_COLORS)
    return QColor(ANIMAL_COLORS[idx % len(ANIMAL_COLORS)])


class VideoPanel(QWidget):
    frame_clicked = Signal(float, float)

    def __init__(self) -> None:
        super().__init__()
        self.current_frame: np.ndarray | None = None
        self.current_frame_index = 0
        self.role_markers: Dict[str, Tuple[float, float]] = {}
        self.tracking_markers: Dict[str, Tuple[float, float]] = {}
        self._tracking_subjects: list[str] = []
        self._show_tracking = True

        self.status_label = QLabel("datetime: -, unix: -, frame: -")
        self.tracking_toggle = QCheckBox("Show tracking")
        self.tracking_toggle.setChecked(True)
        self.tracking_toggle.toggled.connect(self._on_tracking_toggled)
        self.tracking_status_label = QLabel("tracking: not loaded")
        self.tracking_status_label.setStyleSheet("color: palette(mid);")

        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, stretch=1)
        status_row.addWidget(self.tracking_toggle)
        status_row.addWidget(self.tracking_status_label)

        self.frame_label = ClickableFrameLabel()

        layout = QVBoxLayout(self)
        layout.addLayout(status_row)
        layout.addWidget(self.frame_label)

        self.frame_label.clicked.connect(self._emit_frame_click)

    def _on_tracking_toggled(self, checked: bool) -> None:
        self._show_tracking = checked
        self._render()

    def set_tracking_overlay(
        self,
        markers: Dict[str, Tuple[float, float]] | None,
        *,
        subjects: list[str] | None = None,
        loaded: bool = True,
        source_name: str = "",
        refresh: bool = True,
    ) -> None:
        self.tracking_markers = dict(markers) if markers else {}
        if subjects is not None:
            self._tracking_subjects = list(subjects)
        if loaded and source_name:
            n = len(self._tracking_subjects)
            self.tracking_status_label.setText(f"tracking: {source_name} ({n} subjects)")
            self.tracking_toggle.setEnabled(True)
        elif not loaded:
            self.tracking_markers = {}
            self._tracking_subjects = []
            self.tracking_status_label.setText("tracking: not loaded")
            self.tracking_toggle.setEnabled(False)
        if refresh:
            self._render()

    def tracking_visible(self) -> bool:
        return self._show_tracking and bool(self.tracking_markers)

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
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._show_tracking and self.tracking_markers:
            font = QFont()
            font.setPointSize(9)
            font.setBold(True)
            painter.setFont(font)
            for subject_id, (px, py) in sorted(self.tracking_markers.items()):
                color = _subject_color(subject_id, self._tracking_subjects)
                cx = int(max(0.0, min(float(width - 1), px)))
                cy = int(max(0.0, min(float(height - 1), py)))
                painter.setBrush(color)
                painter.setPen(QPen(QColor("#202020"), 2))
                painter.drawEllipse(QPoint(cx, cy), 10, 10)
                painter.setPen(QPen(QColor("#FFFFFF"), 1))
                label = subject_id.replace("_center", "")
                painter.drawText(cx + 12, cy - 12, label)
        if self.role_markers:
            for role, (rx, ry) in self.role_markers.items():
                color = ROLE_COLORS.get(role, QColor("yellow"))
                painter.setPen(QPen(color, 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                cx = int(max(0.0, min(1.0, rx)) * width)
                cy = int(max(0.0, min(1.0, ry)) * height)
                painter.drawEllipse(QPoint(cx, cy), 12, 12)
                painter.drawText(cx + 14, cy - 14, role)
        painter.end()

        scaled = pixmap.scaled(self.frame_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.frame_label.set_display_pixmap(scaled)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._render()

