from __future__ import annotations

from typing import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from app.gui.colors import ANIMAL_COLORS
from app.services.kinematics_service import KinematicsSeries, compute_pair_kinematics, resolve_tracking_subject
from app.services.tracking_service import TrackingService


class KinematicsWidget(QWidget):
    """Three stacked time-series plots: distance, relative speed, egocentric angle."""

    def __init__(self) -> None:
        super().__init__()
        self._tracking: TrackingService | None = None
        self._start_unix: float | None = None
        self._end_unix: float | None = None
        self._default_rat_a: str = ""
        self._default_rat_b: str = ""
        self._user_picked_a = False
        self._user_picked_b = False
        self._refresh_callback: Callable[[], None] | None = None

        self.rat_a_combo = QComboBox()
        self.rat_b_combo = QComboBox()
        self.rat_a_combo.setToolTip("Focal rat (egocentric heading); default: initiator")
        self.rat_b_combo.setToolTip("Target rat; default: victim")
        self.rat_a_combo.currentTextChanged.connect(self._on_rat_a_changed)
        self.rat_b_combo.currentTextChanged.connect(self._on_rat_b_changed)

        picker_row = QFormLayout()
        picker_row.addRow("Focal rat (A)", self.rat_a_combo)
        picker_row.addRow("Target rat (B)", self.rat_b_combo)

        self._figure = Figure(figsize=(4.2, 3.6), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setMinimumHeight(220)
        self._status = QLabel("Load tracking CSV and set event start to view kinematics.")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: palette(mid);")

        layout = QVBoxLayout(self)
        layout.addLayout(picker_row)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._status)

        self._clear_figure("")

    def set_refresh_callback(self, callback: Callable[[], None]) -> None:
        self._refresh_callback = callback

    def _on_rat_a_changed(self, _text: str) -> None:
        self._user_picked_a = True
        if self._refresh_callback is not None:
            self._refresh_callback()

    def _on_rat_b_changed(self, _text: str) -> None:
        self._user_picked_b = True
        if self._refresh_callback is not None:
            self._refresh_callback()

    def set_event_timing(
        self,
        start_unix: float | None,
        end_unix: float | None,
        *,
        default_rat_a: str = "",
        default_rat_b: str = "",
    ) -> None:
        self._start_unix = start_unix
        self._end_unix = end_unix
        if default_rat_a:
            self._default_rat_a = default_rat_a
        if default_rat_b:
            self._default_rat_b = default_rat_b

    def set_tracking(self, tracking: TrackingService | None) -> None:
        self._tracking = tracking if tracking is not None and tracking.is_loaded else None
        self._rebuild_subject_combos()

    def _rebuild_subject_combos(self) -> None:
        subjects = list(self._tracking.subjects) if self._tracking else []
        for combo, user_picked, default in (
            (self.rat_a_combo, self._user_picked_a, self._default_rat_a),
            (self.rat_b_combo, self._user_picked_b, self._default_rat_b),
        ):
            prev = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(subjects)
            if user_picked and prev in subjects:
                combo.setCurrentText(prev)
            elif default:
                resolved = resolve_tracking_subject(default, subjects)
                if resolved:
                    combo.setCurrentText(resolved)
            combo.blockSignals(False)

    def rat_a_subject(self) -> str:
        return self.rat_a_combo.currentText().strip()

    def rat_b_subject(self) -> str:
        return self.rat_b_combo.currentText().strip()

    def apply_role_defaults(self, rat_a: str, rat_b: str) -> None:
        """Set combo defaults from initiator/victim when the user has not chosen manually."""
        self._default_rat_a = rat_a
        self._default_rat_b = rat_b
        self._rebuild_subject_combos()

    def refresh_plot(self) -> None:
        if self._tracking is None:
            self._clear_figure("Load a tracking CSV (File → Open project or Load tracking CSV…).")
            return
        if self._start_unix is None:
            self._clear_figure("Set event start time to define the kinematics window.")
            return

        rat_a = self.rat_a_subject()
        rat_b = self.rat_b_subject()
        if not rat_a or not rat_b:
            self._clear_figure("Select focal and target rats from tracking subjects.")
            return
        if rat_a == rat_b:
            self._clear_figure("Choose two different rats.")
            return

        series = compute_pair_kinematics(
            self._tracking,
            rat_a,
            rat_b,
            start_unix=self._start_unix,
            end_unix=self._end_unix,
        )
        if series is None:
            self._clear_figure(
                f"No overlapping tracking for {rat_a} and {rat_b} in "
                "[start − 2 s, end + 2 s]."
            )
            return

        self._draw_series(series)
        self._status.setText(
            f"{series.rat_a} → {series.rat_b} | "
            f"window [{series.window_start_s:.1f}, {series.window_end_s:.1f}] s rel. start | "
            f"n={len(series.times_s)}"
        )

    def _clear_figure(self, message: str) -> None:
        self._figure.clear()
        ax = self._figure.add_subplot(111)
        ax.axis("off")
        ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, wrap=True)
        self._canvas.draw_idle()
        if message:
            self._status.setText(message)

    @staticmethod
    def _rat_colors(rat_a: str, rat_b: str, subjects: list[str]) -> tuple[str, str]:
        def pick(rat_id: str) -> str:
            if subjects:
                try:
                    idx = subjects.index(rat_id)
                except ValueError:
                    idx = hash(rat_id) % len(ANIMAL_COLORS)
            else:
                idx = hash(rat_id) % len(ANIMAL_COLORS)
            return ANIMAL_COLORS[idx % len(ANIMAL_COLORS)]

        return pick(rat_a), pick(rat_b)

    def _draw_series(self, s: KinematicsSeries) -> None:
        self._figure.clear()
        axes = self._figure.subplots(3, 1, sharex=True)
        subjects = list(self._tracking.subjects) if self._tracking else []
        color_a, color_b = self._rat_colors(s.rat_a, s.rat_b, subjects)

        # Distance: single symmetric metric
        axes[0].plot(s.times_s, s.distance_px, color="#000000", linewidth=1.2, label="distance")
        axes[0].set_ylabel("Distance (px)", fontsize=8)

        axes[1].plot(
            s.times_s,
            s.relative_speed_a_px_s,
            color=color_a,
            linewidth=1.2,
            label=f"{s.rat_a} focal",
        )
        axes[1].plot(
            s.times_s,
            s.relative_speed_b_px_s,
            color=color_b,
            linewidth=1.2,
            label=f"{s.rat_b} focal",
        )
        axes[1].set_ylabel("Relative speed \n (px/s)", fontsize=8)

        axes[2].plot(
            s.times_s,
            s.egocentric_angle_a_deg,
            color=color_a,
            linewidth=1.2,
            label=f"{s.rat_a} → {s.rat_b}",
        )
        axes[2].plot(
            s.times_s,
            s.egocentric_angle_b_deg,
            color=color_b,
            linewidth=1.2,
            label=f"{s.rat_b} → {s.rat_a}",
        )
        x_min, x_max = s.times_s.min(), s.times_s.max()
        axes[2].plot([x_min, x_max], [-90, -90], color="#000000", linestyle="--", linewidth=1.2)
        axes[2].plot([x_min, x_max], [90, 90], color="#000000", linestyle="--", linewidth=1.2)
        axes[2].set_ylabel("Egocentric angle \n (deg)", fontsize=8)

        for ax in axes:
            ax.grid(True, alpha=0.3)
            ax.axvline(s.event_start_s, color="#E53935", linestyle="--", linewidth=1.2)
            if s.event_end_s is not None:
                ax.axvline(s.event_end_s, color="#FB8C00", linestyle="--", linewidth=1.2)

        axes[0].plot([], [], color="#E53935", linestyle="--", label="event start")
        if s.event_end_s is not None:
            axes[0].plot([], [], color="#FB8C00", linestyle="--", label="event end")
        axes[1].legend(loc="upper right", fontsize=6)
        axes[2].legend(loc="upper right", fontsize=6)

        axes[-1].set_xlabel("Time relative to event start (s)")
        axes[0].set_title(f"Kinematics: {s.rat_a} & {s.rat_b}", fontsize=9)
        self._canvas.draw_idle()
