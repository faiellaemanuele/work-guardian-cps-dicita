from __future__ import annotations

from dataclasses import replace
from typing import Optional

from drone.config import APP_CONFIG
from drone.control.autopilot import AprilTagAutopilot
from drone.data.flight_data_logger import FlightDataLogger
from drone.hardware.tello_controller import RealTelloController
from drone.perception.object_detector import ObjectDetector
from drone.perception.pose_estimator import CameraPoseEstimator
from drone.perception.pose_filter import PositionKalmanFilter
from drone.ui.console import print_event


def create_controller() -> RealTelloController:
    return RealTelloController(
        min_takeoff_battery_pct=APP_CONFIG.battery_critical_pct,
        host=APP_CONFIG.tello_host,
    )


def _select_yolo_configs(selected_names: Optional[list[str]] = None) -> list:
    if selected_names is None:
        return list(APP_CONFIG.yolo_models)
    by_name = {m.name: m for m in APP_CONFIG.yolo_models}
    return [by_name[n] for n in selected_names if n in by_name]


def create_detectors(selected_names: Optional[list[str]] = None) -> list[dict]:
    selected_configs = _select_yolo_configs(selected_names)
    if not selected_configs:
        return []

    try:
        import torch
    except ImportError as exc:
        raise ImportError(
            "Per usare il detector devi installare torch e le dipendenze richieste da ultralytics."
        ) from exc

    detector_device = 0 if torch.cuda.is_available() else "cpu"
    detectors = []
    load_errors = []

    for model_cfg in selected_configs:
        try:
            detectors.append(
                {
                    "name": model_cfg.name,
                    "color": model_cfg.color,
                    "detector": ObjectDetector(
                        model_path=str(model_cfg.path),
                        conf=APP_CONFIG.detection_confidence_min,
                        imgsz=APP_CONFIG.detection_image_size_px,
                        device=detector_device,
                    ),
                }
            )
        except Exception as exc:
            load_errors.append(f"{model_cfg.name} ({model_cfg.path}): {exc}")

    if not detectors and load_errors:
        raise RuntimeError(
            "Nessun modello YOLO inizializzato correttamente. Errori: "
            + " | ".join(load_errors)
        )

    if load_errors:
        print_event(
            "Alcuni modelli non sono stati caricati: " + " | ".join(load_errors),
            prefix="AVVISO",
        )

    return detectors


def create_flight_data_logger() -> FlightDataLogger:
    return FlightDataLogger(
        output_dir=APP_CONFIG.flight_sessions_dir,
        max_samples=APP_CONFIG.flight_log_max_samples,
    )


def create_pose_estimator() -> Optional[CameraPoseEstimator]:
    pose_cfg = APP_CONFIG.camera_pose

    if not pose_cfg.enabled:
        return None

    return CameraPoseEstimator(pose_cfg)


def create_pose_filter() -> Optional[PositionKalmanFilter]:
    filter_cfg = APP_CONFIG.pose_filter

    if not filter_cfg.enabled:
        return None

    return PositionKalmanFilter(filter_cfg)


def create_apriltag_autopilot(
    waypoints=None,
    supervision_waypoints=None,
    supervision_stop_sec=None,
    home_waypoint=None,
) -> Optional[AprilTagAutopilot]:
    autopilot_cfg = APP_CONFIG.apriltag_autopilot

    if not autopilot_cfg.enabled:
        return None

    if not waypoints:
        return None

    try:
        autopilot_cfg = replace(autopilot_cfg, waypoints=tuple(waypoints))

        autopilot_cfg = replace(
            autopilot_cfg,
            supervision_waypoints=(
                () if supervision_waypoints is None else tuple(supervision_waypoints)
            ),
            supervision_stop_sec=(
                0.0 if supervision_stop_sec is None else float(supervision_stop_sec)
            ),
            home_waypoint=home_waypoint,
        )

        return AprilTagAutopilot(autopilot_cfg)
    except (ValueError, TypeError) as exc:
        print_event(
            f"Autopilota non creato: configurazione del percorso non valida ({exc}). "
            "Autonomia non disponibile, il volo prosegue in manuale.",
            prefix="ERRORE",
        )
        return None
