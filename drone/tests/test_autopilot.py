from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import AprilTagAutopilotConfig, AutopilotWaypointConfig
from drone.control.autopilot import AprilTagAutopilot
from common_doubles import FakeClock


def make_config(**overrides) -> AprilTagAutopilotConfig:
    base = dict(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),),
        yaw_offset_deg=0.0,
        z_priority_enabled=False,
        supervision_waypoints=(),
        supervision_stop_sec=0.0,
        pose_timeout_sec=1.0,
        xy_tolerance_m=0.1,
        home_waypoint=None,
        auto_land_on_finish=False,
    )
    base.update(overrides)
    return AprilTagAutopilotConfig(**base)


def pose(x: float, y: float, z: float, yaw_deg: float = 0.0) -> dict:
    return {
        "position_world": {"x": x, "y": y, "z": z},
        "yaw_world_deg": yaw_deg,
        "source": "test",
    }


def test_reached_single_waypoint_sets_finished():
    ap = AprilTagAutopilot(make_config(), time_source=FakeClock())
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reached"] is True
    assert cmd["finished"] is True
    assert cmd["target_index"] == 0


def test_finished_mission_returns_zero_command():
    ap = AprilTagAutopilot(make_config(), time_source=FakeClock())
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "mission_finished"
    assert cmd["finished"] is True
    assert (cmd["lr"], cmd["fb"], cmd["ud"], cmd["yaw"]) == (0, 0, 0, 0)


def test_out_of_yaw_tolerance_not_reached():
    cfg = make_config(yaw_tolerance_deg=8.0)
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, yaw_deg=45.0))
    assert cmd["reached"] is False
    assert cmd["yaw_ok"] is False
    assert ap.current_waypoint_index == 0


def test_sequential_advancement_two_waypoints():
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())

    c0 = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert c0["reached"] is True and c0["finished"] is False
    assert ap.current_waypoint_index == 1

    c1 = ap.compute_command(pose(2.0, 0.0, 1.0, 0.0))
    assert c1["reached"] is True and c1["finished"] is True


def test_supervision_stop_started_does_not_advance():
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_started"
    assert ap.current_waypoint_index == 0


def test_supervision_stop_in_progress_requests_detection():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
        supervision_detection_enabled=True,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(2.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop"
    assert cmd["supervision_detection_requested"] is True
    assert ap.current_waypoint_index == 0


def test_supervision_stop_completes_after_timeout():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(6.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_completed"
    assert cmd["reached"] is True
    assert ap.current_waypoint_index == 1


def test_supervision_stop_timer_runs_continuously_through_drift():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)

    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))

    clk.advance(2.0)
    cmd = ap.compute_command(pose(1.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_tracking"
    assert abs(cmd["supervision_stop_elapsed_sec"] - 2.0) < 1e-6
    assert ap.current_waypoint_index == 0

    clk.advance(4.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_completed"
    assert ap.current_waypoint_index == 1


def test_supervision_stop_drift_keeps_correcting():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(2.0)
    cmd = ap.compute_command(pose(1.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_tracking"
    assert cmd["reached"] is False
    assert ap.current_waypoint_index == 0


def test_supervision_stop_same_duration_for_all_waypoints():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1, 2),
        supervision_stop_sec=6.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)

    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(5.0)
    assert ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))["reason"] == "supervision_stop"
    clk.advance(1.5)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_completed"
    assert ap.current_waypoint_index == 1

    cmd = ap.compute_command(pose(2.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_started"
    clk.advance(5.0)
    assert ap.compute_command(pose(2.0, 0.0, 1.0, 0.0))["reason"] == "supervision_stop"
    clk.advance(1.5)
    cmd = ap.compute_command(pose(2.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "supervision_stop_completed"
    assert cmd["finished"] is True


def test_supervision_stop_with_z_drift_enters_z_priority():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
        z_priority_enabled=True,
        z_priority_enter_m=0.30,
        z_priority_exit_m=0.22,
        z_priority_keep_yaw=True,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(1.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 2.0, 0.0))
    assert cmd["reason"] == "supervision_stop_z_priority_tracking"
    assert cmd["lr"] == 0 and cmd["fb"] == 0
    assert cmd["ud"] != 0
    assert ap.current_waypoint_index == 0
    assert ap._supervision_stop_active is True


def test_home_waypoint_appended_in_sequence():
    home = AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0)
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=1.0, y=0.0, z=1.0, yaw_deg=0.0),),
        home_waypoint=home,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    assert len(ap.waypoints) == 2
    assert ap.waypoints[-1].x == 0.0 and ap.waypoints[-1].y == 0.0
    assert ap.waypoints[-1].z == 1.0
    assert ap.home_waypoint_index == 1


def test_home_waypoint_none_no_append():
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=1.0, y=0.0, z=1.0, yaw_deg=0.0),),
        home_waypoint=None,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    assert len(ap.waypoints) == 1
    assert ap.home_waypoint_index is None


