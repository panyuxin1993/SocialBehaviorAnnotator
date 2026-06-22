from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.config_loader import parse_animal_names_xlsx, repo_config_dir


class AnimalListEditor(QDialog):
    """Dialog to edit a single-column list of animal names."""

    def __init__(self, values: list[str], parent=None, default_xlsx_dir: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit animals")
        self.resize(400, 300)
        self.default_xlsx_dir = default_xlsx_dir

        layout = QVBoxLayout(self)

        self.table = QTableWidget(self)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["animal"])
        self.table.verticalHeader().setVisible(False)
        self._fill_table_from_names(values)
        layout.addWidget(self.table)

        hint = QLabel(
            "Add, edit, or clear rows. Empty rows are ignored when saving. "
            "Load from Excel reads rat names from the first column of the first sheet "
            "(e.g. rats_background.xlsx)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons_row = QHBoxLayout()
        add_btn = QPushButton("Add row")
        add_btn.clicked.connect(self._add_row)
        load_btn = QPushButton("Load from Excel…")
        load_btn.clicked.connect(self._load_xlsx)
        buttons_row.addWidget(add_btn)
        buttons_row.addWidget(load_btn)
        buttons_row.addStretch(1)

        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        buttons_row.addWidget(ok_btn)
        buttons_row.addWidget(cancel_btn)

        layout.addLayout(buttons_row)

    def _fill_table_from_names(self, names: list[str]) -> None:
        self.table.setRowCount(max(1, len(names)))
        for row in range(self.table.rowCount()):
            value = names[row] if row < len(names) else ""
            self.table.setItem(row, 0, QTableWidgetItem(value))

    def _add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

    def _load_xlsx(self) -> None:
        start_dir = self.default_xlsx_dir or str(repo_config_dir())
        start_path = Path(start_dir)
        default_file = start_path / "rats_background.xlsx"
        if default_file.is_file():
            start_dir = str(default_file)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load animals from Excel",
            start_dir,
            "Excel files (*.xlsx *.xls);;All files (*)",
        )
        if not path:
            return
        try:
            names = parse_animal_names_xlsx(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", f"Could not read animal names:\n{exc}")
            return
        if not names:
            QMessageBox.warning(
                self,
                "No animals found",
                "No animal names were found in the first column of the first sheet.",
            )
            return
        self._fill_table_from_names(names)

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
