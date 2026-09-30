from __future__ import annotations

import json
import logging
import sys
import threading
import time
from typing import TYPE_CHECKING, Optional

import cv2
import numpy as np

from drone.config import APP_CONFIG
from drone.data.biometric_data_logger import BIOMETRIC_ALARM_EVENT, BiometricDataLogger
from drone.hardware.joystick import is_joystick_connected
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

MQTT_TOPIC_ALARMS = "cantiere/allarmi"
MQTT_TOPIC_STATUS = "cantiere/sistema/drone/status"
MQTT_TOPIC_WATCHES = "cantiere/sensori/orologio/+"
MQTT_WATCH_TOPIC_PREFIX = "cantiere/sensori/orologio/"
WATCH_BIOMETRIC_EVENT = BIOMETRIC_ALARM_EVENT
MQTT_OFFLINE_WAIT_SEC = 1.0

# Valori del campo "tipo" che l'orologio riconosce per l'inizio e la fine della
# missione (onMqttMessage nel firmware). Per l'orologio la missione coincide
# con il volo: comincia al decollo e finisce a qualunque atterraggio.
WATCH_MISSION_STARTED = "AVVIO_MISSIONE"
WATCH_MISSION_ENDED = "FINE_MISSIONE"

_MQTT_ERR_NO_CONN = 4

_MQTT_NON_CREATO = object()
_mqtt_singleton = _MQTT_NON_CREATO

# La sessione biometrica dura quanto il collegamento al broker: si apre con
# start_mqtt_client e la raccoglie run_postflight con take_biometric_logger.
_biometric_logger: Optional[BiometricDataLogger] = None

# Ultimo stato della missione comunicato all'orologio.
_watch_mission_active = False

# L'orologio pubblica la telemetria ogni 0,5 s: dopo questo silenzio il
# pannello sul video lo considera scollegato.
WATCH_TIMEOUT_SEC = 3.0

# Ultima telemetria dell'orologio, per il pannello sul video. La scrive il
# thread di paho e la legge il ciclo del video: si sostituisce sempre il
# dizionario intero, cosi' chi legge non ne vede mai uno a meta'.
_watch_live: Optional[dict] = None


def _publish_watch_mission(client, active: bool) -> None:
    # Il messaggio resta sul broker (retain): un orologio che si collega a volo
    # già iniziato, o che si ricollega dopo un calo del Wi-Fi, lo riceve subito
    # invece di restare in attesa dell'avvio.
    tipo = WATCH_MISSION_STARTED if active else WATCH_MISSION_ENDED
    try:
        client.publish(
            MQTT_TOPIC_ALARMS,
            json.dumps({"source": "drone", "tipo": tipo}),
            qos=1,
            retain=True,
        )
    except Exception:
        LOGGER.warning("Non è stato possibile comunicare all'orologio lo stato della missione", exc_info=True)


def update_watch_mission(flying: bool) -> None:
    # Pubblica solo i cambi di stato: il ciclo di volo la chiama a ogni giro.
    global _watch_mission_active
    if flying == _watch_mission_active:
        return
    _watch_mission_active = flying
    client = _mqtt_client()
    if client is not None:
        _publish_watch_mission(client, flying)


def _on_mqtt_connect(client, *_args) -> None:
    try:
        client.publish(MQTT_TOPIC_STATUS, "online", qos=1, retain=True)
        client.subscribe(MQTT_TOPIC_WATCHES)
    except Exception:
        LOGGER.warning("Non è stato possibile comunicare al broker che il drone è in linea", exc_info=True)
    # A ogni collegamento, anche dopo una caduta del broker, lo stato della
    # missione viene ripetuto. Al primo collegamento, a terra, sostituisce un
    # eventuale avvio rimasto sul broker da una sessione chiusa male.
    _publish_watch_mission(client, _watch_mission_active)