def test_home_waypoint_terminates_mission_on_reached():
    home = AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0)
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),),
        home_waypoint=home,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(2.0, 0.0, 1.0, 0.0))
    assert cmd["reached"] is True and cmd["finished"] is False
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reached"] is True
    assert cmd["finished"] is True
    assert cmd["target_index"] == ap.home_waypoint_index


def test_engage_return_home_jumps_to_home_waypoint():
    home = AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0)
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=1.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        home_waypoint=home,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    assert ap.current_waypoint_index == 0
    assert ap.engage_return_home() is True
    assert ap.current_waypoint_index == ap.home_waypoint_index
    assert ap.finished is False
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reached"] is True and cmd["finished"] is True
    assert cmd["target_index"] == ap.home_waypoint_index


def test_engage_return_home_without_home_returns_false():
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=1.0, y=0.0, z=1.0, yaw_deg=0.0),),
        home_waypoint=None,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    assert ap.engage_return_home() is False
    assert ap.current_waypoint_index == 0
    assert ap.finished is False


def test_engage_return_home_resets_finished_mission():
    home = AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0)
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),),
        home_waypoint=home,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    ap.compute_command(pose(2.0, 0.0, 1.0, 0.0))
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert ap.finished is True
    assert ap.engage_return_home() is True
    assert ap.finished is False
    assert ap.current_waypoint_index == ap.home_waypoint_index


def test_config_rejects_home_waypoint_with_unsafe_z():
    raised = False
    try:
        AprilTagAutopilotConfig(
            home_waypoint=AutopilotWaypointConfig(x=0.0, y=0.0, z=0.0, yaw_deg=0.0),
        )
    except ValueError:
        raised = True
    assert raised is True


def test_config_accepts_home_waypoint_with_safe_z():
    cfg = AprilTagAutopilotConfig(
        home_waypoint=AutopilotWaypointConfig(x=0.0, y=0.0, z=0.5, yaw_deg=0.0),
    )
    assert cfg.home_waypoint is not None and cfg.home_waypoint.z == 0.5


def test_config_rejects_invalid_z_priority_hysteresis():
    raised = False
    try:
        AprilTagAutopilotConfig(z_priority_enter_m=0.20, z_priority_exit_m=0.30)
    except ValueError:
        raised = True
    assert raised is True


def test_config_accepts_valid_z_priority_hysteresis():
    cfg = AprilTagAutopilotConfig(z_priority_enter_m=0.30, z_priority_exit_m=0.22)
    assert cfg.z_priority_exit_m < cfg.z_priority_enter_m


def test_config_rejects_non_positive_tolerance():
    for override in (
        {"xy_tolerance_m": 0.0},
        {"z_tolerance_m": -0.1},
        {"yaw_tolerance_deg": 0.0},
    ):
        raised = False
        try:
            AprilTagAutopilotConfig(**override)
        except ValueError:
            raised = True
        assert raised is True, f"tolleranza non positiva accettata: {override}"


def test_config_accepts_positive_tolerances():
    cfg = AprilTagAutopilotConfig(xy_tolerance_m=0.15, z_tolerance_m=0.20, yaw_tolerance_deg=4.0)
    assert min(cfg.xy_tolerance_m, cfg.z_tolerance_m, cfg.yaw_tolerance_deg) > 0


