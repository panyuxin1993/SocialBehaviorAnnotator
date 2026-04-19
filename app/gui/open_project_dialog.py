"""Dialog to pick video, timestamp, and annotation paths in one place."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class OpenProjectDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open project inputs")
        self.setMinimumWidth(560)
        self._settings = QSettings("SocialBehaviorAnnotator", "SocialBehaviorAnnotator")

        self._key_last_any_dir = "paths/last_any_dir"
        self._key_video_dir = "paths/video_dir"
        self._key_timestamp_dir = "paths/timestamp_dir"
        self._key_annotation_dir = "paths/annotation_dir"
        self._key_video_path = "paths/video_path"
        self._key_timestamp_path = "paths/timestamp_path"
        self._key_annotation_path = "paths/annotation_path"

        self._video_edit = QLineEdit()
        self._video_edit.setPlaceholderText("Path to video file…")
        self._ts_edit = QLineEdit()
        self._ts_edit.setPlaceholderText("Path to timestamp file (.npy or .json)…")
        self._ann_edit = QLineEdit()
        self._ann_edit.setPlaceholderText("Path to annotation table (.csv / .xlsx) or create new…")
        self._restore_last_paths()
        self._last_video_dir_for_sync = self._path_dir(self._video_edit.text())

        self._video_edit.editingFinished.connect(self._sync_timestamp_from_video)

        btn_video = QPushButton("Browse…")
        btn_video.clicked.connect(self._browse_video)
        btn_ts = QPushButton("Browse…")
        btn_ts.clicked.connect(self._browse_timestamp)
        btn_ann_open = QPushButton("Open…")
        btn_ann_open.setToolTip("Choose an existing annotation file")
        btn_ann_open.clicked.connect(self._browse_annotation_open)
        btn_ann_new = QPushButton("Save as new…")
        btn_ann_new.setToolTip("Pick path for a new annotation file")
        btn_ann_new.clicked.connect(self._browse_annotation_new)

        row_video = QHBoxLayout()
        row_video.addWidget(self._video_edit)
        row_video.addWidget(btn_video)

        row_ts = QHBoxLayout()
        row_ts.addWidget(self._ts_edit)
        row_ts.addWidget(btn_ts)

        row_ann = QHBoxLayout()
        row_ann.addWidget(self._ann_edit)
        row_ann.addWidget(btn_ann_open)
        row_ann.addWidget(btn_ann_new)

        form = QFormLayout()
        form.addRow("Video:", self._wrap_row(row_video))
        form.addRow("Timestamps:", self._wrap_row(row_ts))
        form.addRow("Annotation table:", self._wrap_row(row_ann))

        hint = QLabel(
            "Fill paths manually or use Browse. For a new table, use “Save as new…” or type a path that does not exist yet."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(hint)
        root.addWidget(buttons)

    @staticmethod
    def _wrap_row(layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def _browse_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select video",
            self._start_dir(self._video_edit.text(), self._key_video_dir),
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)",
        )
        if path:
            self._video_edit.setText(path)
            self._remember_selected_path(path, self._key_video_dir, self._key_video_path)
            self._sync_timestamp_from_video()

    def _browse_timestamp(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select timestamp file",
            self._start_dir(self._ts_edit.text(), self._key_timestamp_dir),
            "Timestamp Files (*.npy *.json);;All Files (*)",
        )
        if path:
            self._ts_edit.setText(path)
            self._remember_selected_path(path, self._key_timestamp_dir, self._key_timestamp_path)

    def _browse_annotation_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select annotation table",
            self._start_dir(self._ann_edit.text(), self._key_annotation_dir),
            "Tables (*.csv *.xlsx *.xls);;All Files (*)",
        )
        if path:
            self._ann_edit.setText(path)
            self._remember_selected_path(path, self._key_annotation_dir, self._key_annotation_path)

    def _browse_annotation_new(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Create annotation table",
            self._start_dir(self._ann_edit.text(), self._key_annotation_dir),
            "Tables (*.csv *.xlsx);;All Files (*)",
        )
        if path:
            self._ann_edit.setText(path)
            self._remember_selected_path(path, self._key_annotation_dir, self._key_annotation_path)

    def accept(self) -> None:
        # Persist typed paths too, not only picker selections.
        self._persist_from_line_edit(self._video_edit.text(), self._key_video_dir, self._key_video_path)
        self._persist_from_line_edit(self._ts_edit.text(), self._key_timestamp_dir, self._key_timestamp_path)
        self._persist_from_line_edit(self._ann_edit.text(), self._key_annotation_dir, self._key_annotation_path)
        super().accept()

    def _restore_last_paths(self) -> None:
        self._video_edit.setText(str(self._settings.value(self._key_video_path, "")))
        self._ts_edit.setText(str(self._settings.value(self._key_timestamp_path, "")))
        self._ann_edit.setText(str(self._settings.value(self._key_annotation_path, "")))

    def _start_dir(self, current_text: str, scoped_dir_key: str) -> str:
        text = (current_text or "").strip()
        if text:
            p = Path(text)
            if p.exists():
                if p.is_dir():
                    return str(p)
                return str(p.parent)
            if p.parent.exists():
                return str(p.parent)

        scoped = str(self._settings.value(scoped_dir_key, "")).strip()
        if scoped and Path(scoped).exists():
            return scoped
        generic = str(self._settings.value(self._key_last_any_dir, "")).strip()
        if generic and Path(generic).exists():
            return generic
        return str(Path.home())

    def _remember_selected_path(self, path: str, scoped_dir_key: str, scoped_path_key: str) -> None:
        p = Path(path)
        dir_path = p if p.is_dir() else p.parent
        self._settings.setValue(scoped_dir_key, str(dir_path))
        self._settings.setValue(self._key_last_any_dir, str(dir_path))
        self._settings.setValue(scoped_path_key, str(p))

    def _persist_from_line_edit(self, text: str, scoped_dir_key: str, scoped_path_key: str) -> None:
        value = text.strip()
        if not value:
            return
        p = Path(value)
        if p.exists():
            dir_path = p if p.is_dir() else p.parent
        elif p.parent.exists():
            dir_path = p.parent
        else:
            return
        self._settings.setValue(scoped_dir_key, str(dir_path))
        self._settings.setValue(self._key_last_any_dir, str(dir_path))
        self._settings.setValue(scoped_path_key, value)

    @staticmethod
    def _path_dir(path_text: str) -> Path | None:
        value = path_text.strip()
        if not value:
            return None
        p = Path(value)
        if p.exists():
            return p if p.is_dir() else p.parent
        if p.parent.exists():
            return p.parent
        return None

    def _sync_timestamp_from_video(self) -> None:
        video_text = self._video_edit.text().strip()
        if not video_text:
            return
        video_path = Path(video_text)
        video_dir = self._path_dir(video_text)
        if video_dir is None:
            return

        # Only auto-update if ts is empty or still following prior video directory.
        ts_text = self._ts_edit.text().strip()
        ts_dir = self._path_dir(ts_text) if ts_text else None
        can_override = (not ts_text) or (ts_dir is not None and self._last_video_dir_for_sync is not None and ts_dir == self._last_video_dir_for_sync)
        if not can_override:
            self._last_video_dir_for_sync = video_dir
            return

        stem = video_path.stem
        candidates = [video_dir / f"{stem}_ts.npy", video_dir / f"{stem}_ts.json"]
        chosen = next((c for c in candidates if c.exists()), candidates[0])
        self._ts_edit.setText(str(chosen))
        self._remember_selected_path(str(chosen), self._key_timestamp_dir, self._key_timestamp_path)
        self._last_video_dir_for_sync = video_dir

    def video_path(self) -> str:
        return self._video_edit.text().strip()

    def timestamp_path(self) -> str:
        return self._ts_edit.text().strip()

    def annotation_path(self) -> str:
        return self._ann_edit.text().strip()
