from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import io
import logging

import numpy as np

from dataclasses import replace

from drone.config import APP_CONFIG
from drone.perception.pose_estimator import CameraPoseEstimator

_WORLD_TAGS = {0: {"position_m": (0.0, 0.0, 0.0)}}


class _Det:
    def __init__(self, margin):
        self.decision_margin = margin


def _make_estimator(**over):
    modifiche = dict(
        camera_matrix=((900.0, 0.0, 480.0), (0.0, 900.0, 360.0), (0.0, 0.0, 1.0)),
        dist_coeffs=(0.0, 0.0, 0.0, 0.0, 0.0),
        tag_family="tag25h9",
        threads=1,
        decimate=2.0,
        tag_size_m=0.2,
        world_tags=_WORLD_TAGS,
        drone_extrinsics=None,
        enabled=False,
    )
    modifiche.update(over)
    return CameraPoseEstimator(replace(APP_CONFIG.camera_pose, **modifiche))


def _estimator(exp):
    return _make_estimator(fusion_distance_weight_exponent=exp)


def test_inverse_square_downweights_far_tags_more_than_linear():
    det = _Det(margin=50.0)
    near = np.array([[0.0], [0.0], [1.0]])
    far = np.array([[0.0], [0.0], [4.0]])

    e1 = _estimator(1.0)
    e2 = _estimator(2.0)

    ratio_linear = (
        e1._compute_detection_weight(det, near)
        / e1._compute_detection_weight(det, far)
    )
    ratio_square = (
        e2._compute_detection_weight(det, near)
        / e2._compute_detection_weight(det, far)
    )

    assert abs(ratio_linear - 4.0) < 1e-6
    assert abs(ratio_square - 16.0) < 1e-6
    assert ratio_square > ratio_linear


def test_exponent_is_clamped_non_negative():
    e = _estimator(-3.0)
    assert e.fusion_distance_weight_exponent == 0.0


def test_default_exponent_is_two():
    est = _make_estimator()
    assert est.fusion_distance_weight_exponent == 2.0


def _estimator_gating(factor=5.0, enabled=True, absolute_max=None):
    return _make_estimator(
        pose_error_gating_enabled=enabled,
        pose_error_relative_factor=factor,
        pose_error_absolute_max=absolute_max,
    )


def test_pose_error_gate_drops_ambiguous_tag():
    est = _estimator_gating(factor=5.0)
    hyps = [
        {"tag_id": 4, "pose_err": 0.001},
        {"tag_id": 2, "pose_err": 0.010},
        {"tag_id": 5, "pose_err": 0.003},
    ]
    kept, dropped = est._filter_hypotheses_by_pose_error(hyps)
    assert 2 in dropped
    assert {h["tag_id"] for h in kept} == {4, 5}


def test_pose_error_gate_keeps_hypotheses_without_pose_err():
    est = _estimator_gating(factor=5.0)
    hyps = [
        {"tag_id": 4, "pose_err": 0.001},
        {"tag_id": 9, "pose_err": None},
        {"tag_id": 2, "pose_err": 0.010},
    ]
    kept, dropped = est._filter_hypotheses_by_pose_error(hyps)
    assert 9 in {h["tag_id"] for h in kept}
    assert 2 in dropped


def test_pose_error_gate_disabled_keeps_all():
    est = _estimator_gating(enabled=False)
    hyps = [{"tag_id": 4, "pose_err": 0.001}, {"tag_id": 2, "pose_err": 0.010}]
    kept, dropped = est._filter_hypotheses_by_pose_error(hyps)
    assert len(kept) == 2 and dropped == []


def test_pose_error_gate_absolute_cap():
    est = _estimator_gating(factor=1000.0, absolute_max=0.005)
    hyps = [{"tag_id": 4, "pose_err": 0.001}, {"tag_id": 2, "pose_err": 0.010}]
    kept, dropped = est._filter_hypotheses_by_pose_error(hyps)
    assert 2 in dropped
    assert {h["tag_id"] for h in kept} == {4}


def test_pose_error_gate_never_empties():
    est = _estimator_gating(factor=1.0)
    hyps = [{"tag_id": 4, "pose_err": 0.001}, {"tag_id": 2, "pose_err": 0.5}]
    kept, dropped = est._filter_hypotheses_by_pose_error(hyps)
    assert len(kept) >= 1
    assert kept[0]["tag_id"] == 4 or 4 in {h["tag_id"] for h in kept}


