from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from dataclasses import replace

from drone.config import APP_CONFIG
from drone.perception.pose_filter import PositionKalmanFilter


def _kf(**over) -> PositionKalmanFilter:
    return PositionKalmanFilter(replace(APP_CONFIG.pose_filter, **over))


def _pose(x, y, z, yaw=None) -> dict:
    p = {"position_world": {"x": x, "y": y, "z": z}, "source": "test"}
    if yaw is not None:
        p["yaw_world_deg"] = yaw
    return p


def test_returns_none_on_empty_input():
    kf = _kf()
    assert kf.filter_pose_estimate(None) is None
    assert kf.filter_pose_estimate({}) is None


def test_returns_none_without_position_world():
    kf = _kf()
    assert kf.filter_pose_estimate({"yaw_world_deg": 10.0}) is None


def test_first_measurement_initializes_to_measurement():
    kf = _kf()
    out = kf.filter_pose_estimate(_pose(1.0, 2.0, 3.0, 0.0), timestamp=0.0)
    pos = out["position_world"]
    assert isinstance(pos, dict)
    assert abs(pos["x"] - 1.0) < 1e-6
    assert abs(pos["y"] - 2.0) < 1e-6
    assert abs(pos["z"] - 3.0) < 1e-6


def test_position_output_is_dict_after_updates():
    kf = _kf()
    kf.filter_pose_estimate(_pose(0.0, 0.0, 0.0, 0.0), timestamp=0.0)
    out = kf.filter_pose_estimate(_pose(0.1, 0.0, 0.0, 0.0), timestamp=0.05)
    assert set(out["position_world"].keys()) == {"x", "y", "z"}


def test_invalid_position_returns_none():
    kf = _kf()
    assert kf.filter_pose_estimate(_pose(float("nan"), 0.0, 0.0, 0.0), timestamp=0.0) is None


def test_yaw_preserved_when_filter_disabled():
    kf = _kf(yaw_filter_enabled=False)
    out = kf.filter_pose_estimate(_pose(0.0, 0.0, 0.0, 42.0), timestamp=0.0)
    assert out["yaw_world_deg"] == 42.0


def test_source_is_tagged_kalman():
    kf = _kf()
    out = kf.filter_pose_estimate(_pose(0.0, 0.0, 0.0, 0.0), timestamp=0.0)
    assert out["source"].startswith("kalman(")


def test_converges_to_constant_measurement():
    kf = _kf(process_noise=10.0, measurement_noise=0.05)
    t = 0.0
    out = None
    for _ in range(60):
        out = kf.filter_pose_estimate(_pose(5.0, -3.0, 2.0, 30.0), timestamp=t)
        t += 0.05
    pos = out["position_world"]
    assert abs(pos["x"] - 5.0) < 0.05
    assert abs(pos["y"] - (-3.0)) < 0.05
    assert abs(pos["z"] - 2.0) < 0.05


def _converge(kf, x, y, z, *, n=40, t0=0.0, dt=0.05):
    t = t0
    for _ in range(n):
        kf.filter_pose_estimate(_pose(x, y, z, 0.0), timestamp=t)
        t += dt
    return t


def test_outlier_gate_rejects_isolated_jump():
    kf = _kf(
        process_noise=4.0, measurement_noise=0.05,
        outlier_gate_enabled=True, outlier_gate_threshold=16.0,
    )
    t = _converge(kf, 1.0, 1.0, 1.0)
    out = kf.filter_pose_estimate(_pose(1.0, 1.0, 5.0, 0.0), timestamp=t)
    assert out["position_world"]["z"] < 1.2


def test_outlier_gate_disabled_follows_jump():
    kf = _kf(
        process_noise=4.0, measurement_noise=0.05,
        outlier_gate_enabled=False,
    )
    t = _converge(kf, 1.0, 1.0, 1.0)
    out = kf.filter_pose_estimate(_pose(1.0, 1.0, 5.0, 0.0), timestamp=t)
    assert out["position_world"]["z"] > 1.2


def test_outlier_gate_reinitializes_on_persistent_shift():
    kf = _kf(
        process_noise=4.0, measurement_noise=0.05,
        outlier_gate_enabled=True, outlier_gate_threshold=16.0,
        outlier_gate_max_consecutive=5,
    )
    t = _converge(kf, 1.0, 1.0, 1.0)
    out = None
    for _ in range(10):
        out = kf.filter_pose_estimate(_pose(1.0, 1.0, 5.0, 0.0), timestamp=t)
        t += 0.05
    assert out["position_world"]["z"] > 4.0


def test_singular_S_falls_back_to_prediction():
    kf = _kf()
    kf.filter_pose_estimate(_pose(0.0, 0.0, 0.0, 0.0), timestamp=0.0)

    orig_solve = np.linalg.solve

    def _boom(*_args, **_kwargs):
        raise np.linalg.LinAlgError("solve forzato a fallire")

    np.linalg.solve = _boom
    try:
        out = kf.filter_pose_estimate(_pose(1.0, 1.0, 1.0, 0.0), timestamp=0.05)
    finally:
        np.linalg.solve = orig_solve

    assert out is not None
    assert isinstance(out["position_world"], dict)


def test_predict_yaw_noop_before_initialization():
    kf = _kf()
    assert kf.predict_yaw(0.1) is None
    assert kf.yaw_initialized is False
    assert kf.last_yaw_timestamp is None


def test_predict_yaw_advances_timestamp_after_init():
    kf = _kf()
    kf.update_yaw(10.0, timestamp=0.0)
    y = kf.predict_yaw(0.1)
    assert y is not None
    assert abs(kf.last_yaw_timestamp - 0.1) < 1e-9


def test_filter_pose_estimate_predicts_yaw_when_measurement_missing():
    kf = _kf()
    kf.filter_pose_estimate(_pose(0.0, 0.0, 0.0, 5.0), timestamp=0.0)
    assert kf.yaw_initialized is True

    out = kf.filter_pose_estimate(_pose(0.1, 0.0, 0.0), timestamp=0.05)
    assert abs(kf.last_yaw_timestamp - 0.05) < 1e-9
    assert out.get("yaw_world_deg") is None


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
