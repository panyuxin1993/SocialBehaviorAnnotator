from __future__ import annotations

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

from app.gui.ethogram_widget import fallback_event_type_hex, parse_event_color_hex


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
        load_btn = QPushButton("Load CSV…")
        load_btn.clicked.connect(self._load_csv)
        save_btn = QPushButton("Export CSV…")
        save_btn.clicked.connect(self._save_csv)
        buttons_row.addWidget(add_btn)
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

    def _load_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load event types CSV",
            self.default_csv_dir,
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        try:
            import csv

            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if not rows:
                return
            headers = [h.strip().lower() for h in rows[0]]
            data_rows = rows[1:]

            abbr_idx = headers.index("abbr") if "abbr" in headers else 0
            type_idx = headers.index("type") if "type" in headers else min(1, len(headers) - 1)
            color_idx = headers.index("color") if "color" in headers else None

            self.table.setRowCount(0)
            for raw in data_rows:
                if not raw:
                    continue
                abbr = raw[abbr_idx].strip() if abbr_idx < len(raw) else ""
                type_name = raw[type_idx].strip() if type_idx < len(raw) else ""
                color_cell = ""
                if color_idx is not None and color_idx < len(raw):
                    color_cell = raw[color_idx].strip()
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(abbr))
                self.table.setItem(row, 1, QTableWidgetItem(type_name))
                self.table.setItem(row, 2, QTableWidgetItem(color_cell))
        except Exception:
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
