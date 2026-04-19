from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.event import AnimalRoleSelection, EventRecord
from app.models.schema import ROLE_COLUMNS
from app.gui.ethogram_widget import fallback_event_type_hex, parse_event_color_hex


ROLE_TO_COLUMN = {role: idx for idx, role in enumerate(ROLE_COLUMNS)}

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
        #: Rows ``(abbr, type, #RRGGBB)`` aligned with ``event_type_combo`` items (in order).
        self._event_type_specs: list[tuple[str, str, str]] = []
        self._build_ui()
        self._sync_event_type_specs_from_combo()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_zoom_group())
        layout.addWidget(self._build_event_scroll_area(), stretch=1)
        layout.addWidget(self._build_console_group())

    def _build_event_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addWidget(self._build_timing_group())
        content_layout.addWidget(self._build_event_group())
        content_layout.addWidget(self._build_role_table_group())
        content_layout.addWidget(self._build_notes_group())
        content_layout.addWidget(self._build_submit_row())
        content_layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_zoom_group(self) -> QGroupBox:
        group = QGroupBox("Zoom view")
        g = QVBoxLayout(group)
        self.zoom_label = QLabel("Click frame to inspect region")
        self.zoom_label.setMinimumHeight(180)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_factor = QSpinBox()
        self.zoom_factor.setRange(1, 20)
        self.zoom_factor.setValue(10)
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
        self.event_type_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.event_type_combo.view().setMinimumWidth(280)
        self.event_type_combo.addItems(["fight", "chase", "push", "defend", "rob"])
        form.addRow("Event type", self.event_type_combo)
        return group

    def _sync_event_type_specs_from_combo(self) -> None:
        self._event_type_specs = []
        for i in range(self.event_type_combo.count()):
            t = self.event_type_combo.itemText(i).strip()
            if not t:
                continue
            self._event_type_specs.append(("", t, fallback_event_type_hex(t)))

    def event_type_specs(self) -> list[tuple[str, str, str]]:
        return list(self._event_type_specs)

    def event_type_color_map(self) -> dict[str, str]:
        """Keys: full ``type`` and non-empty ``abbr`` (lowercase) — annotation ``type`` may store either."""
        m: dict[str, str] = {}
        for abbr, t, hx in self._event_type_specs:
            m[t.lower()] = hx
            a = (abbr or "").strip()
            if a:
                m[a.lower()] = hx
        return m

    def event_type_legend_label_map(self) -> dict[str, str]:
        """Map stored ``type`` cell token → preferred legend text (full type name)."""
        m: dict[str, str] = {}
        for abbr, t, _hx in self._event_type_specs:
            m[t.lower()] = t
            a = (abbr or "").strip()
            if a:
                m[a.lower()] = t
        return m

    def display_type_for_combo(self, stored_type: str) -> str:
        """Combo lists full names; tables may store abbreviation in ``type``."""
        s = (stored_type or "").strip()
        if not s:
            return ""
        sl = s.lower()
        for abbr, full, _hx in self._event_type_specs:
            if sl == full.lower():
                return full
            if abbr and sl == abbr.strip().lower():
                return full
        return s

    def stored_type_for_submit(self, combo_text: str) -> str:
        """Persist abbreviation in ``type`` when the row defines one, else the full type name."""
        s = (combo_text or "").strip()
        if not s:
            return ""
        sl = s.lower()
        for abbr, full, _hx in self._event_type_specs:
            if sl == full.lower():
                return abbr.strip() if (abbr or "").strip() else full
            if abbr and sl == abbr.strip().lower():
                return abbr.strip()
        return s

    def _event_type_combo_index(self, label: str) -> int:
        target = label.strip().casefold()
        for i in range(self.event_type_combo.count()):
            if self.event_type_combo.itemText(i).strip().casefold() == target:
                return i
        return -1

    def set_event_type_specs(self, specs: list[tuple[str, str, str]]) -> None:
        cleaned: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for abbr, t, c in specs:
            t = (t or "").strip()
            if not t or t.lower() == "nan":
                continue
            kl = t.lower()
            if kl in seen:
                continue
            seen.add(kl)
            hx = parse_event_color_hex(str(c)) if c else None
            if not hx:
                hx = fallback_event_type_hex(t)
            cleaned.append((abbr.strip() if abbr else "", t, hx))
        if not cleaned:
            return
        self._event_type_specs = cleaned
        self.event_type_combo.blockSignals(True)
        self.event_type_combo.clear()
        for _abbr, type_name, _hx in cleaned:
            self.event_type_combo.addItem(type_name)
        self.event_type_combo.blockSignals(False)

    def _build_role_table_group(self) -> QGroupBox:
        group = QGroupBox("Animal roles")
        layout = QHBoxLayout(group)

        # Frozen first column: separate table for names (always visible).
        self.name_table = QTableWidget(0, 1)
        self.name_table.setHorizontalHeaderLabels(["name"])
        self.name_table.verticalHeader().setVisible(False)
        self.name_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.name_table.setFocusPolicy(Qt.NoFocus)
        self.name_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.name_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.name_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.name_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)

        # Scrollable role columns.
        self.roles_table = QTableWidget(0, len(ROLE_COLUMNS))
        self.roles_table.setHorizontalHeaderLabels(ROLE_COLUMNS)
        self.roles_table.setMinimumHeight(320)
        self.roles_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.roles_table.horizontalHeader().setStretchLastSection(False)
        self.roles_table.verticalHeader().setVisible(False)
        self.roles_table.itemChanged.connect(self._on_role_item_changed)
        self.roles_table.verticalScrollBar().valueChanged.connect(self.name_table.verticalScrollBar().setValue)
        self.name_table.verticalScrollBar().valueChanged.connect(self.roles_table.verticalScrollBar().setValue)

        layout.addWidget(self.name_table)
        layout.addWidget(self.roles_table, stretch=1)
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

    def _build_console_group(self) -> QGroupBox:
        group = QGroupBox("Console")
        g = QVBoxLayout(group)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("Status and log messages appear here…")
        self.console.setMinimumHeight(120)
        self.console.setMaximumHeight(220)
        font = QFont("Menlo")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        self.console.setFont(font)
        g.addWidget(self.console)
        return group

    def append_log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self.console.appendPlainText(line)

    def set_animal_names(self, animal_names: list[str]) -> None:
        self.animal_names = animal_names
        self.name_table.blockSignals(True)
        self.roles_table.blockSignals(True)
        self.name_table.setRowCount(len(animal_names))
        self.roles_table.setRowCount(len(animal_names))
        for row, name in enumerate(animal_names):
            name_item = QTableWidgetItem(name)
            color = QColor(ANIMAL_COLORS[row % len(ANIMAL_COLORS)])
            name_item.setBackground(color)
            name_item.setForeground(QColor("#202020"))
            name_item.setFlags(Qt.ItemIsEnabled)
            self.name_table.setItem(row, 0, name_item)

            for role in ROLE_COLUMNS:
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Unchecked)
                self.roles_table.setItem(row, ROLE_TO_COLUMN[role], item)
        self.name_table.resizeColumnToContents(0)
        fitted_width = self.name_table.columnWidth(0) + 8
        self.name_table.setFixedWidth(max(60, fitted_width))
        self.name_table.blockSignals(False)
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
        # Numpy views from slicing are often non-contiguous; QImage requires contiguous buffer.
        crop_contiguous = np.ascontiguousarray(crop)
        bytes_per_line = int(crop_contiguous.strides[0])
        image = QImage(
            crop_contiguous.data,
            int(crop_contiguous.shape[1]),
            int(crop_contiguous.shape[0]),
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()
        target_size = self.zoom_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        pix = QPixmap.fromImage(image).scaled(
            target_size,
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

        display_type = self.event_type_combo.currentText().strip()
        if not display_type:
            raise ValueError("Event type is required.")
        event_type = self.stored_type_for_submit(display_type)

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
        event_type = str(event.get("type", "")).strip()
        if event_type:
            combo_label = self.display_type_for_combo(event_type)
            idx = self._event_type_combo_index(combo_label)
            if idx < 0:
                self.event_type_combo.addItem(combo_label)
                self._event_type_specs.append(("", event_type, fallback_event_type_hex(event_type)))
                idx = self._event_type_combo_index(combo_label)
            self.event_type_combo.setCurrentIndex(idx)
        self.notes_edit.setText(str(event.get("other_notes", "")))

