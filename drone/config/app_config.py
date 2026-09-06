from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from drone.config.measurements import (
    CAMERA_MATRIX,
    DIST_COEFFS,
    SITE_AREA_VERTICES_M,
    WORLD_TAGS_RAW,
)
from drone.loaders.yolo_models_loader import (
    YoloModelConfig,
    load_models_registry,
)
from drone.ui.appearance import (
    VIDEO_WINDOW_TITLE,
    WINDOW_TITLE,
    DashboardConfig,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent.parent

_MODELS_REGISTRY = load_models_registry(BASE_DIR)


@dataclass(frozen=True)
class JoystickMapping:
    button_takeoff: int = 0
    button_land: int = 1
    button_detection: int = 2
    button_autonomy: int = 3
    button_quit: int = 6

    axis_lr: int = 0
    axis_fb: int = 1
    axis_yaw: int = 2
    axis_ud: int = 3

    deadzone: float = 0.15

    label_takeoff: str = "Croce"
    label_land: str = "Cerchio"
    label_detection: str = "Quadrato"
    label_autonomy: str = "Triangolo"
    label_quit: str = "Options"

    label_axis_lr: str = "Stick sinistro orizzontale"
    label_axis_fb: str = "Stick sinistro verticale"
    label_axis_ud: str = "Stick destro verticale"
    label_axis_yaw: str = "Stick destro orizzontale"


@dataclass(frozen=True)
class AprilTagWorldPose:
    position_m: tuple[float, float, float]

    orientation_rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class DroneExtrinsicsConfig:
    camera_position_in_drone_frame_m: tuple[float, float, float] = (0.0, 0.0, 0.0)

    camera_orientation_rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class CameraPoseConfig:
    enabled: bool = True

    tag_family: str = "tag25h9"
    tag_size_m: float = 0.2

    threads: int = 4
    decimate: float = 2.0

    world_tags: dict[int, AprilTagWorldPose] = field(
        default_factory=lambda: {
            tag_id: AprilTagWorldPose(
                position_m=spec["position_m"],
                orientation_rpy_deg=spec["orientation_rpy_deg"],
            )
            for tag_id, spec in WORLD_TAGS_RAW.items()
        }
    )

    drone_extrinsics: DroneExtrinsicsConfig = field(default_factory=DroneExtrinsicsConfig)

    fusion_mode: str = "weighted_average"
    fusion_distance_weight_exponent: float = 2.0

    pose_error_gating_enabled: bool = True
    pose_error_relative_factor: float = 5.0
    pose_error_absolute_max: float | None = None

    max_tag_distance_m: float | None = 3.5

    camera_matrix: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ] = CAMERA_MATRIX

    dist_coeffs: tuple[float, float, float, float, float] = DIST_COEFFS


@dataclass(frozen=True)
class PoseKalmanFilterConfig:
    enabled: bool = True

    process_noise: float = 8.0
    measurement_noise: float = 0.05
    initial_covariance: float = 1.0

    outlier_gate_enabled: bool = True
    outlier_gate_threshold: float = 16.0
    outlier_gate_max_consecutive: int = 5

    yaw_filter_enabled: bool = True
    yaw_process_noise: float = 500.0
    yaw_measurement_noise: float = 5.0
    yaw_initial_covariance: float = 10.0


@dataclass(frozen=True)
class AutopilotWaypointConfig:
    x: float
    y: float
    z: float

    yaw_deg: float = 0.0


@dataclass(frozen=True)
class AprilTagAutopilotConfig:
    enabled: bool = True

    waypoints: tuple[AutopilotWaypointConfig, ...] = ()

    max_xy_speed: int = 18
    max_z_speed: int = 35
    max_yaw_speed: int = 23

    kp_xy: float = 50.0
    kp_z: float = 45.0
    kp_yaw: float = 2.5

    yaw_offset_deg: float = 180.0

    xy_tolerance_m: float = 0.15
    z_tolerance_m: float = 0.20
    yaw_tolerance_deg: float = 4.0

    z_priority_enabled: bool = True
    z_priority_enter_m: float = 0.40
    z_priority_exit_m: float = 0.22
    z_priority_keep_yaw: bool = True

    pose_timeout_sec: float = 1.0
    waypoint_timeout_enabled: bool = True
    waypoint_timeout_sec: float = 60.0

    supervision_waypoints: tuple[int, ...] = ()
    supervision_stop_sec: float = 0.0
    supervision_detection_enabled: bool = True

    home_waypoint: AutopilotWaypointConfig | None = None
    auto_land_on_finish: bool = True

    def __post_init__(self):
        for name, value in (
            ("xy_tolerance_m", self.xy_tolerance_m),
            ("z_tolerance_m", self.z_tolerance_m),
            ("yaw_tolerance_deg", self.yaw_tolerance_deg),
        ):
            if value <= 0:
                raise ValueError(
                    f"{name} ({value}) deve essere positivo: è una soglia di tolleranza "
                    "confrontata con il valore assoluto dell'errore."
                )
        if self.z_priority_exit_m >= self.z_priority_enter_m:
            raise ValueError(
                f"z_priority_exit_m ({self.z_priority_exit_m}) deve essere minore di "
                f"z_priority_enter_m ({self.z_priority_enter_m}) per garantire l'isteresi."
            )
        if self.home_waypoint is not None and float(self.home_waypoint.z) < 0.5:
            raise ValueError(
                f"home_waypoint.z ({self.home_waypoint.z}) deve essere >= 0.5 m. "
                "Nel frame mondo z=0 è il pavimento; il drone vola sopra l'origine "
                "a quota di sicurezza e poi Tello.land() gestisce la discesa."
            )
        if (
            self.waypoint_timeout_enabled
            and self.waypoint_timeout_sec <= self.supervision_stop_sec
        ):
            raise ValueError(
                f"waypoint_timeout_sec ({self.waypoint_timeout_sec}) deve essere maggiore di "
                f"supervision_stop_sec ({self.supervision_stop_sec}) per non far scattare il "
                "timeout durante una sosta di supervisione legittima."
            )


