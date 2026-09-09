from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.data.flight_data_logger import FlightDataLogger

from flight_log_samples import logger_with_autopilot_data, logger_with_both


def _openpyxl_available() -> bool:
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def test_excel_has_expected_sheets_and_translations():
    if not _openpyxl_available():
        return
    from openpyxl import load_workbook
    from drone.data import flight_excel_report

    log = logger_with_both()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "test.xlsx"
        flight_excel_report.save_session_workbook(log, path)
        wb = load_workbook(path)

    assert wb.sheetnames == ["Riepilogo", "Autopilota", "Kalman", "Legenda"]
    ws = wb["Autopilota"]
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    assert "Stato del controllo" in headers
    values = {ws.cell(r, headers.index("Stato del controllo") + 1).value
              for r in range(2, ws.max_row + 1)}
    assert "Inseguimento waypoint" in values
    assert "tracking" not in values


def test_excel_columns_fit_headers():
    if not _openpyxl_available():
        return
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    from drone.data import flight_excel_report

    log = logger_with_both()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "test.xlsx"
        flight_excel_report.save_session_workbook(log, path)
        wb = load_workbook(path)

    for sheet in ("Autopilota", "Kalman"):
        ws = wb[sheet]
        for c in range(1, ws.max_column + 1):
            header = ws.cell(1, c).value
            width = ws.column_dimensions[get_column_letter(c)].width
            assert width is not None and width >= len(header), (
                f"{sheet}: colonna '{header}' troppo stretta ({width})"
            )


def test_excel_parameters_sheet_from_config():
    if not _openpyxl_available():
        return
    from openpyxl import load_workbook
    from drone.config import APP_CONFIG
    from drone.data import flight_excel_report

    log = logger_with_autopilot_data()
    params = flight_excel_report.collect_run_parameters(log, APP_CONFIG, path_name="Percorso di prova")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "test.xlsx"
        flight_excel_report.save_session_workbook(log, path, params)
        wb = load_workbook(path)

    assert "Parametri" in wb.sheetnames
    testo = "\n".join(
        str(wb["Parametri"].cell(r, c).value)
        for r in range(1, wb["Parametri"].max_row + 1)
        for c in (1, 2)
    )
    assert "Percorso di prova" in testo
    assert "kp XY" in testo


def test_export_session_creates_excel():
    if not _openpyxl_available():
        return
    log = logger_with_autopilot_data()
    with tempfile.TemporaryDirectory() as d:
        session = log.export_session(output_root=d)
        assert session is not None
        assert (session / FlightDataLogger.EXCEL_FILENAME).exists()


def test_export_session_falls_back_to_text_without_excel():
    log = logger_with_autopilot_data()
    original = FlightDataLogger._save_excel
    FlightDataLogger._save_excel = lambda self, *a, **k: None
    try:
        with tempfile.TemporaryDirectory() as d:
            session = log.export_session(output_root=d)
            assert session is not None
            assert (session / FlightDataLogger.AUTOPILOT_TEXT_FILENAME).exists()
            assert not (session / FlightDataLogger.EXCEL_FILENAME).exists()
    finally:
        FlightDataLogger._save_excel = original


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
