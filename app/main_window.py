from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QSettings
from PySide6.QtGui import QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QApplication,
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QFileDialog,
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
from app.config_loader import repo_config_dir
from app.services.annotation_service import AnnotationService
from app.services.timestamp_service import TimestampService
from app.services.tracking_service import TrackingService
from app.services.video_service import VideoService




class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Social Behavior Annotator")
        self.resize(1600, 900)

        self.video_service = VideoService()
        self.timestamp_service = TimestampService()
        self.tracking_service = TrackingService()
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
        if ke.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False
        if ke.key() == Qt.Key_Left:
            self.navigator_panel.step_frame(-1)
            return True
        if ke.key() == Qt.Key_Right:
            self.navigator_panel.step_frame(1)
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
        self.control_panel.kinematics_refresh_requested.connect(self.control_panel.refresh_kinematics)

    def _init_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        load_action = file_menu.addAction("Open project inputs")
        load_action.triggered.connect(self._open_project_inputs)

        frame_extract_action = file_menu.addAction("Extract all frames (fallback mode)")
        frame_extract_action.triggered.connect(self._extract_frames_mode)

        save_action = file_menu.addAction("Save annotations")
        save_action.triggered.connect(self._save_annotations)

        load_tracking_action = file_menu.addAction("Load tracking CSV…")
        load_tracking_action.triggered.connect(self._load_tracking_csv)

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
        tracking_path = dialog.tracking_path()

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
            table_path = str(OpenProjectDialog._default_annotation_path(Path(video_path).parent))

        table_file = AnnotationService.resolve_table_path(table_path, video_path=video_path)
        table_path = str(table_file)

        try:
            self.video_service.load_video(video_path)
            self.timestamp_service.load_file(timestamp_path)
            self._load_or_clear_tracking(tracking_path)

            animal_names: list[str] = []
            creating_new_table = not table_file.exists()
            if creating_new_table:
                if self.tracking_service.is_loaded and self.tracking_service.subjects:
                    animal_names = list(self.tracking_service.subjects)
                else:
                    text, ok = QInputDialog.getText(
                        self,
                        "Animal names",
                        "Annotation table not found — a new one will be created.\n"
                        "Enter comma-separated animal names (optional; edit later via Annotation → Animals…):",
                    )
                    if ok and text.strip():
                        animal_names = [name.strip() for name in text.split(",") if name.strip()]

            self.annotation_service.load_or_create_table(
                table_path,
                animal_names,
                video_path=video_path,
            )
            id_images_dir = self._resolve_id_images_dir(
                self.annotation_service.id_images_dir,
                video_path=video_path,
                table_path=table_path,
            )
            if id_images_dir:
                self.annotation_service.id_images_dir = id_images_dir
            if creating_new_table:
                self.control_panel.append_log(
                    f"New annotation table will be created on first Submit event: {table_path}"
                )
            self._sync_tracking_to_control_panel()
            self.control_panel.set_animal_names(self.annotation_service.animal_names)
            self.control_panel.set_id_images_dir(self.annotation_service.id_images_dir or None)
            self.navigator_panel.ethogram.set_data(
                self.annotation_service.annotations,
                0,
                self.video_service.total_frames,
                self.timestamp_service.timestamps,
                animal_names=self.annotation_service.animal_names,
                fps=self.video_service.fps,
                type_colors=self.control_panel.event_type_color_map(),
                type_legend_labels=self.control_panel.event_type_legend_label_map(),
                environmental_types=self.control_panel.environmental_type_keys(),
            )
            self.navigator_panel.set_playback_fps(self.video_service.fps)
            self.navigator_panel.pause_playback()
            self._seek_to_frame(0)
            self.statusBar().showMessage("Project loaded.", 4000)
            self.control_panel.append_log(f"Project loaded: video={video_path}")
            self.control_panel.append_log(f"Timestamps: {timestamp_path}")
            self.control_panel.append_log(f"Annotations: {table_path}")
            if self.tracking_service.is_loaded and self.tracking_service.source_path is not None:
                self.control_panel.append_log(
                    f"Tracking: {self.tracking_service.source_path} "
                    f"({self.tracking_service.row_count} rows, "
                    f"{len(self.tracking_service.subjects)} subjects)"
                )
            if self.annotation_service.id_images_dir and Path(self.annotation_service.id_images_dir).is_dir():
                self.control_panel.append_log(f"ID images: {self.annotation_service.id_images_dir}")
        except Exception as exc:
            QMessageBox.critical(self, "Failed to load project", str(exc))
            self.control_panel.append_log(f"ERROR: load failed — {exc}")

    @staticmethod
    def _id_images_dir_candidates(search_dir: Path) -> list[Path]:
        return [
            search_dir / "id_images",
            search_dir / "ID_images",
            search_dir / "id_photos",
        ]

    def _resolve_id_images_dir(
        self,
        stored_dir: str,
        *,
        video_path: str,
        table_path: str,
    ) -> str:
        stored = (stored_dir or "").strip()
        if stored:
            p = Path(stored).expanduser()
            if p.is_dir():
                return str(p)

        settings = QSettings("SocialBehaviorAnnotator", "SocialBehaviorAnnotator")
        from_csv = str(settings.value(f"paths/id_images_for/{table_path}", "")).strip()
        if from_csv and Path(from_csv).expanduser().is_dir():
            return str(Path(from_csv).expanduser())

        video_parent = Path(video_path).parent
        for candidate in self._id_images_dir_candidates(video_parent):
            if candidate.is_dir():
                return str(candidate)
        table_parent = Path(table_path).parent
        if table_parent != video_parent:
            for candidate in self._id_images_dir_candidates(table_parent):
                if candidate.is_dir():
                    return str(candidate)
        return stored

    def _persist_id_images_dir_for_table(self, table_path: Path, id_images_dir: str) -> None:
        if table_path.suffix.lower() != ".csv":
            return
        table_path = table_path.expanduser().resolve()
        value = (id_images_dir or "").strip()
        settings = QSettings("SocialBehaviorAnnotator", "SocialBehaviorAnnotator")
        key = f"paths/id_images_for/{table_path}"
        if value:
            settings.setValue(key, value)
        else:
            settings.remove(key)

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

    def _seek_to_frame(self, frame_index: int) -> None:
        try:
            frame = self.video_service.get_frame(frame_index)
        except Exception as exc:
            self.navigator_panel.pause_playback()
            QMessageBox.warning(self, "Seek error", str(exc))
            self.control_panel.append_log(f"Seek error (frame {frame_index}): {exc}")
            return

        actual_index = int(self.video_service.current_frame_index)
        dt_value, unix_value, ts_raw = self.timestamp_service.timestamp_for_frame(actual_index)
        tracking_poses = self._tracking_poses_for_frame(actual_index)
        self._apply_tracking_overlay(tracking_poses, refresh=False)
        self.video_panel.set_frame(frame, actual_index, dt_value, unix_value)
        self.control_panel.set_current_frame_image(frame)
        self.control_panel.set_current_time(actual_index, dt_value, unix_value, ts_raw)
        self.navigator_panel.set_current_frame(actual_index, self.video_service.total_frames)
        self.navigator_panel.ethogram.set_playhead(actual_index)
        self.control_panel.update_kinematics_playhead(unix_value)

    def _sync_tracking_to_control_panel(self) -> None:
        self.control_panel.set_tracking_service(self.tracking_service)
        self.control_panel.refresh_kinematics()

    def _load_or_clear_tracking(self, tracking_path: str) -> None:
        path = (tracking_path or "").strip()
        if not path:
            self.tracking_service.clear()
            self.video_panel.set_tracking_overlay({}, loaded=False)
            self._sync_tracking_to_control_panel()
            return
        if not Path(path).is_file():
            self.tracking_service.clear()
            self.video_panel.set_tracking_overlay({}, loaded=False)
            self.control_panel.append_log(f"Tracking file not found (skipped): {path}")
            self._sync_tracking_to_control_panel()
            return
        self.tracking_service.load_file(path)
        name = self.tracking_service.source_path.name if self.tracking_service.source_path else path
        self.video_panel.set_tracking_overlay(
            {},
            subjects=self.tracking_service.subjects,
            loaded=True,
            source_name=name,
        )
        self._sync_tracking_to_control_panel()

    def _tracking_poses_for_frame(self, frame_index: int) -> dict[str, tuple[float, float]]:
        if not self.tracking_service.is_loaded:
            return {}
        return self.tracking_service.poses_for_frame(
            frame_index,
            self.timestamp_service.timestamps,
        )

    def _apply_tracking_overlay(
        self,
        poses: dict[str, tuple[float, float]],
        *,
        refresh: bool = True,
    ) -> None:
        if not self.tracking_service.is_loaded:
            self.video_panel.set_tracking_overlay({}, loaded=False, refresh=refresh)
            return
        name = self.tracking_service.source_path.name if self.tracking_service.source_path else ""
        self.video_panel.set_tracking_overlay(
            poses,
            subjects=self.tracking_service.subjects,
            loaded=True,
            source_name=name,
            refresh=refresh,
        )

    def _update_tracking_overlay(self, frame_index: int) -> None:
        self._apply_tracking_overlay(self._tracking_poses_for_frame(frame_index))

    def _load_tracking_csv(self) -> None:
        start_dir = ""
        if self.tracking_service.source_path is not None:
            start_dir = str(self.tracking_service.source_path.parent)
        elif self.annotation_service.table_path is not None:
            start_dir = str(self.annotation_service.table_path.parent)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load tracking CSV",
            start_dir,
            "CSV files (*.csv);;All Files (*)",
        )
        if not path:
            return
        try:
            self.tracking_service.load_file(path)
            self._apply_tracking_overlay(
                self._tracking_poses_for_frame(self.video_service.current_frame_index)
            )
            self._sync_tracking_to_control_panel()
            self.control_panel.append_log(
                f"Tracking loaded: {path} ({self.tracking_service.row_count} rows, "
                f"{len(self.tracking_service.subjects)} subjects)"
            )
            self.statusBar().showMessage("Tracking loaded.", 3000)
        except Exception as exc:
            QMessageBox.warning(self, "Tracking load failed", str(exc))
            self.control_panel.append_log(f"ERROR: tracking load — {exc}")

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
        frame_index, event, iloc = self.annotation_service.next_event_from_current_time(
            self.video_service.current_frame_index,
            self.timestamp_service.timestamps,
            max_frame_index=max_idx,
            current_iloc=self.control_panel._editing_iloc,
        )
        if frame_index is not None:
            self._seek_to_frame(frame_index)
            if event is not None and iloc is not None:
                self.control_panel.populate_from_event(event, iloc=iloc, seek_frame=frame_index)

    def _jump_to_previous_event(self) -> None:
        max_idx = self._max_video_frame_index()
        if max_idx is None:
            return
        frame_index, event, iloc = self.annotation_service.previous_event_from_current_time(
            self.video_service.current_frame_index,
            self.timestamp_service.timestamps,
            max_frame_index=max_idx,
            current_iloc=self.control_panel._editing_iloc,
        )
        if frame_index is not None:
            self._seek_to_frame(frame_index)
            if event is not None and iloc is not None:
                self.control_panel.populate_from_event(event, iloc=iloc, seek_frame=frame_index)

    def _on_submit_event(self, event) -> None:
        try:
            prev_rows = len(self.annotation_service.annotations)
            if event.editing_iloc is not None:
                self.annotation_service.update_event_at_iloc(event.editing_iloc, event)
            else:
                if not (event.event_id or "").strip():
                    event.event_id = self.annotation_service.generate_event_id()
                self.annotation_service.append_event(event)
                if len(self.annotation_service.annotations) <= prev_rows:
                    raise RuntimeError("Event was not added to the annotation table.")
            self._save_annotations()
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            self.control_panel.append_log(f"ERROR: event save failed — {exc}")
            return

        self.navigator_panel.ethogram.set_data(
            self.annotation_service.annotations,
            self.video_service.current_frame_index,
            self.video_service.total_frames,
            self.timestamp_service.timestamps,
            animal_names=self.annotation_service.animal_names,
            fps=self.video_service.fps,
            type_colors=self.control_panel.event_type_color_map(),
            type_legend_labels=self.control_panel.event_type_legend_label_map(),
            environmental_types=self.control_panel.environmental_type_keys(),
        )
        if event.editing_iloc is not None:
            iloc = event.editing_iloc
            row_dict = self.annotation_service.annotations.iloc[iloc].to_dict()
            eid = str(row_dict.get("event_id", "")).strip()
            self.control_panel.populate_from_event(row_dict, iloc=iloc, seek_frame=None)
            QMessageBox.information(self, "Saved", f"Event {eid} updated.")
            self.control_panel.append_log(f"Updated event {eid} ({event.event_type})")
        else:
            QMessageBox.information(self, "Saved", f"Event {event.event_id} saved.")
            self.control_panel.append_log(f"Saved event {event.event_id} ({event.event_type})")
            self.control_panel.reset_new_event_form()

    def _save_annotations(self) -> None:
        try:
            row_count = len(self.annotation_service.annotations)
            if row_count == 0:
                self.control_panel.append_log(
                    "WARNING: no events in memory — use Submit event to save annotations."
                )
            self.annotation_service.save()
            table_path = self.annotation_service.table_path
            path_text = str(table_path) if table_path is not None else "(unknown path)"
            self.statusBar().showMessage("Annotations saved.", 3000)
            self.control_panel.append_log(
                f"Annotations saved to disk: {path_text} ({row_count} event{'s' if row_count != 1 else ''})"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            self.control_panel.append_log(f"ERROR: save failed — {exc}")

    def _edit_event_types(self) -> None:
        """Open a dialog to edit the list of event types shown in the control panel."""
        specs = self.control_panel.event_type_specs()
        default_csv_dir = str(repo_config_dir())
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
            environmental_types=self.control_panel.environmental_type_keys(),
        )

    def _edit_animals(self) -> None:
        """Open a dialog to edit the list of animals used in the project."""
        current_animals = list(self.annotation_service.animal_names)
        default_xlsx_dir = ""
        if self.annotation_service.table_path is not None:
            default_xlsx_dir = str(self.annotation_service.table_path.parent)
        elif self.video_service.video_path is not None:
            default_xlsx_dir = str(self.video_service.video_path.parent)
        dialog = AnimalListEditor(
            current_animals,
            self,
            default_xlsx_dir=default_xlsx_dir,
            id_images_dir=self.annotation_service.id_images_dir,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        new_animals = dialog.values()
        if not new_animals:
            return
        new_id_images_dir = dialog.id_images_dir()
        self.annotation_service.animal_names = new_animals
        self.annotation_service.id_images_dir = new_id_images_dir
        self.control_panel.set_animal_names(new_animals)
        self.control_panel.set_id_images_dir(new_id_images_dir or None)
        if self.annotation_service.table_path is not None:
            self._persist_id_images_dir_for_table(
                self.annotation_service.table_path,
                new_id_images_dir,
            )
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