@dataclass(frozen=True)
class AppConfig:
    tello_host: str | None = None
    loop_hz: int = 20
    manual_speed_pct: int = 50

    window_title: str = WINDOW_TITLE
    video_window_title: str = VIDEO_WINDOW_TITLE

    frame_from_controller_is_rgb: bool = True
    frame_timeout_sec: float = 2.0
    video_fade_in_sec: float = 0.25
    status_refresh_sec: float = 1.0
    pose_valid_for_sec: float = 1.0
    vision_warning_repeat_after_sec: float = 5.0

    dashboard_render_interval_sec: float = 0.2

    detection_confidence_min: float = 0.5
    detection_image_size_px: int = 640
    detection_interval_sec: float = 0.2

    safety_net_model_name: str = _MODELS_REGISTRY["safety_net"]
    person_fall_model_name: str = _MODELS_REGISTRY["person_fall"]
    restricted_area_model_name: str = _MODELS_REGISTRY["restricted_area"]
    dpi_model_name: str = _MODELS_REGISTRY["dpi"]

    person_class_label: str = "Person"
    fall_class_label: str = "Fall"

    fall_alarm_after_sec: float = 0.3
    restricted_area_alarm_after_sec: float = 0.3
    alarm_clear_after_sec: float = 0.5

    safety_net_verdict_banner_sec: float = 6.0

    battery_rth_pct: int = 30
    battery_warning_pct: int = 25
    battery_critical_pct: int = 20

    ground_height_max_cm: int = 10
    ground_confirm_after_sec: float = 3.0

    log_level: str = "WARNING"
    flight_log_max_samples: int | None = 25_000

    flight_sessions_dir: Path = PACKAGE_DIR / "flight_sessions"
    waypoint_paths_dir: Path = PACKAGE_DIR / "waypoint_paths"

    yolo_models: tuple[YoloModelConfig, ...] = field(
        default_factory=lambda: _MODELS_REGISTRY["models"]
    )
    site_area_vertices_m: tuple[tuple[float, float], ...] = field(
        default_factory=lambda: SITE_AREA_VERTICES_M
    )

    joystick: JoystickMapping = field(default_factory=JoystickMapping)
    camera_pose: CameraPoseConfig = field(default_factory=CameraPoseConfig)
    pose_filter: PoseKalmanFilterConfig = field(default_factory=PoseKalmanFilterConfig)
    apriltag_autopilot: AprilTagAutopilotConfig = field(default_factory=AprilTagAutopilotConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    def __post_init__(self):
        if self.battery_warning_pct <= self.battery_critical_pct:
            raise ValueError(
                f"battery_warning_pct ({self.battery_warning_pct}) deve essere maggiore di "
                f"battery_critical_pct ({self.battery_critical_pct})."
            )
        if self.battery_rth_pct <= self.battery_critical_pct:
            raise ValueError(
                f"battery_rth_pct ({self.battery_rth_pct}) deve essere maggiore di "
                f"battery_critical_pct ({self.battery_critical_pct})."
            )
        if self.battery_rth_pct < self.battery_warning_pct:
            raise ValueError(
                f"battery_rth_pct ({self.battery_rth_pct}) non può essere minore di "
                f"battery_warning_pct ({self.battery_warning_pct})."
            )
        if self.fall_alarm_after_sec < 0:
            raise ValueError(
                f"fall_alarm_after_sec ({self.fall_alarm_after_sec}) non può "
                "essere negativo: è una durata in secondi."
            )
        if self.restricted_area_alarm_after_sec < 0:
            raise ValueError(
                f"restricted_area_alarm_after_sec ({self.restricted_area_alarm_after_sec}) "
                "non può essere negativo: è una durata in secondi."
            )
        if self.alarm_clear_after_sec < 0:
            raise ValueError(
                f"alarm_clear_after_sec ({self.alarm_clear_after_sec}) non può "
                "essere negativo: è una durata in secondi."
            )


APP_CONFIG = AppConfig()
