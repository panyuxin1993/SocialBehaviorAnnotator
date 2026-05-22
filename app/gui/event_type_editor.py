from __future__ import annotations

from pathlib import Path

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
from app.config_loader import example_event_types_csv_path, parse_event_types_csv, repo_config_dir


class EventTypeEditor(QDialog):
    """Dialog to edit event types: ``abbr``, ``type``, and ``color`` (CSV import/export)."""

    def __init__(
        self,
        values: list[tuple[str, str, str]],
        parent=None,
        default_csv_dir: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit event types")
        self.resize(640, 380)
        self.default_csv_dir = default_csv_dir

        layout = QVBoxLayout(self)

        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["abbr", "type", "color"])
        self.table.verticalHeader().setVisible(False)
        n = max(1, len(values))
        self.table.setRowCount(n)
        for row, triple in enumerate(values):
            abbr, type_name, color = triple
            if row >= self.table.rowCount():
                self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(abbr))
            self.table.setItem(row, 1, QTableWidgetItem(type_name))
            self.table.setItem(row, 2, QTableWidgetItem(color))
        layout.addWidget(self.table)

        hint = QLabel(
            "Each row: shorthand abbr, full type name, and color (#hex or Qt color name). "
            "Empty color uses the built-in default for that type. Colors drive the ethogram."
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

    def value_triples(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for row in range(self.table.rowCount()):
            abbr_item = self.table.item(row, 0)
            type_item = self.table.item(row, 1)
            color_item = self.table.item(row, 2)
            type_text = (type_item.text().strip() if type_item else "")
            if not type_text:
                continue
            abbr_text = (abbr_item.text().strip() if abbr_item else "")
            raw_color = (color_item.text().strip() if color_item else "")
            parsed = parse_event_color_hex(raw_color)
            color_hex = parsed if parsed else fallback_event_type_hex(type_text)
            out.append((abbr_text, type_text, color_hex))
        seen: set[str] = set()
        unique: list[tuple[str, str, str]] = []
        for triple in out:
            key = triple[1].lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(triple)
        return unique

    def _fill_table_from_specs(self, triples: list[tuple[str, str, str]]) -> None:
        self.table.setRowCount(0)
        for abbr, type_name, color_hex in triples:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(abbr))
            self.table.setItem(row, 1, QTableWidgetItem(type_name))
            self.table.setItem(row, 2, QTableWidgetItem(color_hex))

    def _load_shipped_defaults(self) -> None:
        path = example_event_types_csv_path()
        if not path.is_file():
            path = repo_config_dir() / "event_types.csv"
        if not path.is_file():
            return
        try:
            triples = parse_event_types_csv(path)
            if triples:
                self._fill_table_from_specs(triples)
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
            triples = parse_event_types_csv(Path(path))
            if triples:
                self._fill_table_from_specs(triples)
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
            triples = self.value_triples()
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["abbr", "type", "color"])
                for abbr, type_name, color_hex in triples:
                    writer.writerow([abbr, type_name, color_hex])
        except Exception:
            return
