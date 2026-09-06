from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable, Optional

import cv2
import numpy as np

from drone.ui.video import panels
from drone.ui.video.mission_map import MissionMapState
from drone.ui.video.stdout_redirect import StdoutRedirect
from drone.geometry import normalize_position_world

LOGGER = logging.getLogger(__name__)


class Dashboard:
    def __init__(
        self,
        config,
        render_interval_sec: float = 0.0,
        time_source: Optional[Callable[[], float]] = None,
    ):
        self.config = config
        self.enabled = bool(getattr(config, "enabled", False))
        self._now = time_source if time_source is not None else time.monotonic

        max_lines = int(getattr(config, "max_lines", 500)) if config is not None else 500

        self._terminal_lines: deque[str] = deque(maxlen=max_lines)
        self._alert_lines: deque[str] = deque(maxlen=max_lines)

        self._autonomy_engaged = False

        self._stdout_redirect: Optional[StdoutRedirect] = None

        self._autopilot_command: dict = {}

        self._manual_command: dict = {}

        self._state_active = False

        self._mission_map: Optional[MissionMapState] = None
        self._map_yaw_offset_deg = 0.0

        self._scenario_name: Optional[str] = None

        self._drone_xy: Optional[tuple[float, float]] = None
        self._drone_yaw_deg = 0.0
        self._drone_pose_fresh = False

        self._render_error_logged = False

        self._panels_cache: Optional[np.ndarray] = None
        self._panels_cache_height: Optional[int] = None
        self._panels_cache_at = 0.0
        self._render_interval_sec = float(render_interval_sec or 0.0)

    def configure_mission(
        self,
        waypoints,
        home_index: Optional[int] = None,
        yaw_offset_deg: float = 0.0,
        site_area=(),
        world_tags=None,
    ) -> None:
        if not self.enabled or not waypoints:
            return
        self._mission_map = MissionMapState(
            waypoints,
            home_index=home_index,
            site_area=site_area or (),
            world_tags=world_tags,
        )
        self._map_yaw_offset_deg = float(yaw_offset_deg)

    def set_scenario_name(self, scenario_name: Optional[str]) -> None:
        if not self.enabled:
            return
        self._scenario_name = scenario_name or None

    def set_autopilot(self, command) -> None:
        if not self.enabled:
            return
        self._state_active = True
        self._autonomy_engaged = True
        self._autopilot_command = dict(command or {})
        if self._mission_map is not None:
            self._mission_map.update_command(self._autopilot_command)

    def clear_autopilot(self) -> None:
        if not self.enabled:
            return
        self._state_active = False
        self._autopilot_command = {}
        if self._mission_map is not None:
            self._mission_map.set_autonomy_inactive()

    def set_manual_command(self, command) -> None:
        if not self.enabled:
            return
        self._manual_command = dict(command or {})

    def set_pose(self, pose_estimate, fresh: bool = False) -> None:
        if not self.enabled:
            return
        self._drone_pose_fresh = bool(fresh)
        if pose_estimate is None:
            return
        try:
            position = normalize_position_world(pose_estimate["position_world"])
            x, y = (float(v) for v in position.flatten()[:2])
            yaw = pose_estimate.get("yaw_world_deg")
            self._drone_xy = (x, y)
            self._drone_yaw_deg = float(yaw) if yaw is not None else 0.0
        except Exception:
            pass

    def log_alert(self, line: str) -> None:
        if not self.enabled:
            return
        for part in str(line).split("\n"):
            self._alert_lines.append(part)

    def clear_alerts(self) -> None:
        if not self.enabled:
            return
        self._alert_lines.clear()

    def clear_terminal(self) -> None:
        if not self.enabled:
            return
        self._terminal_lines.clear()

    def log_terminal(self, line: str) -> None:
        if not self.enabled:
            return
        for part in str(line).split("\n"):
            self._terminal_lines.append(part)

    def make_stdout_redirect(self, original) -> StdoutRedirect:
        self._stdout_redirect = StdoutRedirect(original, self.log_terminal, echo_to_original=False)
        return self._stdout_redirect

    def scale_video(self, video_frame: np.ndarray) -> np.ndarray:
        if not self.enabled or video_frame is None:
            return video_frame
        try:
            video_w, video_h = getattr(self.config, "video_size", (1280, 960))
            video_w, video_h = int(video_w), int(video_h)
            if (video_frame.shape[1], video_frame.shape[0]) == (video_w, video_h):
                return video_frame
            interpolation = (
                cv2.INTER_CUBIC if video_w >= video_frame.shape[1] else cv2.INTER_AREA
            )
            return cv2.resize(video_frame, (video_w, video_h), interpolation=interpolation)
        except (cv2.error, ValueError):
            self._log_compose_error()
            return video_frame

    def attach_panels(self, video_frame: np.ndarray) -> np.ndarray:
        if not self.enabled or video_frame is None:
            return video_frame
        try:
            panels = self._panels_for_height(video_frame.shape[0])
            if panels is None:
                return video_frame
            return np.hstack((video_frame, panels))
        except (cv2.error, ValueError):
            self._log_compose_error()
            return video_frame

    def _log_compose_error(self) -> None:
        if not self._render_error_logged:
            self._render_error_logged = True
            LOGGER.warning("Composizione del cruscotto non riuscita.", exc_info=True)

    def _panels_for_height(self, total_height: int) -> Optional[np.ndarray]:
        interval = self._render_interval_sec
        cached = self._panels_cache
        if (
            cached is not None
            and self._panels_cache_height == total_height
            and interval > 0.0
            and (self._now() - self._panels_cache_at) < interval
        ):
            return cached

        panels = self._render_to_image(total_height)
        if panels is None:
            return cached if self._panels_cache_height == total_height else None

        self._panels_cache = panels
        self._panels_cache_height = total_height
        self._panels_cache_at = self._now()
        return panels

    def _render_to_image(self, total_height: int) -> Optional[np.ndarray]:
        total_height = int(total_height)
        pw = int(getattr(self.config, "panel_width", 940))
        gap = max(0, int(getattr(self.config, "gap_px", 6)))
        log_h = max(1, int(getattr(self.config, "log_row_height", 262)))
        map_h = total_height - gap - log_h
        if map_h < 120:
            map_h = max(1, int(total_height * 0.5))
            log_h = max(1, total_height - gap - map_h)

        left_w = (pw - gap) // 2
        right_w = pw - gap - left_w

        map_img = panels.map_panel(
            self.config, map_h,
            mission_map=self._mission_map,
            scenario_name=self._scenario_name,
            drone_xy=self._drone_xy,
            drone_heading_deg=self._drone_yaw_deg + self._map_yaw_offset_deg,
            drone_pose_fresh=self._drone_pose_fresh,
            drone_command=self._drone_command(),
            axes=self._tolerance_axes(),
        )
        term_img = panels.text_panel(
            self.config,
            getattr(self.config, "terminal_title", "Terminale drone"),
            list(self._terminal_lines), log_h, engaged=self._autonomy_engaged,
            line_color=panels.terminal_line_color, width=left_w,
        )
        alerts_img = panels.text_panel(
            self.config,
            getattr(self.config, "alerts_title", "Log degli alert"),
            list(self._alert_lines), log_h, engaged=self._autonomy_engaged,
            line_color=panels.alert_line_color, width=right_w,
        )

        bg = np.array(panels.BG[::-1], dtype=np.uint8)
        log_row = term_img
        if gap:
            log_row = np.hstack(
                (term_img, np.full((log_h, gap, 3), bg, dtype=np.uint8), alerts_img)
            )
        else:
            log_row = np.hstack((term_img, alerts_img))

        parts = [map_img]
        if gap:
            parts.append(np.full((gap, pw, 3), bg, dtype=np.uint8))
        parts.append(log_row)
        column = np.vstack(parts)

        if column.shape[0] != total_height:
            if column.shape[0] > total_height:
                column = column[:total_height]
            else:
                pad = np.full((total_height - column.shape[0], pw, 3), panels.BG[::-1], dtype=np.uint8)
                column = np.vstack((column, pad))
        return column

    def close(self) -> None:
        return

    def _tolerance_axes(self):
        cmd = self._autopilot_command if self._state_active else {}

        def mag(v):
            return None if v is None else abs(v)

        return (
            ("XY", cmd.get("distance_xy"), cmd.get("xy_tolerance_m"), cmd.get("xy_ok"), "m", 2),
            ("Z", mag(cmd.get("z_error_m")), cmd.get("z_tolerance_m"), cmd.get("z_ok"), "m", 2),
            ("Yaw", mag(cmd.get("yaw_error_deg")), cmd.get("yaw_tolerance_deg"), cmd.get("yaw_ok"), "°", 1),
        )

    def _drone_command(self) -> dict:
        if not self._state_active:
            return self._manual_command
        if self._autopilot_command.get("supervision_stop_active", False):
            return {}
        return self._autopilot_command
