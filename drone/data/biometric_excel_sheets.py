from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

from openpyxl.worksheet.worksheet import Worksheet

from drone.data.biometric_report_stats import (
    alarm_cause_label,
    format_duration,
    hr_out_of_band,
    mean_abs_delta,
    monitored_duration_sec,
    relative_time,
    sample_step_sec,
    spo2_out_of_band,
    state_durations,
    state_label,
    telemetry_gaps,
    valid_reading_percent,
)
from drone.data.excel_tables import (
    write_data_sheet,
    write_legend_sheet as write_legend_blocks,
    write_parameters_sheet as write_parameters_block,
    write_stats_table,
)
from drone.data.flight_excel_style import (
    ALERT_FILL,
    ALERT_FONT,
    BASE_FONT,
    CELL_BORDER,
    CENTER,
    FMT_INT,
    FMT_PCT,
    FMT_S,
    FMT_TIME,
    LEFT,
    RIGHT,
    SUBTITLE_FONT,
    TITLE_FONT,
    WARN_FILL,
    WARN_FONT,
    autofit_columns,
    bool_it,
    clock as as_clock,
    fmt_num_it,
    kv,
    section_title,
    table_header,
)
from drone.data.flight_report_stats import (
    column_stats,
    percent_within,
    total_duration_sec,
)

# Battito e saturazione si leggono con un decimale. Le stringhe valgono anche
# per autofit_columns, che riconosce il formato a un decimale.
FMT_BPM = "0.0"
FMT_SPO2 = "0.0"
FMT_HZ = "0.0"
FMT_SEC = "0.0"

_STAT_LABELS = {
    "hr_grezzo": "Battito grezzo [bpm]",
    "hr_filtrato": "Battito filtrato [bpm]",
    "spo2_grezzo": "SpO2 grezza [%]",
    "spo2_filtrato": "SpO2 filtrata [%]",
}

_STAT_COLUMNS = ["hr_grezzo", "hr_filtrato", "spo2_grezzo", "spo2_filtrato"]

# Caratteri che Excel non accetta nel nome di un foglio, più il limite di 31.
_INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")
_MAX_SHEET_NAME = 31


def worker_label(worker: str, *, single: bool) -> str:
    # È previsto un solo operaio: il suo identificativo compare solo se gli
    # orologi collegati sono più di uno.
    return "Orologio" if single else f"Orologio {worker}"


def sheet_name(label: str) -> str:
    return _INVALID_SHEET_CHARS.sub("-", label)[:_MAX_SHEET_NAME]


def _delta(filtered: Any, raw: Any) -> Optional[float]:
    if filtered is None or raw is None:
        return None
    return float(filtered) - float(raw)


def _sample_columns(
    thresholds, clock: tuple[str, float]
) -> list[tuple[str, Callable, Optional[str]]]:
    return [
        ("Orario", lambda c: as_clock(c["timestamp"]), FMT_TIME),
        ("Tempo dall'avvio [s]", lambda c: relative_time(c, clock), FMT_S),
        ("Stato dell'orologio", lambda c: state_label(c.get("stato")), None),
        ("Lettura valida", lambda c: bool_it(c.get("lettura_valida")), None),
        ("Battito grezzo [bpm]", lambda c: c.get("hr_grezzo"), FMT_BPM),
        ("Battito filtrato [bpm]", lambda c: c.get("hr_filtrato"), FMT_BPM),
        ("Scarto battito [bpm]",
         lambda c: _delta(c.get("hr_filtrato"), c.get("hr_grezzo")), FMT_BPM),
        ("SpO2 grezza [%]", lambda c: c.get("spo2_grezzo"), FMT_SPO2),
        ("SpO2 filtrata [%]", lambda c: c.get("spo2_filtrato"), FMT_SPO2),
        ("Scarto SpO2 [%]",
         lambda c: _delta(c.get("spo2_filtrato"), c.get("spo2_grezzo")), FMT_SPO2),
        ("Battito fuori soglia",
         lambda c: bool_it(hr_out_of_band(c.get("hr_filtrato"), thresholds)), None),
        ("SpO2 fuori soglia",
         lambda c: bool_it(spo2_out_of_band(c.get("spo2_filtrato"), thresholds)), None),
    ]


