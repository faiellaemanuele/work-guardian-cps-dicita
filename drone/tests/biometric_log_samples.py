from __future__ import annotations

from drone.data.biometric_data_logger import BiometricDataLogger


def telemetria(hr_grezzo, hr_filtrato, spo2_grezzo, spo2_filtrato, stato="NORMALE"):
    valida = hr_filtrato is not None and spo2_filtrato is not None
    return {
        "bpm": None if hr_filtrato is None else round(hr_filtrato),
        "spo2": None if spo2_filtrato is None else round(spo2_filtrato),
        "stato": stato,
        "lettura_valida": valida,
        "hr_grezzo": hr_grezzo,
        "hr_filtrato": hr_filtrato,
        "spo2_grezzo": spo2_grezzo,
        "spo2_filtrato": spo2_filtrato,
    }


def logger_con_sessione(operai=("operaio_1",)) -> BiometricDataLogger:
    log = BiometricDataLogger()
    for operaio in operai:
        ts = 1000.0
        for i in range(40):
            stato = "RICERCA_SEGNALE" if i < 4 else "ALLARME" if 25 <= i < 32 else "NORMALE"
            hr = None if i < 4 else 72.0 + (60.0 if 25 <= i < 32 else 0.0)
            spo2 = None if i < 4 else 97.0
            log.log_message(
                operaio,
                telemetria(
                    None if hr is None else hr + (15.0 if i % 7 == 0 else 1.0),
                    hr, 98.0, spo2, stato,
                ),
                timestamp=ts,
            )
            ts += 0.5
            if i == 20:
                ts += 10.0  # l'orologio perde il broker per dieci secondi
        log.log_message(
            operaio, {"bpm": 132, "spo2": 97, "evento": "BIOMETRIA_ANOMALA"},
            timestamp=1000.0 + 25 * 0.5 + 10.0,
        )
    return log
