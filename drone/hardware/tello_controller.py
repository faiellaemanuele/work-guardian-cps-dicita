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
                "per collegarsi al drone serve la libreria djitellopy (pip install djitellopy)"
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
            LOGGER.info("Il drone è già collegato")
            return

        try:
            self.tello.connect()
        except Exception:
            LOGGER.exception("Il collegamento al drone non è riuscito")
            raise

        self.is_connected = True

        try:
            self.tello.get_battery()
        except Exception:
            LOGGER.info(
                "Non è stato possibile leggere la carica della batteria al momento del collegamento",
                exc_info=True,
            )

        LOGGER.info("Il drone è collegato")

    def _telemetry_says_airborne(self) -> bool:
        height = self.get_height_cm()
        if height is None or height <= self._AIRBORNE_HEIGHT_CM:
            return False

        time.sleep(self._AIRBORNE_CONFIRM_DELAY_SEC)
        height_confirm = self.get_height_cm()
        if height_confirm is not None and height_confirm > self._AIRBORNE_HEIGHT_CM:
            LOGGER.info(
                "Secondo la telemetria il drone è in volo (altezza di %s cm, confermata a %s cm)",
                height,
                height_confirm,
            )
            return True

        LOGGER.info(
            "La seconda lettura non conferma l'altezza di volo (%s cm, poi %s cm)",
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
            LOGGER.info(
                "Decollo rifiutato: la carica della batteria non è leggibile dopo %d tentativi",
                self._PRE_TAKEOFF_BATTERY_READ_ATTEMPTS,
            )
            return False

        if battery <= self.min_takeoff_battery_pct:
            LOGGER.info(
                "Decollo rifiutato: la batteria è al %s%% e per decollare deve superare il %s%%",
                battery,
                self.min_takeoff_battery_pct,
            )
            return False

        return True

    def takeoff(self) -> bool:
        if not self.is_connected:
            LOGGER.warning("Il decollo non è stato eseguito perché il drone non è collegato")
            return False

        if self.is_flying:
            LOGGER.info("Il comando di decollo è stato ignorato perché il drone è già in volo")
            return False

        if self._telemetry_says_airborne():
            LOGGER.info(
                "Il comando di decollo è stato ignorato: il drone risultava a terra ma era "
                "già in volo, e lo stato è stato corretto"
            )
            self.is_flying = True
            return True

        if not self._battery_allows_takeoff():
            return False

        try:
            self.tello.takeoff()
        except Exception:
            LOGGER.exception("Il comando di decollo non è andato a buon fine")
            raise

        self.is_flying = True
        LOGGER.info("Decollo eseguito")
        return True

    def land(self) -> bool:
        if not self.is_connected:
            LOGGER.warning("L'atterraggio non è stato eseguito perché il drone non è collegato")
            return False

        if not self.is_flying:
            if not self._telemetry_says_airborne():
                LOGGER.info("Il comando di atterraggio è stato ignorato perché il drone è già a terra")
                return False
            LOGGER.info(
                "Il drone risultava a terra, ma secondo la telemetria è in volo: "
                "lo stato è stato corretto e l'atterraggio è in corso"
            )
            self.is_flying = True

        try:
            self.tello.land()
        except Exception:
            LOGGER.exception("Il comando di atterraggio non è andato a buon fine")
            raise

        self.is_flying = False
        LOGGER.info("Atterraggio eseguito")
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
            LOGGER.exception("Non è stato possibile inviare i comandi di movimento al drone")
            raise

        return True

    def get_status(self) -> dict:
        battery = None
        if self.is_connected:
            try:
                battery = self.tello.get_battery()
            except Exception:
                LOGGER.info("Non è stato possibile leggere la carica della batteria", exc_info=True)

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
            LOGGER.exception("Non è stato possibile leggere l'altezza del drone")
            return None

        try:
            return int(height)
        except (TypeError, ValueError):
            return None

    def notify_landed_externally(self) -> None:
        if self.is_flying:
            self.is_flying = False
            LOGGER.info("Il drone risultava in volo, ma è a terra: lo stato è stato corretto")

    def _streamoff_after_failed_start(self) -> None:
        try:
            self.tello.streamoff()
        except Exception:
            LOGGER.exception(
                "Non è stato possibile chiudere il video della camera dopo l'avvio non riuscito"
            )

    def start_video_stream(self) -> None:
        if not self.is_connected:
            raise RuntimeError("il drone deve essere collegato prima di avviare il video")

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
            LOGGER.exception("Non è stato possibile avviare il video della camera")
            if stream_started:
                self._streamoff_after_failed_start()
            raise

        if frame_reader is None:
            if stream_started:
                self._streamoff_after_failed_start()
            raise RuntimeError("non è stato possibile avviare la ricezione delle immagini")

        self.frame_reader = frame_reader
        LOGGER.info("Il video della camera è stato avviato")

    def get_frame(self) -> Optional["np.ndarray"]:
        if self.frame_reader is None:
            return None

        try:
            frame = self.frame_reader.frame
        except Exception:
            LOGGER.exception("L'immagine della camera non è stata ricevuta")
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
                LOGGER.exception("Non è stato possibile interrompere la ricezione delle immagini della camera")

        if self.is_connected:
            try:
                self.tello.streamoff()
            except Exception:
                if had_reader:
                    LOGGER.exception("Non è stato possibile fermare il video della camera")

        if had_reader:
            LOGGER.info("Il video della camera è stato fermato")

    def end(self) -> None:
        self.stop_video_stream()

        if self.is_connected:
            try:
                self.tello.end()
            except Exception:
                LOGGER.exception("Il collegamento al drone non è stato chiuso correttamente")

        self.is_connected = False
        self.is_flying = False
        LOGGER.info("Il collegamento al drone è stato chiuso")
