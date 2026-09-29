from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from biometric_log_samples import logger_con_sessione, telemetria
from drone.data.biometric_data_logger import BiometricDataLogger


def _matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def test_la_telemetria_tiene_grezzo_e_filtrato():
    log = BiometricDataLogger()
    assert log.log_message("operaio_1", telemetria(80.2, 75.4, 96.0, 97.1), timestamp=1.0)

    campione = log.samples("operaio_1")[0]
    assert campione["hr_grezzo"] == 80.2
    assert campione["hr_filtrato"] == 75.4
    assert campione["spo2_grezzo"] == 96.0
    assert campione["spo2_filtrato"] == 97.1
    assert campione["stato"] == "NORMALE"
    assert campione["lettura_valida"] is True


def test_un_valore_null_resta_un_buco_e_non_diventa_zero():
    log = BiometricDataLogger()
    log.log_message("operaio_1", telemetria(None, None, None, None, "RICERCA_SEGNALE"),
                    timestamp=1.0)

    campione = log.samples("operaio_1")[0]
    for chiave in ("hr_grezzo", "hr_filtrato", "spo2_grezzo", "spo2_filtrato"):
        assert campione[chiave] is None
    assert campione["lettura_valida"] is False


def test_il_firmware_precedente_senza_grezzi_da_comunque_il_filtrato():
    log = BiometricDataLogger()
    log.log_message(
        "operaio_1",
        {"bpm": 76, "spo2": 98, "stato": "NORMALE", "lettura_valida": True},
        timestamp=1.0,
    )

    campione = log.samples("operaio_1")[0]
    assert campione["hr_filtrato"] == 76.0
    assert campione["spo2_filtrato"] == 98.0
    assert campione["hr_grezzo"] is None


def test_l_allarme_biometrico_e_un_evento_e_non_un_campione():
    log = BiometricDataLogger()
    log.log_message("operaio_1", {"bpm": 131, "spo2": 95, "evento": "BIOMETRIA_ANOMALA"},
                    timestamp=1.0)

    assert log.samples("operaio_1") == []
    eventi = log.events("operaio_1")
    assert len(eventi) == 1
    assert eventi[0]["bpm"] == 131.0


def test_un_messaggio_senza_stato_ne_evento_viene_ignorato():
    log = BiometricDataLogger()
    assert log.log_message("operaio_1", {"ciao": 1}) is False
    assert log.workers() == []


def test_ogni_orologio_ha_la_sua_serie():
    log = logger_con_sessione(("operaio_1", "operaio_2"))
    assert log.workers() == ["operaio_1", "operaio_2"]
    assert len(log.samples("operaio_1")) == 40
    assert len(log.samples("operaio_2")) == 40


def test_senza_almeno_due_campioni_non_ci_sono_dati_da_salvare():
    log = BiometricDataLogger()
    assert not log.has_data()
    log.log_message("operaio_1", telemetria(80.0, 75.0, 96.0, 97.0), timestamp=1.0)
    assert not log.has_data()
    log.log_message("operaio_1", telemetria(81.0, 75.5, 96.0, 97.0), timestamp=1.5)
    assert log.has_data()


def test_senza_dati_non_si_crea_la_cartella():
    with tempfile.TemporaryDirectory() as d:
        assert BiometricDataLogger().export_session(d) is None
        assert list(Path(d).iterdir()) == []


def test_la_sessione_finisce_in_una_cartella_con_data_e_ora():
    if not _matplotlib_available():
        return
    log = logger_con_sessione()
    with tempfile.TemporaryDirectory() as d:
        cartella = log.export_session(d)
        assert cartella is not None
        assert cartella.parent == Path(d)
        assert cartella.name.startswith("sessione_biometrica_")
        nomi = {p.name for p in cartella.glob("*.png")}
    assert nomi == {
        "biometria_battito_grezzo_e_filtrato.png",
        "biometria_spo2_grezza_e_filtrata.png",
        "biometria_andamento_battito.png",
        "biometria_andamento_spo2.png",
    }


def test_due_sessioni_nello_stesso_secondo_non_si_sovrascrivono():
    if not _matplotlib_available():
        return
    log = logger_con_sessione()
    with tempfile.TemporaryDirectory() as d:
        prima = log.export_session(d)
        seconda = log.export_session(d)
        assert prima is not None and seconda is not None
        assert prima != seconda


def test_con_piu_orologi_ogni_file_porta_l_operaio():
    if not _matplotlib_available():
        return
    log = logger_con_sessione(("operaio_1", "operaio_2"))
    with tempfile.TemporaryDirectory() as d:
        salvati = log.save_plots(d)
        nomi = {p.name for p in Path(d).glob("*.png")}
    assert len(salvati) == 8
    assert "biometria_operaio_1_battito_grezzo_e_filtrato.png" in nomi
    assert "biometria_operaio_2_andamento_spo2.png" in nomi


def test_il_riassunto_conta_campioni_e_allarmi():
    riassunto = logger_con_sessione().get_summary()
    assert riassunto == "Orologio: 40 campioni, 1 allarme biometrico"


def test_con_piu_orologi_il_riassunto_li_distingue():
    riassunto = logger_con_sessione(("operaio_1", "operaio_2")).get_summary()
    assert "Orologio operaio_1:" in riassunto
    assert "Orologio operaio_2:" in riassunto