def test_fused_yaw_degenerate_antipodal_falls_back_to_max_weight():
    est = _estimator(2.0)
    p = np.array([[1.0], [2.0], [3.0]])
    hyps = [
        {"tag_id": 1, "position_world": p.copy(), "yaw_world_deg": 90.0, "weight": 1.0},
        {"tag_id": 2, "position_world": p.copy(), "yaw_world_deg": -90.0, "weight": 1.0},
    ]
    fused = est._fuse_absolute_world_pose(hyps)
    assert abs(fused["yaw_world_deg"] - 90.0) < 1e-6
    assert fused["source"] == "weighted_average"


def test_fused_yaw_normal_case_is_circular_mean():
    est = _estimator(2.0)
    p = np.array([[0.0], [0.0], [1.0]])
    hyps = [
        {"tag_id": 1, "position_world": p.copy(), "yaw_world_deg": 10.0, "weight": 1.0},
        {"tag_id": 2, "position_world": p.copy(), "yaw_world_deg": 30.0, "weight": 1.0},
    ]
    fused = est._fuse_absolute_world_pose(hyps)
    assert abs(fused["yaw_world_deg"] - 20.0) < 1e-6


def _estimator_distance(max_dist):
    return _make_estimator(max_tag_distance_m=max_dist)


def test_distance_cutoff_drops_far_tags():
    est = _estimator_distance(4.0)
    hyps = [
        {"tag_id": 4, "distance": 1.5},
        {"tag_id": 3, "distance": 7.0},
        {"tag_id": 5, "distance": 3.0},
    ]
    kept, dropped = est._filter_hypotheses_by_distance(hyps)
    assert 3 in dropped
    assert {h["tag_id"] for h in kept} == {4, 5}


def test_distance_cutoff_fallback_keeps_nearest_when_all_far():
    est = _estimator_distance(4.0)
    hyps = [{"tag_id": 3, "distance": 7.0}, {"tag_id": 15, "distance": 6.0}]
    kept, dropped = est._filter_hypotheses_by_distance(hyps)
    assert len(kept) == 1 and kept[0]["tag_id"] == 15
    assert dropped == [3]


def test_distance_cutoff_disabled_keeps_all():
    est = _estimator_distance(None)
    hyps = [{"tag_id": 4, "distance": 1.5}, {"tag_id": 3, "distance": 7.0}]
    kept, dropped = est._filter_hypotheses_by_distance(hyps)
    assert len(kept) == 2 and dropped == []


def test_distance_cutoff_keeps_hypotheses_without_distance():
    est = _estimator_distance(4.0)
    hyps = [{"tag_id": 9, "distance": None}, {"tag_id": 3, "distance": 7.0}]
    kept, dropped = est._filter_hypotheses_by_distance(hyps)
    assert 9 in {h["tag_id"] for h in kept}
    assert 3 in dropped



_TAG_A_PARETE = {
    0: {"position_m": (0.0, 0.0, 1.5), "orientation_rpy_deg": (-90.0, 0.0, 0.0)},
}

_IDENTITA = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class _DetFinta:
    def __init__(self, tag_id, t, R=_IDENTITA, margin=60.0, pose_err=0.001):
        self.tag_id = tag_id
        self.pose_t = np.array(t, dtype=np.float32).reshape(3, 1)
        self.pose_R = np.array(R, dtype=np.float32).reshape(3, 3)
        self.decision_margin = margin
        self.pose_err = pose_err
        self.corners = np.array([[10, 10], [40, 10], [40, 40], [10, 40]], dtype=np.float32)
        self.center = np.array([25.0, 25.0], dtype=np.float32)


class _DetectorFinto:
    def __init__(self, detections):
        self._detections = detections

    def detect(self, *a, **k):
        return self._detections


def _estimator_a_parete(detections, **over):
    modifiche = dict(
        enabled=True,
        world_tags=_TAG_A_PARETE,
        drone_extrinsics=APP_CONFIG.camera_pose.drone_extrinsics,
    )
    modifiche.update(over)
    est = _make_estimator(**modifiche)
    est.detector = _DetectorFinto(detections)
    return est


def _frame():
    return np.full((120, 160, 3), 40, dtype=np.uint8)


def _posizione(posa):
    return np.asarray(posa["position_world"], dtype=float).flatten()


def test_un_tag_a_parete_da_la_posa_della_camera_nel_mondo():
    est = _estimator_a_parete([_DetFinta(0, (0.0, 0.0, 1.5))])

    _, risultati = est.process_frame(_frame())

    assert est.last_fused_camera_pose is not None
    posizione = _posizione(est.last_fused_camera_pose)
    assert np.allclose(posizione, (0.0, 1.5, 1.5), atol=1e-5)
    assert abs(est.last_fused_camera_pose["yaw_world_deg"] - 90.0) < 1e-4
    assert est.last_fused_camera_pose["source_tag_ids"] == [0]
    assert any(r.get("type") == "fused_camera_pose_world" for r in risultati)
    assert any(r.get("type") == "fused_drone_pose_world" for r in risultati)
    assert np.allclose(_posizione(est.last_fused_body_pose), posizione, atol=1e-6)
    assert est.last_fused_body_pose["yaw_world_deg"] == est.last_fused_camera_pose["yaw_world_deg"]