def _alarm_columns(
    thresholds, clock: tuple[str, float], *, include_worker: bool
) -> list[tuple[str, Callable, Optional[str]]]:
    columns: list[tuple[str, Callable, Optional[str]]] = [
        ("Orario", lambda e: as_clock(e["timestamp"]), FMT_TIME),
        ("Tempo dall'avvio [s]", lambda e: relative_time(e, clock), FMT_S),
    ]
    if include_worker:
        columns.append(("Orologio", lambda e: e.get("operaio", ""), None))
    columns.extend([
        ("Battito [bpm]", lambda e: e.get("bpm"), FMT_BPM),
        ("SpO2 [%]", lambda e: e.get("spo2"), FMT_SPO2),
        ("Causa", lambda e: alarm_cause_label(e, thresholds), None),
    ])
    return columns


def write_worker_sheet(ws: Worksheet, samples, thresholds, clock) -> None:
    write_data_sheet(
        ws,
        samples,
        _sample_columns(thresholds, clock),
        highlights={
            "Stato dell'orologio": ("Allarme", ALERT_FILL, ALERT_FONT),
            "Battito fuori soglia": ("Sì", ALERT_FILL, ALERT_FONT),
            "SpO2 fuori soglia": ("Sì", ALERT_FILL, ALERT_FONT),
            "Lettura valida": ("No", WARN_FILL, WARN_FONT),
        },
    )


def write_alarms_sheet(
    ws: Worksheet, events, thresholds, clock, *, include_worker: bool
) -> None:
    write_data_sheet(
        ws, events, _alarm_columns(thresholds, clock, include_worker=include_worker)
    )


def _write_overview(ws: Worksheet, row: int, samples, titolo: str) -> int:
    row = section_title(ws, row, titolo, span=5)
    row = kv(ws, row, "Campioni ricevuti", len(samples), FMT_INT)
    row = kv(ws, row, "Durata della sessione [s]", total_duration_sec(samples), FMT_SEC)
    row = kv(
        ws, row, "Telemetria effettivamente coperta [s]",
        monitored_duration_sec(samples), FMT_SEC,
    )
    # La cadenza è la mediana dei passi, non i campioni diviso la durata: con
    # un buco nella telemetria la media direbbe che l'orologio pubblica piano.
    passo = sample_step_sec(samples)
    row = kv(ws, row, "Cadenza misurata [s]", passo, FMT_SEC)
    if passo > 0:
        row = kv(ws, row, "Frequenza di campionamento [Hz]", 1.0 / passo, FMT_HZ)
    t0 = float(samples[0]["timestamp"])
    t1 = float(samples[-1]["timestamp"])
    row = kv(
        ws, row, "Orario del monitoraggio",
        f"da {time.strftime('%H:%M:%S', time.localtime(t0))} "
        f"a {time.strftime('%H:%M:%S', time.localtime(t1))}",
    )
    valide = valid_reading_percent(samples)
    if valide is not None:
        row = kv(ws, row, "Letture valide del sensore", valide, FMT_PCT)
    return row + 1


def _write_outcome(ws: Worksheet, row: int, samples, events, thresholds, titolo: str) -> int:
    row = section_title(ws, row, titolo, span=5)
    row = kv(ws, row, "Allarmi biometrici confermati dall'orologio", len(events), FMT_INT)
    row = kv(
        ws, row, "Campioni col battito fuori soglia",
        sum(1 for c in samples if hr_out_of_band(c.get("hr_filtrato"), thresholds)),
        FMT_INT,
    )
    row = kv(
        ws, row, "Campioni con la SpO2 fuori soglia",
        sum(1 for c in samples if spo2_out_of_band(c.get("spo2_filtrato"), thresholds)),
        FMT_INT,
    )

    entro_hr = percent_within(
        samples,
        lambda c: not hr_out_of_band(c["hr_filtrato"], thresholds),
        lambda c: c.get("hr_filtrato") is not None,
    )
    if entro_hr is not None:
        row = kv(
            ws, row,
            "Tempo col battito entro le soglie "
            f"({thresholds.bpm_min_in}–{thresholds.bpm_max_in} bpm)",
            entro_hr, FMT_PCT,
        )
    entro_spo2 = percent_within(
        samples,
        lambda c: not spo2_out_of_band(c["spo2_filtrato"], thresholds),
        lambda c: c.get("spo2_filtrato") is not None,
    )
    if entro_spo2 is not None:
        row = kv(
            ws, row,
            f"Tempo con la SpO2 entro la soglia (≥ {thresholds.spo2_min_in}%)",
            entro_spo2, FMT_PCT,
        )
    return row + 1


