from __future__ import annotations

from pathlib import Path
from typing import Optional

from openpyxl import Workbook

from drone.data.biometric_excel_sheets import (
    SAMPLES_SHEET,
    write_alarms_sheet,
    write_legend_sheet,
    write_parameters_sheet,
    write_samples_sheet,
    write_summary_sheet,
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
    samples = logger.samples()

    telemetria = [
        ("Cadenza attesa di pubblicazione", f"{fmt_num_it(NOMINAL_STEP_SEC, 1)} s"),
    ]
    if samples:
        telemetria.append(
            ("Cadenza misurata nella sessione", f"{fmt_num_it(sample_step_sec(samples), 2)} s")
        )
        telemetria.append(("Campioni ricevuti", str(len(samples))))
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


def _build_workbook(
    logger,
    thresholds,
    parameters: Optional[list[tuple[str, list[tuple[str, str]]]]] = None,
) -> Workbook:
    samples = logger.samples()
    allarmi = logger.events()
    clock = session_clock(samples, allarmi)

    wb = Workbook()
    summary_ws = wb.active
    summary_ws.title = "Riepilogo"
    write_summary_sheet(summary_ws, logger, thresholds)

    if parameters:
        write_parameters_sheet(wb.create_sheet("Parametri"), parameters)

    if samples:
        write_samples_sheet(
            wb.create_sheet(SAMPLES_SHEET), samples, thresholds, clock
        )

    if allarmi:
        write_alarms_sheet(wb.create_sheet("Allarmi"), allarmi, thresholds, clock)

    write_legend_sheet(
        wb.create_sheet("Legenda"),
        include_samples=bool(samples),
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
