from __future__ import annotations

import time
from pathlib import Path

from drone.data.biometric_report_stats import (
    MAX_GAP_SEC,
    alarm_cause_label,
    format_duration,
    mean_abs_delta,
    monitored_duration_sec,
    relative_time,
    sample_hr_out_of_band,
    sample_spo2_out_of_band,
    sample_step_sec,
    session_clock,
    state_durations,
    state_label,
    telemetry_gaps,
    valid_reading_percent,
)
from drone.data.flight_report_stats import percent_within
from drone.data.text_tables import (
    format_bool,
    format_optional_float,
    safe_text_value,
    write_column_line,
    write_header,
    write_section,
    write_stats_footer,
)

_COLUMNS = [
    ("timestamp_s", "timestamp assoluto UNIX del campione [s]"),
    ("tempo_relativo_s", "tempo trascorso dal primo campione del file [s]"),
    ("stato", "stato del firmware dell'orologio in quel momento"),
    ("lettura_valida", "true quando il sensore stava davvero misurando"),
    ("hr_grezzo_bpm", "battito letto dal sensore MAX30100, senza filtro [bpm]"),
    ("hr_filtrato_bpm", "battito dopo il filtro dell'orologio; arrotondato all'intero, e' quello su cui decide l'allarme [bpm]"),
    ("scarto_hr_bpm", "differenza hr_filtrato_bpm - hr_grezzo_bpm [bpm]"),
    ("spo2_grezzo_pct", "saturazione letta dal sensore, senza filtro [%]"),
    ("spo2_filtrato_pct", "saturazione dopo il filtro dell'orologio [%]"),
    ("scarto_spo2_pct", "differenza spo2_filtrato_pct - spo2_grezzo_pct [%]"),
    ("hr_fuori_soglia", "true quando hr_filtrato_bpm, arrotondato all'intero come nell'orologio, e' oltre le soglie di ingresso dell'allarme"),
    ("spo2_fuori_soglia", "true quando spo2_filtrato_pct, arrotondato all'intero come nell'orologio, e' sotto la soglia di ingresso dell'allarme"),
]

_STATS_COLUMNS = ["hr_grezzo", "hr_filtrato", "spo2_grezzo", "spo2_filtrato"]


def _delta(filtrato, grezzo):
    if filtrato is None or grezzo is None:
        return None
    return float(filtrato) - float(grezzo)


def _overview_lines(samples, events, thresholds) -> list[str]:
    righe = [
        f"Campioni ricevuti: {len(samples)}",
        f"Cadenza misurata: {sample_step_sec(samples):.2f} s",
        f"Telemetria coperta: {monitored_duration_sec(samples):.1f} s",
        f"Allarmi biometrici confermati dall'orologio: {len(events)}",
    ]
    valide = valid_reading_percent(samples)
    if valide is not None:
        righe.append(f"Letture valide del sensore: {valide:.1f}%")

    entro_hr = percent_within(
        samples,
        lambda c: not sample_hr_out_of_band(c, thresholds),
        lambda c: c.get("bpm") is not None,
    )
    if entro_hr is not None:
        righe.append(
            f"Tempo col battito entro le soglie "
            f"({thresholds.bpm_min_in}-{thresholds.bpm_max_in} bpm): {entro_hr:.1f}%"
        )
    entro_spo2 = percent_within(
        samples,
        lambda c: not sample_spo2_out_of_band(c, thresholds),
        lambda c: c.get("spo2") is not None,
    )
    if entro_spo2 is not None:
        righe.append(
            f"Tempo con la SpO2 entro la soglia (>= {thresholds.spo2_min_in}%): "
            f"{entro_spo2:.1f}%"
        )

    scarto_hr = mean_abs_delta(samples, "hr_grezzo", "hr_filtrato")
    if scarto_hr is not None:
        righe.append(f"Scarto medio del battito (grezzo - filtrato): {scarto_hr:.2f} bpm")
    scarto_spo2 = mean_abs_delta(samples, "spo2_grezzo", "spo2_filtrato")
    if scarto_spo2 is not None:
        righe.append(f"Scarto medio della SpO2 (grezza - filtrata): {scarto_spo2:.2f} %")
    return righe


