from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import contextlib
import json
import time
from dataclasses import replace

import cv2
import numpy as np

from drone.config import APP_CONFIG
from drone.perception.vision_loop import VisionLoop

cv2.imshow = lambda *a, **k: None
cv2.waitKey = lambda *a, **k: -1
cv2.getWindowProperty = lambda *a, **k: 1.0


_CAMPI_DI_CONFIGURAZIONE = (
    "frame_timeout_sec",
    "frame_from_controller_is_rgb",
    "status_refresh_sec",
    "pose_valid_for_sec",
    "detection_interval_sec",
    "video_fade_in_sec",
    "safety_net_verdict_banner_sec",
    "vision_warning_repeat_after_sec",
)


def _vision_loop(**kw):
    modifiche = {nome: kw.pop(nome) for nome in _CAMPI_DI_CONFIGURAZIONE if nome in kw}
    params = dict(detectors=[], pose_estimator=None)
    params.update(kw)
    return VisionLoop(config=replace(APP_CONFIG, **modifiche), **params)


def _frame():
    return np.zeros((48, 64, 3), dtype=np.uint8)


class _FrameController:
    def __init__(self, frame=None):
        self._frame = frame

    def get_frame(self):
        return self._frame

    def get_status(self):
        return {"connected": True, "flying": True, "battery": 77}


class _StatusSequenceController:
    def __init__(self, status_sequence):
        self._seq = list(status_sequence)
        self.calls = 0

    def get_status(self):
        self.calls += 1
        outcome = self._seq.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


_DETECTOR_DELAY_SEC = 0.15

_STEP_BUDGET_SEC = 0.05


class _SlowDetector:
    def __init__(self, detections, delay=_DETECTOR_DELAY_SEC):
        self._detections = detections
        self._delay = delay

    def detect(self, frame):
        time.sleep(self._delay)
        return frame, self._detections


def _detectors():
    return [
        {
            "name": "Slow",
            "color": (0, 0, 255),
            "detector": _SlowDetector([{"bbox": (2, 2, 10, 10), "label": "x", "confidence": 0.8}]),
        }
    ]


class _FakeDetector:
    def __init__(self, detections):
        self._detections = detections

    def detect(self, frame):
        return frame, self._detections


def _make_detectors():
    return [
        {
            "name": "M1",
            "color": (0, 0, 255),
            "detector": _FakeDetector([{"bbox": (1, 2, 3, 4), "label": "obj", "confidence": 0.9}]),
        }
    ]


