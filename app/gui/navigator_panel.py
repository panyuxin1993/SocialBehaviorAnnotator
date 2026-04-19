from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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

        etho_row = QHBoxLayout()
        etho_row.addWidget(QLabel("Ethogram ± (s)"))
        self.ethogram_window_spin = QDoubleSpinBox()
        self.ethogram_window_spin.setRange(0.5, 86400.0)
        self.ethogram_window_spin.setDecimals(1)
        self.ethogram_window_spin.setSingleStep(5.0)
        self.ethogram_window_spin.setToolTip(
            "Half-width of the ethogram time window in seconds (each side of the playhead)."
        )
        self.ethogram_window_spin.setValue(self.ethogram.window_radius_seconds)
        self.ethogram_window_spin.valueChanged.connect(self.ethogram.set_window_radius_seconds)
        etho_row.addWidget(self.ethogram_window_spin)
        etho_row.addSpacing(12)
        etho_row.addWidget(QLabel("Legend"))
        self._legend_scroll = QScrollArea()
        self._legend_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._legend_scroll.setWidgetResizable(True)
        self._legend_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._legend_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._legend_scroll.setMaximumHeight(30)
        self._legend_host = QWidget()
        self._legend_inner = QHBoxLayout(self._legend_host)
        self._legend_inner.setContentsMargins(0, 0, 0, 0)
        self._legend_inner.setSpacing(0)
        self._legend_scroll.setWidget(self._legend_host)
        etho_row.addWidget(self._legend_scroll, stretch=1)
        self.ethogram.legend_items_changed.connect(self._populate_ethogram_legend)
        self.ethogram.refresh_legend()

        layout.addLayout(top_row)
        layout.addLayout(etho_row)
        layout.addWidget(self.ethogram)

    def _populate_ethogram_legend(self, items: object) -> None:
        layout = self._legend_inner
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        pairs = list(items) if items is not None else []
        for name, color_hex in pairs:
            group = QWidget()
            h = QHBoxLayout(group)
            h.setContentsMargins(0, 0, 12, 0)
            h.setSpacing(4)
            swatch = QLabel()
            swatch.setFixedSize(12, 12)
            swatch.setStyleSheet(
                f"background-color: {color_hex}; border: 1px solid #888888; border-radius: 2px;"
            )
            h.addWidget(swatch)
            h.addWidget(QLabel(str(name)))
            layout.addWidget(group)
        layout.addStretch(1)

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

