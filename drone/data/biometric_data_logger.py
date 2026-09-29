from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Optional

LOGGER = logging.getLogger(__name__)

BIOMETRIC_ALARM_EVENT = "BIOMETRIA_ANOMALA"


def _optional_float(value: Any) -> Optional[float]:
    # Il firmware manda null quando la lettura non c'è; un booleano o un testo
    # non sono una misura e diventano anch'essi un buco nei dati.
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class BiometricDataLogger:
    # Raccoglie la telemetria che gli orologi pubblicano via MQTT (un campione
    # ogni 0,5 s per operaio) e gli eventi di allarme biometrico. I messaggi
    # arrivano dal thread di paho, l'esportazione dal thread principale: per
    # questo ogni accesso passa dal lock.

    SESSION_PREFIX = "sessione_biometrica"

    def __init__(self, max_samples: Optional[int] = None):
        self._max_samples = None if max_samples is None else max(1, int(max_samples))
        self._lock = threading.Lock()
        self._samples: dict[str, deque[dict[str, Any]]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}

    def log_message(
        self,
        worker: str,
        message: Mapping[str, Any],
        timestamp: Optional[float] = None,
    ) -> bool:
        monotonic = None
        if timestamp is None:
            timestamp = time.time()
            monotonic = time.monotonic()
        tempo = {
            "timestamp": float(timestamp),
            **({} if monotonic is None else {"monotonic": float(monotonic)}),
        }

        if message.get("evento") == BIOMETRIC_ALARM_EVENT:
            event = {
                **tempo,
                "bpm": _optional_float(message.get("bpm")),
                "spo2": _optional_float(message.get("spo2")),
            }
            with self._lock:
                self._events.setdefault(worker, []).append(event)
            return True

        if "stato" not in message:
            return False

        valid = bool(message.get("lettura_valida", False))
        # Un firmware precedente manda solo bpm e spo2 arrotondati: diventano il
        # valore filtrato, e i grafici restano senza la serie grezza.
        hr_filtered = _optional_float(message.get("hr_filtrato"))
        spo2_filtered = _optional_float(message.get("spo2_filtrato"))
        if hr_filtered is None and "hr_filtrato" not in message and valid:
            hr_filtered = _optional_float(message.get("bpm"))
        if spo2_filtered is None and "spo2_filtrato" not in message and valid:
            spo2_filtered = _optional_float(message.get("spo2"))

        sample = {
            **tempo,
            "stato": str(message.get("stato")),
            "lettura_valida": valid,
            "hr_grezzo": _optional_float(message.get("hr_grezzo")),
            "hr_filtrato": hr_filtered,
            "spo2_grezzo": _optional_float(message.get("spo2_grezzo")),
            "spo2_filtrato": spo2_filtered,
        }
        with self._lock:
            buffer = self._samples.get(worker)
            if buffer is None:
                buffer = deque(maxlen=self._max_samples)
                self._samples[worker] = buffer
            buffer.append(sample)
        return True

    def workers(self) -> list[str]:
        with self._lock:
            return sorted(set(self._samples) | set(self._events))

    def samples(self, worker: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._samples.get(worker, ()))

    def events(self, worker: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events.get(worker, ()))

    def has_data(self) -> bool:
        with self._lock:
            # Con meno di due campioni non c'è una linea da disegnare: la
            # cartella resterebbe vuota.
            return any(len(buffer) >= 2 for buffer in self._samples.values())

    def save_plots(self, output_dir: str | Path) -> list[Path]:
        from drone.ui.plots import flight_plots
        return flight_plots.save_biometric_plots(self, output_dir)

    def export_session(self, output_root: str | Path) -> Optional[Path]:
        if not self.has_data():
            LOGGER.info(
                "Nessun dato dagli orologi: la cartella della sessione biometrica "
                "non viene creata."
            )
            return None

        try:
            output_root = Path(output_root)
            session_name = time.strftime(f"{self.SESSION_PREFIX}_%d_%m_%Y_%H_%M_%S")
            session_dir = output_root / session_name
            if session_dir.exists():
                suffix = 2
                while (output_root / f"{session_name}_{suffix}").exists():
                    suffix += 1
                session_dir = output_root / f"{session_name}_{suffix}"
            session_dir.mkdir(parents=True, exist_ok=True)

            try:
                self.save_plots(session_dir)
            except Exception:
                LOGGER.exception("Non è stato possibile generare i grafici biometrici")

            return session_dir

        except Exception:
            LOGGER.exception("Non è stato possibile esportare la sessione biometrica")
            return None

    def get_summary(self) -> str:
        righe = []
        workers = self.workers()
        for worker in workers:
            campioni = len(self.samples(worker))
            allarmi = len(self.events(worker))
            testo_allarmi = (
                "nessun allarme biometrico" if allarmi == 0
                else "1 allarme biometrico" if allarmi == 1
                else f"{allarmi} allarmi biometrici"
            )
            # È previsto un solo operaio: il suo identificativo compare solo se
            # gli orologi collegati sono più di uno.
            nome = f"Orologio {worker}" if len(workers) > 1 else "Orologio"
            righe.append(f"{nome}: {campioni} campioni, {testo_allarmi}")
        return "\n".join(righe) if righe else "Nessun dato ricevuto dagli orologi"
