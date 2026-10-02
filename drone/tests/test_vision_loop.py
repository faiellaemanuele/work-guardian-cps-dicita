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

from drone.config import APP_CONFIG, YoloModelConfig
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


def test_the_label_drawn_on_the_video_is_the_italian_class():
    modelli = (
        YoloModelConfig(
            name="M1", path="m1.pt", label="Modello uno",
            classes={"Safety_Net": "Rete di sicurezza"},
        ),
    )
    rilevate = [
        {"bbox": (1, 2, 3, 4), "label": "Safety_Net", "confidence": 0.9},
        {"bbox": (5, 6, 7, 8), "label": "Without_Helmet", "confidence": 0.5},
    ]
    vl = VisionLoop(
        config=replace(APP_CONFIG, yolo_models=modelli),
        detectors=[{"name": "M1", "color": (0, 0, 255), "detector": _FakeDetector(rilevate)}],
        pose_estimator=None,
    )
    risultati = vl._run_multi_model_detections(_frame())
    etichette = [d["display_label"] for d in risultati[0]["detections"]]
    assert etichette == ["Rete di sicurezza", "Without Helmet"]
    assert risultati[0]["detections"][0]["label"] == "Safety_Net"


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


@contextlib.contextmanager
def _orologio_mai_sentito():
    modulo = sys.modules["drone.perception.vision_loop"]
    modulo._watch_live = None
    try:
        yield modulo
    finally:
        modulo._watch_live = None


def _telemetria_orologio(bpm, spo2, valida=True):
    return _MessaggioMqtt(
        "cantiere/sensori/orologio/operaio_1",
        {"bpm": bpm, "spo2": spo2, "stato": "NORMALE", "lettura_valida": valida},
    )


def test_senza_telemetria_l_orologio_risulta_scollegato():
    with _orologio_mai_sentito() as modulo:
        assert modulo.get_watch_status() == {"connected": False, "bpm": None, "spo2": None}


def test_la_telemetria_accende_la_connessione_e_porta_i_valori():
    with _orologio_mai_sentito() as modulo:
        modulo._on_mqtt_message(None, None, _telemetria_orologio(74, 97))
        assert modulo.get_watch_status() == {"connected": True, "bpm": 74, "spo2": 97}


def test_senza_lettura_valida_l_orologio_e_collegato_ma_senza_valori():
    with _orologio_mai_sentito() as modulo:
        modulo._on_mqtt_message(None, None, _telemetria_orologio(None, None, valida=False))
        assert modulo.get_watch_status() == {"connected": True, "bpm": None, "spo2": None}


def test_una_telemetria_troppo_vecchia_vale_come_orologio_scollegato():
    with _orologio_mai_sentito() as modulo:
        modulo._on_mqtt_message(None, None, _telemetria_orologio(74, 97))
        modulo._watch_live["received_at"] -= modulo.WATCH_TIMEOUT_SEC + 1.0
        assert modulo.get_watch_status() == {"connected": False, "bpm": None, "spo2": None}


def test_l_evento_di_allarme_non_sostituisce_la_telemetria():
    with _orologio_mai_sentito() as modulo:
        modulo._on_mqtt_message(None, None, _telemetria_orologio(74, 97))
        evento = _MessaggioMqtt(
            "cantiere/sensori/orologio/operaio_1",
            {"bpm": 131, "spo2": 95, "evento": "BIOMETRIA_ANOMALA"},
        )
        with _alert_catturati():
            modulo._on_mqtt_message(None, None, evento)
        assert modulo.get_watch_status()["bpm"] == 74