def test_config_rejects_timeout_not_exceeding_hold():
    raised = False
    try:
        AprilTagAutopilotConfig(
            supervision_waypoints=(1, 2),
            supervision_stop_sec=15.0,
            waypoint_timeout_enabled=True,
            waypoint_timeout_sec=12.0,
        )
    except ValueError:
        raised = True
    assert raised is True


def test_config_accepts_timeout_exceeding_hold():
    cfg = AprilTagAutopilotConfig(
        supervision_waypoints=(1, 2),
        supervision_stop_sec=15.0,
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=20.0,
    )
    assert cfg.waypoint_timeout_sec == 20.0


def test_config_default_waypoints_is_empty():
    assert AprilTagAutopilotConfig().waypoints == ()


def test_autopilot_requires_at_least_one_waypoint():
    raised = False
    try:
        AprilTagAutopilot(AprilTagAutopilotConfig(waypoints=()))
    except ValueError:
        raised = True
    assert raised is True


def test_z_priority_enter_zeroes_xy():
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=2.0, yaw_deg=0.0),),
        z_priority_enabled=True,
        z_priority_enter_m=0.30,
        z_priority_exit_m=0.22,
        z_priority_keep_yaw=True,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(1.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "z_priority_tracking"
    assert cmd["lr"] == 0 and cmd["fb"] == 0
    assert cmd["ud"] != 0
    assert ap._z_priority_active is True


def test_z_priority_stays_active_in_hysteresis_band():
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=2.0, yaw_deg=0.0),),
        z_priority_enabled=True,
        z_priority_enter_m=0.30,
        z_priority_exit_m=0.22,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    ap.compute_command(pose(1.0, 0.0, 1.0, 0.0))
    cmd = ap.compute_command(pose(1.0, 0.0, 1.75, 0.0))
    assert ap._z_priority_active is True
    assert cmd["lr"] == 0 and cmd["fb"] == 0


def test_z_priority_exits_below_exit_threshold():
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=2.0, yaw_deg=0.0),),
        z_priority_enabled=True,
        z_priority_enter_m=0.30,
        z_priority_exit_m=0.22,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    ap.compute_command(pose(1.0, 0.0, 1.0, 0.0))
    cmd = ap.compute_command(pose(1.0, 0.0, 1.90, 0.0))
    assert ap._z_priority_active is False
    assert cmd["reason"] == "tracking"
    assert cmd["lr"] != 0 or cmd["fb"] != 0


def test_pose_missing_single_is_not_fault():
    ap = AprilTagAutopilot(make_config(pose_timeout_sec=1.0), time_source=FakeClock())
    cmd = ap.compute_command(None)
    assert cmd["reason"] == "pose_missing"
    assert cmd["fault"] is False


def test_pose_timeout_triggers_fault():
    clk = FakeClock()
    ap = AprilTagAutopilot(make_config(pose_timeout_sec=1.0), time_source=clk)
    ap.compute_command(None)
    clk.advance(1.5)
    cmd = ap.compute_command(None)
    assert cmd["reason"] == "pose_timeout"
    assert cmd["fault"] is True


def test_pose_recovery_resets_timeout():
    clk = FakeClock()
    ap = AprilTagAutopilot(make_config(pose_timeout_sec=1.0), time_source=clk)
    ap.compute_command(None)
    clk.advance(1.5)
    ap.compute_command(None)
    clk.advance(0.1)
    ap.compute_command(pose(5.0, 5.0, 1.0, 0.0))
    clk.advance(0.1)
    cmd = ap.compute_command(None)
    assert cmd["reason"] == "pose_missing"
    assert cmd["fault"] is False


def test_sign_target_ahead_drives_forward():
    cfg = make_config(waypoints=(AutopilotWaypointConfig(x=1.0, y=0.0, z=1.0, yaw_deg=0.0),))
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["fb"] > 0
    assert cmd["lr"] == 0


def test_sign_lateral_error_maps_to_lr():
    cfg = make_config(waypoints=(AutopilotWaypointConfig(x=0.0, y=1.0, z=1.0, yaw_deg=0.0),))
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["lr"] != 0
    assert cmd["fb"] == 0


