from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.data.biometric_data_logger import BiometricDataLogger

from biometric_log_samples import logger_con_sessione, telemetria


def _testo(log=None) -> str:
    log = log if log is not None else logger_con_sessione()
    with tempfile.TemporaryDirectory() as d:
        path = log.save_text_file(d, app_config=APP_CONFIG)
        assert path is not None
        return path.read_text(encoding="utf-8")


def _righe_dati(testo: str) -> list[list[str]]:
    return [
        riga.split(",")
        for riga in testo.splitlines()
        if riga and not riga.startswith("#") and not riga.startswith("timestamp_s")
    ]


def test_the_csv_has_a_row_per_sample_with_every_column():
    log = logger_con_sessione()
    righe = _righe_dati(_testo(log))
    assert len(righe) == len(log.samples())
    assert all(len(riga) == 12 for riga in righe)


def test_the_header_lists_the_columns_and_the_firmware_thresholds():
    testo = _testo()
    soglie = APP_CONFIG.smartwatch_thresholds
    assert "hr_filtrato_bpm" in testo
    assert "spo2_fuori_soglia" in testo
    assert f"battito fuori {soglie.bpm_min_in}-{soglie.bpm_max_in} bpm" in testo
    assert f"SpO2 sotto {soglie.spo2_min_in}%" in testo


def test_the_samples_out_of_the_thresholds_are_flagged():
    testo = _testo()
    fuori = [riga for riga in _righe_dati(testo) if riga[10] == "true"]
    assert len(fuori) == 7
    assert all(float(riga[5]) > APP_CONFIG.smartwatch_thresholds.bpm_max_in for riga in fuori)


def test_a_sample_without_a_reading_leaves_the_values_empty():
    testo = _testo()
    senza = [riga for riga in _righe_dati(testo) if riga[3] == "false"]
    assert senza
    for riga in senza:
        # il sensore non dava un battito: le tre colonne del battito e quelle
        # della SpO2 filtrata restano vuote, non diventano zero
        assert riga[4:7] == ["", "", ""]
        assert riga[8:10] == ["", ""]


def test_the_footer_reports_the_session_the_states_and_the_gaps():
    testo = _testo()
    assert "Panoramica della sessione" in testo
    assert "Tempo per stato dell'orologio" in testo
    assert "Ricerca segnale:" in testo
    assert "# Allarmi biometrici\n" in testo
    assert "causa: Battito" in testo
    assert "Buchi nella telemetria" in testo
    assert "senza campioni" in testo


def test_without_alarms_the_alarm_section_is_left_out():
    log = BiometricDataLogger()
    for i in range(6):
        log.log_message(telemetria(74.0, 72.0, 98.0, 97.0), timestamp=1000.0 + 0.5 * i)
    testo = _testo(log)
    assert "Panoramica della sessione" in testo
    assert "Allarmi biometrici confermati dall'orologio: 0" in testo
    assert "# Allarmi biometrici\n" not in testo
    assert "Buchi nella telemetria" not in testo


def test_the_text_file_has_a_fixed_name_and_title():
    with tempfile.TemporaryDirectory() as d:
        path = logger_con_sessione().save_text_file(d, app_config=APP_CONFIG)
        assert path is not None
        assert path.name == BiometricDataLogger.TEXT_FILENAME
        assert "LOG BIOMETRICO DELL'OROLOGIO\n" in path.read_text(encoding="utf-8")


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