def test_la_taratura_arriva_tutta_dalla_configurazione():
    config = replace(
        APP_CONFIG,
        frame_timeout_sec=12.5,
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

    assert ciclo.frame_timeout_sec == 12.5
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


class _Esito:
    def __init__(self, rc):
        self.rc = rc


class _ClientMqtt:
    def __init__(self, rc=0):
        self.pubblicazioni: list[tuple[str, str]] = []
        self.qos: list[int] = []
        self.retain: list[bool] = []
        self._rc = rc

    def publish(self, topic, payload, qos=0, retain=False):
        self.pubblicazioni.append((topic, payload))
        self.qos.append(qos)
        self.retain.append(retain)
        return _Esito(self._rc)


@contextlib.contextmanager
def _mqtt_finto(client):
    modulo = sys.modules["drone.perception.vision_loop"]
    originale = modulo._mqtt_client
    modulo._mqtt_client = lambda: client
    try:
        yield
    finally:
        modulo._mqtt_client = originale


def test_l_avvio_del_collegamento_crea_il_client_mqtt():
    modulo = sys.modules["drone.perception.vision_loop"]
    chiamate = []
    originale = modulo._mqtt_client
    modulo._mqtt_client = lambda: chiamate.append("client")
    try:
        modulo.start_mqtt_client()
    finally:
        modulo._mqtt_client = originale
        modulo.take_biometric_logger()
    assert chiamate == ["client"]


@contextlib.contextmanager
def _sessione_biometrica():
    modulo = sys.modules["drone.perception.vision_loop"]
    originale = modulo._mqtt_client
    modulo._mqtt_client = lambda: None
    try:
        modulo.start_mqtt_client()
    finally:
        modulo._mqtt_client = originale
    try:
        yield modulo
    finally:
        modulo.take_biometric_logger()


def test_la_telemetria_dell_orologio_finisce_nella_sessione_biometrica():
    with _sessione_biometrica() as modulo:
        telemetria = _MessaggioMqtt(
            "cantiere/sensori/orologio/operaio_1",
            {"bpm": 78, "spo2": 97, "stato": "NORMALE", "lettura_valida": True,
             "hr_grezzo": 81.5, "hr_filtrato": 78.2,
             "spo2_grezzo": 96.0, "spo2_filtrato": 97.3},
        )
        evento = _MessaggioMqtt(
            "cantiere/sensori/orologio/operaio_1",
            {"bpm": 131, "spo2": 95, "evento": "BIOMETRIA_ANOMALA"},
        )
        with _alert_catturati():
            modulo._on_mqtt_message(None, None, telemetria)
            modulo._on_mqtt_message(None, None, evento)
        log = modulo.take_biometric_logger()

    assert log is not None
    campioni = log.samples("operaio_1")
    assert len(campioni) == 1
    assert campioni[0]["hr_grezzo"] == 81.5
    assert len(log.events("operaio_1")) == 1


def test_la_sessione_biometrica_si_consegna_una_volta_sola():
    with _sessione_biometrica() as modulo:
        primo = modulo.take_biometric_logger()
        secondo = modulo.take_biometric_logger()
    assert primo is not None
    assert secondo is None


def test_senza_sessione_aperta_la_telemetria_non_si_registra_e_non_rompe():
    modulo = sys.modules["drone.perception.vision_loop"]
    modulo.take_biometric_logger()
    telemetria = _MessaggioMqtt(
        "cantiere/sensori/orologio/operaio_1",
        {"bpm": 78, "spo2": 97, "stato": "NORMALE", "lettura_valida": True},
    )
    with _alert_catturati() as catturati:
        modulo._on_mqtt_message(None, None, telemetria)
    assert catturati == []
    assert modulo.take_biometric_logger() is None


def test_un_errore_di_pubblicazione_non_interrompe_il_volo():
    class _Rotto:
        def publish(self, topic, payload, qos=0, retain=False):
            raise RuntimeError("broker sparito")

    vl = _vision_loop()
    with _mqtt_finto(_Rotto()):
        assert vl.publish_alarm(kind="fall", message="Caduta") is False


def test_la_batteria_non_leggibile_resta_fuori_dal_log_degli_errori():
    import logging

    class _SenzaBatteria:
        def get_status(self):
            return {"connected": True, "flying": True, "battery": None}

    logger = logging.getLogger("drone.perception.vision_loop")
    registrati = []
    raccoglitore = logging.Handler()
    raccoglitore.emit = registrati.append
    logger.addHandler(raccoglitore)
    livello_precedente = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        vl = _vision_loop(status_refresh_sec=0.0)
        vl.cached_status["battery"] = 40
        vl._refresh_status(_SenzaBatteria())
    finally:
        logger.removeHandler(raccoglitore)
        logger.setLevel(livello_precedente)
    assert registrati, "il messaggio deve comunque essere registrato"
    assert all(r.levelno < logging.WARNING for r in registrati)


def test_l_allarme_non_consegnato_finisce_nel_log_degli_errori():
    import logging

    logger = logging.getLogger("drone.perception.vision_loop")
    registrati = []
    raccoglitore = logging.Handler()
    raccoglitore.emit = registrati.append
    logger.addHandler(raccoglitore)
    try:
        vl = _vision_loop()
        with _mqtt_finto(_ClientMqtt(rc=4)):
            vl.publish_alarm(kind="fall", message="Caduta")
    finally:
        logger.removeHandler(raccoglitore)
    assert len(registrati) == 1
    assert registrati[0].levelno >= logging.WARNING


def test_l_allarme_va_sul_topic_degli_allarmi_con_qos_1():
    vl = _vision_loop()
    client = _ClientMqtt()
    with _mqtt_finto(client):
        assert vl.publish_alarm(
            kind="restricted_area",
            message="Una persona in un'area vietata",
            level="critical",
        ) is True

    topic, carico = client.pubblicazioni[0]
    assert topic == "cantiere/allarmi"
    assert client.qos[0] == 1
    corpo = json.loads(carico)
    assert corpo["type"] == "restricted_area"
    assert corpo["level"] == "critical"
    assert corpo["source"] == "drone"
    assert corpo["msg"] == "Una persona in un'area vietata"


def test_l_allarme_non_ha_target_cosi_lo_riceve_ogni_orologio():
    vl = _vision_loop()
    client = _ClientMqtt()
    with _mqtt_finto(client):
        vl.publish_alarm(kind="dpi_missing", message="Manca l'elmetto")

    assert "target" not in json.loads(client.pubblicazioni[0][1])


def test_l_allarme_a_broker_giu_resta_in_coda_e_non_si_perde():
    vl = _vision_loop()
    client = _ClientMqtt(rc=4)
    with _mqtt_finto(client):
        assert vl.publish_alarm(kind="fall", message="Caduta") is True
    assert client.qos[0] == 1, "l'accodamento vale solo con QoS >= 1"


def test_un_errore_diverso_dalla_disconnessione_fa_fallire_l_allarme():
    vl = _vision_loop()
    with _mqtt_finto(_ClientMqtt(rc=1)):
        assert vl.publish_alarm(kind="fall", message="Caduta") is False


def test_senza_broker_l_allarme_non_blocca_il_volo():
    vl = _vision_loop()
    with _mqtt_finto(None):
        assert vl.publish_alarm(kind="fall", message="Caduta") is False


class _MessaggioMqtt:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")


@contextlib.contextmanager
def _alert_catturati():
    modulo = sys.modules["drone.perception.vision_loop"]
    originale = modulo.print_event
    catturati = []
    modulo.print_event = lambda msg, **kw: catturati.append((msg, kw))
    try:
        yield catturati
    finally:
        modulo.print_event = originale


def test_all_avvio_il_drone_ascolta_gli_orologi():
    modulo = sys.modules["drone.perception.vision_loop"]

    class _Client(_ClientMqtt):
        def __init__(self):
            super().__init__()
            self.iscrizioni = []

        def subscribe(self, topic, qos=0):
            self.iscrizioni.append(topic)

    client = _Client()
    modulo._on_mqtt_connect(client)
    assert client.iscrizioni == ["cantiere/sensori/orologio/+"]


@contextlib.contextmanager
def _missione_a_terra():
    modulo = sys.modules["drone.perception.vision_loop"]
    modulo._watch_mission_active = False
    try:
        yield modulo
    finally:
        modulo._watch_mission_active = False


def _tipi_pubblicati(client) -> list:
    return [
        json.loads(carico).get("tipo")
        for topic, carico in client.pubblicazioni
        if topic == "cantiere/allarmi"
    ]


def test_il_decollo_avvia_la_missione_dell_orologio():
    client = _ClientMqtt()
    with _missione_a_terra() as modulo, _mqtt_finto(client):
        modulo.update_watch_mission(True)

    assert client.pubblicazioni[0][0] == "cantiere/allarmi"
    assert _tipi_pubblicati(client) == ["AVVIO_MISSIONE"]
    assert client.qos == [1]
    assert client.retain == [True], "un orologio collegato a volo iniziato deve riceverlo"


def test_l_atterraggio_chiude_la_missione_dell_orologio():
    client = _ClientMqtt()
    with _missione_a_terra() as modulo, _mqtt_finto(client):
        modulo.update_watch_mission(True)
        modulo.update_watch_mission(False)

    assert _tipi_pubblicati(client) == ["AVVIO_MISSIONE", "FINE_MISSIONE"]


def test_senza_cambi_di_stato_l_orologio_non_riceve_niente():
    client = _ClientMqtt()
    with _missione_a_terra() as modulo, _mqtt_finto(client):
        modulo.update_watch_mission(False)
        modulo.update_watch_mission(True)
        modulo.update_watch_mission(True)

    assert _tipi_pubblicati(client) == ["AVVIO_MISSIONE"]


def test_senza_broker_la_missione_non_blocca_il_volo():
    with _missione_a_terra() as modulo, _mqtt_finto(None):
        modulo.update_watch_mission(True)
        assert modulo._watch_mission_active is True


def test_un_errore_di_pubblicazione_della_missione_non_interrompe_il_volo():
    class _Rotto:
        def publish(self, topic, payload, qos=0, retain=False):
            raise RuntimeError("broker sparito")

    with _missione_a_terra() as modulo, _mqtt_finto(_Rotto()):
        modulo.update_watch_mission(True)


def test_a_ogni_collegamento_il_drone_ripete_lo_stato_della_missione():
    class _Client(_ClientMqtt):
        def subscribe(self, topic, qos=0):
            pass

    a_terra = _Client()
    in_volo = _Client()
    with _missione_a_terra() as modulo:
        modulo._on_mqtt_connect(a_terra)
        modulo._watch_mission_active = True
        modulo._on_mqtt_connect(in_volo)

    assert _tipi_pubblicati(a_terra) == ["FINE_MISSIONE"]
    assert _tipi_pubblicati(in_volo) == ["AVVIO_MISSIONE"]
    assert a_terra.retain[-1] is True


class _ClientDaChiudere(_ClientMqtt):
    def __init__(self):
        super().__init__()
        self.chiuso = False

    def publish(self, topic, payload, qos=0, retain=False):
        super().publish(topic, payload, qos, retain)
        return type("_Info", (), {"rc": 0, "wait_for_publish": lambda self, timeout: None})()

    def disconnect(self):
        self.chiuso = True

    def loop_stop(self):
        pass


def test_la_chiusura_del_collegamento_chiude_la_missione_aperta():
    client = _ClientDaChiudere()
    with _missione_a_terra() as modulo:
        modulo._watch_mission_active = True
        modulo._mqtt_singleton = client
        modulo.stop_mqtt_client()

        assert modulo._watch_mission_active is False
    assert client.pubblicazioni[0][0] == "cantiere/allarmi"
    assert json.loads(client.pubblicazioni[0][1])["tipo"] == "FINE_MISSIONE"
    assert client.pubblicazioni[-1] == ("cantiere/sistema/drone/status", "offline")
    assert client.chiuso is True


def test_la_chiusura_a_missione_gia_finita_non_ripete_la_fine():
    client = _ClientDaChiudere()
    with _missione_a_terra() as modulo:
        modulo._mqtt_singleton = client
        modulo.stop_mqtt_client()

    assert [topic for topic, _ in client.pubblicazioni] == ["cantiere/sistema/drone/status"]


def test_l_allarme_biometrico_dell_orologio_entra_nel_log_degli_alert():
    modulo = sys.modules["drone.perception.vision_loop"]
    messaggio = _MessaggioMqtt(
        "cantiere/sensori/orologio/operaio_1",
        {"bpm": 131, "spo2": 95, "evento": "BIOMETRIA_ANOMALA"},
    )
    with _alert_catturati() as catturati:
        modulo._on_mqtt_message(None, None, messaggio)

    assert len(catturati) == 1
    testo, opzioni = catturati[0]
    assert testo == "operaio_1: 131 bpm, SpO2 95%"
    assert opzioni["channel"] == "alert"


def test_la_telemetria_dell_orologio_non_entra_nel_log_degli_alert():
    modulo = sys.modules["drone.perception.vision_loop"]
    telemetria = _MessaggioMqtt(
        "cantiere/sensori/orologio/operaio_1",
        {"bpm": 131, "spo2": 95, "stato": "ALLARME", "lettura_valida": True},
    )
    with _alert_catturati() as catturati:
        modulo._on_mqtt_message(None, None, telemetria)
    assert catturati == []


def test_un_messaggio_illeggibile_dell_orologio_viene_ignorato():
    modulo = sys.modules["drone.perception.vision_loop"]
    for payload in (b"{non json", b"\xff\xfe", json.dumps([1, 2]).encode("utf-8")):
        with _alert_catturati() as catturati:
            modulo._on_mqtt_message(
                None, None, _MessaggioMqtt("cantiere/sensori/orologio/operaio_1", payload)
            )
        assert catturati == []


def test_lo_stato_del_joystick_resta_noto_se_la_telemetria_fallisce():
    modulo = sys.modules["drone.perception.vision_loop"]
    vl = _vision_loop(status_refresh_sec=0.0)
    ctrl = _StatusSequenceController([RuntimeError("timeout SDK")])
    originale = modulo.is_joystick_connected
    modulo.is_joystick_connected = lambda: True
    try:
        vl._refresh_status(ctrl)
    finally:
        modulo.is_joystick_connected = originale
    assert vl.cached_status["joystick"] is True


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
