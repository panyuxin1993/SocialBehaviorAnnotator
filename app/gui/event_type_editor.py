from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.color_utils import fallback_event_type_hex, parse_event_color_hex
from app.config_loader import EventTypeSpec, example_event_types_csv_path, parse_event_types_csv, repo_config_dir


class EventTypeEditor(QDialog):
    """Dialog to edit event types: ``abbr``, ``type``, ``color``, and ``environmental`` (CSV import/export)."""

    def __init__(
        self,
        values: list[EventTypeSpec],
        parent=None,
        default_csv_dir: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit event types")
        self.resize(720, 380)
        self.default_csv_dir = default_csv_dir

        layout = QVBoxLayout(self)

        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["abbr", "type", "color", "environmental"])
        self.table.verticalHeader().setVisible(False)
        n = max(1, len(values))
        self.table.setRowCount(n)
        for row, spec in enumerate(values):
            if len(spec) == 3:
                abbr, type_name, color = spec  # type: ignore[misc]
                environmental = False
            else:
                abbr, type_name, color, environmental = spec
            if row >= self.table.rowCount():
                self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(abbr))
            self.table.setItem(row, 1, QTableWidgetItem(type_name))
            self.table.setItem(row, 2, QTableWidgetItem(color))
            env_item = QTableWidgetItem()
            env_item.setFlags(env_item.flags() | Qt.ItemIsUserCheckable)
            env_item.setCheckState(Qt.Checked if environmental else Qt.Unchecked)
            self.table.setItem(row, 3, env_item)
        layout.addWidget(self.table)

        hint = QLabel(
            "Each row: shorthand abbr, full type name, color (#hex or Qt color name), and whether the "
            "event is environmental (no initiator required; ethogram patch spans all animals). "
            "Empty color uses the built-in default for that type."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons_row = QHBoxLayout()
        add_btn = QPushButton("Add row")
        add_btn.clicked.connect(self._add_row)
        load_defaults_btn = QPushButton("Load defaults…")
        load_defaults_btn.clicked.connect(self._load_shipped_defaults)
        load_btn = QPushButton("Load CSV…")
        load_btn.clicked.connect(self._load_csv)
        save_btn = QPushButton("Export CSV…")
        save_btn.clicked.connect(self._save_csv)
        buttons_row.addWidget(add_btn)
        buttons_row.addWidget(load_defaults_btn)
        buttons_row.addWidget(load_btn)
        buttons_row.addWidget(save_btn)
        buttons_row.addStretch(1)

        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons_row.addWidget(ok_btn)
        buttons_row.addWidget(cancel_btn)

        layout.addLayout(buttons_row)

    def _add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        env_item = QTableWidgetItem()
        env_item.setFlags(env_item.flags() | Qt.ItemIsUserCheckable)
        env_item.setCheckState(Qt.Unchecked)
        self.table.setItem(row, 3, env_item)

    def value_triples(self) -> list[EventTypeSpec]:
        out: list[EventTypeSpec] = []
        for row in range(self.table.rowCount()):
            abbr_item = self.table.item(row, 0)
            type_item = self.table.item(row, 1)
            color_item = self.table.item(row, 2)
            env_item = self.table.item(row, 3)
            type_text = (type_item.text().strip() if type_item else "")
            if not type_text:
                continue
            abbr_text = (abbr_item.text().strip() if abbr_item else "")
            raw_color = (color_item.text().strip() if color_item else "")
            parsed = parse_event_color_hex(raw_color)
            color_hex = parsed if parsed else fallback_event_type_hex(type_text)
            environmental = env_item is not None and env_item.checkState() == Qt.Checked
            out.append((abbr_text, type_text, color_hex, environmental))
        seen: set[str] = set()
        unique: list[EventTypeSpec] = []
        for spec in out:
            key = spec[1].lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(spec)
        return unique

    def _fill_table_from_specs(self, specs: list[EventTypeSpec]) -> None:
        self.table.setRowCount(0)
        for spec in specs:
            if len(spec) == 3:
                abbr, type_name, color_hex = spec  # type: ignore[misc]
                environmental = False
            else:
                abbr, type_name, color_hex, environmental = spec
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(abbr))
            self.table.setItem(row, 1, QTableWidgetItem(type_name))
            self.table.setItem(row, 2, QTableWidgetItem(color_hex))
            env_item = QTableWidgetItem()
            env_item.setFlags(env_item.flags() | Qt.ItemIsUserCheckable)
            env_item.setCheckState(Qt.Checked if environmental else Qt.Unchecked)
            self.table.setItem(row, 3, env_item)

    def _load_shipped_defaults(self) -> None:
        path = example_event_types_csv_path()
        if not path.is_file():
            path = repo_config_dir() / "event_types.csv"
        if not path.is_file():
            return
        try:
            specs = parse_event_types_csv(path)
            if specs:
                self._fill_table_from_specs(specs)
        except OSError:
            return

    def _load_csv(self) -> None:
        start_dir = self.default_csv_dir or str(repo_config_dir())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load event types CSV",
            start_dir,
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            specs = parse_event_types_csv(Path(path))
            if specs:
                self._fill_table_from_specs(specs)
        except OSError:
            return

    def _save_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export event types CSV",
            self.default_csv_dir,
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            import csv

            if not path.lower().endswith(".csv"):
                path = path + ".csv"
            specs = self.value_triples()
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["abbr", "type", "color", "environmental"])
                for abbr, type_name, color_hex, environmental in specs:
                    writer.writerow([abbr, type_name, color_hex, "yes" if environmental else ""])
        except Exception:
            return