def test_il_tag_visto_in_alto_a_destra_mette_la_camera_in_basso_a_sinistra():
    est = _estimator_a_parete([_DetFinta(0, (0.3, -0.2, 1.5))])

    est.process_frame(_frame())

    posizione = _posizione(est.last_fused_camera_pose)
    assert np.allclose(posizione, (-0.3, 1.5, 1.3), atol=1e-5)


def test_il_tag_di_pavimento_non_rende_osservabile_il_yaw():
    tag_a_terra = {0: {"position_m": (0.0, 0.0, 1.0), "orientation_rpy_deg": (0.0, 0.0, 0.0)}}
    est = _estimator_a_parete([_DetFinta(0, (0.0, 0.0, 1.5))], world_tags=tag_a_terra)

    _, risultati = est.process_frame(_frame())

    assert est.last_fused_camera_pose is None
    assert len(risultati) == 1
    assert "camera_position_in_world_frame" not in risultati[0]


def test_un_tag_sconosciuto_non_produce_una_posa_nel_mondo():
    est = _estimator_a_parete([_DetFinta(7, (0.0, 0.0, 1.5))])
    registro = logging.getLogger("drone.perception.pose_estimator")
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    registro.addHandler(handler)
    try:
        _, risultati = est.process_frame(_frame())
    finally:
        registro.removeHandler(handler)

    assert buffer.getvalue() == ""

    assert est.last_fused_camera_pose is None
    assert est.last_fused_body_pose is None
    assert len(risultati) == 1
    assert risultati[0]["tag_id"] == 7
    assert "camera_position_in_world_frame" not in risultati[0]


def test_senza_detection_lo_stato_precedente_si_azzera():
    est = _estimator_a_parete([_DetFinta(0, (0.0, 0.0, 1.5))])
    est.process_frame(_frame())
    assert est.last_fused_camera_pose is not None

    est.detector = _DetectorFinto([])
    _, risultati = est.process_frame(_frame())

    assert risultati == []
    assert est.last_pose_results == []
    assert est.last_fused_camera_pose is None
    assert est.last_fused_body_pose is None


def test_fra_due_tag_il_gate_tiene_solo_quello_vicino():
    due_tag = {
        0: {"position_m": (0.0, 0.0, 1.5), "orientation_rpy_deg": (-90.0, 0.0, 0.0)},
        1: {"position_m": (0.0, 0.0, 1.5), "orientation_rpy_deg": (-90.0, 0.0, 0.0)},
    }
    est = _estimator_a_parete(
        [_DetFinta(0, (0.0, 0.0, 1.5)), _DetFinta(1, (0.0, 0.0, 50.0))],
        world_tags=due_tag,
    )

    est.process_frame(_frame())

    assert est.last_fused_camera_pose["source_tag_ids"] == [0]


def test_un_solo_tag_lontano_si_tiene_lo_stesso():
    est = _estimator_a_parete([_DetFinta(0, (0.0, 0.0, 50.0))])

    est.process_frame(_frame())

    assert est.last_fused_camera_pose is not None
    assert est.last_fused_camera_pose["source_tag_ids"] == [0]


def test_spegnendolo_lo_stato_precedente_viene_dimenticato():
    est = _estimator_a_parete([_DetFinta(0, (0.0, 0.0, 1.5))])
    est.process_frame(_frame())
    assert est.last_fused_camera_pose is not None

    est.enabled = False
    disegno = _frame()
    uscita, risultati = est.process_frame(_frame(), drawing_frame=disegno)

    assert risultati == []
    assert uscita is disegno
    assert est.last_pose_results == []
    assert est.last_fused_camera_pose is None
    assert est.last_fused_body_pose is None


def test_il_frame_annotato_e_una_copia_non_l_originale():
    est = _estimator_a_parete([_DetFinta(0, (0.0, 0.0, 1.5))])
    ingresso = _frame()

    uscita, _ = est.process_frame(ingresso)

    assert uscita is not ingresso
    assert uscita.shape == ingresso.shape


def test_una_detection_rotta_non_ferma_le_altre():
    class _Rotta:
        tag_id = 0
        pose_t = None
        pose_R = None

    est = _estimator_a_parete([_Rotta(), _DetFinta(0, (0.0, 0.0, 1.5))])

    _, risultati = est.process_frame(_frame())

    assert est.last_fused_camera_pose is not None
    assert sum(1 for r in risultati if r.get("tag_id") == 0) == 1


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
    sys.exit(_run_all())