def _wait_for(predicate, timeout=3.0, poll=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return predicate()


def test_fresh_pose_is_returned():
    vl = _vision_loop(pose_valid_for_sec=0.5)
    pose = {"position_world": {"x": 1.0, "y": 2.0, "z": 3.0}}
    vl.last_filtered_pose_estimate = pose
    vl.last_pose_estimate_at = time.monotonic()
    assert vl.get_latest_pose_estimate() is pose


def test_stale_pose_is_dropped():
    vl = _vision_loop(pose_valid_for_sec=0.5)
    pose = {"position_world": {"x": 1.0, "y": 2.0, "z": 3.0}}
    vl.last_filtered_pose_estimate = pose
    vl.last_pose_estimate_at = time.monotonic() - 1.0
    assert vl.get_latest_pose_estimate() is None


def test_no_pose_returns_none():
    vl = _vision_loop(pose_valid_for_sec=0.5)
    assert vl.last_filtered_pose_estimate is None
    assert vl.get_latest_pose_estimate() is None


def test_rgb_frame_is_swapped_to_bgr():
    vl = _vision_loop(frame_from_controller_is_rgb=True)
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    frame[..., 0] = 10
    frame[..., 2] = 200
    out = vl._normalize_frame_for_opencv(frame)
    assert int(out[0, 0, 0]) == 200
    assert int(out[0, 0, 2]) == 10


def test_bgr_frame_is_passthrough():
    vl = _vision_loop(frame_from_controller_is_rgb=False)
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    frame[..., 0] = 10
    out = vl._normalize_frame_for_opencv(frame)
    assert out is frame
    assert int(out[0, 0, 0]) == 10


def test_step_returns_true_with_frame():
    vl = _vision_loop(detectors=[], detection_interval_sec=0.0)
    ctrl = _FrameController(_frame())
    try:
        assert vl.step(ctrl, run_detection=False) is True
    finally:
        vl.stop()


def test_step_times_out_without_frames():
    vl = _vision_loop(detectors=[], detection_interval_sec=0.0)
    ctrl = _FrameController(None)
    try:
        vl.frame_timeout_sec = 0.05
        vl.last_frame_received_at = time.monotonic() - 10.0
        assert vl.step(ctrl, run_detection=False) is False
    finally:
        vl.stop()


def test_step_does_not_block_on_slow_detection():
    vl = _vision_loop(detectors=_detectors(), detection_interval_sec=0.0)
    ctrl = _FrameController(_frame())
    try:
        durations = []
        for _ in range(20):
            t0 = time.perf_counter()
            ok = vl.step(ctrl, run_detection=True)
            durations.append(time.perf_counter() - t0)
            assert ok is True
            time.sleep(0.03)

        steady = sorted(durations[3:])
        median = steady[len(steady) // 2]
        slowest = steady[-1]

        assert median < _STEP_BUDGET_SEC, (
            f"step() troppo lento a regime: mediana {median*1000:.1f} ms "
            f"(atteso < {_STEP_BUDGET_SEC*1000:.0f} ms, il budget di un giro a 20 Hz)"
        )

        ceiling = _DETECTOR_DELAY_SEC * 0.66
        assert slowest < ceiling, (
            f"step() ha atteso l'inferenza: il più lento {slowest*1000:.1f} ms, "
            f"vicino ai {_DETECTOR_DELAY_SEC*1000:.0f} ms del detector"
        )

        with vl._detection_lock:
            cached = vl._cached_detections
        assert cached, "il worker non ha popolato la cache"
        assert cached[0]["name"] == "Slow"
        assert cached[0]["detections"][0]["label"] == "x"
    finally:
        vl.stop()


def test_cache_empty_without_detection():
    vl = _vision_loop(detectors=_detectors(), detection_interval_sec=0.0)
    ctrl = _FrameController(_frame())
    try:
        for _ in range(5):
            assert vl.step(ctrl, run_detection=False) is True
            time.sleep(0.02)
        with vl._detection_lock:
            assert vl._cached_detections == []
    finally:
        vl.stop()


def test_valid_battery_is_cached():
    vl = _vision_loop(status_refresh_sec=0.0)
    ctrl = _StatusSequenceController([{"connected": True, "flying": True, "battery": 80}])
    vl._refresh_status(ctrl)
    assert vl.cached_status["battery"] == 80


def test_none_battery_keeps_last_known():
    vl = _vision_loop(status_refresh_sec=0.0)
    ctrl = _StatusSequenceController([
        {"connected": True, "flying": True, "battery": 42},
        {"connected": True, "flying": True, "battery": None},
    ])
    vl._refresh_status(ctrl)
    assert vl.cached_status["battery"] == 42
    vl._refresh_status(ctrl)
    assert vl.cached_status["battery"] == 42


def test_exception_keeps_last_known_battery():
    vl = _vision_loop(status_refresh_sec=0.0)
    ctrl = _StatusSequenceController([
        {"connected": True, "flying": True, "battery": 30},
        RuntimeError("timeout SDK"),
    ])
    vl._refresh_status(ctrl)
    assert vl.cached_status["battery"] == 30
    vl._refresh_status(ctrl)
    assert vl.cached_status["battery"] == 30
    assert vl.cached_status["connected"] is False


def test_none_battery_without_previous_stays_none():
    vl = _vision_loop(status_refresh_sec=0.0)
    ctrl = _StatusSequenceController([{"connected": True, "flying": False, "battery": None}])
    vl._refresh_status(ctrl)
    assert vl.cached_status["battery"] is None


def test_worker_populates_cache_when_active():
    vl = _vision_loop(detectors=_make_detectors(), detection_interval_sec=0.0)
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    with vl._detection_lock:
        vl._detection_active = True
        vl._pending_analysis_frame = frame
    vl._ensure_detection_thread()
    try:
        populated = _wait_for(lambda: bool(vl._cached_detections))
        assert populated is True
        cached = vl._cached_detections
        assert cached[0]["name"] == "M1"
        assert cached[0]["detections"][0]["label"] == "obj"
    finally:
        vl.stop()
    assert vl._detection_thread is None


def test_worker_idle_when_inactive():
    vl = _vision_loop(detectors=_make_detectors(), detection_interval_sec=0.0)
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    with vl._detection_lock:
        vl._detection_active = False
        vl._pending_analysis_frame = frame
    vl._ensure_detection_thread()
    try:
        time.sleep(0.3)
        assert vl._cached_detections == []
    finally:
        vl.stop()


def test_stop_is_idempotent_without_start():
    vl = _vision_loop(detectors=[], detection_interval_sec=0.0)
    vl.stop()
    vl.stop()
    assert vl._detection_thread is None


def test_stop_joins_running_thread():
    vl = _vision_loop(detectors=_make_detectors(), detection_interval_sec=0.0)
    vl._ensure_detection_thread()
    assert vl._detection_thread is not None
    assert vl._detection_thread.is_alive() is True
    vl.stop()
    assert vl._detection_thread is None



class _ControllerConStato:
    def __init__(self, frame):
        self._frame = frame

    def get_frame(self):
        return self._frame

    def get_status(self):
        return {"connected": True, "flying": True, "battery": 55}


def test_step_si_ferma_quando_la_finestra_viene_chiusa():
    ciclo = _vision_loop()
    originale = cv2.getWindowProperty
    cv2.getWindowProperty = lambda *a, **k: 0.0
    try:
        assert ciclo.step(_ControllerConStato(_frame())) is False
    finally:
        cv2.getWindowProperty = originale


def test_step_prosegue_con_la_finestra_aperta():
    ciclo = _vision_loop()
    assert ciclo.step(_ControllerConStato(_frame())) is True


def test_senza_modelli_la_detection_resta_spenta_anche_se_richiesta():
    ciclo = _vision_loop(detectors=[])

    ciclo.step(_ControllerConStato(_frame()), run_detection=True)

    assert ciclo._detection_active is False
    assert ciclo._pending_analysis_frame is None
    assert ciclo.get_cached_detections_snapshot() == []


def test_con_un_modello_la_detection_richiesta_pubblica_il_frame():
    class _Rilevatore:
        name = "Prova"
        color = (0, 255, 0)

        def detect(self, frame):
            return []

    ciclo = _vision_loop(detectors=[_Rilevatore()])
    try:
        ciclo.step(_ControllerConStato(_frame()), run_detection=True)
        assert ciclo._detection_active is True
        assert ciclo._pending_analysis_frame is not None
    finally:
        ciclo.stop()


def test_lo_stato_del_drone_arriva_al_pannello():
    ciclo = _vision_loop()

    ciclo.step(_ControllerConStato(_frame()))

    assert ciclo.cached_status["battery"] == 55
    assert ciclo.cached_status["connected"] is True


def test_l_autopilota_chiede_la_detection_in_sosta():
    ciclo = _vision_loop()

    ciclo.last_autopilot_command = {"supervision_detection_requested": True}

    assert ciclo.autopilot_requests_detection() is True


def test_fuori_dalla_sosta_l_autopilota_non_chiede_la_detection():
    ciclo = _vision_loop()

    ciclo.last_autopilot_command = {"supervision_detection_requested": False}

    assert ciclo.autopilot_requests_detection() is False


def test_un_comando_senza_la_chiave_non_chiede_la_detection():
    ciclo = _vision_loop()

    ciclo.last_autopilot_command = {"reason": "moving"}

    assert ciclo.autopilot_requests_detection() is False


def test_senza_comando_dell_autopilota_non_si_chiede_la_detection():
    ciclo = _vision_loop()

    assert ciclo.last_autopilot_command is None
    assert ciclo.autopilot_requests_detection() is False


class _ThreadCheNonMuore:
    def __init__(self):
        self.join_calls = 0

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_calls += 1


def test_stop_non_dimentica_un_thread_che_non_muore():
    ciclo = _vision_loop()
    thread = _ThreadCheNonMuore()
    ciclo._detection_thread = thread

    ciclo.stop()

    assert thread.join_calls == 1
    assert ciclo._detection_thread is thread


class _CruscottoFinto:
    enabled = True

    def __init__(self):
        self.tag_visti = None

    def set_pose(self, pose_estimate, fresh=False):
        pass

    def set_visible_tags(self, tag_ids):
        self.tag_visti = set(tag_ids)

    def scale_video(self, frame):
        return frame

    def attach_panels(self, frame):
        return frame


class _StimatoreConTag:
    enabled = True
    last_fused_body_pose = None
    last_fused_camera_pose = None
    last_pose_results = ({"tag_id": 8}, {"tag_id": 16})

    def undistort_frame(self, frame):
        return frame

    def process_frame(self, frame, drawing_frame=None, frame_is_undistorted=False):
        return drawing_frame, None


def test_i_tag_visti_arrivano_alla_mappa_del_cruscotto():
    ciclo = _vision_loop(pose_estimator=_StimatoreConTag())
    cruscotto = _CruscottoFinto()

    ciclo.step(_ControllerConStato(_frame()), dashboard=cruscotto)

    assert cruscotto.tag_visti == {8, 16}


def test_lo_stato_dell_orologio_parte_scollegato_e_senza_carica():
    ciclo = _vision_loop()

    assert ciclo.watch_status == {"connected": False, "battery": None}


def test_la_taratura_arriva_tutta_dalla_configurazione():
    config = replace(
        APP_CONFIG,
        frame_timeout_sec=3.5,
        frame_from_controller_is_rgb=False,
        status_refresh_sec=0.25,
        pose_valid_for_sec=0.75,
        detection_interval_sec=0.4,
        video_fade_in_sec=0.6,
        safety_net_verdict_banner_sec=9.0,
        vision_warning_repeat_after_sec=11.0,
        project_title="PROVA",
    )

    ciclo = VisionLoop(config=config, detectors=[], pose_estimator=None)

    assert ciclo.frame_timeout_sec == 3.5
    assert ciclo.frame_from_controller_is_rgb is False
    assert ciclo.status_refresh_sec == 0.25
    assert ciclo.pose_valid_for_sec == 0.75
    assert ciclo.detection_interval_sec == 0.4
    assert ciclo.video_fade_in_sec == 0.6
    assert ciclo.safety_net_verdict_banner_sec == 9.0
    assert ciclo._warning_repeat_after_sec == 11.0
    assert ciclo.project_title == "PROVA"


def test_lo_stato_dice_anche_se_il_joystick_e_collegato():
    from drone.perception import vision_loop as modulo

    vl = _vision_loop(status_refresh_sec=0.0)
    ctrl = _StatusSequenceController([{"connected": True, "flying": False, "battery": 55}])
    originale = modulo.is_joystick_connected
    modulo.is_joystick_connected = lambda: True
    try:
        vl._refresh_status(ctrl)
    finally:
        modulo.is_joystick_connected = originale
    assert vl.cached_status["joystick"] is True


def test_senza_controller_lo_stato_del_joystick_parte_spento():
    vl = _vision_loop(status_refresh_sec=0.0)
    assert vl.cached_status["joystick"] is False


class _ClientMqtt:
    def __init__(self):
        self.pubblicazioni: list[tuple[str, str]] = []

    def publish(self, topic, payload):
        self.pubblicazioni.append((topic, payload))


@contextlib.contextmanager
def _mqtt_finto(client):
    modulo = sys.modules["drone.perception.vision_loop"]
    originale = modulo._mqtt_client
    modulo._mqtt_client = lambda: client
    try:
        yield
    finally:
        modulo._mqtt_client = originale


def test_la_telemetria_va_sul_topic_dei_sensori():
    vl = _vision_loop()
    client = _ClientMqtt()
    with _mqtt_finto(client):
        assert vl.publish_state(now=0.0) is True

    topic, carico = client.pubblicazioni[0]
    assert topic == "cantiere/sensori/drone"
    assert set(json.loads(carico)) == {"battery", "is_flying", "position", "detections"}


def test_le_detection_hanno_le_chiavi_che_il_server_legge():
    vl = _vision_loop()
    vl._cached_detections = [
        {"name": "Caduta_delle_Persone", "detections": [{"label": "person", "confidence": 0.89}]}
    ]
    client = _ClientMqtt()
    with _mqtt_finto(client):
        vl.publish_state(now=0.0)

    detections = json.loads(client.pubblicazioni[0][1])["detections"]
    assert detections == [{"label": "person", "conf": 0.89}]


def test_la_telemetria_rispetta_l_intervallo():
    vl = _vision_loop()
    client = _ClientMqtt()
    with _mqtt_finto(client):
        assert vl.publish_state(now=0.0) is True
        assert vl.publish_state(now=0.2) is False
        assert vl.publish_state(now=0.6) is True
    assert len(client.pubblicazioni) == 2


def test_senza_broker_il_volo_prosegue():
    vl = _vision_loop()
    with _mqtt_finto(None):
        assert vl.publish_state(now=0.0) is False


def test_un_errore_di_pubblicazione_non_interrompe_il_volo():
    class _Rotto:
        def publish(self, topic, payload):
            raise RuntimeError("broker sparito")

    vl = _vision_loop()
    with _mqtt_finto(_Rotto()):
        assert vl.publish_state(now=0.0) is False


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
