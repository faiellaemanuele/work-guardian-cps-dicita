from __future__ import annotations

from typing import Any, Optional

from drone.data.flight_report_stats import duration_key, elapsed_seconds

# L'orologio pubblica un campione ogni 0,5 s: un silenzio più lungo è un buco
# nella telemetria (orologio spento o fuori copertura, broker irraggiungibile) e
# non va letto come se i valori in mezzo fossero noti.
MAX_GAP_SEC = 3.0
NOMINAL_STEP_SEC = 0.5

# Stati dell'automa del firmware (getStateName() in smartwatch.ino), nell'ordine
# in cui compaiono nei report.
STATE_LABELS: dict[str, str] = {
    "MISSIONE_NON_AVVIATA": "Missione non avviata",
    "RICERCA_SEGNALE": "Ricerca segnale",
    "NORMALE": "Normale",
    "VERIFICA": "Verifica",
    "ALLARME": "Allarme",
    "SILENZIATO": "Silenziato",
    "GUASTO": "Guasto del sensore",
}


def session_clock(*groups) -> tuple[str, float]:
    # Campioni ed eventi della sessione vengono dallo stesso orologio: il tempo
    # relativo si misura dal primo di tutti, così la colonna «tempo dall'avvio»
    # dei vari fogli e dei vari file è confrontabile.
    tutti = [voce for gruppo in groups for voce in gruppo]
    chiave = duration_key(tutti)
    return chiave, min((float(voce[chiave]) for voce in tutti), default=0.0)


def relative_time(entry, clock: tuple[str, float]) -> float:
    chiave, base = clock
    return float(entry[chiave]) - base


def state_label(code: Any) -> str:
    if code is None:
        return ""
    testo = str(code).strip()
    return STATE_LABELS.get(testo, testo)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    minuti, secondi = divmod(seconds, 60)
    if not minuti:
        return f"{secondi} s"
    return f"{minuti} min {secondi} s" if secondi else f"{minuti} min"


def sample_step_sec(samples) -> float:
    # La cadenza vera della sessione: la mediana dei passi, saltando i buchi,
    # perché un orologio lento non deve far credere che manchino campioni.
    tempi = elapsed_seconds(samples)
    passi = sorted(
        dopo - prima
        for prima, dopo in zip(tempi, tempi[1:])
        if 0.0 < dopo - prima <= MAX_GAP_SEC
    )
    if not passi:
        return NOMINAL_STEP_SEC
    mezzo = len(passi) // 2
    if len(passi) % 2:
        return passi[mezzo]
    return (passi[mezzo - 1] + passi[mezzo]) / 2.0


def telemetry_gaps(samples) -> list[dict[str, float]]:
    tempi = elapsed_seconds(samples)
    return [
        {"start": prima, "end": dopo, "duration": dopo - prima}
        for prima, dopo in zip(tempi, tempi[1:])
        if dopo - prima > MAX_GAP_SEC
    ]


def state_segments(samples) -> list[dict[str, Any]]:
    # Ogni campione vale fino al successivo; l'ultimo prima di un buco o della
    # fine della sessione vale un passo di pubblicazione.
    tempi = elapsed_seconds(samples)
    passo = sample_step_sec(samples)
    segmenti: list[dict[str, Any]] = []
    for i, campione in enumerate(samples):
        stato = campione.get("stato")
        if stato is None:
            continue
        inizio = tempi[i]
        prossimo = tempi[i + 1] if i + 1 < len(tempi) else None
        if prossimo is None or prossimo - inizio > MAX_GAP_SEC:
            fine = inizio + passo
        else:
            fine = prossimo
        if (
            segmenti
            and segmenti[-1]["stato"] == stato
            and abs(segmenti[-1]["end"] - inizio) < 1e-9
        ):
            segmenti[-1]["end"] = fine
        else:
            segmenti.append({"stato": stato, "start": inizio, "end": fine})
    return segmenti


def state_durations(samples) -> list[tuple[str, float]]:
    durate: dict[str, float] = {}
    for segmento in state_segments(samples):
        stato = segmento["stato"]
        durate[stato] = durate.get(stato, 0.0) + (segmento["end"] - segmento["start"])
    noti = [codice for codice in STATE_LABELS if codice in durate]
    altri = sorted(codice for codice in durate if codice not in STATE_LABELS)
    return [(codice, durate[codice]) for codice in noti + altri]


def monitored_duration_sec(samples) -> float:
    # Quanto della sessione è davvero coperto dalla telemetria: la durata
    # totale meno i buchi.
    return sum(
        segmento["end"] - segmento["start"] for segmento in state_segments(samples)
    )


def valid_reading_percent(samples) -> Optional[float]:
    if not samples:
        return None
    valide = sum(1 for campione in samples if campione.get("lettura_valida"))
    return 100.0 * valide / len(samples)


def mean_abs_delta(samples, raw_key: str, filtered_key: str) -> Optional[float]:
    scarti = [
        abs(float(campione[raw_key]) - float(campione[filtered_key]))
        for campione in samples
        if campione.get(raw_key) is not None and campione.get(filtered_key) is not None
    ]
    if not scarti:
        return None
    return sum(scarti) / len(scarti)


def hr_out_of_band(value: Any, thresholds) -> bool:
    # Fuori dalle soglie di ingresso dell'allarme, le stesse che il firmware usa
    # per decidere: qui servono solo a contare e a colorare le celle.
    if value is None:
        return False
    valore = float(value)
    return valore > thresholds.bpm_max_in or valore < thresholds.bpm_min_in


def spo2_out_of_band(value: Any, thresholds) -> bool:
    if value is None:
        return False
    return float(value) < thresholds.spo2_min_in


# Per i campioni si usano i valori arrotondati all'intero (bpm e spo2), gli
# stessi che il firmware confronta con le soglie, in quanto il filtrato con un
# decimale, vicino a una soglia, può dare un esito diverso da quello dell'orologio.
def sample_hr_out_of_band(sample, thresholds) -> bool:
    return hr_out_of_band(sample.get("bpm"), thresholds)


def sample_spo2_out_of_band(sample, thresholds) -> bool:
    return spo2_out_of_band(sample.get("spo2"), thresholds)


def alarm_causes(event, thresholds) -> tuple[bool, bool]:
    # L'evento dice solo che l'allarme è scattato, ma porta i valori del
    # momento della conferma: il firmware lo conferma solo con almeno uno dei
    # due fuori dalle soglie di ingresso, quindi la causa si ricava da lì.
    # Senza valori leggibili l'allarme resta attribuito a entrambi.
    battito = hr_out_of_band(event.get("bpm"), thresholds)
    saturazione = spo2_out_of_band(event.get("spo2"), thresholds)
    if not battito and not saturazione:
        return True, True
    return battito, saturazione


def alarm_cause_label(event, thresholds) -> str:
    battito = hr_out_of_band(event.get("bpm"), thresholds)
    saturazione = spo2_out_of_band(event.get("spo2"), thresholds)
    if battito and saturazione:
        return "Battito e saturazione"
    if battito:
        return "Battito"
    if saturazione:
        return "Saturazione"
    return "Non ricavabile dai valori dell'evento"