def _write_state_table(ws: Worksheet, row: int, samples, titolo: str) -> int:
    durate = state_durations(samples)
    if not durate:
        return row
    totale = sum(durata for _codice, durata in durate)
    row = section_title(ws, row, titolo, span=5)
    row = table_header(ws, row, ["Stato dell'orologio", "Durata [s]", "Quota", "In chiaro"])
    for codice, durata in durate:
        nome = ws.cell(row=row, column=1, value=state_label(codice))
        nome.font = BASE_FONT
        nome.alignment = LEFT
        nome.border = CELL_BORDER
        secondi = ws.cell(row=row, column=2, value=durata)
        secondi.font = BASE_FONT
        secondi.number_format = FMT_SEC
        secondi.alignment = RIGHT
        secondi.border = CELL_BORDER
        quota = ws.cell(
            row=row, column=3, value=(100.0 * durata / totale) if totale else 0.0
        )
        quota.font = BASE_FONT
        quota.number_format = FMT_PCT
        quota.alignment = RIGHT
        quota.border = CELL_BORDER
        leggibile = ws.cell(row=row, column=4, value=format_duration(durata))
        leggibile.font = BASE_FONT
        leggibile.alignment = CENTER
        leggibile.border = CELL_BORDER
        row += 1
    return row + 1


def _write_filter_section(ws: Worksheet, row: int, samples, titolo: str) -> int:
    scarto_hr = mean_abs_delta(samples, "hr_grezzo", "hr_filtrato")
    scarto_spo2 = mean_abs_delta(samples, "spo2_grezzo", "spo2_filtrato")
    if scarto_hr is None and scarto_spo2 is None:
        return row
    row = section_title(ws, row, titolo, span=5)
    if scarto_hr is not None:
        row = kv(
            ws, row, "Scarto medio del battito (grezzo − filtrato) [bpm]",
            scarto_hr, FMT_BPM,
        )
    if scarto_spo2 is not None:
        row = kv(
            ws, row, "Scarto medio della SpO2 (grezza − filtrata) [%]",
            scarto_spo2, FMT_SPO2,
        )
    return row + 1


def _write_gaps_section(ws: Worksheet, row: int, samples, titolo: str) -> int:
    buchi = telemetry_gaps(samples)
    if not buchi:
        return row
    row = section_title(ws, row, titolo, span=5)
    row = kv(ws, row, "Interruzioni della telemetria", len(buchi), FMT_INT)
    row = kv(
        ws, row, "Tempo senza campioni [s]",
        sum(buco["duration"] for buco in buchi), FMT_SEC,
    )
    for buco in buchi:
        cella = ws.cell(
            row=row, column=1,
            value=(
                f"• da {fmt_num_it(buco['start'], 1)} s a {fmt_num_it(buco['end'], 1)} s "
                f"({format_duration(buco['duration'])} senza campioni)"
            ),
        )
        cella.font = BASE_FONT
        cella.alignment = LEFT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
        row += 1
    return row + 1


