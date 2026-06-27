from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
from PySide6.QtCore import QPoint, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
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
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.models.event import AnimalRoleSelection, EventRecord
from app.models.schema import ROLE_COLUMNS
from app.color_utils import fallback_event_type_hex, parse_event_color_hex
from app.config_loader import EventTypeSpec, environmental_type_keys, load_event_type_specs
from app.gui.colors import ANIMAL_COLORS
from app.gui.kinematics_widget import KinematicsWidget
from app.services.annotation_service import annotation_datetime_to_unix
from app.services.annotation_datetime import annotation_ts_to_unix
from app.services.kinematics_service import resolve_tracking_subject
from app.services.tracking_service import TrackingService


ROLE_TO_COLUMN = {role: idx for idx, role in enumerate(ROLE_COLUMNS)}

class ControlPanel(QWidget):
    request_seek_frame = Signal(int)
    submit_event_requested = Signal(EventRecord)
    kinematics_refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.animal_names: list[str] = []
        self.current_frame_image: Optional[np.ndarray] = None
        self.start_frame: Optional[int] = None
        self.end_frame: Optional[int] = None
        self.start_datetime: Optional[datetime] = None
        self.end_datetime: Optional[datetime] = None
        self.start_unix: Optional[float] = None
        self.end_unix: Optional[float] = None
        self.start_ts_raw: str = ""
        self.end_ts_raw: str = ""
        #: Rows ``(abbr, type, #RRGGBB, environmental)`` aligned with ``event_type_combo`` items.
        self._event_type_specs: list[EventTypeSpec] = []
        self._roles_table_group: QGroupBox | None = None
        self._editing_iloc: Optional[int] = None
        self._loaded_event_id: str = ""
        self._tracking_service: TrackingService | None = None
        self._id_images_dir: Path | None = None
        self._id_image_index: dict[str, Path] = {}
        self._id_photo_thumb_height = 96
        self._id_photo_tile_width = 88
        #: Normalized (0–1) center from the last video click; refreshed on each seek.
        self._zoom_center: Optional[Tuple[float, float]] = None
        self._build_ui()
        self.set_event_type_specs(load_event_type_specs())
        self.kinematics_widget.set_refresh_callback(self._request_kinematics_refresh)

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        if hasattr(self, "id_photos_scroll"):
            self._update_id_photos_container_geometry()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        body = QHBoxLayout()
        body.setSpacing(8)
        inspection = self._build_inspection_tabs()
        inspection.setMinimumWidth(260)
        body.addWidget(inspection, stretch=1)
        annotation = self._build_annotation_section()
        annotation.setMinimumWidth(300)
        body.addWidget(annotation, stretch=1)
        layout.addLayout(body, stretch=1)

        layout.addWidget(self._build_console_group())

    def _build_annotation_section(self) -> QGroupBox:
        group = QGroupBox("Annotation")
        layout = QVBoxLayout(group)
        layout.addWidget(self._build_event_scroll_area())
        return group

    def _build_event_scroll_area(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addWidget(self._build_mode_group())
        content_layout.addWidget(self._build_timing_group())
        content_layout.addWidget(self._build_role_table_group())
        content_layout.addWidget(self._build_notes_group())
        content_layout.addWidget(self._build_submit_row())
        content_layout.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _build_inspection_tabs(self) -> QGroupBox:
        group = QGroupBox("Inspection")
        layout = QVBoxLayout(group)

        self.inspection_tabs = QTabWidget()
        zoom_page = QWidget()
        zoom_layout = QVBoxLayout(zoom_page)
        self.zoom_label = QLabel("Click video to inspect region")
        self.zoom_label.setMinimumHeight(180)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_factor = QSpinBox()
        self.zoom_factor.setRange(1, 20)
        self.zoom_factor.setValue(10)
        self.zoom_factor.valueChanged.connect(lambda _v: self._refresh_zoom_preview())
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("Zoom factor"))
        zoom_row.addWidget(self.zoom_factor)
        self.zoom_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        zoom_layout.addWidget(self.zoom_label, stretch=1)
        zoom_layout.addLayout(zoom_row, stretch=0)

        zoom_layout.addWidget(QLabel("ID photos"), stretch=0)
        zoom_layout.addWidget(self._build_id_photos_strip(), stretch=0)

        self.kinematics_widget = KinematicsWidget()
        self.inspection_tabs.addTab(zoom_page, "Zoom")
        self.inspection_tabs.addTab(self.kinematics_widget, "Kinematics")
        layout.addWidget(self.inspection_tabs)
        return group

    def _build_id_photos_strip(self) -> QScrollArea:
        row_height = self._id_photo_thumb_height + 44
        self.id_photos_scroll = QScrollArea()
        self.id_photos_scroll.setWidgetResizable(False)
        self.id_photos_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.id_photos_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.id_photos_scroll.setFixedHeight(row_height)
        self.id_photos_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.id_photos_container = QWidget()
        self.id_photos_container.setMinimumHeight(row_height - 8)
        self.id_photos_row = QHBoxLayout(self.id_photos_container)
        self.id_photos_row.setContentsMargins(4, 4, 4, 4)
        self.id_photos_row.setSpacing(10)
        self.id_photos_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.id_photos_scroll.setWidget(self.id_photos_container)
        return self.id_photos_scroll

    def set_tracking_service(self, tracking: TrackingService | None) -> None:
        self._tracking_service = tracking if tracking is not None and tracking.is_loaded else None
        self.kinematics_widget.set_tracking(self._tracking_service)
        self._refresh_zoom_preview()

    def set_id_images_dir(self, path: str | Path | None) -> None:
        if path is None or not str(path).strip():
            self._id_images_dir = None
            self._id_image_index = {}
        else:
            p = Path(path).expanduser()
            if p.is_dir():
                self._id_images_dir = p
                self._id_image_index = self._build_id_image_index(p)
            else:
                self._id_images_dir = None
                self._id_image_index = {}
                self.append_log(f"ID images folder not found: {p}")
        self._schedule_id_demo_refresh()

    def _request_kinematics_refresh(self) -> None:
        self.kinematics_refresh_requested.emit()

    def refresh_kinematics(self) -> None:
        rat_a, rat_b = self._default_kinematics_rats()
        self.kinematics_widget.set_event_timing(
            self.start_unix,
            self.end_unix,
            default_rat_a=rat_a,
            default_rat_b=rat_b,
            event_type=self._current_event_type_label(),
        )
        self.kinematics_widget.apply_role_defaults(rat_a, rat_b)
        self.kinematics_widget.set_tracking(self._tracking_service)
        self.kinematics_widget.refresh_plot()
        if hasattr(self, "_current_unix"):
            self.update_kinematics_playhead(self._current_unix)

    def update_kinematics_playhead(self, current_unix: float) -> None:
        self.kinematics_widget.set_playhead_unix(current_unix)

    def _current_event_type_label(self) -> str:
        text = self.event_type_combo.currentText().strip()
        if not text:
            return ""
        return self.display_type_for_combo(text)

    def _default_kinematics_rats(self) -> tuple[str, str]:
        initiator = self._first_animal_with_role("initiator")
        victim = self._first_animal_with_role("victim")
        return initiator, victim

    def _first_animal_with_role(self, role: str) -> str:
        col = ROLE_TO_COLUMN.get(role)
        if col is None:
            return ""
        for row, name in enumerate(self.animal_names):
            item = self.roles_table.item(row, col)
            if item is not None and item.checkState() == Qt.Checked:
                return name
        return ""

    def _emit_kinematics_refresh(self) -> None:
        self.kinematics_refresh_requested.emit()

    def _build_mode_group(self) -> QGroupBox:
        group = QGroupBox("Event mode")
        row = QHBoxLayout(group)
        self._mode_button_group = QButtonGroup(self)
        self.btn_mode_create = QPushButton("Create new event")
        self.btn_mode_modify = QPushButton("Modify current event")
        self.btn_mode_create.setCheckable(True)
        self.btn_mode_modify.setCheckable(True)
        self._mode_button_group.addButton(self.btn_mode_create)
        self._mode_button_group.addButton(self.btn_mode_modify)
        self.btn_mode_create.setChecked(True)
        self.btn_mode_create.toggled.connect(self._on_mode_create_toggled)
        row.addWidget(self.btn_mode_create)
        row.addWidget(self.btn_mode_modify)
        row.addStretch(1)
        return group

    def _on_mode_create_toggled(self, checked: bool) -> None:
        if checked:
            self._editing_iloc = None
            self._loaded_event_id = ""
            self._reset_for_next_event()

    def _build_timing_group(self) -> QGroupBox:
        group = QGroupBox("Event Info")
        layout = QFormLayout(group)

        self.event_type_combo = QComboBox()
        self.event_type_combo.setEditable(True)
        self.event_type_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.event_type_combo.view().setMinimumWidth(280)
        self.event_type_combo.currentTextChanged.connect(self._emit_kinematics_refresh)
        self.event_type_combo.currentTextChanged.connect(self._update_role_table_hint)
        layout.addRow("Event type", self.event_type_combo)

        self.start_time_edit = QLineEdit()
        self.end_time_edit = QLineEdit()
        self.start_time_edit.setReadOnly(True)
        self.end_time_edit.setReadOnly(True)

        self.btn_set_start = QPushButton("Set event start time")
        self.btn_set_end = QPushButton("Set event end time")

        layout.addRow(self.btn_set_start, self.start_time_edit)
        layout.addRow(self.btn_set_end, self.end_time_edit)

        self.event_location_combo = QComboBox()
        self.event_location_combo.addItems(["left", "right", "door"])
        self.event_location_combo.setToolTip(
            "Arena / site for this event (saved in the annotation table ``location`` column)."
        )
        layout.addRow("Event location", self.event_location_combo)

        return group

    def _sync_event_type_specs_from_combo(self) -> None:
        self._event_type_specs = []
        for i in range(self.event_type_combo.count()):
            t = self.event_type_combo.itemText(i).strip()
            if not t:
                continue
            self._event_type_specs.append(("", t, fallback_event_type_hex(t), False))

    def event_type_specs(self) -> list[EventTypeSpec]:
        return list(self._event_type_specs)

    def environmental_type_keys(self) -> set[str]:
        return environmental_type_keys(self._event_type_specs)

    def event_type_color_map(self) -> dict[str, str]:
        """Keys: full ``type`` and non-empty ``abbr`` (lowercase) — annotation ``type`` may store either."""
        m: dict[str, str] = {}
        for abbr, t, hx, _environmental in self._event_type_specs:
            m[t.lower()] = hx
            a = (abbr or "").strip()
            if a:
                m[a.lower()] = hx
        return m

    def event_type_legend_label_map(self) -> dict[str, str]:
        """Map stored ``type`` cell token → preferred legend text (full type name)."""
        m: dict[str, str] = {}
        for abbr, t, _hx, _environmental in self._event_type_specs:
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
        for abbr, full, _hx, _environmental in self._event_type_specs:
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
        for abbr, full, _hx, _environmental in self._event_type_specs:
            if sl == full.lower():
                return abbr.strip() if (abbr or "").strip() else full
            if abbr and sl == abbr.strip().lower():
                return abbr.strip()
        return s

    def _current_event_type_environmental(self) -> bool:
        display_type = self.event_type_combo.currentText().strip()
        if not display_type:
            return False
        sl = display_type.casefold()
        for abbr, full, _hx, environmental in self._event_type_specs:
            if sl == full.casefold() or (abbr and sl == abbr.strip().casefold()):
                return environmental
        return False

    def _update_role_table_hint(self, _text: str = "") -> None:
        if self._roles_table_group is None:
            return
        if self._current_event_type_environmental():
            self._roles_table_group.setTitle("Animal roles (optional — environmental event)")
        else:
            self._roles_table_group.setTitle("Animal roles")

    def _event_type_combo_index(self, label: str) -> int:
        target = label.strip().casefold()
        for i in range(self.event_type_combo.count()):
            if self.event_type_combo.itemText(i).strip().casefold() == target:
                return i
        return -1

    def set_event_type_specs(self, specs: list[EventTypeSpec]) -> None:
        cleaned: list[EventTypeSpec] = []
        seen: set[str] = set()
        for spec in specs:
            if len(spec) == 3:
                abbr, t, c = spec  # type: ignore[misc]
                environmental = False
            else:
                abbr, t, c, environmental = spec
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
            cleaned.append((abbr.strip() if abbr else "", t, hx, bool(environmental)))
        if not cleaned:
            return
        self._event_type_specs = cleaned
        self.event_type_combo.blockSignals(True)
        self.event_type_combo.clear()
        for _abbr, type_name, _hx, _environmental in cleaned:
            self.event_type_combo.addItem(type_name)
        self.event_type_combo.blockSignals(False)
        self._update_role_table_hint()

    def _build_role_table_group(self) -> QGroupBox:
        group = QGroupBox("Animal roles")
        self._roles_table_group = group
        layout = QHBoxLayout(group)

        # Frozen first column: separate table for names (always visible).
        self.name_table = QTableWidget(0, 1)
        self.name_table.setHorizontalHeaderLabels(["name"])
        self.name_table.verticalHeader().setVisible(False)
        self.name_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.name_table.setFocusPolicy(Qt.NoFocus)
        self.name_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.name_table.setSelectionBehavior(QAbstractItemView.SelectRows)
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
        self.submit_button = QPushButton("Submit event")
        layout.addWidget(self.submit_button, 0, 0)
        return row

    def _build_console_group(self) -> QGroupBox:
        group = QGroupBox("Console")
        g = QVBoxLayout(group)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("Status and log messages appear here…")
        self.console.setMinimumHeight(100)
        self.console.setMaximumHeight(200)
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
        self._select_default_animal_row()
        self._schedule_id_demo_refresh()
        self._emit_kinematics_refresh()

    def _schedule_id_demo_refresh(self) -> None:
        QTimer.singleShot(0, self._refresh_id_demo)

    def _select_default_animal_row(self) -> None:
        if not self.animal_names:
            return
        for role in ("initiator", "victim"):
            row = self._row_for_animal_with_role(role)
            if row is not None:
                self.name_table.selectRow(row)
                return
        self.name_table.selectRow(0)

    def _row_for_animal_with_role(self, role: str) -> int | None:
        col = ROLE_TO_COLUMN.get(role)
        if col is None:
            return None
        for row in range(self.roles_table.rowCount()):
            item = self.roles_table.item(row, col)
            if item is not None and item.checkState() == Qt.Checked:
                return row
        return None

    @staticmethod
    def _id_image_lookup_keys(animal_name: str) -> list[str]:
        base = (animal_name or "").strip()
        if not base:
            return []
        keys = [base]
        lowered = base.lower()
        for suffix in ("_center", "_area", "_perimeter"):
            if lowered.endswith(suffix):
                keys.append(base[: -len(suffix)])
        return list(dict.fromkeys(keys))

    @staticmethod
    def _build_id_image_index(directory: Path) -> dict[str, Path]:
        index: dict[str, Path] = {}
        allowed = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
        try:
            entries = list(directory.iterdir())
        except OSError:
            return index
        for path in entries:
            if not path.is_file():
                continue
            if path.suffix.lower() not in allowed:
                continue
            index[path.stem.casefold()] = path
        return index

    def _find_id_image(self, animal_name: str) -> Path | None:
        if not self._id_image_index:
            return None
        for key in self._id_image_lookup_keys(animal_name):
            hit = self._id_image_index.get(key.casefold())
            if hit is not None:
                return hit
        base = self._id_image_lookup_keys(animal_name)[0].casefold()
        for stem, path in self._id_image_index.items():
            if stem == base or stem in base or base in stem:
                return path
        return None

    @staticmethod
    def _load_id_pixmap(image_path: Path, thumb_height: int) -> QPixmap | None:
        reader = QImageReader(str(image_path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            return None
        pix = QPixmap.fromImage(image)
        if pix.isNull():
            return None
        return pix.scaledToHeight(thumb_height, Qt.TransformationMode.SmoothTransformation)

    def _clear_id_photos_row(self) -> None:
        while self.id_photos_row.count():
            item = self.id_photos_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_id_photo_tile(self, name: str, row: int) -> QWidget:
        tile = QWidget()
        tile.setFixedWidth(self._id_photo_tile_width)
        col = QVBoxLayout(tile)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        image_label = QLabel()
        image_label.setFixedSize(self._id_photo_tile_width, self._id_photo_thumb_height)
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setStyleSheet("border: 1px solid palette(mid); border-radius: 4px;")

        name_label = QLabel(name)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setFixedWidth(self._id_photo_tile_width)
        color = QColor(ANIMAL_COLORS[row % len(ANIMAL_COLORS)])
        name_label.setStyleSheet(
            f"background-color: {color.name()}; color: #202020; padding: 2px 4px; border-radius: 3px;"
        )

        if self._id_images_dir is None:
            image_label.setText("No folder")
        else:
            image_path = self._find_id_image(name)
            if image_path is None:
                image_label.setText("No image")
            else:
                scaled = self._load_id_pixmap(image_path, self._id_photo_thumb_height)
                if scaled is None:
                    detail = QImageReader(str(image_path)).errorString()
                    image_label.setText("Load error")
                    image_label.setToolTip(f"{image_path.name}: {detail}")
                else:
                    image_label.setPixmap(scaled)
                    image_label.setToolTip(str(image_path))

        col.addWidget(image_label)
        col.addWidget(name_label)
        return tile

    def _update_id_photos_container_geometry(self) -> None:
        row_height = self._id_photo_thumb_height + 44
        self.id_photos_container.setMinimumHeight(row_height - 8)
        total_width = 8
        for index in range(self.id_photos_row.count()):
            item = self.id_photos_row.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                total_width += widget.sizeHint().width() or self._id_photo_tile_width
        if self.id_photos_row.count() > 1:
            total_width += self.id_photos_row.spacing() * (self.id_photos_row.count() - 1)
        viewport_width = self.id_photos_scroll.viewport().width()
        self.id_photos_container.setMinimumWidth(max(total_width, viewport_width))
        self.id_photos_container.adjustSize()
        self.id_photos_scroll.updateGeometry()

    def _refresh_id_demo(self) -> None:
        self._clear_id_photos_row()

        if not self.animal_names:
            placeholder = QLabel("No animals loaded")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setMinimumWidth(self.id_photos_scroll.viewport().width())
            self.id_photos_row.addWidget(placeholder)
            self._update_id_photos_container_geometry()
            return

        loaded = 0
        missing: list[str] = []
        for row, name in enumerate(self.animal_names):
            tile = self._make_id_photo_tile(name, row)
            self.id_photos_row.addWidget(tile)
            if self._id_images_dir is not None:
                if self._find_id_image(name) is not None:
                    loaded += 1
                else:
                    missing.append(name)

        self._update_id_photos_container_geometry()

        if self._id_images_dir is None:
            self.append_log("ID photos: no folder set (Annotation → Animals…)")
            return

        msg = (
            f"ID photos: {loaded}/{len(self.animal_names)} matched in "
            f"{self._id_images_dir} ({len(self._id_image_index)} image files)"
        )
        if loaded == 0 and missing:
            sample = ", ".join(missing[:4])
            if len(missing) > 4:
                sample += ", …"
            msg += f"; no file for: {sample}"
        self.append_log(msg)

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
            self.name_table.selectRow(item.row())
        if role in ("initiator", "victim"):
            self._emit_kinematics_refresh()
            if self._zoom_center is None:
                self._refresh_zoom_preview()

    def handle_frame_click_for_role(self, x: float, y: float) -> None:
        """Update zoom preview from a video click (optional inspection only)."""
        self._zoom_center = (x, y)
        self._update_zoom_preview(x, y)

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
        pix = QPixmap.fromImage(image)
        self._paint_tracking_on_zoom(pix, x1, y1, x2 - x1, y2 - y1)
        target_size = self.zoom_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        pix = pix.scaled(
            target_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.zoom_label.setPixmap(pix)

    def _paint_tracking_on_zoom(
        self, pixmap: QPixmap, crop_x1: int, crop_y1: int, crop_w: int, crop_h: int
    ) -> None:
        if self._tracking_service is None or not self._tracking_service.is_loaded:
            return
        if not hasattr(self, "_current_unix"):
            return
        poses = self._tracking_service.poses_for_unix(float(self._current_unix))
        if not poses:
            return

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        font.setPointSize(max(7, min(11, max(1, pixmap.height()) // 36)))
        font.setBold(True)
        painter.setFont(font)
        radius = max(4, min(10, max(1, pixmap.height()) // 18))
        label_offset = radius + 4
        subjects = self._tracking_service.subjects

        for subject_id, (px, py) in sorted(poses.items()):
            lx = int(px) - crop_x1
            ly = int(py) - crop_y1
            margin = radius + 40
            if lx < -margin or ly < -margin or lx > crop_w + margin or ly > crop_h + margin:
                continue
            lx = int(max(0.0, min(float(crop_w - 1), lx)))
            ly = int(max(0.0, min(float(crop_h - 1), ly)))
            color = self._marker_color_for_subject(subject_id, subjects)
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#202020"), 2))
            painter.drawEllipse(QPoint(lx, ly), radius, radius)
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            painter.drawText(lx + label_offset, ly - label_offset, self._label_for_subject(subject_id, subjects))
        painter.end()

    def _label_for_subject(self, subject_id: str, subjects: list[str]) -> str:
        for name in self.animal_names:
            if resolve_tracking_subject(name, subjects) == subject_id:
                return name
        return subject_id.replace("_center", "")

    def _marker_color_for_subject(self, subject_id: str, subjects: list[str]) -> QColor:
        for row, name in enumerate(self.animal_names):
            if resolve_tracking_subject(name, subjects) == subject_id:
                return QColor(ANIMAL_COLORS[row % len(ANIMAL_COLORS)])
        try:
            idx = subjects.index(subject_id)
        except ValueError:
            idx = hash(subject_id) % len(ANIMAL_COLORS)
        return QColor(ANIMAL_COLORS[idx % len(ANIMAL_COLORS)])

    def set_current_time(self, frame: int, dt_value: str, unix_value: float, ts_raw: str = "") -> None:
        self._current_frame = frame
        self._current_dt = dt_value
        self._current_unix = unix_value
        self._current_ts_raw = ts_raw
        self._refresh_zoom_preview()

    def _refresh_zoom_preview(self) -> None:
        center = self._zoom_center or self._tracking_zoom_center()
        if center is None:
            return
        self._update_zoom_preview(center[0], center[1])

    def _tracking_zoom_center(self) -> Optional[Tuple[float, float]]:
        if self._tracking_service is None or not self._tracking_service.is_loaded:
            return None
        if self.current_frame_image is None or not hasattr(self, "_current_unix"):
            return None
        poses = self._tracking_service.poses_for_unix(float(self._current_unix))
        if not poses:
            return None
        subjects = self._tracking_service.subjects
        for name in (self._first_animal_with_role("initiator"), self._first_animal_with_role("victim")):
            if not name:
                continue
            sid = resolve_tracking_subject(name, subjects)
            if sid and sid in poses:
                return self._pixel_to_normalized(*poses[sid])
        sid = next(iter(sorted(poses.keys())))
        return self._pixel_to_normalized(*poses[sid])

    def _pixel_to_normalized(self, px: float, py: float) -> Tuple[float, float]:
        if self.current_frame_image is None:
            return 0.5, 0.5
        h, w, _ = self.current_frame_image.shape
        if w <= 0 or h <= 0:
            return 0.5, 0.5
        return (
            max(0.0, min(1.0, px / w)),
            max(0.0, min(1.0, py / h)),
        )

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
        self.start_ts_raw = getattr(self, "_current_ts_raw", "") or ""
        self.start_time_edit.setText(
            f"{self._current_dt} ({self._current_unix:.6f}) frame={self.start_frame}"
        )
        self._emit_kinematics_refresh()

    def _set_end_time_from_current(self) -> None:
        if not hasattr(self, "_current_frame"):
            QMessageBox.warning(self, "Time unavailable", "Load a frame first.")
            return
        self.end_frame = self._current_frame
        self.end_datetime = datetime.fromisoformat(self._current_dt) if self._current_dt else None
        self.end_unix = self._current_unix
        self.end_ts_raw = getattr(self, "_current_ts_raw", "") or ""
        self.end_time_edit.setText(
            f"{self._current_dt} ({self._current_unix:.6f}) frame={self.end_frame}"
        )
        self._emit_kinematics_refresh()

    def _submit_event(self) -> None:
        if self.btn_mode_modify.isChecked() and self._editing_iloc is None:
            QMessageBox.warning(
                self,
                "No event loaded",
                "Jump to an event in the navigator first, or choose Create new event.",
            )
            return
        try:
            event = self.build_event()
        except ValueError as exc:
            QMessageBox.warning(self, "Validation", str(exc))
            return
        self.submit_event_requested.emit(event)

    def build_event(self) -> EventRecord:
        if self.start_frame is None or self.start_datetime is None or self.start_unix is None:
            raise ValueError("Start time is required.")

        display_type = self.event_type_combo.currentText().strip()
        if not display_type:
            raise ValueError("Event type is required.")
        event_type = self.stored_type_for_submit(display_type)

        editing_iloc = self._editing_iloc if self.btn_mode_modify.isChecked() else None
        event_id = (self._loaded_event_id or "").strip() if editing_iloc is not None else ""

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
            animals.append(selection)

        if initiator_count < 1 and not self._current_event_type_environmental():
            raise ValueError("At least one initiator must be selected for this event type.")

        return EventRecord(
            event_id=event_id,
            event_type=event_type,
            start_frame=self.start_frame,
            end_frame=self.end_frame,
            start_datetime=self.start_datetime,
            end_datetime=self.end_datetime,
            start_unix=self.start_unix,
            end_unix=self.end_unix,
            start_ts_raw=self.start_ts_raw,
            end_ts_raw=self.end_ts_raw,
            event_location=self.event_location_combo.currentText().strip() or "left",
            notes=self.notes_edit.toPlainText().strip(),
            animals=animals,
            editing_iloc=editing_iloc,
        )

    def reset_new_event_form(self) -> None:
        """Clear fields after a new event is saved (keeps Create mode selected)."""
        self._reset_for_next_event()

    def _reset_for_next_event(self) -> None:
        self._editing_iloc = None
        self._loaded_event_id = ""
        self.start_frame = None
        self.end_frame = None
        self.start_datetime = None
        self.end_datetime = None
        self.start_unix = None
        self.end_unix = None
        self.start_ts_raw = ""
        self.end_ts_raw = ""
        self.start_time_edit.clear()
        self.end_time_edit.clear()
        self.notes_edit.clear()
        self.event_location_combo.setCurrentIndex(0)
        self.roles_table.blockSignals(True)
        for row in range(self.roles_table.rowCount()):
            for role in ROLE_COLUMNS:
                item = self.roles_table.item(row, ROLE_TO_COLUMN[role])
                item.setCheckState(Qt.Unchecked)
        self.roles_table.blockSignals(False)
        self._emit_kinematics_refresh()

    @staticmethod
    def _event_field_str(event: dict, key: str) -> str:
        v = event.get(key)
        if v is None:
            return ""
        s = str(v).strip()
        return "" if s.lower() in ("", "nan", "none") else s

    def _set_event_location_combo(self, value: str) -> None:
        v = (value or "").strip().lower()
        for i in range(self.event_location_combo.count()):
            if self.event_location_combo.itemText(i).strip().lower() == v:
                self.event_location_combo.setCurrentIndex(i)
                return
        self.event_location_combo.setCurrentIndex(0)

    def _fill_timing_from_event(self, event: dict, seek_frame: Optional[int]) -> None:
        ny = ZoneInfo("America/New_York")
        date_v = self._event_field_str(event, "date")
        st_v = self._event_field_str(event, "start_time")
        et_v = self._event_field_str(event, "end_time")

        self.start_frame = seek_frame

        self.start_ts_raw = self._event_field_str(event, "ts_start")
        self.end_ts_raw = self._event_field_str(event, "ts_end")

        u_s = annotation_ts_to_unix(self.start_ts_raw) if self.start_ts_raw else None
        if u_s is None:
            u_s = annotation_datetime_to_unix(date_v, st_v) if date_v else annotation_datetime_to_unix(st_v)
        if u_s is not None:
            self.start_unix = float(u_s)
            self.start_datetime = datetime.fromtimestamp(self.start_unix, tz=ny).replace(tzinfo=None)
            dt_display = f"{date_v} {st_v}".strip() if date_v else st_v
            self.start_time_edit.setText(
                f"{dt_display} ({self.start_unix:.6f}) frame={self.start_frame}"
            )
        else:
            self.start_datetime = None
            self.start_unix = None
            self.start_time_edit.setText(st_v)

        if et_v or self.end_ts_raw:
            u_e = annotation_ts_to_unix(self.end_ts_raw) if self.end_ts_raw else None
            if u_e is None:
                u_e = annotation_datetime_to_unix(date_v, et_v) if date_v else annotation_datetime_to_unix(et_v)
            if u_e is not None:
                self.end_unix = float(u_e)
                self.end_datetime = datetime.fromtimestamp(self.end_unix, tz=ny).replace(tzinfo=None)
                dt_e = f"{date_v} {et_v}".strip() if date_v else et_v
                self.end_frame = None
                self.end_time_edit.setText(f"{dt_e} ({self.end_unix:.6f})")
            else:
                self.end_datetime = None
                self.end_unix = None
                self.end_frame = None
                self.end_time_edit.setText(et_v)
        else:
            self.end_datetime = None
            self.end_unix = None
            self.end_frame = None
            self.end_time_edit.clear()
        self._emit_kinematics_refresh()

    def _apply_role_columns_from_event(self, event: dict) -> None:
        self.roles_table.blockSignals(True)
        try:
            for row in range(self.roles_table.rowCount()):
                for role in ROLE_COLUMNS:
                    item = self.roles_table.item(row, ROLE_TO_COLUMN[role])
                    if item is not None:
                        item.setCheckState(Qt.Unchecked)
            for role in ROLE_COLUMNS:
                raw = self._event_field_str(event, role)
                if not raw:
                    continue
                for name in (x.strip() for x in raw.split(",") if x.strip()):
                    try:
                        r = self.animal_names.index(name)
                    except ValueError:
                        continue
                    item = self.roles_table.item(r, ROLE_TO_COLUMN[role])
                    if item is not None:
                        item.setCheckState(Qt.Checked)
        finally:
            self.roles_table.blockSignals(False)

    def populate_from_event(
        self, event: dict, iloc: Optional[int] = None, seek_frame: Optional[int] = None
    ) -> None:
        self.btn_mode_modify.blockSignals(True)
        self.btn_mode_modify.setChecked(True)
        self.btn_mode_modify.blockSignals(False)

        self._editing_iloc = iloc
        self._loaded_event_id = self._event_field_str(event, "event_id")

        self._fill_timing_from_event(event, seek_frame)

        event_type = str(event.get("type", "")).strip()
        if event_type:
            combo_label = self.display_type_for_combo(event_type)
            idx = self._event_type_combo_index(combo_label)
            if idx < 0:
                self.event_type_combo.addItem(combo_label)
                self._event_type_specs.append(("", event_type, fallback_event_type_hex(event_type), False))
                idx = self._event_type_combo_index(combo_label)
            self.event_type_combo.setCurrentIndex(idx)
        self._update_role_table_hint()
        self.notes_edit.setText(str(event.get("other_notes", "")))

        self._apply_role_columns_from_event(event)

        loc_raw = self._event_field_str(event, "location")
        if loc_raw:
            self._set_event_location_combo(loc_raw)
        else:
            self.event_location_combo.setCurrentIndex(0)

        self._select_default_animal_row()
        self._emit_kinematics_refresh()

