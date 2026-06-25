from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.config_loader import parse_animal_names_xlsx, repo_config_dir

_ID_IMAGE_DIR_CANDIDATES = ("id_images", "ID_images", "id_photos")


class AnimalListEditor(QDialog):
    """Dialog to edit animal names and the correlated ID images folder."""

    def __init__(
        self,
        values: list[str],
        parent=None,
        default_xlsx_dir: str = "",
        id_images_dir: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit animals")
        self.resize(520, 360)
        self.default_xlsx_dir = default_xlsx_dir
        self._settings = QSettings("SocialBehaviorAnnotator", "SocialBehaviorAnnotator")
        self._key_id_images_dir = "paths/id_images_dir"

        layout = QVBoxLayout(self)

        self.table = QTableWidget(self)
        self.table.setColumnCount(1)
        self.table.setHorizontalHeaderLabels(["animal"])
        self.table.verticalHeader().setVisible(False)
        self._fill_table_from_names(values)
        layout.addWidget(self.table)

        form = QFormLayout()
        self._id_images_edit = QLineEdit()
        self._id_images_edit.setPlaceholderText("Folder of ID images named by animal (e.g. rat616.jpg)…")
        self._id_images_edit.setText((id_images_dir or "").strip())
        btn_id_images = QPushButton("Browse…")
        btn_id_images.clicked.connect(self._browse_id_images)
        id_row = QHBoxLayout()
        id_row.addWidget(self._id_images_edit)
        id_row.addWidget(btn_id_images)
        form.addRow("ID images folder:", id_row)
        layout.addLayout(form)

        hint = QLabel(
            "Add, edit, or clear rows. Empty rows are ignored when saving. "
            "Load from Excel reads rat names from the first column of the first sheet "
            "(e.g. rats_background.xlsx). ID images should use the same names as filenames."
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

    def _start_dir(self, current_text: str) -> str:
        text = (current_text or "").strip()
        if text:
            p = Path(text).expanduser()
            if p.exists():
                return str(p if p.is_dir() else p.parent)
            if p.parent.exists():
                return str(p.parent)
        if self.default_xlsx_dir:
            base = Path(self.default_xlsx_dir)
            if base.is_dir():
                return str(base)
            if base.parent.exists():
                return str(base.parent)
        scoped = str(self._settings.value(self._key_id_images_dir, "")).strip()
        if scoped and Path(scoped).exists():
            return scoped
        return str(Path.home())

    def _browse_id_images(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select ID images folder",
            self._start_dir(self._id_images_edit.text()),
        )
        if path:
            self._id_images_edit.setText(path)
            self._settings.setValue(self._key_id_images_dir, path)

    def _suggest_id_images_dir(self) -> None:
        if self._id_images_edit.text().strip():
            return
        if not self.default_xlsx_dir:
            return
        base = Path(self.default_xlsx_dir)
        search_dir = base if base.is_dir() else base.parent
        if not search_dir.is_dir():
            return
        for name in _ID_IMAGE_DIR_CANDIDATES:
            candidate = search_dir / name
            if candidate.is_dir():
                self._id_images_edit.setText(str(candidate))
                return

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
        self._suggest_id_images_dir()

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

    def id_images_dir(self) -> str:
        return self._id_images_edit.text().strip()

    def accept(self) -> None:
        value = self.id_images_dir()
        if value:
            self._settings.setValue(self._key_id_images_dir, value)
        super().accept()