def test_commands_saturated_to_limits():
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=100.0, y=0.0, z=50.0, yaw_deg=0.0),),
        max_xy_speed=20,
        max_z_speed=35,
        z_priority_enabled=False,
    )
    ap = AprilTagAutopilot(cfg, time_source=FakeClock())
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert -20 <= cmd["fb"] <= 20
    assert -20 <= cmd["lr"] <= 20
    assert -35 <= cmd["ud"] <= 35


def test_yaw_offset_shifts_body_frame_consistently():
    cfg_a = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.2, y=0.0, z=1.0, yaw_deg=0.0),),
        yaw_offset_deg=0.0,
    )
    cfg_b = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.2, y=0.0, z=1.0, yaw_deg=-180.0),),
        yaw_offset_deg=180.0,
    )
    ap_a = AprilTagAutopilot(cfg_a, time_source=FakeClock())
    ap_b = AprilTagAutopilot(cfg_b, time_source=FakeClock())
    cmd_a = ap_a.compute_command(pose(0.0, 0.0, 1.0, yaw_deg=0.0))
    cmd_b = ap_b.compute_command(pose(0.0, 0.0, 1.0, yaw_deg=-180.0))
    assert cmd_a["fb"] > 0 and cmd_a["lr"] == 0
    assert cmd_b["fb"] == cmd_a["fb"]
    assert cmd_b["lr"] == cmd_a["lr"]


def test_non_finite_yaw_treated_as_transient_invalid_pose():
    clk = FakeClock()
    ap = AprilTagAutopilot(make_config(pose_timeout_sec=1.0), time_source=clk)

    bad = pose(0.0, 0.0, 1.0, 0.0)
    bad["yaw_world_deg"] = float("inf")
    cmd = ap.compute_command(bad)
    assert cmd["reason"].startswith("invalid_pose_transient")
    assert cmd["fault"] is False
    assert (cmd["lr"], cmd["fb"], cmd["ud"], cmd["yaw"]) == (0, 0, 0, 0)

    clk.advance(1.5)
    worse = pose(0.0, 0.0, 1.0, 0.0)
    worse["yaw_world_deg"] = float("nan")
    cmd2 = ap.compute_command(worse)
    assert cmd2["fault"] is True
    assert cmd2["reason"].startswith("invalid_pose")


def test_supervision_z_priority_recovers_to_xy_tracking():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=2.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
        z_priority_enabled=True,
        z_priority_enter_m=0.30,
        z_priority_exit_m=0.22,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))

    clk.advance(1.0)
    c1 = ap.compute_command(pose(0.5, 0.0, 2.0, 0.0))
    assert c1["reason"] == "supervision_stop_z_priority_tracking"
    assert c1["lr"] == 0 and c1["fb"] == 0 and c1["ud"] != 0
    assert ap._z_priority_active is True

    clk.advance(0.5)
    c2 = ap.compute_command(pose(0.5, 0.0, 1.05, 0.0))
    assert ap._z_priority_active is False
    assert c2["reason"] == "supervision_stop_tracking"
    assert c2["fb"] != 0 or c2["lr"] != 0
    assert ap._supervision_stop_active is True
    assert ap.current_waypoint_index == 0


def test_waypoint_timeout_triggers_fault_when_stuck():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=5.0, y=0.0, z=1.0, yaw_deg=0.0),),
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=10.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(11.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["reason"] == "waypoint_timeout"
    assert cmd["fault"] is True
    assert (cmd["lr"], cmd["fb"], cmd["ud"], cmd["yaw"]) == (0, 0, 0, 0)


def test_waypoint_timeout_does_not_fire_when_reached_in_time():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),),
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=10.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    clk.advance(2.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["fault"] is False
    assert cmd["reached"] is True


def test_waypoint_timeout_does_not_fire_during_supervision_stop():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),),
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=10.0,
        supervision_waypoints=(1,),
        supervision_stop_sec=8.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)

    ap.compute_command(pose(3.0, 0.0, 1.0, 0.0))
    clk.advance(9.0)
    lontano = ap.compute_command(pose(3.0, 0.0, 1.0, 0.0))
    assert lontano["fault"] is False

    avvio = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert avvio["reason"] == "supervision_stop_started"

    clk.advance(2.0)
    durante = ap.compute_command(pose(0.6, 0.0, 1.0, 0.0))
    assert durante["reason"] == "supervision_stop_tracking"
    assert durante["fault"] is False
    assert ap._supervision_stop_active is True


