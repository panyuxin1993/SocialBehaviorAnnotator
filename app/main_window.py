from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.gui.video_panel import VideoPanel
from app.gui.control_panel import ControlPanel
from app.gui.navigator_panel import NavigatorPanel
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

    def _init_layout(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(self.video_panel)
        top_splitter.addWidget(self.control_panel)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 2)

        main_splitter = QSplitter(Qt.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(self.navigator_panel)
        main_splitter.setStretchFactor(0, 4)
        main_splitter.setStretchFactor(1, 1)

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

    def _open_project_inputs(self) -> None:
        video_path, _ = QFileDialog.getOpenFileName(self, "Select video", "", "Video Files (*.mp4 *.avi *.mov *.mkv)")
        if not video_path:
            return
        timestamp_path, _ = QFileDialog.getOpenFileName(
            self, "Select timestamp file", "", "Timestamp Files (*.npy *.json)"
        )
        if not timestamp_path:
            return
        table_path, _ = QFileDialog.getOpenFileName(
            self, "Select annotation table or cancel for new", "", "Tables (*.csv *.xlsx *.xls)"
        )
        if not table_path:
            table_path, _ = QFileDialog.getSaveFileName(self, "Create annotation table", "", "Tables (*.csv *.xlsx)")
            if not table_path:
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
            self._seek_to_frame(0)
            self.statusBar().showMessage("Project loaded.", 4000)
        except Exception as exc:
            QMessageBox.critical(self, "Failed to load project", str(exc))

    def _seek_to_frame(self, frame_index: int) -> None:
        try:
            frame = self.video_service.get_frame(frame_index)
        except Exception as exc:
            QMessageBox.warning(self, "Seek error", str(exc))
            return

        dt_value, unix_value = self.timestamp_service.timestamp_for_frame(frame_index)
        self.video_panel.set_frame(frame, frame_index, dt_value, unix_value)
        self.control_panel.set_current_frame_image(frame)
        self.control_panel.set_current_time(frame_index, dt_value, unix_value)
        self.navigator_panel.set_current_frame(frame_index, self.video_service.total_frames)
        self.navigator_panel.ethogram.set_data(
            self.annotation_service.annotations,
            frame_index,
            self.video_service.total_frames,
        )

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

    def _jump_to_next_event(self) -> None:
        frame_index = self.annotation_service.next_event_start_frame(self.video_service.current_frame_index)
        if frame_index is not None:
            self._seek_to_frame(frame_index)
            event = self.annotation_service.find_event_by_start_frame(frame_index)
            if event is not None:
                self.control_panel.populate_from_event(event)

    def _jump_to_previous_event(self) -> None:
        frame_index = self.annotation_service.previous_event_start_frame(self.video_service.current_frame_index)
        if frame_index is not None:
            self._seek_to_frame(frame_index)
            event = self.annotation_service.find_event_by_start_frame(frame_index)
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
        )
        QMessageBox.information(self, "Saved", f"Event {event.event_id} saved.")

    def _save_annotations(self) -> None:
        try:
            self.annotation_service.save()
            self.statusBar().showMessage("Annotations saved.", 3000)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", str(exc))

    def _extract_frames_mode(self) -> None:
        if self.video_service.video_path is None:
            QMessageBox.warning(self, "No video", "Load project inputs first.")
            return
        workspace = self.video_service.video_path.parent
        video_id = self.video_service.video_path.stem
        try:
            out_dir = self.video_service.enable_frame_extraction_mode(workspace, video_id)
            self.statusBar().showMessage(f"Frame fallback enabled: {out_dir}", 6000)
        except Exception as exc:
            QMessageBox.warning(self, "Extraction failed", str(exc))

