from __future__ import annotations

import ast
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.config import logging_setup
from drone.config.logging_setup import ensure_utf8_console
from drone.ui import console
from drone.ui.console import ConsoleHandler, RepeatedErrorFilter

RADICE = Path(__file__).resolve().parent.parent.parent

COPIE = (
    RADICE / "drone" / "config" / "logging_setup.py",
    RADICE / "drone" / "scripts" / "camera_calibration.py",
    RADICE / "drone" / "scripts" / "joystick_diagnostics.py",
)


class _Stream:
    def __init__(self, errore=None):
        self.chiamate = []
        self._errore = errore

    def reconfigure(self, **kwargs):
        self.chiamate.append(kwargs)
        if self._errore is not None:
            raise self._errore


class _StreamSenzaReconfigure:
    pass


def _con_flussi(stdout, stderr):
    originali = (sys.stdout, sys.stderr)
    sys.stdout, sys.stderr = stdout, stderr
    try:
        ensure_utf8_console()
    finally:
        sys.stdout, sys.stderr = originali


def _funzione(percorso: Path, nome: str):
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    for nodo in albero.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nome:
            return nodo
    raise AssertionError(f"{nome} non trovata in {percorso.name}")


def test_reconfigures_both_streams_to_utf8():
    stdout, stderr = _Stream(), _Stream()
    _con_flussi(stdout, stderr)
    atteso = {"encoding": "utf-8", "errors": "replace"}
    assert stdout.chiamate == [atteso]
    assert stderr.chiamate == [atteso]


def test_skips_streams_without_reconfigure():
    stderr = _Stream()
    _con_flussi(_StreamSenzaReconfigure(), stderr)
    assert stderr.chiamate == [{"encoding": "utf-8", "errors": "replace"}]


def test_a_failing_reconfigure_does_not_stop_the_other_stream():
    stdout, stderr = _Stream(errore=ValueError("no")), _Stream()
    _con_flussi(stdout, stderr)
    assert stderr.chiamate == [{"encoding": "utf-8", "errors": "replace"}]


def test_an_os_error_from_reconfigure_is_swallowed():
    _con_flussi(_Stream(errore=OSError("no")), _Stream(errore=OSError("no")))


def test_the_standalone_scripts_keep_an_identical_copy():
    riferimento = ast.dump(_funzione(COPIE[0], "ensure_utf8_console"))
    for percorso in COPIE[1:]:
        assert ast.dump(_funzione(percorso, "ensure_utf8_console")) == riferimento, percorso.name


def test_log_level_is_read_from_the_configuration():
    originale = logging_setup.APP_CONFIG
    try:
        logging_setup.APP_CONFIG = replace(APP_CONFIG, log_level="debug")
        assert logging_setup._resolve_log_level() == logging.DEBUG
    finally:
        logging_setup.APP_CONFIG = originale


def test_an_unknown_log_level_falls_back_to_the_default_and_warns():
    originale = logging_setup.APP_CONFIG
    passi = []
    originale_print = logging_setup.print_step
    try:
        logging_setup.APP_CONFIG = replace(APP_CONFIG, log_level="URLA")
        logging_setup.print_step = lambda esito, testo: passi.append((esito, testo))
        assert logging_setup._resolve_log_level() == logging.WARNING
        assert logging_setup._resolve_log_level(logging.ERROR) == logging.ERROR
    finally:
        logging_setup.APP_CONFIG = originale
        logging_setup.print_step = originale_print
    assert passi and passi[0][0] == "!!"
    assert "URLA" in passi[0][1]



def _con_livello(nome_livello):
    originale = logging_setup.APP_CONFIG
    livelli = {}
    try:
        logging_setup.APP_CONFIG = replace(APP_CONFIG, log_level=nome_livello)
        logging_setup.configure_logging()
        for nome in ("", "drone.phase", "drone.setup", "drone.event",
                     "drone.control.autopilot", "djitellopy", "ultralytics"):
            livelli[nome or "radice"] = logging.getLogger(nome).getEffectiveLevel()
    finally:
        logging_setup.APP_CONFIG = originale
    return livelli


def test_i_messaggi_del_setup_restano_visibili_anche_con_la_radice_a_warning():
    livelli = _con_livello("warning")

    assert livelli["radice"] == logging.WARNING
    assert livelli["drone.phase"] == logging.INFO
    assert livelli["drone.setup"] == logging.INFO
    assert livelli["drone.event"] == logging.INFO


def test_i_moduli_del_drone_seguono_il_livello_della_radice():
    assert _con_livello("warning")["drone.control.autopilot"] == logging.WARNING
    assert _con_livello("debug")["drone.control.autopilot"] == logging.DEBUG


def test_le_librerie_esterne_restano_zitte():
    livelli = _con_livello("debug")

    assert livelli["djitellopy"] == logging.ERROR
    assert livelli["ultralytics"] == logging.ERROR


def test_la_console_conserva_le_righe_dell_avvio_per_poterle_ridisegnare():
    _con_livello("warning")
    gestori = [g for g in logging.getLogger().handlers if isinstance(g, ConsoleHandler)]
    assert len(gestori) == 1
    assert console._console_handler is gestori[0]


def test_la_console_non_ripete_lo_stesso_errore():
    _con_livello("warning")
    filtri = [
        filtro
        for gestore in logging.getLogger().handlers
        for filtro in gestore.filters
        if isinstance(filtro, RepeatedErrorFilter)
    ]
    assert len(filtri) == 1
    assert filtri[0]._repeat_after_sec == APP_CONFIG.console_error_repeat_after_sec


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
