from __future__ import annotations

from typing import Optional


def battery_guard_action(
    battery: Optional[int],
    is_flying: bool,
    critical_pct: int,
    warning_pct: int,
    rth_pct: Optional[int] = None,
) -> Optional[str]:
    if battery is None:
        return None
    if is_flying and battery <= critical_pct:
        return "critical"
    if is_flying and rth_pct is not None and battery <= rth_pct:
        return "return_home"
    if battery <= warning_pct:
        return "warning"
    return None


def desync_ground_update(
    is_flying: bool,
    height_cm: Optional[int],
    ground_since: Optional[float],
    now: float,
    ground_height_max_cm: int,
    ground_confirm_after_sec: float,
) -> tuple[Optional[float], bool]:
    if not is_flying:
        return None, False
    if height_cm is None or height_cm > ground_height_max_cm:
        return None, False
    if ground_since is None:
        return now, False
    if (now - ground_since) >= ground_confirm_after_sec:
        return None, True
    return ground_since, False
