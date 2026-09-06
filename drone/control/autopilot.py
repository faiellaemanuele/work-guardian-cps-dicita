from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

if TYPE_CHECKING:
    from drone.config import AprilTagAutopilotConfig

from drone.geometry import (
    wrap_angle_deg as _wrap_angle_deg,
    normalize_position_world as _normalize_position_world,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    z: float
    yaw_deg: float = 0.0


@dataclass
class _PoseState:
    x: float
    y: float
    z: float
    yaw_deg: float


class AprilTagAutopilot:
    def __init__(
        self,
        config: "AprilTagAutopilotConfig",
        time_source: Optional[Callable[[], float]] = None,
    ):
        if config is None:
            raise ValueError("AprilTagAutopilot richiede una configurazione valida.")

        if not config.waypoints:
            raise ValueError("AprilTagAutopilot richiede almeno un waypoint.")

        self._now = time_source if time_source is not None else time.monotonic

        self.waypoints = tuple(
            wp if isinstance(wp, Waypoint) else Waypoint(
                x=float(wp.x),
                y=float(wp.y),
                z=float(wp.z),
                yaw_deg=float(wp.yaw_deg),
            )
            for wp in config.waypoints
        )

        mission_waypoint_count = len(self.waypoints)

        home_cfg = config.home_waypoint
        if home_cfg is not None:
            home_wp = (
                home_cfg if isinstance(home_cfg, Waypoint) else Waypoint(
                    x=float(home_cfg.x),
                    y=float(home_cfg.y),
                    z=float(home_cfg.z),
                    yaw_deg=float(home_cfg.yaw_deg),
                )
            )
            self.waypoints = self.waypoints + (home_wp,)
            self.home_waypoint_index: Optional[int] = len(self.waypoints) - 1
        else:
            self.home_waypoint_index = None

        self.kp_xy = float(config.kp_xy)
        self.kp_z = float(config.kp_z)
        self.kp_yaw = float(config.kp_yaw)

        self.max_xy_speed = int(config.max_xy_speed)
        self.max_z_speed = int(config.max_z_speed)
        self.max_yaw_speed = int(config.max_yaw_speed)

        self.xy_tolerance_m = float(config.xy_tolerance_m)
        self.z_tolerance_m = float(config.z_tolerance_m)
        self.yaw_tolerance_deg = float(config.yaw_tolerance_deg)
        self.pose_timeout_sec = float(config.pose_timeout_sec)

        self.waypoint_timeout_enabled = bool(config.waypoint_timeout_enabled)
        self.waypoint_timeout_sec = float(config.waypoint_timeout_sec)

        self.z_priority_enabled = bool(config.z_priority_enabled)
        self.z_priority_enter_m = float(config.z_priority_enter_m)
        self.z_priority_exit_m = float(config.z_priority_exit_m)
        self.z_priority_keep_yaw = bool(config.z_priority_keep_yaw)

        self._z_priority_active = False

        self.yaw_offset_deg = float(config.yaw_offset_deg)

        self.current_waypoint_index = 0
        self.finished = False
        self._missing_pose_since: Optional[float] = None

        self._waypoint_active_since: Optional[float] = None

        supervision_indices: list[int] = []
        for waypoint_number in config.supervision_waypoints:
            try:
                waypoint_index = int(waypoint_number) - 1
            except (TypeError, ValueError):
                continue

            if 0 <= waypoint_index < mission_waypoint_count:
                supervision_indices.append(waypoint_index)

        self.supervision_waypoint_indices = tuple(sorted(set(supervision_indices)))
        self.supervision_stop_sec = max(0.0, float(config.supervision_stop_sec))
        self.supervision_detection_enabled = bool(config.supervision_detection_enabled)

        self._supervision_stop_active = False
        self._supervision_stop_started_at: Optional[float] = None

    @staticmethod
    def _clamp(value: float, limit: int) -> int:
        value = float(value)
        if not math.isfinite(value):
            value = 0.0
        value = int(round(value))
        limit = abs(int(limit))
        return max(-limit, min(limit, value))

    def _yaw_is_relevant(self) -> bool:
        return abs(self.kp_yaw) > 1e-9

    def _zero_command(
        self,
        *,
        reason: str = "idle",
        fault: bool = False,
        reached: bool = False,
        finished: Optional[bool] = None,
        target_index: Optional[int] = None,
        distance_xy: Optional[float] = None,
        distance_3d: Optional[float] = None,
        yaw_error_deg: Optional[float] = None,
        z_error_m: Optional[float] = None,
        xy_ok: Optional[bool] = None,
        z_ok: Optional[bool] = None,
        yaw_ok: Optional[bool] = None,
        supervision_stop_active: bool = False,
        supervision_detection_requested: bool = False,
        supervision_stop_elapsed_sec: Optional[float] = None,
        supervision_stop_remaining_sec: Optional[float] = None,
    ) -> dict[str, Any]:
        if finished is None:
            finished = self.finished
        if target_index is None:
            target_index = self.current_waypoint_index

        return {
            "lr": 0,
            "fb": 0,
            "ud": 0,
            "yaw": 0,
            "distance_xy": distance_xy,
            "distance_3d": distance_3d,
            "yaw_error_deg": yaw_error_deg,
            "z_error_m": z_error_m,
            "target_index": target_index,
            "xy_ok": None if xy_ok is None else bool(xy_ok),
            "z_ok": None if z_ok is None else bool(z_ok),
            "yaw_ok": None if yaw_ok is None else bool(yaw_ok),
            "xy_tolerance_m": float(self.xy_tolerance_m),
            "z_tolerance_m": float(self.z_tolerance_m),
            "yaw_tolerance_deg": float(self.yaw_tolerance_deg),
            "supervision_stop_active": bool(supervision_stop_active),
            "supervision_detection_requested": bool(supervision_detection_requested),
            "supervision_stop_elapsed_sec": (
                None if supervision_stop_elapsed_sec is None else float(supervision_stop_elapsed_sec)
            ),
            "supervision_stop_remaining_sec": (
                None if supervision_stop_remaining_sec is None else float(supervision_stop_remaining_sec)
            ),
            "reached": bool(reached),
            "finished": bool(finished),
            "fault": bool(fault),
            "reason": str(reason),
        }

    def _build_tracking_command(
        self,
        *,
        lr_cmd: float,
        fb_cmd: float,
        ud_cmd: float,
        yaw_cmd: float,
        distance_xy: float,
        distance_3d: float,
        yaw_error_deg: float,
        dz: float,
        xy_ok: bool,
        z_ok: bool,
        yaw_ok: bool,
        now: float,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "lr": self._clamp(lr_cmd, self.max_xy_speed),
            "fb": self._clamp(fb_cmd, self.max_xy_speed),
            "ud": self._clamp(ud_cmd, self.max_z_speed),
            "yaw": self._clamp(yaw_cmd, self.max_yaw_speed),

            "distance_xy": float(distance_xy),
            "distance_3d": float(distance_3d),
            "yaw_error_deg": float(yaw_error_deg),
            "z_error_m": float(dz),

            "target_index": int(self.current_waypoint_index),
            "xy_ok": bool(xy_ok),
            "z_ok": bool(z_ok),
            "yaw_ok": bool(yaw_ok),
            "xy_tolerance_m": float(self.xy_tolerance_m),
            "z_tolerance_m": float(self.z_tolerance_m),
            "yaw_tolerance_deg": float(self.yaw_tolerance_deg),
            **self._supervision_command_fields(now),
            "reached": False,
            "finished": False,
            "fault": False,
            "reason": reason,
        }

    def reset(self) -> None:
        self.current_waypoint_index = 0
        self.finished = False
        self._missing_pose_since = None
        self._waypoint_active_since = None
        self._z_priority_active = False
        self._clear_supervision_stop()

    def engage_return_home(self) -> bool:
        if self.home_waypoint_index is None:
            return False
        self.finished = False
        self.current_waypoint_index = int(self.home_waypoint_index)
        self._missing_pose_since = None
        self._waypoint_active_since = None
        self._z_priority_active = False
        self._clear_supervision_stop()
        return True

    def get_current_waypoint(self) -> Optional[Waypoint]:
        if self.finished or self.current_waypoint_index >= len(self.waypoints):
            return None
        return self.waypoints[self.current_waypoint_index]

    def _advance_waypoint(self) -> None:
        self.current_waypoint_index += 1
        self._waypoint_active_since = None
        if self.current_waypoint_index >= len(self.waypoints):
            self.finished = True

    def _is_supervision_waypoint_index(self, waypoint_index: int) -> bool:
        return (
            self.supervision_stop_sec > 0.0
            and int(waypoint_index) in self.supervision_waypoint_indices
        )

    def _start_supervision_stop(self, now: float) -> None:
        self._supervision_stop_active = True
        self._supervision_stop_started_at = float(now)
        self._waypoint_active_since = float(now)

    def _clear_supervision_stop(self) -> None:
        self._supervision_stop_active = False
        self._supervision_stop_started_at = None

    def cancel_supervision_stop(self) -> None:
        self._clear_supervision_stop()
        self._waypoint_active_since = None

    def _supervision_command_fields(self, now: float) -> dict[str, Any]:
        if not self._supervision_stop_active or self._supervision_stop_started_at is None:
            return {
                "supervision_stop_active": False,
                "supervision_detection_requested": False,
                "supervision_stop_elapsed_sec": None,
                "supervision_stop_remaining_sec": None,
            }

        elapsed = max(0.0, float(now) - float(self._supervision_stop_started_at))
        remaining = max(0.0, self.supervision_stop_sec - elapsed)

        return {
            "supervision_stop_active": True,
            "supervision_detection_requested": bool(self.supervision_detection_enabled),
            "supervision_stop_elapsed_sec": elapsed,
            "supervision_stop_remaining_sec": remaining,
        }

    def _extract_pose(self, pose_estimate: Mapping[str, Any]) -> _PoseState:
        position_world = pose_estimate["position_world"]
        position = _normalize_position_world(position_world)
        x, y, z = position.flatten()
        _yaw = pose_estimate.get("yaw_world_deg")
        yaw_world_deg = float(_yaw) if _yaw is not None else 0.0
        if not math.isfinite(yaw_world_deg):
            raise ValueError("yaw_world_deg deve essere un valore numerico finito.")
        return _PoseState(
            x=float(x),
            y=float(y),
            z=float(z),
            yaw_deg=float(yaw_world_deg),
        )

    def _missing_pose_command(
        self, now: float, *, timeout_reason: str, transient_reason: str
    ) -> dict[str, Any]:
        if self._missing_pose_since is None:
            self._missing_pose_since = now
        elapsed = now - self._missing_pose_since
        timed_out = elapsed > self.pose_timeout_sec
        return self._zero_command(
            reason=timeout_reason if timed_out else transient_reason,
            fault=timed_out,
        )

    def _z_priority_command(
        self,
        now: float,
        *,
        dz: float,
        z_ok: bool,
        yaw_ok: bool,
        yaw_error_deg: float,
        distance_xy: float,
        distance_3d: float,
        xy_ok: bool,
    ) -> Optional[dict[str, Any]]:
        if not self.z_priority_enabled:
            return None

        abs_dz = abs(dz)

        if self._z_priority_active:
            if abs_dz <= self.z_priority_exit_m:
                self._z_priority_active = False
        else:
            if abs_dz >= self.z_priority_enter_m:
                self._z_priority_active = True

        if not self._z_priority_active:
            return None

        fb_cmd = 0.0
        lr_cmd = 0.0

        if z_ok:
            ud_cmd = 0.0
        else:
            ud_cmd = self.kp_z * dz

        if self.z_priority_keep_yaw:
            yaw_cmd = 0.0
        else:
            if yaw_ok:
                yaw_cmd = 0.0
            else:
                yaw_cmd = (
                    self.kp_yaw * yaw_error_deg
                    if self._yaw_is_relevant()
                    else 0.0
                )

        return self._build_tracking_command(
            lr_cmd=lr_cmd,
            fb_cmd=fb_cmd,
            ud_cmd=ud_cmd,
            yaw_cmd=yaw_cmd,
            distance_xy=distance_xy,
            distance_3d=distance_3d,
            yaw_error_deg=yaw_error_deg,
            dz=dz,
            xy_ok=xy_ok,
            z_ok=z_ok,
            yaw_ok=yaw_ok,
            now=now,
            reason=(
                "supervision_stop_z_priority_tracking"
                if self._supervision_stop_active
                else "z_priority_tracking"
            ),
        )

    def compute_command(self, pose_estimate: Optional[Mapping[str, Any]]) -> dict[str, Any]:
        now = self._now()

        if self.finished:
            return self._zero_command(reason="mission_finished", finished=True)

        target = self.get_current_waypoint()
        if target is None:
            self.finished = True
            return self._zero_command(reason="mission_finished", finished=True)

        if pose_estimate is None:
            return self._missing_pose_command(
                now, timeout_reason="pose_timeout", transient_reason="pose_missing"
            )

        try:
            pose = self._extract_pose(pose_estimate)
        except Exception as exc:
            return self._missing_pose_command(
                now,
                timeout_reason=f"invalid_pose: {exc}",
                transient_reason=f"invalid_pose_transient: {exc}",
            )

        self._missing_pose_since = None

        if self._waypoint_active_since is None:
            self._waypoint_active_since = now

        dx = target.x - pose.x
        dy = target.y - pose.y
        dz = target.z - pose.z

        distance_xy = math.hypot(dx, dy)
        distance_3d = math.hypot(dx, dy, dz)

        yaw_error_deg = _wrap_angle_deg(target.yaw_deg - pose.yaw_deg)

        xy_ok = distance_xy <= self.xy_tolerance_m
        z_ok = abs(dz) <= self.z_tolerance_m
        yaw_ok = (not self._yaw_is_relevant()) or (abs(yaw_error_deg) <= self.yaw_tolerance_deg)

        reached = xy_ok and z_ok and yaw_ok

        geometry = {
            "distance_xy": float(distance_xy),
            "distance_3d": float(distance_3d),
            "yaw_error_deg": float(yaw_error_deg),
            "z_error_m": float(dz),
            "xy_ok": xy_ok,
            "z_ok": z_ok,
            "yaw_ok": yaw_ok,
        }

        if (
            self.waypoint_timeout_enabled
            and not reached
            and self._waypoint_active_since is not None
            and (now - self._waypoint_active_since) > self.waypoint_timeout_sec
        ):
            return self._zero_command(
                reason="waypoint_timeout",
                fault=True,
                target_index=self.current_waypoint_index,
                **geometry,
            )

        if self._supervision_stop_active:
            supervision_fields = self._supervision_command_fields(now)
            hold_elapsed = supervision_fields["supervision_stop_elapsed_sec"]
            hold_complete = (
                hold_elapsed is not None
                and hold_elapsed >= self.supervision_stop_sec
            )

            if hold_complete and reached:
                reached_target_index = self.current_waypoint_index
                self._clear_supervision_stop()
                self._advance_waypoint()

                return self._zero_command(
                    reason="supervision_stop_completed",
                    reached=True,
                    finished=self.finished,
                    target_index=reached_target_index,
                    **geometry,
                )

            if reached:
                return self._zero_command(
                    reason="supervision_stop",
                    reached=False,
                    finished=False,
                    target_index=self.current_waypoint_index,
                    **geometry,
                    **supervision_fields,
                )

        if reached:
            reached_target_index = self.current_waypoint_index

            if self._is_supervision_waypoint_index(reached_target_index):
                self._start_supervision_stop(now)
                return self._zero_command(
                    reason="supervision_stop_started",
                    reached=False,
                    finished=False,
                    target_index=reached_target_index,
                    **geometry,
                    **self._supervision_command_fields(now),
                )

            self._advance_waypoint()

            return self._zero_command(
                reason="waypoint_reached",
                reached=True,
                finished=self.finished,
                target_index=reached_target_index,
                **geometry,
            )

        theta = math.radians(pose.yaw_deg + self.yaw_offset_deg)

        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        error_forward = cos_t * dx + sin_t * dy
        error_left = -sin_t * dx + cos_t * dy

        zp_command = self._z_priority_command(
            now,
            dz=dz,
            z_ok=z_ok,
            yaw_ok=yaw_ok,
            yaw_error_deg=yaw_error_deg,
            distance_xy=distance_xy,
            distance_3d=distance_3d,
            xy_ok=xy_ok,
        )
        if zp_command is not None:
            return zp_command

        if xy_ok:
            fb_cmd = 0.0
            lr_cmd = 0.0
        else:
            fb_cmd = self.kp_xy * error_forward
            lr_cmd = self.kp_xy * error_left

        if z_ok:
            ud_cmd = 0.0
        else:
            ud_cmd = self.kp_z * dz

        if yaw_ok:
            yaw_cmd = 0.0
        else:
            yaw_cmd = (
                self.kp_yaw * yaw_error_deg
                if self._yaw_is_relevant()
                else 0.0
            )

        return self._build_tracking_command(
            lr_cmd=lr_cmd,
            fb_cmd=fb_cmd,
            ud_cmd=ud_cmd,
            yaw_cmd=yaw_cmd,
            distance_xy=distance_xy,
            distance_3d=distance_3d,
            yaw_error_deg=yaw_error_deg,
            dz=dz,
            xy_ok=xy_ok,
            z_ok=z_ok,
            yaw_ok=yaw_ok,
            now=now,
            reason=(
                "supervision_stop_tracking"
                if self._supervision_stop_active
                else "tracking"
            ),
        )
