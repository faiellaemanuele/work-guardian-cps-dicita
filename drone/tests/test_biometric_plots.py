from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from biometric_log_samples import logger_con_sessione


def _matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _dati():
    from drone.ui.plots.biometric_plots import _prepare
    with tempfile.TemporaryDirectory() as d:
        return _prepare(logger_con_sessione(), Path(d), _plt(), [])


def test_il_tempo_parte_da_zero_e_le_serie_restano_appaiate():
    if not _matplotlib_available():
        return
    dati = _dati()
    assert dati.t[0] == 0.0
    for serie in (dati.hr_raw, dati.hr_filtered, dati.spo2_raw, dati.spo2_filtered):
        assert len(serie) == len(dati.t)
    assert len(dati.states) == len(dati.t)
    assert "campioni" in dati.meta


def test_un_buco_nella_telemetria_spezza_le_linee():
    if not _matplotlib_available():
        return
    import numpy as np
    dati = _dati()
    # 40 campioni più un punto vuoto nel silenzio di dieci secondi
    assert len(dati.t) == 41
    vuoti = [i for i, stato in enumerate(dati.states) if stato is None]
    assert len(vuoti) == 1
    assert np.isnan(dati.hr_filtered[vuoti[0]])
    assert np.all(np.diff(dati.t) > 0)


def test_gli_stati_diventano_intervalli_senza_attraversare_i_buchi():
    if not _matplotlib_available():
        return
    from drone.ui.plots.biometric_plots import _state_segments
    segmenti = _state_segments(_dati())
    assert [s[0] for s in segmenti] == [
        "RICERCA_SEGNALE", "NORMALE", "NORMALE", "ALLARME", "NORMALE",
    ]
    for _stato, inizio, fine in segmenti:
        assert fine > inizio
    # il primo tratto NORMALE si chiude prima del buco, non a metà silenzio
    assert segmenti[1][2] < segmenti[2][1] - 5.0


def test_l_allarme_biometrico_cade_sul_tempo_della_sessione():
    if not _matplotlib_available():
        return
    dati = _dati()
    # l'evento del campione ha 132 bpm e SpO2 97: è un allarme sul battito
    assert len(dati.hr_alarm_times) == 1
    assert len(dati.spo2_alarm_times) == 0
    assert abs(dati.hr_alarm_times[0] - (25 * 0.5 + 10.0)) < 1e-9


def test_la_causa_dell_allarme_si_ricava_dai_valori_dell_evento():
    if not _matplotlib_available():
        return
    from drone.ui.plots.biometric_plots import _alarm_causes
    assert _alarm_causes({"bpm": 131.0, "spo2": 97.0}) == (True, False)
    assert _alarm_causes({"bpm": 25.0, "spo2": 97.0}) == (True, False)
    assert _alarm_causes({"bpm": 80.0, "spo2": 90.0}) == (False, True)
    assert _alarm_causes({"bpm": 130.0, "spo2": 90.0}) == (True, True)
    # senza valori leggibili l'allarme non si perde: va su entrambi
    assert _alarm_causes({"bpm": None, "spo2": None}) == (True, True)


def test_un_allarme_solo_non_ha_numero_e_due_si_numerano():
    if not _matplotlib_available():
        return
    from drone.ui.plots.biometric_plots import _alarm_labels, _alarm_legend_label
    assert _alarm_labels("BPM", 1) == ["BPM"]
    assert _alarm_labels("SpO2", 2) == ["SpO2 1", "SpO2 2"]
    assert _alarm_legend_label("sul battito", ["BPM"]) == "Allarme sul battito (BPM)"
    assert "BPM 1, BPM 2" in _alarm_legend_label("sul battito", ["BPM 1", "BPM 2"])


def test_senza_valori_grezzi_i_grafici_nascono_lo_stesso():
    if not _matplotlib_available():
        return
    from drone.data.biometric_data_logger import BiometricDataLogger
    from drone.ui.plots.biometric_plots import save_watch_biometric_plots
    log = BiometricDataLogger()
    for i in range(10):
        log.log_message(
            {"bpm": 70 + i, "spo2": 97, "stato": "NORMALE", "lettura_valida": True},
            timestamp=100.0 + i * 0.5,
        )
    with tempfile.TemporaryDirectory() as d:
        salvati = save_watch_biometric_plots(log, Path(d), _plt())
        assert all(p.exists() for p in salvati)
    assert len(salvati) == 4
