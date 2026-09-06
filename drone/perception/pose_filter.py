from __future__ import annotations

import logging
import time

from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    from drone.config import PoseKalmanFilterConfig

import numpy as np

from drone.geometry import (
    wrap_angle_deg as _wrap_angle_deg,
    normalize_position_world as _normalize_position_world,
)

LOGGER = logging.getLogger(__name__)


class PositionKalmanFilter:
    MAX_DT_SEC = 0.2

    def __init__(self, config: "PoseKalmanFilterConfig"):
        self.process_noise = float(config.process_noise)
        self.measurement_noise = float(config.measurement_noise)
        self.initial_covariance = float(config.initial_covariance)

        self.yaw_filter_enabled = bool(config.yaw_filter_enabled)
        self.yaw_process_noise = float(config.yaw_process_noise)
        self.yaw_measurement_noise = float(config.yaw_measurement_noise)
        self.yaw_initial_covariance = float(config.yaw_initial_covariance)

        self.x = np.zeros((6, 1), dtype=np.float64)
        self.P = np.eye(6, dtype=np.float64) * self.initial_covariance

        self.H = np.zeros((3, 6), dtype=np.float64)
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0
        self.H[2, 2] = 1.0

        self.R = np.eye(3, dtype=np.float64) * (self.measurement_noise ** 2)

        self.outlier_gate_enabled = bool(config.outlier_gate_enabled)
        self.outlier_gate_threshold = float(config.outlier_gate_threshold)
        self.outlier_gate_max_consecutive = int(config.outlier_gate_max_consecutive)
        self._consecutive_rejections = 0
        self.last_position_update_rejected = False

        self.initialized = False
        self.last_timestamp: Optional[float] = None

        self.yaw_x = np.zeros((2, 1), dtype=np.float64)
        self.yaw_P = np.eye(2, dtype=np.float64) * self.yaw_initial_covariance

        self.yaw_H = np.zeros((1, 2), dtype=np.float64)
        self.yaw_H[0, 0] = 1.0

        self.yaw_R = np.array(
            [[self.yaw_measurement_noise ** 2]],
            dtype=np.float64,
        )

        self.yaw_initialized = False
        self.last_yaw_timestamp: Optional[float] = None

    def reset(self):
        self.x = np.zeros((6, 1), dtype=np.float64)
        self.P = np.eye(6, dtype=np.float64) * self.initial_covariance

        self._consecutive_rejections = 0
        self.last_position_update_rejected = False
        self.initialized = False
        self.last_timestamp = None

        self.yaw_x = np.zeros((2, 1), dtype=np.float64)
        self.yaw_P = np.eye(2, dtype=np.float64) * self.yaw_initial_covariance

        self.yaw_initialized = False
        self.last_yaw_timestamp = None

    def _build_transition_matrix(self, dt: float) -> np.ndarray:
        F = np.eye(6, dtype=np.float64)

        F[0, 3] = dt
        F[1, 4] = dt
        F[2, 5] = dt

        return F

    def _build_process_noise_matrix(self, dt: float) -> np.ndarray:
        q = self.process_noise ** 2

        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2

        Q = np.zeros((6, 6), dtype=np.float64)

        for i in range(3):
            Q[i, i] = dt4 / 4.0 * q
            Q[i, i + 3] = dt3 / 2.0 * q
            Q[i + 3, i] = dt3 / 2.0 * q
            Q[i + 3, i + 3] = dt2 * q

        return Q

    def _build_yaw_transition_matrix(self, dt: float) -> np.ndarray:
        F = np.eye(2, dtype=np.float64)
        F[0, 1] = dt
        return F

    def _build_yaw_process_noise_matrix(self, dt: float) -> np.ndarray:
        q = self.yaw_process_noise ** 2

        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2

        Q = np.array(
            [
                [dt4 / 4.0 * q, dt3 / 2.0 * q],
                [dt3 / 2.0 * q, dt2 * q],
            ],
            dtype=np.float64,
        )

        return Q

    def update_yaw(self, yaw_world_deg: float, timestamp: Optional[float] = None) -> float:
        if timestamp is None:
            timestamp = time.monotonic()

        yaw_measurement = _wrap_angle_deg(float(yaw_world_deg))

        if not np.isfinite(yaw_measurement):
            raise ValueError("yaw_world_deg deve essere un valore numerico finito.")

        if not self.yaw_initialized:
            self.yaw_x[0, 0] = yaw_measurement
            self.yaw_x[1, 0] = 0.0
            self.last_yaw_timestamp = float(timestamp)
            self.yaw_initialized = True
            return float(self.yaw_x[0, 0])

        dt = float(timestamp) - float(self.last_yaw_timestamp)
        self.last_yaw_timestamp = float(timestamp)

        if dt <= 0.0:
            dt = 1e-3
        elif dt > self.MAX_DT_SEC:
            dt = self.MAX_DT_SEC

        F = self._build_yaw_transition_matrix(dt)
        Q = self._build_yaw_process_noise_matrix(dt)

        self.yaw_x = F @ self.yaw_x
        self.yaw_P = F @ self.yaw_P @ F.T + Q

        self.yaw_x[0, 0] = _wrap_angle_deg(self.yaw_x[0, 0])

        predicted_yaw = float((self.yaw_H @ self.yaw_x)[0, 0])
        innovation = _wrap_angle_deg(yaw_measurement - predicted_yaw)
        y = np.array([[innovation]], dtype=np.float64)

        S = self.yaw_H @ self.yaw_P @ self.yaw_H.T + self.yaw_R

        try:
            K = np.linalg.solve(S, self.yaw_H @ self.yaw_P).T
        except np.linalg.LinAlgError:
            LOGGER.warning(
                "Filtro di Kalman: matrice non invertibile nell'aggiornamento dello yaw, "
                "si applica la sola predizione."
            )
            return float(self.yaw_x[0, 0])

        self.yaw_x = self.yaw_x + K @ y

        IKH = np.eye(2, dtype=np.float64) - K @ self.yaw_H
        self.yaw_P = IKH @ self.yaw_P @ IKH.T + K @ self.yaw_R @ K.T
        self.yaw_P = (self.yaw_P + self.yaw_P.T) * 0.5

        self.yaw_x[0, 0] = _wrap_angle_deg(self.yaw_x[0, 0])

        return float(self.yaw_x[0, 0])

    def predict_yaw(self, timestamp: Optional[float] = None) -> Optional[float]:
        if not self.yaw_initialized or self.last_yaw_timestamp is None:
            return None

        if timestamp is None:
            timestamp = time.monotonic()

        dt = float(timestamp) - float(self.last_yaw_timestamp)
        self.last_yaw_timestamp = float(timestamp)

        if dt <= 0.0:
            return float(self.yaw_x[0, 0])
        if dt > self.MAX_DT_SEC:
            dt = self.MAX_DT_SEC

        F = self._build_yaw_transition_matrix(dt)
        Q = self._build_yaw_process_noise_matrix(dt)

        self.yaw_x = F @ self.yaw_x
        self.yaw_P = F @ self.yaw_P @ F.T + Q
        self.yaw_x[0, 0] = _wrap_angle_deg(self.yaw_x[0, 0])

        return float(self.yaw_x[0, 0])

    def update(self, position_world: Any, timestamp: Optional[float] = None) -> np.ndarray:
        if timestamp is None:
            timestamp = time.monotonic()

        self.last_position_update_rejected = False

        z = _normalize_position_world(position_world)

        if not self.initialized:
            self.x[0:3, :] = z
            self.x[3:6, :] = 0.0
            self.last_timestamp = float(timestamp)
            self.initialized = True
            return self.x[0:3, :].copy()

        dt = float(timestamp) - float(self.last_timestamp)
        self.last_timestamp = float(timestamp)

        if dt <= 0.0:
            dt = 1e-3
        elif dt > self.MAX_DT_SEC:
            dt = self.MAX_DT_SEC

        F = self._build_transition_matrix(dt)
        Q = self._build_process_noise_matrix(dt)

        position_before_predict = self.x[0:3, :].copy()

        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

        y = z - self.H @ self.x

        S = self.H @ self.P @ self.H.T + self.R

        try:
            innovation_distance_sq = float((y.T @ np.linalg.solve(S, y))[0, 0])
            K = np.linalg.solve(S, self.H @ self.P).T
        except np.linalg.LinAlgError:
            LOGGER.warning(
                "Filtro di Kalman: matrice non invertibile nell'aggiornamento della posizione, "
                "si applica la sola predizione."
            )
            return self.x[0:3, :].copy()

        if self.outlier_gate_enabled and innovation_distance_sq > self.outlier_gate_threshold:
            if self._consecutive_rejections < self.outlier_gate_max_consecutive:
                self._consecutive_rejections += 1
                self.last_position_update_rejected = True
                self.x[0:3, :] = position_before_predict
                self.x[3:6, :] = 0.0
                LOGGER.debug(
                    "Filtro di Kalman: misura scartata "
                    "(Mahalanobis²=%.1f > %.1f), la stima resta ferma sull'ultimo valore.",
                    innovation_distance_sq,
                    self.outlier_gate_threshold,
                )
                return self.x[0:3, :].copy()
            LOGGER.debug(
                "Filtro di Kalman: %d misure di fila scartate, "
                "la stima riparte dalla misura corrente.",
                self._consecutive_rejections,
            )
            self.x[0:3, :] = z
            self.x[3:6, :] = 0.0
            self.P = np.eye(6, dtype=np.float64) * self.initial_covariance
            self._consecutive_rejections = 0
            return self.x[0:3, :].copy()

        self._consecutive_rejections = 0

        self.x = self.x + K @ y

        IKH = np.eye(6, dtype=np.float64) - K @ self.H
        self.P = IKH @ self.P @ IKH.T + K @ self.R @ K.T
        self.P = (self.P + self.P.T) * 0.5

        return self.x[0:3, :].copy()

    def filter_pose_estimate(
        self,
        pose_estimate: Optional[Mapping[str, Any]],
        timestamp: Optional[float] = None,
    ) -> Optional[dict]:
        if not pose_estimate:
            return None

        if "position_world" not in pose_estimate:
            return None

        if timestamp is None:
            timestamp = time.monotonic()

        try:
            filtered_position = self.update(
                pose_estimate["position_world"],
                timestamp=timestamp,
            )
        except Exception:
            LOGGER.warning(
                "Filtro di Kalman: aggiornamento della posizione non riuscito, "
                "filter_pose_estimate restituisce None."
            )
            return None

        filtered_pose = dict(pose_estimate)

        fp = filtered_position.flatten()
        filtered_pose["position_world"] = {
            "x": float(fp[0]),
            "y": float(fp[1]),
            "z": float(fp[2]),
        }

        if self.yaw_filter_enabled and "yaw_world_deg" in pose_estimate and pose_estimate["yaw_world_deg"] is not None:
            try:
                filtered_yaw = self.update_yaw(
                    pose_estimate["yaw_world_deg"],
                    timestamp=timestamp,
                )
                filtered_pose["yaw_world_deg"] = filtered_yaw
            except Exception:
                filtered_pose["yaw_world_deg"] = pose_estimate["yaw_world_deg"]
        elif self.yaw_filter_enabled and self.yaw_initialized:
            try:
                self.predict_yaw(timestamp)
            except Exception:
                LOGGER.debug("predict_yaw fallita su frame senza misura di yaw.", exc_info=True)

        filtered_pose["source"] = f"kalman({pose_estimate.get('source', 'raw')})"

        filtered_pose["kalman_outlier_rejected"] = bool(self.last_position_update_rejected)

        return filtered_pose
