from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from openpyxl import Workbook

from drone.data.biometric_excel_sheets import (
    sheet_name,
    worker_label,
    write_alarms_sheet,
    write_legend_sheet,
    write_parameters_sheet,
    write_summary_sheet,
    write_worker_sheet,
)
from drone.data.biometric_report_stats import (
    MAX_GAP_SEC,
    NOMINAL_STEP_SEC,
    sample_step_sec,
    session_clock,
)
from drone.data.flight_excel_style import fmt_num_it


def collect_session_parameters(
    logger, app_config
) -> list[tuple[str, list[tuple[str, str]]]]:
    soglie = app_config.smartwatch_thresholds
    workers = logger.workers()
    single = len(workers) <= 1

    telemetria = [
        ("Orologi collegati", str(len(workers)) if workers else "—"),
        ("Cadenza attesa di pubblicazione", f"{fmt_num_it(NOMINAL_STEP_SEC, 1)} s"),
    ]
    for worker in workers:
        samples = logger.samples(worker)
        if not samples:
            continue
        etichetta = (
            "Cadenza misurata nella sessione" if single
            else f"Cadenza misurata ({worker_label(worker, single=False)})"
        )
        telemetria.append(
            (etichetta, f"{fmt_num_it(sample_step_sec(samples), 2)} s")
        )
        campioni = (
            "Campioni ricevuti" if single
            else f"Campioni ricevuti ({worker_label(worker, single=False)})"
        )
        telemetria.append((campioni, str(len(samples))))
    telemetria.append(
        ("Silenzio oltre il quale si conta un buco", f"{fmt_num_it(MAX_GAP_SEC, 1)} s")
    )
    telemetria.append(
        ("Broker MQTT", f"{app_config.mqtt_broker_ip}:{app_config.mqtt_broker_port}")
    )

    return [
        ("Soglie dell'allarme sul battito", [
            ("Soglia minima di ingresso [bpm]", str(soglie.bpm_min_in)),
            ("Soglia massima di ingresso [bpm]", str(soglie.bpm_max_in)),
            ("Soglia minima di rientro [bpm]", str(soglie.bpm_min_out)),
            ("Soglia massima di rientro [bpm]", str(soglie.bpm_max_out)),
        ]),
        ("Soglie dell'allarme sulla saturazione", [
            ("Soglia di ingresso [%]", f"sotto {soglie.spo2_min_in}"),
            ("Soglia di rientro [%]", str(soglie.spo2_min_out)),
        ]),
        ("Telemetria", telemetria),
    ]


def _alarm_rows(logger) -> list[dict[str, Any]]:
    righe: list[dict[str, Any]] = []
    for worker in logger.workers():
        for evento in logger.events(worker):
            righe.append({**evento, "operaio": worker})
    righe.sort(key=lambda e: float(e["timestamp"]))
    return righe


def _build_workbook(
    logger,
    thresholds,
    parameters: Optional[list[tuple[str, list[tuple[str, str]]]]] = None,
) -> Workbook:
    workers = [worker for worker in logger.workers() if logger.samples(worker)]
    single = len(workers) <= 1
    allarmi = _alarm_rows(logger)
    clock = session_clock(
        *(logger.samples(worker) for worker in workers), allarmi
    )

    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Riepilogo"
    write_summary_sheet(summary_ws, logger, thresholds)

    if parameters:
        write_parameters_sheet(wb.create_sheet("Parametri"), parameters)

    nomi_fogli: list[str] = []
    for worker in workers:
        nome = sheet_name(worker_label(worker, single=single))
        nomi_fogli.append(nome)
        write_worker_sheet(
            wb.create_sheet(nome), logger.samples(worker), thresholds, clock
        )

    if allarmi:
        write_alarms_sheet(
            wb.create_sheet("Allarmi"), allarmi, thresholds, clock,
            include_worker=not single,
        )

    write_legend_sheet(
        wb.create_sheet("Legenda"),
        sample_sheets=nomi_fogli,
        include_alarms=bool(allarmi),
    )

    return wb


def save_session_workbook(
    logger, output_path: Path, thresholds, parameters=None
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = _build_workbook(logger, thresholds, parameters)
    wb.save(output_path)
    return output_path
