from __future__ import annotations

import logging

import math

from dataclasses import asdict, is_dataclass

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from drone.config import CameraPoseConfig

import cv2

import numpy as np

from drone.geometry import wrap_angle_deg as _wrap_angle_deg

from drone.ui.video import overlay


LOGGER = logging.getLogger(__name__)


class CameraPoseEstimator:
    def __init__(self, config: "CameraPoseConfig"):
        self.enabled = config.enabled

        self.camera_matrix = np.array(config.camera_matrix, dtype=np.float32)

        self.dist_coeffs = np.array(config.dist_coeffs, dtype=np.float32).reshape(-1, 1)

        self.zero_dist_coeffs = np.zeros_like(self.dist_coeffs)

        self._undistort_maps = None
        self._undistort_map_size = None

        self.tag_size_m = float(config.tag_size_m)

        if self.camera_matrix.shape != (3, 3):
            raise ValueError(
                f"config.camera_matrix deve avere forma (3, 3), ricevuto {self.camera_matrix.shape}."
            )
        if self.tag_size_m <= 0:
            raise ValueError("config.tag_size_m deve essere maggiore di zero.")

        self.fx = float(self.camera_matrix[0, 0])
        self.fy = float(self.camera_matrix[1, 1])
        self.cx = float(self.camera_matrix[0, 2])
        self.cy = float(self.camera_matrix[1, 2])

        self.world_tags = self._build_world_tags(config.world_tags)

        self.fusion_mode = str(config.fusion_mode).strip().lower()
        if self.fusion_mode not in {"weighted_average", "best_tag"}:
            raise ValueError(
                f"config.fusion_mode non valido: {config.fusion_mode}. Usa 'weighted_average' oppure 'best_tag'."
            )

        self.fusion_distance_weight_exponent = max(0.0, float(config.fusion_distance_weight_exponent))

        self.pose_error_gating_enabled = bool(config.pose_error_gating_enabled)
        self.pose_error_relative_factor = max(1.0, float(config.pose_error_relative_factor))
        self.pose_error_absolute_max = (
            None if config.pose_error_absolute_max is None else float(config.pose_error_absolute_max)
        )

        self.max_tag_distance_m = (
            None if config.max_tag_distance_m is None else float(config.max_tag_distance_m)
        )

        self.drone_extrinsics = self._build_drone_extrinsics(config.drone_extrinsics)

        self.last_pose_results = []
        self.last_fused_camera_pose = None
        self.last_fused_body_pose = None

        self.detector = None

        if self.enabled:
            try:
                from pyapriltags import Detector
            except ImportError as exc:
                raise ImportError(
                    "Per usare la stima della posa devi installare pyapriltags."
                ) from exc

            try:
                self.detector = Detector(
                    families=config.tag_family,
                    nthreads=config.threads,
                    quad_decimate=config.decimate,
                )
            except Exception as exc:
                raise RuntimeError("Impossibile inizializzare il detector AprilTag.") from exc

            LOGGER.info(
                "AprilTag inizializzato | family=%s | tag_size=%.4f m | config.world_tags=%d | fusion=%s | extrinsics_identity=%s",
                config.tag_family,
                self.tag_size_m,
                len(self.world_tags),
                self.fusion_mode,
                self.drone_extrinsics["is_identity"],
            )

    @staticmethod
    def _get_detection_value(det, key, default=None):
        return getattr(det, key, default)

    @staticmethod
    def _matrix_to_serializable(matrix):
        return np.asarray(matrix, dtype=np.float32).tolist()

    @staticmethod
    def _rotation_matrix_from_rpy_deg(roll_deg, pitch_deg, yaw_deg):
        roll = math.radians(float(roll_deg))
        pitch = math.radians(float(pitch_deg))
        yaw = math.radians(float(yaw_deg))

        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cy, sy = math.cos(yaw), math.sin(yaw)

        rx = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, cr, -sr],
                [0.0, sr, cr],
            ],
            dtype=np.float32,
        )

        ry = np.array(
            [
                [cp, 0.0, sp],
                [0.0, 1.0, 0.0],
                [-sp, 0.0, cp],
            ],
            dtype=np.float32,
        )

        rz = np.array(
            [
                [cy, -sy, 0.0],
                [sy, cy, 0.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )

        return rz @ ry @ rx

    def _normalize_world_tag_entry(self, tag_id, entry):
        if is_dataclass(entry):
            entry = asdict(entry)

        if not isinstance(entry, dict):
            raise ValueError(
                f"Configurazione del tag {tag_id} non valida: atteso dict o dataclass."
            )

        position = entry.get("position_m", None)
        orientation = entry.get("orientation_rpy_deg", None)

        if position is None:
            raise ValueError(
                f"Il tag {tag_id} non ha una posizione nel mondo: chiave 'position_m' "
                "mancante."
            )
        if orientation is None:
            orientation = (0.0, 0.0, 0.0)

        position_array = np.asarray(position, dtype=np.float32).reshape(-1)
        orientation_array = np.asarray(orientation, dtype=np.float32).reshape(-1)

        if position_array.size != 3:
            raise ValueError(f"Il tag {tag_id} deve avere 3 coordinate.")
        if orientation_array.size != 3:
            raise ValueError(f"Il tag {tag_id} deve avere 3 angoli roll-pitch-yaw.")

        position_vec = position_array.reshape(3, 1)

        rotation_world_from_tag = self._rotation_matrix_from_rpy_deg(*orientation_array.tolist())

        return {
            "tag_id": int(tag_id),
            "position_world": position_vec,
            "rotation_world_from_tag": rotation_world_from_tag,
            "orientation_rpy_deg": tuple(float(v) for v in orientation_array),
        }

    def _build_world_tags(self, world_tags) -> dict:
        if not isinstance(world_tags, dict) or not world_tags:
            raise ValueError(
                "world_tags deve essere un dizionario non vuoto di pose AprilTag note "
                "nel frame mondo: senza almeno un tag mappato la posa assoluta non è "
                "calcolabile."
            )
        normalized = {}
        for tag_id, entry in world_tags.items():
            normalized[int(tag_id)] = self._normalize_world_tag_entry(tag_id, entry)
        return normalized

    def _build_drone_extrinsics(self, drone_extrinsics):
        if drone_extrinsics is None:
            drone_extrinsics = {}

        if is_dataclass(drone_extrinsics):
            drone_extrinsics = asdict(drone_extrinsics)

        if not isinstance(drone_extrinsics, dict):
            raise ValueError("drone_extrinsics deve essere un dict o una dataclass.")

        camera_position_in_body = drone_extrinsics.get(
            "camera_position_in_drone_frame_m", (0.0, 0.0, 0.0)
        )
        camera_orientation_in_body = drone_extrinsics.get(
            "camera_orientation_rpy_deg", (0.0, 0.0, 0.0)
        )

        p_body_camera = np.asarray(camera_position_in_body, dtype=np.float32).reshape(-1)
        rpy_body_camera = np.asarray(camera_orientation_in_body, dtype=np.float32).reshape(-1)

        if p_body_camera.size != 3:
            raise ValueError("camera_position_in_drone_frame_m deve avere 3 coordinate.")
        if rpy_body_camera.size != 3:
            raise ValueError("camera_orientation_rpy_deg deve avere 3 angoli roll-pitch-yaw.")

        p_body_camera = p_body_camera.reshape(3, 1)

        R_body_from_camera = self._rotation_matrix_from_rpy_deg(*rpy_body_camera.tolist())

        R_camera_from_body = R_body_from_camera.T
        p_camera_body = -R_camera_from_body @ p_body_camera

        is_identity = np.allclose(p_body_camera, 0.0) and np.allclose(R_body_from_camera, np.eye(3), atol=1e-6)

        return {
            "camera_position_in_body": p_body_camera,
            "rotation_body_from_camera": R_body_from_camera,
            "body_position_in_camera": p_camera_body,
            "rotation_camera_from_body": R_camera_from_body,
            "is_identity": bool(is_identity),
        }

    def undistort_frame(self, frame):
        if frame is None:
            return None

        h, w = frame.shape[:2]

        if self._undistort_maps is None or self._undistort_map_size != (w, h):
            self._undistort_maps = cv2.initUndistortRectifyMap(
                self.camera_matrix,
                self.dist_coeffs,
                None,
                self.camera_matrix,
                (w, h),
                cv2.CV_16SC2,
            )
            self._undistort_map_size = (w, h)

        map1, map2 = self._undistort_maps
        return cv2.remap(frame, map1, map2, interpolation=cv2.INTER_LINEAR)

    def _draw_axes(self, frame, R, t, frame_is_undistorted: bool = False):
        dist_coeffs = self.zero_dist_coeffs if frame_is_undistorted else self.dist_coeffs
        overlay.draw_axes(frame, R, t, self.camera_matrix, dist_coeffs)

    def _draw_tag_outline(self, frame, det):
        overlay.draw_tag_outline(
            frame,
            corners=self._get_detection_value(det, "corners"),
            center=self._get_detection_value(det, "center"),
            tag_id=self._get_detection_value(det, "tag_id", -1),
        )

    def _compute_detection_weight(self, det, t_vec):
        decision_margin = getattr(det, "decision_margin", None)
        if decision_margin is None:
            decision_margin = 50.0

        try:
            decision_margin = float(decision_margin)
        except (TypeError, ValueError):
            decision_margin = 50.0

        if not math.isfinite(decision_margin):
            decision_margin = 50.0

        distance = float(np.linalg.norm(t_vec))
        if not math.isfinite(distance):
            distance = 1.0

        distance = max(distance, 0.05)

        return max(decision_margin, 1.0) / (distance ** self.fusion_distance_weight_exponent)

    @staticmethod
    def _extract_world_yaw_deg(R_world_from_local, local_forward_axis: str = "x"):
        axis_name = str(local_forward_axis).strip().lower()
        axis_map = {
            "x": np.array([[1.0], [0.0], [0.0]], dtype=np.float32),
            "y": np.array([[0.0], [1.0], [0.0]], dtype=np.float32),
            "z": np.array([[0.0], [0.0], [1.0]], dtype=np.float32),
        }

        if axis_name not in axis_map:
            raise ValueError(
                f"Asse forward non valido: {local_forward_axis}. Usa 'x', 'y' oppure 'z'."
            )

        local_forward_world = R_world_from_local @ axis_map[axis_name]

        fwd_x = float(local_forward_world[0, 0])
        fwd_y = float(local_forward_world[1, 0])

        if math.hypot(fwd_x, fwd_y) < 1e-6:
            LOGGER.warning(
                "Yaw mondo non osservabile: l'asse in avanti '%s' è quasi verticale. "
                "Rilevazione esclusa dalla fusione per questo frame.",
                axis_name,
            )
            return None

        yaw_rad = math.atan2(fwd_y, fwd_x)
        return math.degrees(yaw_rad)

    @staticmethod
    def _pose_to_serializable(position_world, yaw_world_deg, source, source_tag_ids, pose_type):
        return {
            "type": pose_type,
            "position_world": {
                "x": float(position_world[0, 0]),
                "y": float(position_world[1, 0]),
                "z": float(position_world[2, 0]),
            },
            "yaw_world_deg": float(yaw_world_deg),
            "source": str(source),
            "source_tag_ids": [int(tag_id) for tag_id in source_tag_ids],
        }

    def _filter_hypotheses_by_distance(self, hypotheses):
        if self.max_tag_distance_m is None or len(hypotheses) < 1:
            return hypotheses, []

        near = [
            h for h in hypotheses
            if h.get("distance") is None or h["distance"] <= self.max_tag_distance_m
        ]
        if not near:
            nearest = min(
                hypotheses,
                key=lambda h: (h["distance"] if h.get("distance") is not None else float("inf")),
            )
            near = [nearest]

        kept_ids = {id(h) for h in near}
        dropped = [int(h.get("tag_id", -1)) for h in hypotheses if id(h) not in kept_ids]
        return near, dropped

    def _filter_hypotheses_by_pose_error(self, hypotheses):
        if not self.pose_error_gating_enabled or len(hypotheses) < 2:
            return hypotheses, []

        errs = [h["pose_err"] for h in hypotheses if h.get("pose_err") is not None]
        if len(errs) < 2:
            return hypotheses, []

        min_err = min(errs)
        rel_threshold = self.pose_error_relative_factor * (min_err + 1e-12)

        kept = []
        dropped_tags = []
        for h in hypotheses:
            pe = h.get("pose_err")
            if pe is None:
                kept.append(h)
                continue
            over_relative = pe > rel_threshold
            over_absolute = (
                self.pose_error_absolute_max is not None
                and pe > self.pose_error_absolute_max
            )
            if over_relative or over_absolute:
                dropped_tags.append(int(h.get("tag_id", -1)))
                continue
            kept.append(h)

        if not kept:
            best = min(
                hypotheses,
                key=lambda h: (h["pose_err"] if h.get("pose_err") is not None else float("inf")),
            )
            kept = [best]
            dropped_tags = [int(h.get("tag_id", -1)) for h in hypotheses if h is not best]

        return kept, dropped_tags

    def _fuse_absolute_world_pose(self, hypotheses):
        if not hypotheses:
            return None

        if len(hypotheses) == 1 or self.fusion_mode == "best_tag":
            best = max(hypotheses, key=lambda item: item["weight"])
            return {
                "position_world": best["position_world"].copy(),
                "yaw_world_deg": float(best["yaw_world_deg"]),
                "source": "best_tag" if self.fusion_mode == "best_tag" else self.fusion_mode,
                "source_tag_ids": [int(best["tag_id"])],
            }

        total_weight = sum(item["weight"] for item in hypotheses)
        if total_weight <= 0:
            uniform_w = 1.0
            total_weight = float(len(hypotheses))
            weights = [uniform_w] * len(hypotheses)
        else:
            weights = [item["weight"] for item in hypotheses]

        position_world = (
            sum(w * item["position_world"] for w, item in zip(weights, hypotheses)) / total_weight
        )

        sin_sum = sum(
            w * math.sin(math.radians(item["yaw_world_deg"]))
            for w, item in zip(weights, hypotheses)
        )
        cos_sum = sum(
            w * math.cos(math.radians(item["yaw_world_deg"]))
            for w, item in zip(weights, hypotheses)
        )

        if math.hypot(sin_sum, cos_sum) < 1e-9:
            best = max(hypotheses, key=lambda item: item["weight"])
            fused_yaw_world_deg = float(best["yaw_world_deg"])
        else:
            fused_yaw_world_deg = math.degrees(math.atan2(sin_sum, cos_sum))

        return {
            "position_world": position_world,
            "yaw_world_deg": _wrap_angle_deg(fused_yaw_world_deg),
            "source": "weighted_average",
            "source_tag_ids": [int(item["tag_id"]) for item in hypotheses],
        }
    def _tag_frame_pose(self, det):
        pose_t = self._get_detection_value(det, "pose_t")
        pose_R = self._get_detection_value(det, "pose_R")
        if pose_t is None or pose_R is None:
            raise ValueError("Detection AprilTag senza pose_t o pose_R.")

        t_camera_from_tag = np.asarray(pose_t, dtype=np.float32).reshape(3, 1)
        R_camera_from_tag = np.asarray(pose_R, dtype=np.float32).reshape(3, 3)

        pose_err = self._get_detection_value(det, "pose_err", None)
        try:
            pose_err = float(pose_err) if pose_err is not None else None
            if pose_err is not None and not math.isfinite(pose_err):
                pose_err = None
        except (TypeError, ValueError):
            pose_err = None

        R_tag_from_camera_std = R_camera_from_tag.T
        camera_pos_in_tag_std = -R_tag_from_camera_std @ t_camera_from_tag

        S = np.diag([1.0, 1.0, -1.0]).astype(np.float32)

        return {
            "tag_id": int(self._get_detection_value(det, "tag_id", -1)),
            "pose_err": pose_err,
            "t_camera_from_tag": t_camera_from_tag,
            "R_camera_from_tag": R_camera_from_tag,
            "camera_pos_in_tag": S @ camera_pos_in_tag_std,
            "R_tag_from_camera": S @ R_tag_from_camera_std @ S,
        }

    def _world_pose_from_tag(self, world_tag, camera_pos_in_tag, R_tag_from_camera):
        R_world_from_tag = world_tag["rotation_world_from_tag"]
        p_world_tag = world_tag["position_world"]

        p_world_camera = R_world_from_tag @ camera_pos_in_tag + p_world_tag
        R_world_from_camera = R_world_from_tag @ R_tag_from_camera

        camera_yaw_world_deg = self._extract_world_yaw_deg(
            R_world_from_camera, local_forward_axis="z"
        )
        if camera_yaw_world_deg is None:
            return None
        return p_world_camera, R_world_from_camera, _wrap_angle_deg(camera_yaw_world_deg)

    def _body_pose_from_camera(self, p_world_camera, R_world_from_camera, camera_yaw_world_deg):
        if self.drone_extrinsics["is_identity"]:
            return p_world_camera.copy(), float(camera_yaw_world_deg)

        p_camera_body = self.drone_extrinsics["body_position_in_camera"]
        R_camera_from_body = self.drone_extrinsics["rotation_camera_from_body"]

        p_world_body = R_world_from_camera @ p_camera_body + p_world_camera
        R_world_from_body = R_world_from_camera @ R_camera_from_body

        body_yaw_world_deg = self._extract_world_yaw_deg(
            R_world_from_body, local_forward_axis="x"
        )
        if body_yaw_world_deg is None:
            return None
        return p_world_body, _wrap_angle_deg(body_yaw_world_deg)

    @staticmethod
    def _position_dict(position):
        return {
            "x": float(position[0, 0]),
            "y": float(position[1, 0]),
            "z": float(position[2, 0]),
        }

    @staticmethod
    def _hypothesis(tag_id, position_world, yaw_world_deg, weight, pose_err, distance):
        return {
            "tag_id": tag_id,
            "position_world": position_world,
            "yaw_world_deg": yaw_world_deg,
            "weight": weight,
            "pose_err": pose_err,
            "distance": distance,
        }

    def _process_single_detection(
        self,
        det,
        output_frame,
        frame_is_undistorted,
        pose_results,
        absolute_camera_hypotheses,
        absolute_body_hypotheses,
    ):
        tag_pose = self._tag_frame_pose(det)
        tag_id = tag_pose["tag_id"]
        pose_err = tag_pose["pose_err"]

        self._draw_axes(
            output_frame,
            tag_pose["R_camera_from_tag"],
            tag_pose["t_camera_from_tag"],
            frame_is_undistorted=frame_is_undistorted,
        )
        self._draw_tag_outline(output_frame, det)

        per_tag_result = {
            "tag_id": tag_id,
            "camera_position_in_tag_frame": self._position_dict(tag_pose["camera_pos_in_tag"]),
            "translation_vector": tuple(
                float(v) for v in tag_pose["t_camera_from_tag"].flatten()
            ),
            "rotation_matrix": self._matrix_to_serializable(tag_pose["R_tag_from_camera"]),
            "pose_err": pose_err,
        }
        pose_results.append(per_tag_result)

        world_tag = self.world_tags.get(tag_id)
        if world_tag is None:
            return

        world_pose = self._world_pose_from_tag(
            world_tag, tag_pose["camera_pos_in_tag"], tag_pose["R_tag_from_camera"],
        )
        if world_pose is None:
            return
        p_world_camera, R_world_from_camera, camera_yaw_world_deg = world_pose

        weight = self._compute_detection_weight(det, tag_pose["t_camera_from_tag"])
        tag_distance = float(np.linalg.norm(tag_pose["t_camera_from_tag"]))

        per_tag_result["camera_position_in_world_frame"] = self._position_dict(p_world_camera)
        per_tag_result["camera_yaw_in_world_deg"] = float(camera_yaw_world_deg)
        per_tag_result["weight"] = float(weight)
        per_tag_result["distance_camera_tag_m"] = tag_distance

        absolute_camera_hypotheses.append(self._hypothesis(
            tag_id, p_world_camera, camera_yaw_world_deg, weight, pose_err, tag_distance,
        ))

        body_pose = self._body_pose_from_camera(
            p_world_camera, R_world_from_camera, camera_yaw_world_deg,
        )
        if body_pose is None:
            return
        p_world_body, body_yaw_world_deg = body_pose

        per_tag_result["drone_position_in_world_frame"] = self._position_dict(p_world_body)
        per_tag_result["drone_yaw_in_world_deg"] = float(body_yaw_world_deg)

        absolute_body_hypotheses.append(self._hypothesis(
            tag_id, p_world_body, body_yaw_world_deg, weight, pose_err, tag_distance,
        ))

    def _reset_last_pose(self):
        self.last_pose_results = []
        self.last_fused_camera_pose = None
        self.last_fused_body_pose = None

    def _detect_tags(self, frame_for_detection):
        gray = cv2.cvtColor(frame_for_detection, cv2.COLOR_BGR2GRAY)
        detections = self.detector.detect(
            gray,
            estimate_tag_pose=True,
            camera_params=(self.fx, self.fy, self.cx, self.cy),
            tag_size=self.tag_size_m,
        )
        return [] if detections is None else detections

    def _apply_quality_gates(self, camera_hypotheses, body_hypotheses, pose_results):
        camera_hypotheses, dropped_distance = self._filter_hypotheses_by_distance(
            camera_hypotheses
        )
        camera_hypotheses, dropped_pose_err = self._filter_hypotheses_by_pose_error(
            camera_hypotheses
        )
        dropped_set = set(dropped_distance) | set(dropped_pose_err)
        if dropped_set:
            body_hypotheses = [
                h for h in body_hypotheses if int(h.get("tag_id", -1)) not in dropped_set
            ]
            LOGGER.debug(
                "Gate qualità: scartati %s (distanza=%s, pose_err=%s) | "
                "per-tag pose_err=%s distanze=%s",
                sorted(dropped_set),
                sorted(set(dropped_distance)),
                sorted(set(dropped_pose_err)),
                {int(h["tag_id"]): h.get("pose_err") for h in pose_results if "pose_err" in h},
                {int(h["tag_id"]): round(h["distance_camera_tag_m"], 2)
                 for h in pose_results if "distance_camera_tag_m" in h},
            )
        return camera_hypotheses, body_hypotheses

    def _append_fused_pose(self, pose_results, fused_pose, pose_type):
        if fused_pose is None:
            return
        pose_results.append(
            self._pose_to_serializable(
                position_world=fused_pose["position_world"],
                yaw_world_deg=fused_pose["yaw_world_deg"],
                source=fused_pose["source"],
                source_tag_ids=fused_pose["source_tag_ids"],
                pose_type=pose_type,
            )
        )

    def process_frame(
        self,
        frame_for_detection,
        drawing_frame=None,
        frame_is_undistorted: bool = False,
    ) -> tuple[Optional[np.ndarray], list[dict]]:
        if not self.enabled or self.detector is None or frame_for_detection is None:
            self._reset_last_pose()
            if drawing_frame is not None:
                return drawing_frame, []
            return frame_for_detection, []

        output_frame = (
            drawing_frame.copy()
            if drawing_frame is not None
            else frame_for_detection.copy()
        )

        try:
            detections = self._detect_tags(frame_for_detection)
        except Exception:
            LOGGER.exception("Errore durante il rilevamento degli AprilTag.")
            self._reset_last_pose()
            return output_frame, []

        pose_results = []
        absolute_camera_hypotheses = []
        absolute_body_hypotheses = []

        for det in detections:
            try:
                self._process_single_detection(
                    det,
                    output_frame,
                    frame_is_undistorted,
                    pose_results,
                    absolute_camera_hypotheses,
                    absolute_body_hypotheses,
                )
            except Exception:
                LOGGER.exception("Errore durante l'elaborazione della posa AprilTag.")
                continue

        absolute_camera_hypotheses, absolute_body_hypotheses = self._apply_quality_gates(
            absolute_camera_hypotheses, absolute_body_hypotheses, pose_results,
        )

        self.last_fused_camera_pose = self._fuse_absolute_world_pose(absolute_camera_hypotheses)
        self.last_fused_body_pose = self._fuse_absolute_world_pose(absolute_body_hypotheses)

        self._append_fused_pose(
            pose_results, self.last_fused_camera_pose, "fused_camera_pose_world",
        )
        self._append_fused_pose(
            pose_results, self.last_fused_body_pose, "fused_drone_pose_world",
        )

        self.last_pose_results = pose_results
        return output_frame, pose_results
