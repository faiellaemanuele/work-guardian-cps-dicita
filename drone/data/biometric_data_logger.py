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

    EXCEL_FILENAME = "dati_biometrici.xlsx"

    TEXT_FILENAME = "biometria_log_orologio.txt"

    @staticmethod
    def _app_config(app_config: Any):
        if app_config is not None:
            return app_config
        from drone.config import APP_CONFIG
        return APP_CONFIG

    def _text_filename(self, worker: str, *, tag_files: bool) -> str:
        if not tag_files:
            return self.TEXT_FILENAME
        from drone.data.biometric_report_stats import safe_worker_name
        return f"biometria_log_orologio_{safe_worker_name(worker)}.txt"

    def save_all_text_files(
        self, output_dir: str | Path, *, app_config: Any = None
    ) -> list[Path]:
        if not self.has_data():
            LOGGER.info("Nessun dato dagli orologi da esportare nei file di testo.")
            return []

        from drone.data import biometric_text_report

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        thresholds = self._app_config(app_config).smartwatch_thresholds

        workers = [worker for worker in self.workers() if self.samples(worker)]
        # Con un solo orologio il nome del file resta quello fisso; con più
        # orologi ognuno porta l'identificativo dell'operaio.
        tag_files = len(workers) > 1

        saved_paths: list[Path] = []
        for worker in workers:
            try:
                saved_paths.append(
                    biometric_text_report.save_worker_data_to_file(
                        self,
                        worker,
                        output_dir / self._text_filename(worker, tag_files=tag_files),
                        thresholds,
                    )
                )
            except Exception:
                LOGGER.exception(
                    "Non è stato possibile salvare il file di testo dell'orologio %s",
                    worker,
                )
        return saved_paths

    def _save_excel(
        self, session_dir: Path, *, app_config: Any = None
    ) -> Optional[Path]:
        try:
            from drone.data import biometric_excel_report
        except ImportError:
            LOGGER.info(
                "openpyxl non disponibile: i dati degli orologi vengono salvati nei "
                "file di testo. Per avere il file Excel: pip install openpyxl."
            )
            return None

        try:
            app_config = self._app_config(app_config)
            parameters = biometric_excel_report.collect_session_parameters(
                self, app_config
            )
            return biometric_excel_report.save_session_workbook(
                self,
                session_dir / self.EXCEL_FILENAME,
                app_config.smartwatch_thresholds,
                parameters,
            )
        except Exception:
            LOGGER.exception(
                "Non è stato possibile scrivere il file Excel della sessione "
                "biometrica: vengono salvati i file di testo"
            )
            return None

    def export_session(
        self, output_root: str | Path, *, app_config: Any = None
    ) -> Optional[Path]:
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

            excel_path = self._save_excel(session_dir, app_config=app_config)
            if excel_path is None:
                self.save_all_text_files(session_dir, app_config=app_config)

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
