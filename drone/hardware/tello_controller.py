from __future__ import annotations

import logging

import time

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import numpy as np

LOGGER = logging.getLogger(__name__)


class _DjiDecodeNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not isinstance(record.msg, UnicodeDecodeError)


def _silence_djitellopy_logging(level: int = logging.ERROR) -> None:
    dji_logger = logging.getLogger("djitellopy")
    for handler in list(dji_logger.handlers):
        dji_logger.removeHandler(handler)
    dji_logger.setLevel(level)
    dji_logger.propagate = True

    if not any(isinstance(f, _DjiDecodeNoiseFilter) for f in dji_logger.filters):
        dji_logger.addFilter(_DjiDecodeNoiseFilter())


class RealTelloController:
    def __init__(self, min_takeoff_battery_pct: int = 0, host: Optional[str] = None):
        try:
            from djitellopy import Tello
        except ImportError as exc:
            raise ImportError(
                "Per usare il drone reale devi installare djitellopy: pip install djitellopy"
            ) from exc

        _silence_djitellopy_logging()

        self.tello = Tello(host=host) if host else Tello()

        self.frame_reader = None

        self.is_connected = False
        self.is_flying = False

        self.min_takeoff_battery_pct = int(min_takeoff_battery_pct)

    _AIRBORNE_HEIGHT_CM = 30

    _AIRBORNE_CONFIRM_DELAY_SEC = 0.1

    _PRE_TAKEOFF_BATTERY_READ_ATTEMPTS = 3

    @staticmethod
    def _clamp_rc_value(value: int) -> int:
        value = int(value)
        return max(-100, min(100, value))

    def connect(self) -> None:
        if self.is_connected:
            LOGGER.info("DRONE | Il drone è già connesso.")
            return

        try:
            self.tello.connect()
        except Exception:
            LOGGER.exception("DRONE | Errore durante la connessione al Tello.")
            raise

        self.is_connected = True

        try:
            self.tello.get_battery()
        except Exception:
            LOGGER.exception("DRONE | Errore durante la lettura iniziale della batteria.")

        LOGGER.info("DRONE | Connesso al Tello.")

    def _telemetry_says_airborne(self) -> bool:
        height = self.get_height_cm()
        if height is None or height <= self._AIRBORNE_HEIGHT_CM:
            return False

        time.sleep(self._AIRBORNE_CONFIRM_DELAY_SEC)
        height_confirm = self.get_height_cm()
        if height_confirm is not None and height_confirm > self._AIRBORNE_HEIGHT_CM:
            LOGGER.warning(
                "DRONE | La telemetria indica il drone in volo "
                "(altezza=%scm, confermata %scm).",
                height,
                height_confirm,
            )
            return True

        LOGGER.warning(
            "DRONE | Altezza in volo non confermata (%scm poi %scm).",
            height,
            height_confirm,
        )
        return False

    def _battery_allows_takeoff(self) -> bool:
        if self.min_takeoff_battery_pct <= 0:
            return True

        battery = None
        for _ in range(self._PRE_TAKEOFF_BATTERY_READ_ATTEMPTS):
            try:
                battery = self.tello.get_battery()
            except Exception:
                battery = None
            if battery is not None:
                break

        if battery is None:
            LOGGER.warning(
                "DRONE | Decollo rifiutato: batteria non leggibile dopo %d tentativi "
                "(guardia di sicurezza).",
                self._PRE_TAKEOFF_BATTERY_READ_ATTEMPTS,
            )
            return False

        if battery <= self.min_takeoff_battery_pct:
            LOGGER.warning(
                "DRONE | Decollo rifiutato: batteria %s%% <= soglia minima %s%%.",
                battery,
                self.min_takeoff_battery_pct,
            )
            return False

        return True

    def takeoff(self) -> bool:
        if not self.is_connected:
            LOGGER.warning("DRONE | Impossibile decollare: drone non connesso.")
            return False

        if self.is_flying:
            LOGGER.info("DRONE | Il drone è già in volo.")
            return False

        if self._telemetry_says_airborne():
            LOGGER.warning("DRONE | Decollo ignorato: stato riallineato a 'in volo'.")
            self.is_flying = True
            return True

        if not self._battery_allows_takeoff():
            return False

        try:
            self.tello.takeoff()
        except Exception:
            LOGGER.exception("DRONE | Errore durante il decollo.")
            raise

        self.is_flying = True
        LOGGER.info("DRONE | Decollo eseguito.")
        return True

    def land(self) -> bool:
        if not self.is_connected:
            LOGGER.warning("DRONE | Impossibile atterrare: drone non connesso.")
            return False

        if not self.is_flying:
            if not self._telemetry_says_airborne():
                LOGGER.info("DRONE | Il drone è già a terra.")
                return False
            LOGGER.warning(
                "DRONE | Atterraggio richiesto con stato 'a terra' ma telemetria in volo: "
                "stato riallineato e atterraggio eseguito."
            )
            self.is_flying = True

        try:
            self.tello.land()
        except Exception:
            LOGGER.exception("DRONE | Errore durante l'atterraggio.")
            raise

        self.is_flying = False
        LOGGER.info("DRONE | Atterraggio eseguito.")
        return True

    def send_rc_control(self, lr: int, fb: int, ud: int, yaw: int) -> bool:
        if not self.is_connected or not self.is_flying:
            return False

        try:
            self.tello.send_rc_control(
                self._clamp_rc_value(lr),
                self._clamp_rc_value(fb),
                self._clamp_rc_value(ud),
                self._clamp_rc_value(yaw),
            )
        except Exception:
            LOGGER.exception("DRONE | Errore durante l'invio dei comandi RC.")
            raise

        return True

    def get_status(self) -> dict:
        battery = None
        if self.is_connected:
            try:
                battery = self.tello.get_battery()
            except Exception:
                LOGGER.exception("DRONE | Errore durante la lettura della batteria.")

        return {
            "mode": "REAL",
            "connected": self.is_connected,
            "flying": self.is_flying,
            "battery": battery,
        }

    def get_height_cm(self) -> Optional[int]:
        if not self.is_connected:
            return None

        try:
            height = self.tello.get_height()
        except Exception:
            LOGGER.exception("DRONE | Errore durante la lettura dell'altezza.")
            return None

        try:
            return int(height)
        except (TypeError, ValueError):
            return None

    def notify_landed_externally(self) -> None:
        if self.is_flying:
            self.is_flying = False
            LOGGER.warning("DRONE | Stato riallineato: drone rilevato a terra mentre risultava in volo.")

    def _streamoff_after_failed_start(self) -> None:
        try:
            self.tello.streamoff()
        except Exception:
            LOGGER.exception(
                "DRONE | Errore nel chiudere il flusso video dopo l'avvio non riuscito."
            )

    def start_video_stream(self) -> None:
        if not self.is_connected:
            raise RuntimeError("Connetti prima il drone.")

        self.stop_video_stream()

        try:
            self.tello.streamoff()
        except Exception:
            pass

        frame_reader = None
        stream_started = False

        try:
            self.tello.streamon()
            stream_started = True
            frame_reader = self.tello.get_frame_read()
        except Exception:
            LOGGER.exception("DRONE | Errore durante l'avvio del flusso video.")
            if stream_started:
                self._streamoff_after_failed_start()
            raise

        if frame_reader is None:
            if stream_started:
                self._streamoff_after_failed_start()
            raise RuntimeError("Impossibile avviare il lettore del flusso video.")

        self.frame_reader = frame_reader
        LOGGER.info("DRONE | Flusso video avviato.")

    def get_frame(self) -> Optional["np.ndarray"]:
        if self.frame_reader is None:
            return None

        try:
            frame = self.frame_reader.frame
        except Exception:
            LOGGER.exception("DRONE | Errore durante la lettura del frame video.")
            return None

        if frame is None:
            return None

        if getattr(frame, "size", 0) == 0 or getattr(frame, "ndim", None) != 3:
            return None

        return frame.copy()

    def stop_video_stream(self) -> None:
        frame_reader = self.frame_reader
        had_reader = frame_reader is not None

        self.frame_reader = None

        if frame_reader is not None and hasattr(frame_reader, "stop"):
            try:
                frame_reader.stop()
            except Exception:
                LOGGER.exception("DRONE | Errore durante l'arresto del lettore di frame.")

        if self.is_connected:
            try:
                self.tello.streamoff()
            except Exception:
                if had_reader:
                    LOGGER.exception("DRONE | Errore durante l'arresto del flusso video.")

        if had_reader:
            LOGGER.info("DRONE | Flusso video fermato.")

    def end(self) -> None:
        self.stop_video_stream()

        if self.is_connected:
            try:
                self.tello.end()
            except Exception:
                LOGGER.exception("DRONE | Errore durante la chiusura della connessione Tello.")

        self.is_connected = False
        self.is_flying = False
        LOGGER.info("DRONE | Connessione chiusa.")
