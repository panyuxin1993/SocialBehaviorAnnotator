from __future__ import annotations

from datetime import datetime
from time import perf_counter

from PySide6.QtCore import Qt, QTimer, Signal
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
        self.slider.sliderPressed.connect(self.pause_playback)
        self.slider.valueChanged.connect(self._on_slider_value_changed)

        self.jump_input = QLineEdit()
        self.jump_input.setPlaceholderText("Frame index or datetime (YYYY-MM-DD HH:MM:SS)")
        self.jump_input.returnPressed.connect(self._on_jump_enter)

        self.play_pause_btn = QPushButton("Play")
        self.play_pause_btn.clicked.connect(self.toggle_play_pause)

        self.playback_speed_spin = QDoubleSpinBox()
        self.playback_speed_spin.setRange(0.05, 64.0)
        self.playback_speed_spin.setDecimals(2)
        self.playback_speed_spin.setSingleStep(0.25)
        self.playback_speed_spin.setValue(1.0)
        self.playback_speed_spin.setFixedWidth(88)
        self.playback_speed_spin.setToolTip(
            "Playback speed as a multiple of real time (uses video FPS). "
            "Shortcuts: Space play/pause, ← → one frame."
        )
        self.playback_speed_spin.valueChanged.connect(self._on_playback_speed_changed)

        self._playback_fps: float = 30.0
        self._playing = False
        self._current_frame_idx: int = 0
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_play_frame)
        self._actual_fps_ema: float | None = None
        self._actual_last_t: float | None = None
        self._actual_last_frame: int | None = None

        self.previous_btn = QPushButton("Previous event")
        self.next_btn = QPushButton("Next event")
        self.previous_btn.clicked.connect(self.previous_event_requested.emit)
        self.next_btn.clicked.connect(self.next_event_requested.emit)

        self.status_label = QLabel("frame: - / -")

        top_row.addWidget(QLabel("Navigator"))
        top_row.addWidget(self.play_pause_btn)
        top_row.addWidget(QLabel("× speed"))
        top_row.addWidget(self.playback_speed_spin)
        top_row.addWidget(self.slider, stretch=2)
        top_row.addWidget(self.jump_input, stretch=1)
        top_row.addWidget(self.previous_btn)
        top_row.addWidget(self.next_btn)
        self.playback_status_label = QLabel("actual: - fps")
        self.playback_status_label.setMinimumWidth(110)
        top_row.addWidget(self.playback_status_label)
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

    def _on_slider_value_changed(self, value: int) -> None:
        self.seek_to_frame.emit(int(value))

    def set_playback_fps(self, fps: float) -> None:
        """Video frame rate for play timing (call after loading a clip)."""
        self._playback_fps = float(fps) if fps and fps > 0 else 30.0
        self._update_play_timer_interval()

    def _on_playback_speed_changed(self, _value: float) -> None:
        self._update_play_timer_interval()
        self._refresh_playback_status()

    def _update_play_timer_interval(self) -> None:
        fps = max(self._playback_fps, 0.001)
        speed = max(float(self.playback_speed_spin.value()), 0.01)
        ms = int(round(1000.0 / (fps * speed)))
        ms = max(1, min(ms, 2000))
        self._play_timer.setInterval(ms)

    def _refresh_playback_status(self) -> None:
        if self._actual_fps_ema is None:
            self.playback_status_label.setText("actual: - fps")
        else:
            self.playback_status_label.setText(f"actual: {self._actual_fps_ema:.2f} fps")

    def _reset_actual_fps_tracking(self) -> None:
        self._actual_fps_ema = None
        self._actual_last_t = perf_counter()
        self._actual_last_frame = int(self._current_frame_idx)

    def _update_actual_fps(self, frame_index: int) -> None:
        now = perf_counter()
        if self._actual_last_t is None or self._actual_last_frame is None:
            self._actual_last_t = now
            self._actual_last_frame = int(frame_index)
            return
        dt = now - self._actual_last_t
        df = int(frame_index) - int(self._actual_last_frame)
        self._actual_last_t = now
        self._actual_last_frame = int(frame_index)
        if dt <= 0 or df <= 0:
            return
        inst = float(df) / float(dt)
        if self._actual_fps_ema is None:
            self._actual_fps_ema = inst
        else:
            self._actual_fps_ema = 0.20 * inst + 0.80 * self._actual_fps_ema

    def start_playback(self) -> None:
        last = max(0, self.total_frames - 1)
        if last <= 0:
            return
        if self._current_frame_idx >= last:
            return
        self._playing = True
        self._update_play_timer_interval()
        self._reset_actual_fps_tracking()
        self._play_timer.start()
        self.play_pause_btn.setText("Pause")
        self._refresh_playback_status()

    def pause_playback(self) -> None:
        self._playing = False
        self._play_timer.stop()
        self.play_pause_btn.setText("Play")
        self._refresh_playback_status()

    def toggle_play_pause(self) -> None:
        if self._playing:
            self.pause_playback()
        else:
            self.start_playback()

    def _advance_play_frame(self) -> None:
        if not self._playing:
            return
        last = max(0, self.total_frames - 1)
        nxt = min(self._current_frame_idx + 1, last)
        if nxt <= self._current_frame_idx:
            self.pause_playback()
            return
        self.seek_to_frame.emit(nxt)

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
        self.pause_playback()
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
        self._current_frame_idx = max(0, min(int(frame_index), self.total_frames - 1))
        if self._playing:
            self._update_actual_fps(self._current_frame_idx)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, self.total_frames - 1))
        self.slider.setValue(self._current_frame_idx)
        self.slider.blockSignals(False)
        self._refresh_playback_status()
        self.status_label.setText(f"frame: {self._current_frame_idx} / {self.total_frames - 1}")

