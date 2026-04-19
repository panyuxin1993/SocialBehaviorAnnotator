from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class AnimalListEditor(QDialog):
    """Dialog to edit a single-column list of animal names."""

    def __init__(self, values: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit animals")
        self.resize(400, 300)

        layout = QVBoxLayout(self)

        self.table = QTableWidget(self)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["animal"])
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(max(1, len(values)))
        for row, value in enumerate(values):
            item = QTableWidgetItem(value)
            self.table.setItem(row, 0, item)
        layout.addWidget(self.table)

        hint = QLabel("Add, edit, or clear rows. Empty rows are ignored when saving.")
        layout.addWidget(hint)

        buttons_row = QHBoxLayout()
        add_btn = QPushButton("Add row")
        add_btn.clicked.connect(self._add_row)
        buttons_row.addWidget(add_btn)
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

    def values(self) -> list[str]:
        out: list[str] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            text = item.text().strip()
            if text:
                out.append(text)
        # Remove duplicates while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for v in out:
            if v not in seen:
                seen.add(v)
                unique.append(v)
        return unique

