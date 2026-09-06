from __future__ import annotations

import logging
import sys
import threading
import time
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

from drone.config import APP_CONFIG
from drone.ui.video import overlay
from drone.ui.console import print_event

if TYPE_CHECKING:
    from drone.config import AppConfig
    from drone.data.flight_data_logger import FlightDataLogger
    from drone.hardware.tello_controller import RealTelloController
    from drone.perception.pose_estimator import CameraPoseEstimator
    from drone.perception.pose_filter import PositionKalmanFilter

LOGGER = logging.getLogger(__name__)

VIDEO_WINDOW_TITLE = APP_CONFIG.video_window_title


class VisionLoop:
    def __init__(
        self,
        config: "AppConfig",
        detectors,
        pose_estimator: Optional[CameraPoseEstimator],
        flight_data_logger: Optional[FlightDataLogger] = None,
        pose_filter: Optional[PositionKalmanFilter] = None,
    ):
        self.detectors = list(detectors or [])

        self.pose_estimator = pose_estimator

        self.frame_timeout_sec = config.frame_timeout_sec

        self.frame_from_controller_is_rgb = config.frame_from_controller_is_rgb

        self.status_refresh_sec = config.status_refresh_sec

        self.last_frame_received_at: Optional[float] = None

        self.last_status_refresh_at = 0.0

        self.cached_status = {
            "connected": False,
            "flying": False,
            "battery": None,
        }

        self.flight_data_logger = flight_data_logger

        self.pose_filter = pose_filter

        self.pose_valid_for_sec = float(config.pose_valid_for_sec)

        self.last_pose_estimate_at = 0.0

        self.detection_interval_sec = float(config.detection_interval_sec)
        self._last_detection_run_at = 0.0
        self._cached_detections: list = []

        self.video_fade_in_sec = float(config.video_fade_in_sec)
        self._first_display_at = None

        self.safety_net_verdict_banner_sec = float(config.safety_net_verdict_banner_sec)
        self._safety_net_verdict = None
        self._safety_net_verdict_at = 0.0

        self._detection_lock = threading.Lock()
        self._pending_analysis_frame = None
        self._detection_active = False
        self._detection_stop_event = threading.Event()
        self._detection_thread: Optional[threading.Thread] = None

        self.last_filtered_pose_estimate = None

        self.last_autopilot_command = None

        self._warning_repeat_after_sec = float(config.vision_warning_repeat_after_sec)
        self._warning_last_logged_at: dict[str, float] = {}

    def _throttled_warning(self, key: str, message: str) -> None:
        now = time.monotonic()
        last = self._warning_last_logged_at.get(key, 0.0)
        if now - last >= self._warning_repeat_after_sec:
            self._warning_last_logged_at[key] = now
            LOGGER.warning(message, exc_info=sys.exc_info()[0] is not None)

    def _normalize_frame_for_opencv(self, frame):
        if self.frame_from_controller_is_rgb:
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        return frame

    def _refresh_status(self, controller: RealTelloController):
        now = time.monotonic()
        if (now - self.last_status_refresh_at) < self.status_refresh_sec:
            return

        self.last_status_refresh_at = now
        previous_battery = self.cached_status.get("battery")
        try:
            status = controller.get_status()
            new_battery = status.get("battery")
            if new_battery is None:
                if previous_battery is not None:
                    self._throttled_warning(
                        "battery_read",
                        "Lettura batteria non disponibile: conservo l'ultimo valore noto "
                        f"({previous_battery}%) per la guardia di sicurezza.",
                    )
                    new_battery = previous_battery
                else:
                    self._throttled_warning(
                        "battery_read_blind",
                        "Lettura batteria non disponibile e nessun valore precedente: "
                        "guardia di sicurezza batteria momentaneamente inattiva.",
                    )
            self.cached_status = {
                "connected": status.get("connected", False),
                "flying": status.get("flying", False),
                "battery": new_battery,
            }
        except Exception:
            self._throttled_warning(
                "status_refresh",
                "Aggiornamento stato drone fallito: conservo l'ultima batteria nota "
                f"({previous_battery}%).",
            )
            self.cached_status = {
                "connected": False,
                "flying": False,
                "battery": previous_battery,
            }

    def update_autopilot_overlay(self, command):
        self.last_autopilot_command = dict(command or {})

    def clear_autopilot_overlay(self):
        self.last_autopilot_command = None

    def set_safety_net_verdict(self, verdict) -> None:
        if not verdict or self.safety_net_verdict_banner_sec <= 0.0:
            return
        self._safety_net_verdict = dict(verdict)
        self._safety_net_verdict_at = time.monotonic()

    def _maybe_draw_safety_net_banner(self, frame) -> None:
        verdict = self._safety_net_verdict
        if verdict is None:
            return
        if (time.monotonic() - self._safety_net_verdict_at) > self.safety_net_verdict_banner_sec:
            self._safety_net_verdict = None
            return
        overlay.draw_safety_net_verdict_banner(frame, verdict)

    def autopilot_requests_detection(self) -> bool:
        command = self.last_autopilot_command or {}
        return bool(command.get("supervision_detection_requested", False))

    def get_visible_tag_ids(self) -> set[int]:
        if self.pose_estimator is None:
            return set()
        results = getattr(self.pose_estimator, "last_pose_results", None) or []
        tag_ids: set[int] = set()
        for result in results:
            tag_id = result.get("tag_id")
            if tag_id is not None:
                tag_ids.add(int(tag_id))
        return tag_ids

    def get_detected_model_names(self) -> set[str]:
        with self._detection_lock:
            snapshot = self._cached_detections
        names: set[str] = set()
        for entry in snapshot or []:
            if entry.get("detections"):
                name = entry.get("name")
                if name is not None:
                    names.add(name)
        return names

    def get_detection_summary(self) -> list[dict]:
        with self._detection_lock:
            snapshot = self._cached_detections
        summary: list[dict] = []
        for entry in snapshot or []:
            model_name = entry.get("name")
            for det in entry.get("detections") or []:
                summary.append(
                    {
                        "model": model_name,
                        "label": det.get("label"),
                        "confidence": det.get("confidence"),
                    }
                )
        return summary

    def get_cached_detections_snapshot(self) -> list:
        with self._detection_lock:
            return self._cached_detections

    def _log_latest_pose_estimate(self):
        if self.pose_estimator is None:
            return

        raw_pose = self.pose_estimator.last_fused_body_pose
        if raw_pose is None:
            raw_pose = self.pose_estimator.last_fused_camera_pose

        if raw_pose is None:
            self.last_filtered_pose_estimate = None
            return

        filtered_pose = raw_pose

        if self.pose_filter is not None:
            try:
                kalman_pose = self.pose_filter.filter_pose_estimate(raw_pose)
                if kalman_pose is not None:
                    filtered_pose = kalman_pose
            except Exception:
                LOGGER.exception("Errore durante il filtraggio Kalman: si usa la posa grezza.")

        self.last_filtered_pose_estimate = filtered_pose
        self.last_pose_estimate_at = time.monotonic()

        if self.flight_data_logger is not None:
            self.flight_data_logger.log_pose_pair(
                raw_pose_estimate=raw_pose,
                filtered_pose_estimate=filtered_pose,
            )

    def get_latest_pose_estimate(self):
        if self.last_filtered_pose_estimate is None:
            return None

        age = time.monotonic() - self.last_pose_estimate_at
        if age <= self.pose_valid_for_sec:
            return self.last_filtered_pose_estimate
        return None

    def _run_multi_model_detections(self, analysis_frame):
        results = []
        for item in self.detectors:
            try:
                _, detections = item["detector"].detect(analysis_frame)
            except Exception:
                self._throttled_warning(
                    f"detector_inference:{item['name']}",
                    f"Detector '{item['name']}': errore di inferenza sul frame corrente.",
                )
                continue
            results.append({"name": item["name"], "color": item["color"], "detections": detections})
        return results

    def _ensure_detection_thread(self):
        if self._detection_thread is not None and self._detection_thread.is_alive():
            return
        self._detection_stop_event.clear()
        self._detection_thread = threading.Thread(
            target=self._detection_worker,
            name="yolo-detection",
            daemon=True,
        )
        self._detection_thread.start()

    def _detection_worker(self):
        while not self._detection_stop_event.is_set():
            with self._detection_lock:
                active = self._detection_active
                frame = self._pending_analysis_frame

            if not active or frame is None:
                self._detection_stop_event.wait(0.005)
                continue

            if self.detection_interval_sec > 0.0 and self._last_detection_run_at != 0.0:
                elapsed = time.monotonic() - self._last_detection_run_at
                if elapsed < self.detection_interval_sec:
                    self._detection_stop_event.wait(
                        min(self.detection_interval_sec - elapsed, 0.05)
                    )
                    continue

            try:
                results = self._run_multi_model_detections(frame)
            except Exception:
                self._throttled_warning(
                    "detection_worker",
                    "Object detection multi-modello fallita nel thread dedicato.",
                )
                results = None

            if results is not None:
                with self._detection_lock:
                    if self._detection_active:
                        self._cached_detections = results
                self._last_detection_run_at = time.monotonic()

    def stop(self):
        self._detection_stop_event.set()
        thread = self._detection_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            if thread.is_alive():
                LOGGER.warning(
                    "Thread di riconoscimento ancora attivo dopo l'attesa di chiusura: "
                    "resta registrato per non avviarne un secondo."
                )
                return
        self._detection_thread = None

    def _video_stream_alive(self) -> bool:
        if self.last_frame_received_at is None:
            self.last_frame_received_at = time.monotonic()
            return True
        elapsed = time.monotonic() - self.last_frame_received_at
        if elapsed >= self.frame_timeout_sec:
            print_event(f"Flusso video interrotto: nessun frame da {elapsed:.1f} s", prefix="ERRORE")
            return False
        return True

    def _pose_estimation_available(self) -> bool:
        return self.pose_estimator is not None and self.pose_estimator.enabled

    def _undistorted_frame(self, frame):
        if not self._pose_estimation_available():
            return frame, False
        try:
            undistorted_frame = self.pose_estimator.undistort_frame(frame)
            if undistorted_frame is not None:
                return undistorted_frame, True
        except Exception:
            self._throttled_warning(
                "undistort",
                "Correzione della distorsione fallita sul frame corrente.",
            )
        return frame, False

    def _publish_analysis_frame(self, analysis_frame, display_frame, detection_is_active) -> None:
        if not detection_is_active:
            with self._detection_lock:
                self._detection_active = False
                self._pending_analysis_frame = None
                self._cached_detections = []
            return

        self._ensure_detection_thread()
        with self._detection_lock:
            self._detection_active = True
            self._pending_analysis_frame = analysis_frame
            cached_snapshot = self._cached_detections
        try:
            overlay.draw_cached_detections(display_frame, cached_snapshot)
        except Exception:
            self._throttled_warning(
                "draw_detections",
                "Disegno delle detection fallito sul frame corrente.",
            )

    def _estimate_pose(self, analysis_frame, display_frame, frame_is_undistorted):
        if not self._pose_estimation_available():
            return display_frame
        try:
            display_frame, _ = self.pose_estimator.process_frame(
                analysis_frame,
                drawing_frame=display_frame,
                frame_is_undistorted=frame_is_undistorted,
            )
            self._log_latest_pose_estimate()
        except Exception:
            self._throttled_warning(
                "pose_estimate",
                "Stima posa AprilTag fallita sul frame corrente.",
            )
        return display_frame

    def _apply_fade_in(self, display_frame):
        if self.video_fade_in_sec <= 0.0:
            return display_frame
        now_fade = time.monotonic()
        if self._first_display_at is None:
            self._first_display_at = now_fade
        elapsed_fade = now_fade - self._first_display_at
        if elapsed_fade >= self.video_fade_in_sec:
            return display_frame
        alpha = elapsed_fade / self.video_fade_in_sec
        return cv2.addWeighted(
            display_frame, alpha,
            np.zeros_like(display_frame), 1.0 - alpha, 0.0,
        )

    def _show_frame(self, display_frame, dashboard, detection_is_active, autonomy_enabled) -> None:
        try:
            if dashboard is not None:
                display_frame = dashboard.scale_video(display_frame)

            overlay.draw_status_overlay(
                display_frame,
                self.cached_status,
                detection_enabled=detection_is_active,
                autonomy_enabled=autonomy_enabled,
            )

            self._maybe_draw_safety_net_banner(display_frame)

            if dashboard is not None:
                display_frame = dashboard.attach_panels(display_frame)

            cv2.imshow(VIDEO_WINDOW_TITLE, self._apply_fade_in(display_frame))
        except Exception:
            self._throttled_warning(
                "display",
                "Visualizzazione del frame fallita: frame saltato, il ciclo prosegue.",
            )

    @staticmethod
    def _window_still_open() -> bool:
        try:
            if cv2.getWindowProperty(VIDEO_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                print_event("Finestra video chiusa dall'utente")
                return False
        except cv2.error:
            pass
        return True

    def step(
        self,
        controller: RealTelloController,
        run_detection: bool = False,
        autonomy_enabled: bool = False,
        dashboard=None,
    ) -> bool:
        frame = controller.get_frame()

        if frame is None:
            return self._video_stream_alive()

        self.last_frame_received_at = time.monotonic()
        self._refresh_status(controller)
        frame = self._normalize_frame_for_opencv(frame)

        analysis_frame, analysis_frame_is_undistorted = self._undistorted_frame(frame)
        display_frame = analysis_frame.copy()

        detection_is_active = run_detection and len(self.detectors) > 0
        self._publish_analysis_frame(analysis_frame, display_frame, detection_is_active)

        display_frame = self._estimate_pose(
            analysis_frame, display_frame, analysis_frame_is_undistorted,
        )

        if dashboard is not None and getattr(dashboard, "enabled", False):
            dashboard.set_pose(
                self.last_filtered_pose_estimate,
                fresh=self.get_latest_pose_estimate() is not None,
            )

        self._show_frame(display_frame, dashboard, detection_is_active, autonomy_enabled)

        cv2.waitKey(1)

        return self._window_still_open()
