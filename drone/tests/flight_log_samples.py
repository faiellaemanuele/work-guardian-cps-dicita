from __future__ import annotations

from drone.data.flight_data_logger import FlightDataLogger


class _WP:
    def __init__(self, x, y, z, yaw_deg):
        self.x = x
        self.y = y
        self.z = z
        self.yaw_deg = yaw_deg


def _pose(x, y, z, yaw, *, rejected=None):
    p = {
        "position_world": {"x": x, "y": y, "z": z},
        "yaw_world_deg": yaw,
        "source": "weighted_average",
        "source_tag_ids": [1, 3],
    }
    if rejected is not None:
        p["kalman_outlier_rejected"] = rejected
    return p


def _cmd(**kw):
    base = {
        "lr": 0, "fb": 0, "ud": 0, "yaw": 0,
        "distance_xy": 0.10, "distance_3d": 0.12, "yaw_error_deg": 2.0,
        "target_index": 0, "reached": False, "finished": False, "fault": False,
        "reason": "tracking",
        "xy_tolerance_m": 0.18, "z_tolerance_m": 0.20, "yaw_tolerance_deg": 8.0,
    }
    base.update(kw)
    return base


def logger_with_autopilot_data():
    log = FlightDataLogger()
    ts = 1000.0
    for i in range(3):
        log.log_autopilot_step(
            pose_estimate=_pose(0.1 * i, 0.0, 1.8, 90.0),
            command=_cmd(target_index=0, distance_xy=0.4 - 0.1 * i, distance_3d=0.45 - 0.1 * i),
            target=_WP(0.0, 1.35, 1.8, 90.0),
            timestamp=ts,
        )
        ts += 0.05
    log.log_autopilot_step(
        pose_estimate=_pose(0.0, 1.35, 1.8, 90.0),
        command=_cmd(target_index=0, distance_xy=0.05, distance_3d=0.06, reached=True),
        target=_WP(0.0, 1.35, 1.8, 90.0),
        timestamp=ts,
    )
    ts += 0.05
    for i in range(2):
        log.log_autopilot_step(
            pose_estimate=_pose(0.5 + 0.1 * i, 1.2, 1.8, 45.0),
            command=_cmd(target_index=1, distance_xy=0.3, distance_3d=0.32, yaw_error_deg=-5.0),
            target=_WP(1.35, 1.2, 1.8, 45.0),
            timestamp=ts,
        )
        ts += 0.05
    return log


def logger_with_pose_loss():
    log = logger_with_autopilot_data()
    ts = 1000.30
    for _ in range(3):
        log.log_autopilot_step(
            pose_estimate=None,
            command=_cmd(
                target_index=1, distance_xy=None, distance_3d=None,
                yaw_error_deg=None, reason="pose_missing",
            ),
            target=_WP(1.35, 1.2, 1.8, 45.0),
            timestamp=ts,
        )
        ts += 0.05
    log.log_autopilot_step(
        pose_estimate=None,
        command=_cmd(
            target_index=1, distance_xy=None, distance_3d=None,
            yaw_error_deg=None, reason="pose_timeout", fault=True,
        ),
        target=_WP(1.35, 1.2, 1.8, 45.0),
        timestamp=ts,
    )
    return log


def logger_with_comparison_data():
    log = FlightDataLogger()
    ts = 2000.0
    for i in range(5):
        rejected = (i == 3)
        log.log_pose_pair(
            raw_pose_estimate=_pose(0.1 * i, 0.0, 1.8, 90.0),
            filtered_pose_estimate=_pose(0.1 * i + 0.01, 0.0, 1.79, 90.0, rejected=rejected),
            timestamp=ts,
        )
        ts += 0.05
    return log


def logger_with_both():
    log = logger_with_autopilot_data()
    ts = 3000.0
    for i in range(5):
        log.log_pose_pair(
            raw_pose_estimate=_pose(0.1 * i, 0.0, 1.8, 90.0),
            filtered_pose_estimate=_pose(0.1 * i + 0.01, 0.0, 1.79, 90.0, rejected=(i == 3)),
            timestamp=ts,
        )
        ts += 0.05
    return log
