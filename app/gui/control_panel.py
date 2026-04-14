from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.event import AnimalRoleSelection, EventRecord
from app.models.schema import ROLE_COLUMNS


ROLE_TO_COLUMN = {role: idx + 1 for idx, role in enumerate(ROLE_COLUMNS)}

ANIMAL_COLORS = [
    "#F8BBD0",
    "#BBDEFB",
    "#C8E6C9",
    "#FFECB3",
    "#D1C4E9",
    "#B2EBF2",
    "#FFE0B2",
    "#DCEDC8",
]


class ControlPanel(QWidget):
    request_seek_frame = Signal(int)
    submit_event_requested = Signal(EventRecord)

    def __init__(self) -> None:
        super().__init__()
        self.animal_names: list[str] = []
        self.pending_role_capture: Optional[Tuple[int, str]] = None
        self.current_frame_image: Optional[np.ndarray] = None
        self.start_frame: Optional[int] = None
        self.end_frame: Optional[int] = None
        self.start_datetime: Optional[datetime] = None
        self.end_datetime: Optional[datetime] = None
        self.start_unix: Optional[float] = None
        self.end_unix: Optional[float] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_zoom_group())
        layout.addWidget(self._build_timing_group())
        layout.addWidget(self._build_event_group())
        layout.addWidget(self._build_role_table_group(), stretch=1)
        layout.addWidget(self._build_notes_group())
        layout.addWidget(self._build_submit_row())

    def _build_zoom_group(self) -> QGroupBox:
        group = QGroupBox("Zoom view")
        g = QVBoxLayout(group)
        self.zoom_label = QLabel("Click frame to inspect region")
        self.zoom_label.setMinimumHeight(180)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_factor = QSpinBox()
        self.zoom_factor.setRange(1, 20)
        self.zoom_factor.setValue(4)
        row = QHBoxLayout()
        row.addWidget(QLabel("Zoom factor"))
        row.addWidget(self.zoom_factor)
        g.addWidget(self.zoom_label)
        g.addLayout(row)
        return group

    def _build_timing_group(self) -> QGroupBox:
        group = QGroupBox("Event timing")
        layout = QFormLayout(group)

        self.start_time_edit = QLineEdit()
        self.end_time_edit = QLineEdit()
        self.start_time_edit.setReadOnly(True)
        self.end_time_edit.setReadOnly(True)

        self.btn_set_start = QPushButton("Set event start time")
        self.btn_set_end = QPushButton("Set event end time")

        layout.addRow(self.btn_set_start, self.start_time_edit)
        layout.addRow(self.btn_set_end, self.end_time_edit)
        return group

    def _build_event_group(self) -> QGroupBox:
        group = QGroupBox("Event")
        form = QFormLayout(group)
        self.event_type_combo = QComboBox()
        self.event_type_combo.setEditable(True)
        self.event_type_combo.addItems(["fighting", "chasing", "mounting", "other"])
        form.addRow("Event type", self.event_type_combo)
        return group

    def _build_role_table_group(self) -> QGroupBox:
        group = QGroupBox("Animal roles")
        layout = QVBoxLayout(group)
        cols = ["name", *ROLE_COLUMNS]
        self.roles_table = QTableWidget(0, len(cols))
        self.roles_table.setHorizontalHeaderLabels(cols)
        self.roles_table.itemChanged.connect(self._on_role_item_changed)
        layout.addWidget(self.roles_table)
        return group

    def _build_notes_group(self) -> QGroupBox:
        group = QGroupBox("Other notes")
        layout = QVBoxLayout(group)
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Type notes for this event...")
        layout.addWidget(self.notes_edit)
        return group

    def _build_submit_row(self) -> QWidget:
        row = QWidget()
        layout = QGridLayout(row)
        self.submit_button = QPushButton("Submit new event")
        layout.addWidget(self.submit_button, 0, 0)
        return row

    def set_animal_names(self, animal_names: list[str]) -> None:
        self.animal_names = animal_names
        self.roles_table.blockSignals(True)
        self.roles_table.setRowCount(len(animal_names))
        for row, name in enumerate(animal_names):
            name_item = QTableWidgetItem(name)
            color = QColor(ANIMAL_COLORS[row % len(ANIMAL_COLORS)])
            name_item.setBackground(color)
            name_item.setFlags(Qt.ItemIsEnabled)
            self.roles_table.setItem(row, 0, name_item)

            for role in ROLE_COLUMNS:
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Unchecked)
                self.roles_table.setItem(row, ROLE_TO_COLUMN[role], item)
        self.roles_table.blockSignals(False)

    def _on_role_item_changed(self, item: QTableWidgetItem) -> None:
        role = self.roles_table.horizontalHeaderItem(item.column()).text()
        if role not in ROLE_COLUMNS:
            return

        if role in {"winner", "loser"} and item.checkState() == Qt.Checked:
            initiator = self.roles_table.item(item.row(), ROLE_TO_COLUMN["initiator"]).checkState() == Qt.Checked
            victim = self.roles_table.item(item.row(), ROLE_TO_COLUMN["victim"]).checkState() == Qt.Checked
            if not (initiator or victim):
                self.roles_table.blockSignals(True)
                item.setCheckState(Qt.Unchecked)
                self.roles_table.blockSignals(False)
                QMessageBox.warning(self, "Invalid role", f"{role} can only be selected for initiator/victim rows.")
                return

        if item.checkState() == Qt.Checked:
            self.pending_role_capture = (item.row(), role)
            self.zoom_label.setText(f"Click video to place {role} for {self.animal_names[item.row()]}")

    def handle_frame_click_for_role(self, x: float, y: float) -> None:
        self._update_zoom_preview(x, y)
        if self.pending_role_capture is None:
            return
        row, role = self.pending_role_capture
        self.pending_role_capture = None
        self.roles_table.item(row, ROLE_TO_COLUMN[role]).setData(Qt.UserRole, (x, y))
        self.zoom_label.setText(f"Captured {role} for {self.animal_names[row]} at ({x:.3f}, {y:.3f})")

    def set_current_frame_image(self, frame: np.ndarray) -> None:
        self.current_frame_image = frame

    def _update_zoom_preview(self, x: float, y: float) -> None:
        if self.current_frame_image is None:
            return
        frame = self.current_frame_image
        h, w, _ = frame.shape
        cx = int(max(0.0, min(1.0, x)) * w)
        cy = int(max(0.0, min(1.0, y)) * h)
        half = max(20, min(w, h) // (2 * self.zoom_factor.value()))
        x1 = max(0, cx - half)
        x2 = min(w, cx + half)
        y1 = max(0, cy - half)
        y2 = min(h, cy + half)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return
        image = QImage(crop.data, crop.shape[1], crop.shape[0], crop.shape[1] * 3, QImage.Format_RGB888).copy()
        pix = QPixmap.fromImage(image).scaled(
            self.zoom_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.zoom_label.setPixmap(pix)

    def set_current_time(self, frame: int, dt_value: str, unix_value: float) -> None:
        self._current_frame = frame
        self._current_dt = dt_value
        self._current_unix = unix_value

    def bind_set_time_actions(self) -> None:
        self.btn_set_start.clicked.connect(self._set_start_time_from_current)
        self.btn_set_end.clicked.connect(self._set_end_time_from_current)
        self.submit_button.clicked.connect(self._submit_event)

    def _set_start_time_from_current(self) -> None:
        if not hasattr(self, "_current_frame"):
            QMessageBox.warning(self, "Time unavailable", "Load a frame first.")
            return
        self.start_frame = self._current_frame
        self.start_datetime = datetime.fromisoformat(self._current_dt) if self._current_dt else None
        self.start_unix = self._current_unix
        self.start_time_edit.setText(f"{self._current_dt} ({self._current_unix:.6f}) frame={self.start_frame}")

    def _set_end_time_from_current(self) -> None:
        if not hasattr(self, "_current_frame"):
            QMessageBox.warning(self, "Time unavailable", "Load a frame first.")
            return
        self.end_frame = self._current_frame
        self.end_datetime = datetime.fromisoformat(self._current_dt) if self._current_dt else None
        self.end_unix = self._current_unix
        self.end_time_edit.setText(f"{self._current_dt} ({self._current_unix:.6f}) frame={self.end_frame}")

    def _submit_event(self) -> None:
        try:
            event = self.build_event()
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
            return
        self.submit_event_requested.emit(event)
        self._reset_for_next_event()

    def build_event(self) -> EventRecord:
        if self.start_frame is None or self.start_datetime is None or self.start_unix is None:
            raise ValueError("Start time is required.")

        event_type = self.event_type_combo.currentText().strip()
        if not event_type:
            raise ValueError("Event type is required.")

        animals: list[AnimalRoleSelection] = []
        initiator_count = 0
        for row, name in enumerate(self.animal_names):
            selection = AnimalRoleSelection(animal_name=name)
            for role in ROLE_COLUMNS:
                item = self.roles_table.item(row, ROLE_TO_COLUMN[role])
                selected = item.checkState() == Qt.Checked
                selection.roles[role] = selected
                if selected and role == "initiator":
                    initiator_count += 1
                selection.role_points[role] = item.data(Qt.UserRole)
            animals.append(selection)

        if initiator_count < 1:
            raise ValueError("At least one initiator must be selected.")

        return EventRecord(
            event_id="",
            event_type=event_type,
            start_frame=self.start_frame,
            end_frame=self.end_frame,
            start_datetime=self.start_datetime,
            end_datetime=self.end_datetime,
            start_unix=self.start_unix,
            end_unix=self.end_unix,
            notes=self.notes_edit.toPlainText().strip(),
            animals=animals,
        )

    def _reset_for_next_event(self) -> None:
        self.start_frame = None
        self.end_frame = None
        self.start_datetime = None
        self.end_datetime = None
        self.start_unix = None
        self.end_unix = None
        self.start_time_edit.clear()
        self.end_time_edit.clear()
        self.notes_edit.clear()
        self.roles_table.blockSignals(True)
        for row in range(self.roles_table.rowCount()):
            for role in ROLE_COLUMNS:
                item = self.roles_table.item(row, ROLE_TO_COLUMN[role])
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole, None)
        self.roles_table.blockSignals(False)

    def populate_from_event(self, event: dict) -> None:
        event_type = str(event.get("event_type", "")).strip()
        if event_type:
            idx = self.event_type_combo.findText(event_type)
            if idx < 0:
                self.event_type_combo.addItem(event_type)
                idx = self.event_type_combo.findText(event_type)
            self.event_type_combo.setCurrentIndex(idx)
        self.notes_edit.setText(str(event.get("notes", "")))