def _on_mqtt_message(_client, _userdata, message) -> None:
    # Sul topic dell'orologio passa anche la telemetria continua, che finisce
    # nella sessione biometrica per i grafici di fine sessione e nel pannello
    # sul video. Nel Log degli alert entra solo l'evento che l'orologio
    # pubblica quando va in allarme biometrico, poiché le soglie e la
    # decisione appartengono al firmware.
    global _watch_live
    if not message.topic.startswith(MQTT_WATCH_TOPIC_PREFIX):
        return
    try:
        evento = json.loads(message.payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return
    if not isinstance(evento, dict):
        return
    if "lettura_valida" in evento:  # telemetria, non l'evento di allarme
        _watch_live = {
            "received_at": time.monotonic(),
            "bpm": evento.get("bpm"),
            "spo2": evento.get("spo2"),
        }
    operaio = message.topic[len(MQTT_WATCH_TOPIC_PREFIX):]
    biometric_logger = _biometric_logger
    if biometric_logger is not None:
        try:
            biometric_logger.log_message(operaio, evento)
        except Exception:
            LOGGER.warning("Non è stato possibile registrare il messaggio dell'orologio", exc_info=True)
    if evento.get("evento") != WATCH_BIOMETRIC_EVENT:
        return
    bpm = evento.get("bpm")
    spo2 = evento.get("spo2")
    print_event(f"{operaio}: {bpm} bpm, SpO2 {spo2}%", prefix="AVVISO", channel="alert")


def get_watch_status() -> dict:
    # Collegato finché la telemetria continua ad arrivare. Battito e
    # saturazione valgono None quando l'orologio non ha una lettura valida.
    live = _watch_live
    if live is None or time.monotonic() - live["received_at"] > WATCH_TIMEOUT_SEC:
        return {"connected": False, "bpm": None, "spo2": None}
    return {"connected": True, "bpm": live["bpm"], "spo2": live["spo2"]}


def _mqtt_client():
    global _mqtt_singleton
    if _mqtt_singleton is not _MQTT_NON_CREATO:
        return _mqtt_singleton

    _mqtt_singleton = None
    try:
        import paho.mqtt.client as mqtt

        try:
            client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            client = mqtt.Client()
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.will_set(MQTT_TOPIC_STATUS, "offline", qos=1, retain=True)
        client.on_connect = _on_mqtt_connect
        client.on_message = _on_mqtt_message
        client.connect_async(APP_CONFIG.mqtt_broker_ip, APP_CONFIG.mqtt_broker_port, 30)
        client.loop_start()
        _mqtt_singleton = client
        LOGGER.info(
            "Il collegamento al broker %s:%s è stato avviato",
            APP_CONFIG.mqtt_broker_ip,
            APP_CONFIG.mqtt_broker_port,
        )
    except Exception:
        LOGGER.warning(
            "Non è stato possibile avviare il collegamento al broker: il volo prosegue "
            "senza inviare dati",
            exc_info=True,
        )
    return _mqtt_singleton


def start_mqtt_client() -> None:
    # Il collegamento si apre prima del volo, e non al primo allarme, affinché
    # gli eventi dell'orologio arrivino anche quando il drone non ha nulla da
    # segnalare.
    global _biometric_logger
    if _biometric_logger is None:
        _biometric_logger = BiometricDataLogger()
    _mqtt_client()


def take_biometric_logger() -> Optional[BiometricDataLogger]:
    # Consegna i dati raccolti e ne stacca la registrazione: una chiamata
    # successiva, o un messaggio arrivato in ritardo, non li tocca più.
    global _biometric_logger
    biometric_logger, _biometric_logger = _biometric_logger, None
    return biometric_logger


def stop_mqtt_client() -> None:
    global _mqtt_singleton, _watch_mission_active
    client = _mqtt_singleton
    _mqtt_singleton = _MQTT_NON_CREATO
    mission_open = _watch_mission_active
    _watch_mission_active = False
    if client is None or client is _MQTT_NON_CREATO:
        return
    try:
        # Senza il drone nessuno chiuderebbe più la missione: l'orologio la
        # considererebbe in corso anche dopo l'atterraggio di chiusura.
        if mission_open:
            _publish_watch_mission(client, False)
        info = client.publish(MQTT_TOPIC_STATUS, "offline", qos=1, retain=True)
        try:
            info.wait_for_publish(MQTT_OFFLINE_WAIT_SEC)
        except (RuntimeError, ValueError):
            pass
        client.disconnect()
        client.loop_stop()
    except Exception:
        LOGGER.warning("Il collegamento al broker non è stato chiuso correttamente", exc_info=True)


def _readable_class(raw, labels) -> str:
    if raw is None:
        return ""
    return labels.get(raw) or str(raw).replace("_", " ")


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
        self._model_labels = {m.name: m.label for m in getattr(config, "yolo_models", ())}
        self._class_labels = {
            m.name: dict(getattr(m, "classes", None) or {})
            for m in getattr(config, "yolo_models", ())
        }

        self.pose_estimator = pose_estimator

        self.frame_timeout_sec = config.frame_timeout_sec

        self.frame_from_controller_is_rgb = config.frame_from_controller_is_rgb

        self.status_refresh_sec = config.status_refresh_sec

        self.last_frame_received_at: Optional[float] = None

        self.last_status_refresh_at = 0.0

        self.cached_status = {
            "connected": False,
            "joystick": False,
            "flying": False,
            "battery": None,
        }

        self.project_title = config.project_title

        self.scenario_key_label = config.joystick.label_scenario

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

    def _throttled_warning(self, key: str, message: str, level: int = logging.WARNING) -> None:
        now = time.monotonic()
        last = self._warning_last_logged_at.get(key, 0.0)
        if now - last >= self._warning_repeat_after_sec:
            self._warning_last_logged_at[key] = now
            LOGGER.log(level, message, exc_info=sys.exc_info()[0] is not None)

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
        except Exception:
            self._throttled_warning(
                "status_refresh",
                "Non è stato possibile aggiornare lo stato del drone: resta valida "
                f"l'ultima carica nota ({previous_battery}%)",
                level=logging.INFO,
            )
            status = {}
            new_battery = previous_battery
        else:
            new_battery = status.get("battery")
            if new_battery is None:
                if previous_battery is not None:
                    self._throttled_warning(
                        "battery_read",
                        "Non è stato possibile leggere la carica della batteria: la guardia "
                        f"di sicurezza usa l'ultimo valore noto ({previous_battery}%)",
                        level=logging.INFO,
                    )
                    new_battery = previous_battery
                else:
                    self._throttled_warning(
                        "battery_read_blind",
                        "La carica della batteria non è ancora stata letta: la guardia di "
                        "sicurezza resta inattiva finché non arriva un valore",
                        level=logging.INFO,
                    )

        self.cached_status = {
            "connected": status.get("connected", False),
            "joystick": is_joystick_connected(),
            "flying": status.get("flying", False),
            "battery": new_battery,
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
        snapshot = self.get_cached_detections_snapshot()
        names: set[str] = set()
        for entry in snapshot or []:
            if entry.get("detections"):
                name = entry.get("name")
                if name is not None:
                    names.add(name)
        return names

    @staticmethod
    def _publish(client, topic: str, payload: dict, qos: int, errore: str) -> Optional[int]:
        try:
            info = client.publish(topic, json.dumps(payload), qos=qos)
        except Exception:
            LOGGER.warning(errore, exc_info=True)
            return None
        return int(getattr(info, "rc", 0))

    def publish_alarm(
        self,
        *,
        kind: str,
        message: str,
        level: str = "warning",
        tipo: Optional[str] = None,
        dettaglio: Optional[str] = None,
    ) -> bool:
        client = _mqtt_client()
        if client is None:
            return False

        payload = {"source": "drone", "type": kind, "level": level, "msg": message}
        if tipo is not None:
            payload["tipo"] = tipo
        if dettaglio is not None:
            payload["dettaglio"] = dettaglio
        rc = self._publish(
            client,
            MQTT_TOPIC_ALARMS,
            payload,
            1,
            "Non è stato possibile inviare l'allarme al broker",
        )
        if rc is None:
            return False
        if rc == 0:
            return True

        queued = rc == _MQTT_ERR_NO_CONN
        self._throttled_warning(
            "mqtt_alarm",
            "Il broker non è raggiungibile: l'allarme resta in coda e verrà inviato "
            "non appena il collegamento sarà ripristinato"
            if queued
            else f"L'allarme non è stato inviato al broker (codice {rc})",
        )
        return queued

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
                LOGGER.exception("Il filtro di Kalman ha restituito un errore: viene usata la posizione non filtrata")

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
                    f"Il modello «{self._model_labels.get(item['name'], item['name'])}» "
                    "non è riuscito ad analizzare l'immagine corrente",
                )
                continue
            etichette = self._class_labels.get(item["name"], {})
            for det in detections:
                det["display_label"] = _readable_class(det.get("label"), etichette)
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
                    "Il riconoscimento degli oggetti non è riuscito sull'immagine corrente",
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
                    "Il riconoscimento degli oggetti non si è fermato entro 2 secondi: "
                    "non ne verrà avviato un secondo"
                )
                return
        self._detection_thread = None

    def _video_stream_alive(self) -> bool:
        if self.last_frame_received_at is None:
            self.last_frame_received_at = time.monotonic()
            return True
        elapsed = time.monotonic() - self.last_frame_received_at
        if elapsed >= self.frame_timeout_sec:
            secondi = f"{elapsed:.1f}".replace(".", ",")
            print_event(f"Nessuna immagine video da {secondi} s", prefix="ERRORE")
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
                "Non è stato possibile correggere la distorsione dell'obiettivo sull'immagine corrente",
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
                "Non è stato possibile disegnare i riquadri del riconoscimento sull'immagine corrente",
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
                "Non è stato possibile stimare la posizione dai marker AprilTag sull'immagine corrente",
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
            overlay.draw_watch_overlay(display_frame, get_watch_status())
            overlay.draw_project_title(display_frame, self.project_title)

            self._maybe_draw_safety_net_banner(display_frame)

            if not self.cached_status.get("flying", False):
                overlay.draw_scenario_hint(display_frame, self.scenario_key_label)

            if dashboard is not None:
                display_frame = dashboard.attach_panels(display_frame)

            cv2.imshow(VIDEO_WINDOW_TITLE, self._apply_fade_in(display_frame))
        except Exception:
            self._throttled_warning(
                "display",
                "Non è stato possibile mostrare l'immagine nella finestra video: si passa alla successiva",
            )

    @staticmethod
    def _window_still_open() -> bool:
        try:
            if cv2.getWindowProperty(VIDEO_WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                print_event("Finestra video chiusa dal pilota")
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
            dashboard.set_visible_tags(self.get_visible_tag_ids())

        self._show_frame(display_frame, dashboard, detection_is_active, autonomy_enabled)

        cv2.waitKey(1)

        return self._window_still_open()