def _state_lines(samples) -> list[str]:
    durate = state_durations(samples)
    totale = sum(durata for _codice, durata in durate)
    righe = []
    for codice, durata in durate:
        leggibile = f" ({format_duration(durata)})" if durata >= 60 else ""
        quota = f", {100.0 * durata / totale:.1f}% della sessione" if totale else ""
        righe.append(f"{state_label(codice)}: {durata:.1f} s{leggibile}{quota}")
    return righe


def _alarm_lines(events, thresholds, clock) -> list[str]:
    righe = []
    for evento in events:
        relativo = relative_time(evento, clock)
        orario = time.strftime("%H:%M:%S", time.localtime(float(evento["timestamp"])))
        bpm = evento.get("bpm")
        spo2 = evento.get("spo2")
        righe.append(
            f"{orario} (t+{relativo:.1f} s): "
            f"bpm {'--' if bpm is None else f'{float(bpm):.0f}'}, "
            f"SpO2 {'--' if spo2 is None else f'{float(spo2):.0f}'}%"
            f"  causa: {alarm_cause_label(evento, thresholds)}"
        )
    return righe


def _gap_lines(samples) -> list[str]:
    return [
        f"da {buco['start']:.1f} s a {buco['end']:.1f} s "
        f"({format_duration(buco['duration'])} senza campioni)"
        for buco in telemetry_gaps(samples)
    ]


def save_data_to_file(logger, output_path: Path, thresholds) -> Path:
    samples = logger.samples()
    events = logger.events()
    clock = session_clock(samples, events)

    with Path(output_path).open("w", encoding="utf-8") as f:
        write_header(
            f,
            title="LOG BIOMETRICO DELL'OROLOGIO",
            description=(
                "telemetria che l'orologio dell'operaio ha pubblicato via MQTT durante "
                "la sessione, con i valori grezzi del sensore e quelli filtrati dal "
                "firmware."
            ),
            columns=_COLUMNS,
            notes=[
                f"Soglie di ingresso dell'allarme: battito fuori "
                f"{thresholds.bpm_min_in}-{thresholds.bpm_max_in} bpm, "
                f"SpO2 sotto {thresholds.spo2_min_in}%.",
                f"Soglie di rientro: battito entro "
                f"{thresholds.bpm_min_out}-{thresholds.bpm_max_out} bpm, "
                f"SpO2 da {thresholds.spo2_min_out}%.",
                "L'allarme lo decide il firmware dell'orologio: le soglie qui sopra "
                "servono solo a rileggere i dati.",
                f"Un silenzio oltre {MAX_GAP_SEC:.1f} s e' contato come buco nella "
                f"telemetria, non come valori costanti.",
            ],
        )

        write_column_line(f, _COLUMNS)

        for campione in samples:
            f.write(
                f"{campione['timestamp']:.3f},"
                f"{relative_time(campione, clock):.3f},"
                f"{safe_text_value(campione.get('stato'))},"
                f"{format_bool(campione.get('lettura_valida'))},"
                f"{format_optional_float(campione.get('hr_grezzo'), 2)},"
                f"{format_optional_float(campione.get('hr_filtrato'), 2)},"
                f"{format_optional_float(_delta(campione.get('hr_filtrato'), campione.get('hr_grezzo')), 2)},"
                f"{format_optional_float(campione.get('spo2_grezzo'), 2)},"
                f"{format_optional_float(campione.get('spo2_filtrato'), 2)},"
                f"{format_optional_float(_delta(campione.get('spo2_filtrato'), campione.get('spo2_grezzo')), 2)},"
                f"{format_bool(sample_hr_out_of_band(campione, thresholds))},"
                f"{format_bool(sample_spo2_out_of_band(campione, thresholds))}\n"
            )

        write_stats_footer(f, entries=samples, numeric_columns=_STATS_COLUMNS)

        write_section(f, "Panoramica della sessione", _overview_lines(samples, events, thresholds))
        write_section(f, "Tempo per stato dell'orologio", _state_lines(samples))
        if events:
            write_section(
                f, "Allarmi biometrici", _alarm_lines(events, thresholds, clock)
            )
        buchi = _gap_lines(samples)
        if buchi:
            write_section(f, "Buchi nella telemetria", buchi)

    return Path(output_path)