def test_waypoint_timeout_resets_on_advance():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(
            AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),
            AutopilotWaypointConfig(x=5.0, y=0.0, z=1.0, yaw_deg=0.0),
        ),
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=10.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    clk.advance(8.0)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert ap.current_waypoint_index == 1
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(8.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["fault"] is False
    assert cmd["reason"] == "tracking"


def test_waypoint_timeout_resets_on_resume():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=5.0, y=0.0, z=1.0, yaw_deg=0.0),),
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=10.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(9.0)
    ap.cancel_supervision_stop()
    clk.advance(9.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["fault"] is False
    assert cmd["reason"] == "tracking"


def test_waypoint_timeout_can_be_disabled():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=5.0, y=0.0, z=1.0, yaw_deg=0.0),),
        waypoint_timeout_enabled=False,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    clk.advance(10_000.0)
    cmd = ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert cmd["fault"] is False
    assert cmd["reason"] == "tracking"


def test_waypoint_timeout_catches_supervision_stall():
    clk = FakeClock()
    cfg = make_config(
        waypoints=(AutopilotWaypointConfig(x=0.0, y=0.0, z=1.0, yaw_deg=0.0),),
        supervision_waypoints=(1,),
        supervision_stop_sec=5.0,
        waypoint_timeout_enabled=True,
        waypoint_timeout_sec=12.0,
    )
    ap = AprilTagAutopilot(cfg, time_source=clk)
    ap.compute_command(pose(0.0, 0.0, 1.0, 0.0))
    assert ap._supervision_stop_active is True
    clk.advance(13.0)
    cmd = ap.compute_command(pose(1.0, 0.0, 1.0, 0.0))
    assert cmd["fault"] is True
    assert cmd["reason"] == "waypoint_timeout"



def _wp(x, y, z=1.0, yaw=0.0):
    return AutopilotWaypointConfig(x=x, y=y, z=z, yaw_deg=yaw)


def test_la_home_non_puo_diventare_un_waypoint_di_supervisione():
    ap = AprilTagAutopilot(
        make_config(
            waypoints=(_wp(0.0, 0.0), _wp(1.0, 0.0)),
            home_waypoint=_wp(0.0, 0.0, 1.5),
            supervision_waypoints=(3,),
            supervision_stop_sec=5.0,
        ),
        time_source=FakeClock(),
    )

    assert len(ap.waypoints) == 3
    assert ap.home_waypoint_index == 2
    assert ap.supervision_waypoint_indices == ()


def test_gli_indici_di_supervisione_validi_restano():
    ap = AprilTagAutopilot(
        make_config(
            waypoints=(_wp(0.0, 0.0), _wp(1.0, 0.0)),
            home_waypoint=_wp(0.0, 0.0, 1.5),
            supervision_waypoints=(1, 2),
            supervision_stop_sec=5.0,
        ),
        time_source=FakeClock(),
    )

    assert ap.supervision_waypoint_indices == (0, 1)


def test_il_rientro_alla_home_non_apre_una_sosta_di_supervisione():
    clock = FakeClock()
    ap = AprilTagAutopilot(
        make_config(
            waypoints=(_wp(0.0, 0.0), _wp(1.0, 0.0)),
            home_waypoint=_wp(5.0, 5.0, 1.5),
            supervision_waypoints=(3,),
            supervision_stop_sec=5.0,
        ),
        time_source=clock,
    )

    assert ap.engage_return_home() is True
    comando = ap.compute_command(pose(5.0, 5.0, 1.5, 0.0))

    assert comando["supervision_stop_active"] is False
    assert comando["reached"] is True
    assert comando["finished"] is True


def _run_all() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((name, exc))
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[ OK ] {name}")

    print("-" * 60)
    print(f"Totale: {len(tests)}  |  passati: {passed}  |  falliti: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_all())