def write_summary_sheet(ws: Worksheet, logger, thresholds) -> None:
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:E1")
    title = ws.cell(row=1, column=1, value="Riepilogo sessione biometrica")
    title.font = TITLE_FONT
    ws.merge_cells("A2:E2")
    subtitle = ws.cell(
        row=2, column=1,
        value=f"Generato il {time.strftime('%d/%m/%Y alle %H:%M:%S')}",
    )
    subtitle.font = SUBTITLE_FONT
    row = 4

    workers = logger.workers()
    single = len(workers) <= 1
    for worker in workers:
        samples = logger.samples(worker)
        if not samples:
            continue
        prefisso = "" if single else f"{worker_label(worker, single=False)} — "

        row = _write_overview(ws, row, samples, f"{prefisso}Panoramica")
        row = _write_outcome(
            ws, row, samples, logger.events(worker), thresholds,
            f"{prefisso}Esito del monitoraggio",
        )
        row = _write_state_table(
            ws, row, samples, f"{prefisso}Tempo per stato dell'orologio"
        )

        stats = column_stats(samples, _STAT_COLUMNS)
        if stats:
            row = section_title(ws, row, f"{prefisso}Valori registrati", span=5)
            row = write_stats_table(
                ws, row, stats,
                labels=_STAT_LABELS,
                number_format=lambda nome: FMT_SPO2 if "spo2" in nome else FMT_BPM,
            )
            row += 1
        row = _write_filter_section(
            ws, row, samples,
            f"{prefisso}Filtro dell'orologio (mediana + media mobile)",
        )
        row = _write_gaps_section(ws, row, samples, f"{prefisso}Buchi nella telemetria")

    autofit_columns(ws)


_LEGEND_SAMPLES = [
    ("Orario", "Ora in cui il campione dell'orologio è arrivato dal broker."),
    ("Tempo dall'avvio [s]", "Secondi trascorsi dal primo campione ricevuto nella sessione."),
    ("Stato dell'orologio", "Stato del firmware in quel momento: normale, verifica, allarme, silenziato, guasto del sensore, ricerca segnale."),
    ("Lettura valida", "Sì quando il sensore stava davvero misurando; con No il battito e la saturazione non sono affidabili."),
    ("Battito grezzo [bpm]", "Battito letto dal sensore MAX30100, senza filtro."),
    ("Battito filtrato [bpm]", "Battito dopo il filtro dell'orologio (mediana su più letture e media mobile esponenziale): è il valore su cui il firmware decide l'allarme."),
    ("Scarto battito [bpm]", "Quanto il filtro ha spostato la lettura (filtrato − grezzo)."),
    ("SpO2 grezza [%]", "Saturazione dell'ossigeno letta dal sensore, senza filtro."),
    ("SpO2 filtrata [%]", "Saturazione dopo il filtro dell'orologio."),
    ("Scarto SpO2 [%]", "Quanto il filtro ha spostato la saturazione (filtrata − grezza)."),
    ("Battito fuori soglia", "Sì quando il battito filtrato è oltre le soglie di ingresso dell'allarme."),
    ("SpO2 fuori soglia", "Sì quando la saturazione filtrata è sotto la soglia di ingresso dell'allarme."),
]

_LEGEND_ALARMS = [
    ("Orario", "Ora in cui l'orologio ha confermato l'allarme biometrico."),
    ("Tempo dall'avvio [s]", "Secondi trascorsi dal primo campione della sessione: lo stesso tempo delle altre schede."),
    ("Orologio", "Identificativo dell'operaio che portava l'orologio (compare solo con più orologi collegati)."),
    ("Battito [bpm]", "Battito al momento della conferma dell'allarme."),
    ("SpO2 [%]", "Saturazione al momento della conferma dell'allarme."),
    ("Causa", "Quale dei due valori era fuori soglia quando l'allarme è stato confermato."),
]


def write_legend_sheet(ws: Worksheet, *, sample_sheets: list[str], include_alarms: bool) -> None:
    blocks = [(f"Foglio «{nome}»", _LEGEND_SAMPLES) for nome in sample_sheets]
    if include_alarms:
        blocks.append(("Foglio «Allarmi»", _LEGEND_ALARMS))
    write_legend_blocks(ws, blocks, name_width=30, meaning_width=86)


def write_parameters_sheet(ws: Worksheet, parameters: list[tuple[str, list[tuple[str, str]]]]) -> None:
    write_parameters_block(
        ws,
        parameters,
        subtitle="Soglie e collegamento con cui è stata registrata la sessione biometrica.",
        note=(
            "Le soglie e la decisione dell'allarme appartengono al firmware "
            "dell'orologio: qui sono riportate per leggere i dati, non per cambiarle."
        ),
    )
