from __future__ import annotations

from typing import Callable

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, TextArea
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget, QHBoxLayout

from app.gui.colors import ANIMAL_COLORS
from app.services.kinematics_service import (
    KinematicsSeries,
    compute_pair_kinematics,
    resolve_tracking_subject,
    series_has_scalar,
)
from app.services.tracking_service import TrackingService


class KinematicsWidget(QWidget):
    """Three stacked time-series plots: distance, relative speed, egocentric angle."""

    def __init__(self) -> None:
        super().__init__()
        self._tracking: TrackingService | None = None
        self._start_unix: float | None = None
        self._end_unix: float | None = None
        self._event_type: str = ""
        self._default_rat_a: str = ""
        self._default_rat_b: str = ""
        self._user_picked_a = False
        self._user_picked_b = False
        self._refresh_callback: Callable[[], None] | None = None
        self._axes: list = []
        self._playhead_lines: list = []
        self._playhead_rel_t: float | None = None

        self.rat_a_combo = QComboBox()
        self.rat_b_combo = QComboBox()
        self.rat_a_combo.setToolTip("Focal rat (egocentric heading); default: initiator")
        self.rat_b_combo.setToolTip("Target rat; default: victim")
        self.rat_a_combo.currentTextChanged.connect(self._on_rat_a_changed)
        self.rat_b_combo.currentTextChanged.connect(self._on_rat_b_changed)

        picker_row = QHBoxLayout()
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)

        label_a = QLabel("Focal rat (A)")
        label_b = QLabel("Target rat (B)")

        row_layout.addWidget(label_a)
        row_layout.addWidget(self.rat_a_combo)
        row_layout.addWidget(label_b)
        row_layout.addWidget(self.rat_b_combo)

        picker_row.addWidget(row_widget)
   
   

        self._figure = Figure(figsize=(4.2, 5.2), tight_layout=True)
        self._canvas = FigureCanvas(self._figure)
        self._canvas.setMinimumHeight(280)
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
        event_type: str = "",
    ) -> None:
        self._start_unix = start_unix
        self._end_unix = end_unix
        self._event_type = (event_type or "").strip()
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

    def set_playhead_unix(self, current_unix: float | None) -> None:
        """Move dotted playhead to current video time (seconds relative to event start)."""
        if not self._playhead_lines or self._start_unix is None or current_unix is None:
            return
        rel_t = float(current_unix) - float(self._start_unix)
        self._playhead_rel_t = rel_t
        for line in self._playhead_lines:
            line.set_xdata([rel_t, rel_t])
            line.set_visible(True)
        self._canvas.draw_idle()

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
        self._axes = []
        self._playhead_lines = []
        self._playhead_rel_t = None
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

    @staticmethod
    def _plot_pair_metric(
        ax,
        times_s,
        values_a,
        values_b,
        *,
        rat_a: str,
        rat_b: str,
        color_a: str,
        color_b: str,
        ylabel: str,
    ) -> None:
        ax.plot(times_s, values_a, color=color_a, linewidth=1.2, label=rat_a)
        ax.plot(times_s, values_b, color=color_b, linewidth=1.2, label=rat_b)
        ax.set_ylabel(ylabel, fontsize=8)

    @staticmethod
    def _decorate_event_window(ax, s: KinematicsSeries) -> None:
        ax.grid(True, alpha=0.3)
        ax.axvline(s.event_start_s, color="#E53935", linestyle="--", linewidth=1.2)
        if s.event_end_s is not None:
            ax.axvline(s.event_end_s, color="#FB8C00", linestyle="--", linewidth=1.2)

    def _draw_series(self, s: KinematicsSeries) -> None:
        self._figure.clear()
        has_area = series_has_scalar(s.area_a, s.area_b)
        has_perimeter = series_has_scalar(s.perimeter_a, s.perimeter_b)
        nrows = 3 + int(has_area) + int(has_perimeter)
        axes = self._figure.subplots(nrows, 1, sharex=True)
        if nrows == 1:
            axes = [axes]
        else:
            axes = list(axes)

        subjects = list(self._tracking.subjects) if self._tracking else []
        color_a, color_b = self._rat_colors(s.rat_a, s.rat_b, subjects)
        row = 0

        axes[row].plot(s.times_s, s.distance_px, color="#000000", linewidth=1.2, label="distance")
        axes[row].set_ylabel("Distance (px)", fontsize=8)
        self._decorate_event_window(axes[row], s)
        row += 1

        self._plot_pair_metric(
            axes[row],
            s.times_s,
            s.relative_speed_a_px_s,
            s.relative_speed_b_px_s,
            rat_a=s.rat_a,
            rat_b=s.rat_b,
            color_a=color_a,
            color_b=color_b,
            ylabel="Relative speed\n(px/s)",
        )
        self._decorate_event_window(axes[row], s)
        row += 1

        self._plot_pair_metric(
            axes[row],
            s.times_s,
            s.egocentric_angle_a_deg,
            s.egocentric_angle_b_deg,
            rat_a=s.rat_a,
            rat_b=s.rat_b,
            color_a=color_a,
            color_b=color_b,
            ylabel="Egocentric angle\n(deg)",
        )
        x_min, x_max = s.times_s.min(), s.times_s.max()
        axes[row].plot([x_min, x_max], [-90, -90], color="#000000", linestyle="--", linewidth=0.5)
        axes[row].plot([x_min, x_max], [90, 90], color="#000000", linestyle="--", linewidth=0.5)
        self._decorate_event_window(axes[row], s)
        row += 1

        if has_area:
            self._plot_pair_metric(
                axes[row],
                s.times_s,
                s.area_a,
                s.area_b,
                rat_a=s.rat_a,
                rat_b=s.rat_b,
                color_a=color_a,
                color_b=color_b,
                ylabel="Area",
            )
            self._decorate_event_window(axes[row], s)
            row += 1

        if has_perimeter:
            self._plot_pair_metric(
                axes[row],
                s.times_s,
                s.perimeter_a,
                s.perimeter_b,
                rat_a=s.rat_a,
                rat_b=s.rat_b,
                color_a=color_a,
                color_b=color_b,
                ylabel="Perimeter",
            )
            self._decorate_event_window(axes[row], s)
            row += 1

        axes[0].plot([], [], color="#E53935", linestyle="--", label="event start")
        if s.event_end_s is not None:
            axes[0].plot([], [], color="#FB8C00", linestyle="--", label="event end")

        axes[-1].set_xlabel("Time relative to event start (s)")
        self._add_colored_title(axes[0], s.rat_a, s.rat_b, color_a, color_b, self._event_type)

        self._axes = list(axes)
        self._playhead_lines = []
        for ax in axes:
            line = ax.axvline(
                0.0,
                color="#37474F",
                linestyle=":",
                linewidth=1.6,
                zorder=10,
                visible=False,
            )
            self._playhead_lines.append(line)
        if self._playhead_rel_t is not None:
            for line in self._playhead_lines:
                line.set_xdata([self._playhead_rel_t, self._playhead_rel_t])
                line.set_visible(True)

        self._canvas.draw_idle()

    @staticmethod
    def _add_colored_title(
        ax,
        rat_a: str,
        rat_b: str,
        color_a: str,
        color_b: str,
        event_type: str,
    ) -> None:
        """Title with each rat name colored to match its curve."""
        text_kw = dict(fontsize=9)

        def part(text: str, color: str = "black", weight: str = "normal") -> TextArea:
            return TextArea(text, textprops={**text_kw, "color": color, "weight": weight})

        children = [
            part("Kinematics: "),
            part(rat_a, color=color_a, weight="bold"),
            part(" & "),
            part(rat_b, color=color_b, weight="bold"),
        ]
        if event_type:
            children.append(part(f" — {event_type}"))

        box = HPacker(children=children, align="center", pad=0, sep=0)
        anchored = AnchoredOffsetbox(
            loc="lower center",
            child=box,
            frameon=False,
            bbox_to_anchor=(0.5, 1.02),
            bbox_transform=ax.transAxes,
            borderpad=0,
        )
        ax.add_artist(anchored)
