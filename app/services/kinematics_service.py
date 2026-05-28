from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.tracking_service import TrackingService


@dataclass(frozen=True)
class KinematicsSeries:
    """Time series for a rat pair in an event window."""

    times_s: np.ndarray  # seconds relative to event start
    distance_px: np.ndarray
    #: Target speed along focal heading (px/s): dot(v_target − v_focal, focal heading).
    relative_speed_a_px_s: np.ndarray
    relative_speed_b_px_s: np.ndarray
    egocentric_angle_a_deg: np.ndarray  # focal rat_a → rat_b
    egocentric_angle_b_deg: np.ndarray  # focal rat_b → rat_a
    event_start_s: float  # 0.0 when times_s are relative to start
    event_end_s: float | None  # relative to start; None if open-ended
    rat_a: str
    rat_b: str
    window_start_s: float
    window_end_s: float


def resolve_tracking_subject(animal_or_subject: str, subjects: list[str]) -> str | None:
    """Map annotation animal name or tracking id to a tracking CSV subject id."""
    token = (animal_or_subject or "").strip()
    if not token:
        return None
    lower = token.lower()
    for sid in subjects:
        if sid.lower() == lower:
            return sid
    for sid in subjects:
        sl = sid.lower()
        if lower in sl or sl in lower:
            return sid
    return None


def compute_pair_kinematics(
    tracking: TrackingService,
    rat_a: str,
    rat_b: str,
    *,
    start_unix: float,
    end_unix: float | None = None,
    pre_seconds: float = 2.0,
    post_seconds: float = 2.0,
) -> KinematicsSeries | None:
    """
    Distance (px), egocentric-frame relative speed per focal rat (px/s), and egocentric
    angles (deg) for *rat_a* → *rat_b* and *rat_b* → *rat_a*.
    """
    if not tracking.is_loaded or start_unix is None:
        return None

    subjects = tracking.subjects
    sid_a = resolve_tracking_subject(rat_a, subjects)
    sid_b = resolve_tracking_subject(rat_b, subjects)
    if sid_a is None or sid_b is None:
        return None

    end_ref = float(end_unix) if end_unix is not None else float(start_unix)
    t_min = float(start_unix) - pre_seconds
    t_max = end_ref + post_seconds

    samples = tracking.samples_in_unix_range(t_min, t_max)
    if len(samples) < 3:
        return None

    times = np.array([s[0] for s in samples], dtype=float)
    rel_t = times - float(start_unix)
    event_end_rel = (float(end_unix) - float(start_unix)) if end_unix is not None else None

    xa = np.full(len(times), np.nan)
    ya = np.full(len(times), np.nan)
    xb = np.full(len(times), np.nan)
    yb = np.full(len(times), np.nan)

    for i, (_t, pose) in enumerate(samples):
        pa = pose.get(sid_a)
        pb = pose.get(sid_b)
        if pa is None or pb is None:
            continue
        xa[i], ya[i] = pa
        xb[i], yb[i] = pb

    valid = np.isfinite(xa) & np.isfinite(ya) & np.isfinite(xb) & np.isfinite(yb)
    if np.count_nonzero(valid) < 3:
        return None

    times = times[valid]
    rel_t = rel_t[valid]
    xa, ya, xb, yb = xa[valid], ya[valid], xb[valid], yb[valid]

    distance = np.hypot(xb - xa, yb - ya)

    vax = np.gradient(xa, times)
    vay = np.gradient(ya, times)
    vbx = np.gradient(xb, times)
    vby = np.gradient(yb, times)

    vx_rel = vbx - vax
    vy_rel = vby - vay
    heading_a = np.arctan2(vay, vax)
    bearing_a = np.arctan2(yb - ya, xb - xa)
    heading_b = np.arctan2(vby, vbx)
    bearing_b = np.arctan2(ya - yb, xa - xb)
    relative_speed_a = vax * np.cos(bearing_a) + vay * np.sin(bearing_a)
    relative_speed_b = vbx * np.cos(bearing_b) + vby * np.sin(bearing_b)

    egocentric_a = _egocentric_angle_deg(xa, ya, vax, vay, xb, yb)
    egocentric_b = _egocentric_angle_deg(xb, yb, vbx, vby, xa, ya)

    return KinematicsSeries(
        times_s=rel_t,
        distance_px=distance,
        relative_speed_a_px_s=relative_speed_a,
        relative_speed_b_px_s=relative_speed_b,
        egocentric_angle_a_deg=egocentric_a,
        egocentric_angle_b_deg=egocentric_b,
        event_start_s=0.0,
        event_end_s=event_end_rel,
        rat_a=sid_a,
        rat_b=sid_b,
        window_start_s=-pre_seconds,
        window_end_s=(end_ref - float(start_unix)) + post_seconds,
    )


def _egocentric_angle_deg(
    x_f: np.ndarray,
    y_f: np.ndarray,
    vx_f: np.ndarray,
    vy_f: np.ndarray,
    x_t: np.ndarray,
    y_t: np.ndarray,
) -> np.ndarray:
    heading = np.arctan2(vy_f, vx_f)
    bearing = np.arctan2(y_t - y_f, x_t - x_f)
    ego_rad = np.arctan2(np.sin(bearing - heading), np.cos(bearing - heading))
    return np.degrees(ego_rad)
