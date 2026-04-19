from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QApplication,
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.gui.open_project_dialog import OpenProjectDialog
from app.gui.video_panel import VideoPanel
from app.gui.control_panel import ControlPanel
from app.gui.navigator_panel import NavigatorPanel
from app.gui.event_type_editor import EventTypeEditor
from app.gui.animal_list_editor import AnimalListEditor
from app.services.annotation_service import AnnotationService
from app.services.timestamp_service import TimestampService
from app.services.video_service import VideoService




class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Social Behavior Annotator")
        self.resize(1600, 900)

        self.video_service = VideoService()
        self.timestamp_service = TimestampService()
        self.annotation_service = AnnotationService()

        self.video_panel = VideoPanel()
        self.control_panel = ControlPanel()
        self.navigator_panel = NavigatorPanel()

        self._init_layout()
        self._connect_signals()
        self._init_menu()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Type.KeyPress:
            return False
        if not isinstance(watched, QWidget):
            return False
        if not self.isAncestorOf(watched):
            return False
        if self._navigation_shortcuts_blocked():
            return False
        ke = event
        if not isinstance(ke, QKeyEvent):
            return False
        if ke.key() == Qt.Key_Space:
            if isinstance(watched, QAbstractButton):
                return False
            self.navigator_panel.toggle_play_pause()
            return True
        if ke.key() == Qt.Key_Left:
            self._step_frame_from_keyboard(-1)
            return True
        if ke.key() == Qt.Key_Right:
            self._step_frame_from_keyboard(1)
            return True
        return False

    def _init_layout(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # Left column: video on top, navigator at bottom; right column: full-height control panel + console
        left_column = QSplitter(Qt.Vertical)
        left_column.addWidget(self.video_panel)
        left_column.addWidget(self.navigator_panel)
        left_column.setStretchFactor(0, 4)
        left_column.setStretchFactor(1, 1)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(left_column)
        main_splitter.addWidget(self.control_panel)
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 2)

        root_layout.addWidget(main_splitter)
        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.video_panel.frame_clicked.connect(self.control_panel.handle_frame_click_for_role)
        self.control_panel.request_seek_frame.connect(self._seek_to_frame)
        self.navigator_panel.seek_to_frame.connect(self._seek_to_frame)
        self.navigator_panel.seek_to_datetime.connect(self._seek_to_datetime)
        self.control_panel.submit_event_requested.connect(self._on_submit_event)

        self.navigator_panel.next_event_requested.connect(self._jump_to_next_event)
        self.navigator_panel.previous_event_requested.connect(self._jump_to_previous_event)
        self.control_panel.bind_set_time_actions()

    def _init_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        load_action = file_menu.addAction("Open project inputs")
        load_action.triggered.connect(self._open_project_inputs)

        frame_extract_action = file_menu.addAction("Extract all frames (fallback mode)")
        frame_extract_action.triggered.connect(self._extract_frames_mode)

        save_action = file_menu.addAction("Save annotations")
        save_action.triggered.connect(self._save_annotations)

        annotation_menu = self.menuBar().addMenu("Annotation")
        edit_types_action = annotation_menu.addAction("Event types…")
        edit_types_action.triggered.connect(self._edit_event_types)
        edit_animals_action = annotation_menu.addAction("Animals…")
        edit_animals_action.triggered.connect(self._edit_animals)

    def _open_project_inputs(self) -> None:
        dialog = OpenProjectDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        video_path = dialog.video_path()
        timestamp_path = dialog.timestamp_path()
        table_path = dialog.annotation_path()

        if not video_path:
            QMessageBox.warning(self, "Missing video", "Please set the video file path.")
            return
        if not Path(video_path).is_file():
            QMessageBox.warning(self, "Invalid video", f"Video file not found:\n{video_path}")
            return
        if not timestamp_path:
            QMessageBox.warning(self, "Missing timestamps", "Please set the timestamp file path.")
            return
        if not Path(timestamp_path).is_file():
            QMessageBox.warning(self, "Invalid timestamps", f"Timestamp file not found:\n{timestamp_path}")
            return
        if not table_path:
            QMessageBox.warning(
                self,
                "Missing annotation table",
                "Please set the annotation table path (open existing or Save as new).",
            )
            return

        try:
            self.video_service.load_video(video_path)
            self.timestamp_service.load_file(timestamp_path)

            animal_names: list[str] = []
            if not Path(table_path).exists():
                text, ok = QInputDialog.getText(
                    self,
                    "Animal names",
                    "Enter comma-separated animal names for a new table:",
                )
                if not ok or not text.strip():
                    raise ValueError("Animal names are required when creating a new table.")
                animal_names = [name.strip() for name in text.split(",") if name.strip()]

            self.annotation_service.load_or_create_table(table_path, animal_names)
            self.control_panel.set_animal_names(self.annotation_service.animal_names)
            self.navigator_panel.ethogram.set_data(
                self.annotation_service.annotations,
                0,
                self.video_service.total_frames,
                self.timestamp_service.timestamps,
                animal_names=self.annotation_service.animal_names,
                fps=self.video_service.fps,
                type_colors=self.control_panel.event_type_color_map(),
                type_legend_labels=self.control_panel.event_type_legend_label_map(),
            )
            self.navigator_panel.set_playback_fps(self.video_service.fps)
            self.navigator_panel.pause_playback()
            self._seek_to_frame(0)
            self.statusBar().showMessage("Project loaded.", 4000)
            self.control_panel.append_log(f"Project loaded: video={video_path}")
            self.control_panel.append_log(f"Timestamps: {timestamp_path}")
            self.control_panel.append_log(f"Annotations: {table_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Failed to load project", str(exc))
            self.control_panel.append_log(f"ERROR: load failed — {exc}")

    @staticmethod
    def _navigation_shortcuts_blocked() -> bool:
        w = QApplication.focusWidget()
        while w is not None:
            if isinstance(
                w,
                (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QAbstractItemView, QComboBox),
            ):
                return True
            w = w.parentWidget()
        return False

    def _step_frame_from_keyboard(self, delta: int) -> None:
        self.navigator_panel.pause_playback()
        tf = max(1, self.video_service.total_frames)
        last = tf - 1
        cur = self.video_service.current_frame_index
        nxt = max(0, min(cur + delta, last))
        if nxt != cur:
            self._seek_to_frame(nxt)

    def _seek_to_frame(self, frame_index: int) -> None:
        try:
            frame = self.video_service.get_frame(frame_index)
        except Exception as exc:
            self.navigator_panel.pause_playback()
            QMessageBox.warning(self, "Seek error", str(exc))
            self.control_panel.append_log(f"Seek error (frame {frame_index}): {exc}")
            return

        dt_value, unix_value = self.timestamp_service.timestamp_for_frame(frame_index)
        self.video_panel.set_frame(frame, frame_index, dt_value, unix_value)
        self.control_panel.set_current_frame_image(frame)
        self.control_panel.set_current_time(frame_index, dt_value, unix_value)
        self.navigator_panel.set_current_frame(frame_index, self.video_service.total_frames)
        self.navigator_panel.ethogram.set_playhead(frame_index)

    def _seek_to_datetime(self, dt_text: str) -> None:
        if not self.timestamp_service.timestamps:
            return
        try:
            from datetime import datetime

            target_unix = datetime.fromisoformat(dt_text).timestamp()
        except Exception:
            return
        closest_idx = min(
            range(len(self.timestamp_service.timestamps)),
            key=lambda idx: abs(self.timestamp_service.timestamps[idx] - float(target_unix)),
        )
        self._seek_to_frame(closest_idx)

    def _max_video_frame_index(self) -> int | None:
        """Last valid frame index for the loaded video (None if unknown)."""
        tf = self.video_service.total_frames
        if tf <= 0:
            return None
        return max(0, tf - 1)

    def _jump_to_next_event(self) -> None:
        max_idx = self._max_video_frame_index()
        if max_idx is None:
            return
        frame_index, event = self.annotation_service.next_event_from_current_time(
            self.video_service.current_frame_index,
            self.timestamp_service.timestamps,
            max_frame_index=max_idx,
        )
        if frame_index is not None:
            self._seek_to_frame(frame_index)
            if event is not None:
                self.control_panel.populate_from_event(event)

    def _jump_to_previous_event(self) -> None:
        max_idx = self._max_video_frame_index()
        if max_idx is None:
            return
        frame_index, event = self.annotation_service.previous_event_from_current_time(
            self.video_service.current_frame_index,
            self.timestamp_service.timestamps,
            max_frame_index=max_idx,
        )
        if frame_index is not None:
            self._seek_to_frame(frame_index)
            if event is not None:
                self.control_panel.populate_from_event(event)

    def _on_submit_event(self, event) -> None:
        event.event_id = self.annotation_service.generate_event_id()
        self.annotation_service.append_event(event)
        self._save_annotations()
        self.navigator_panel.ethogram.set_data(
            self.annotation_service.annotations,
            self.video_service.current_frame_index,
            self.video_service.total_frames,
            self.timestamp_service.timestamps,
            animal_names=self.annotation_service.animal_names,
            fps=self.video_service.fps,
            type_colors=self.control_panel.event_type_color_map(),
            type_legend_labels=self.control_panel.event_type_legend_label_map(),
        )
        QMessageBox.information(self, "Saved", f"Event {event.event_id} saved.")
        self.control_panel.append_log(f"Saved event {event.event_id} ({event.event_type})")

    def _save_annotations(self) -> None:
        try:
            self.annotation_service.save()
            self.statusBar().showMessage("Annotations saved.", 3000)
            self.control_panel.append_log("Annotations saved to disk.")
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            self.control_panel.append_log(f"ERROR: save failed — {exc}")

    def _edit_event_types(self) -> None:
        """Open a dialog to edit the list of event types shown in the control panel."""
        specs = self.control_panel.event_type_specs()
        default_csv_dir = ""
        if self.annotation_service.table_path is not None:
            default_csv_dir = str(self.annotation_service.table_path.parent)
        dialog = EventTypeEditor(specs, self, default_csv_dir=default_csv_dir)
        if dialog.exec() != QDialog.Accepted:
            return
        triples = dialog.value_triples()
        if not triples:
            return
        self.control_panel.set_event_type_specs(triples)
        # Full ``set_data`` (not only ``apply_type_color_map``) so the timeline cache and legend
        # always rebuild like on project load / save; matches ``type`` column to new overrides.
        self.navigator_panel.ethogram.set_data(
            self.annotation_service.annotations,
            self.video_service.current_frame_index,
            self.video_service.total_frames,
            self.timestamp_service.timestamps,
            animal_names=self.annotation_service.animal_names,
            fps=self.video_service.fps,
            type_colors=self.control_panel.event_type_color_map(),
            type_legend_labels=self.control_panel.event_type_legend_label_map(),
        )

    def _edit_animals(self) -> None:
        """Open a dialog to edit the list of animals used in the project."""
        current_animals = list(self.annotation_service.animal_names)
        dialog = AnimalListEditor(current_animals, self)
        if dialog.exec() != QDialog.Accepted:
            return
        new_animals = dialog.values()
        if not new_animals:
            return
        self.annotation_service.animal_names = new_animals
        self.control_panel.set_animal_names(new_animals)
        # Persist updated animal list metadata when possible.
        try:
            self.annotation_service.save()
            self.statusBar().showMessage("Animal list updated.", 3000)
        except Exception as exc:
            # Non-fatal; project can continue even if save fails.
            self.control_panel.append_log(f"WARNING: failed to save updated animal list — {exc}")

    def _extract_frames_mode(self) -> None:
        if self.video_service.video_path is None:
            QMessageBox.warning(self, "No video", "Load project inputs first.")
            return
        workspace = self.video_service.video_path.parent
        video_id = self.video_service.video_path.stem
        try:
            out_dir = self.video_service.enable_frame_extraction_mode(workspace, video_id)
            self.statusBar().showMessage(f"Frame fallback enabled: {out_dir}", 6000)
            self.control_panel.append_log(f"Frame extraction mode: {out_dir}")
        except Exception as exc:
            QMessageBox.warning(self, "Extraction failed", str(exc))
            self.control_panel.append_log(f"ERROR: frame extraction — {exc}")

