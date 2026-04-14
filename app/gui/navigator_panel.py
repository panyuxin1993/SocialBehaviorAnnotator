from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.gui.ethogram_widget import EthogramWidget


class NavigatorPanel(QWidget):
    seek_to_frame = Signal(int)
    seek_to_datetime = Signal(str)
    next_event_requested = Signal()
    previous_event_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.total_frames = 1

        layout = QVBoxLayout(self)
        top_row = QHBoxLayout()

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.seek_to_frame.emit)

        self.jump_input = QLineEdit()
        self.jump_input.setPlaceholderText("Frame index or datetime (YYYY-MM-DD HH:MM:SS)")
        self.jump_input.returnPressed.connect(self._on_jump_enter)

        self.previous_btn = QPushButton("Previous event")
        self.next_btn = QPushButton("Next event")
        self.previous_btn.clicked.connect(self.previous_event_requested.emit)
        self.next_btn.clicked.connect(self.next_event_requested.emit)

        self.status_label = QLabel("frame: - / -")

        top_row.addWidget(QLabel("Navigator"))
        top_row.addWidget(self.slider, stretch=2)
        top_row.addWidget(self.jump_input, stretch=1)
        top_row.addWidget(self.previous_btn)
        top_row.addWidget(self.next_btn)
        top_row.addWidget(self.status_label)

        self.ethogram = EthogramWidget()

        layout.addLayout(top_row)
        layout.addWidget(self.ethogram)

    def _on_jump_enter(self) -> None:
        text = self.jump_input.text().strip()
        if not text:
            return
        if text.isdigit():
            self.seek_to_frame.emit(int(text))
            return
        try:
            datetime.fromisoformat(text)
            self.seek_to_datetime.emit(text)
        except ValueError:
            self.jump_input.setText("")
            self.jump_input.setPlaceholderText("Invalid input. Use frame index or datetime.")

    def set_current_frame(self, frame_index: int, total_frames: int) -> None:
        self.total_frames = max(1, total_frames)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, self.total_frames - 1))
        self.slider.setValue(max(0, min(frame_index, self.total_frames - 1)))
        self.slider.blockSignals(False)
        self.status_label.setText(f"frame: {frame_index} / {self.total_frames - 1}")

