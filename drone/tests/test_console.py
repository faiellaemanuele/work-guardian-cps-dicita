from __future__ import annotations

import contextlib
import io
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import drone.ui.console as co
from drone.ui.console import (
    ConsoleLogFormatter,
    print_event,
    log_console_block,
    log_waypoint_reached,
    print_step,
    reset_mission_state,
    set_alert_sink,
)


def _capture(fn) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def _record(level: int, msg: str, *, phase: bool = False, title: bool = False) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="drone.test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    if phase:
        rec.phase = True
    if title:
        rec.title = True
    return rec


def test_format_info_line_has_glyph_and_no_module_path():
    out = ConsoleLogFormatter().format(_record(logging.INFO, "Connesso al Tello."))
    assert "Connesso al Tello." in out
    assert "drone.test" not in out
    assert out[2] == ":" and out[5] == ":"


def test_format_level_glyphs():
    fmt = ConsoleLogFormatter()
    assert "!" in fmt.format(_record(logging.WARNING, "x"))
    assert "×" in fmt.format(_record(logging.ERROR, "x"))
    assert "·" in fmt.format(_record(logging.DEBUG, "x"))


def test_phase_record_rendered_as_titled_rule():
    out = ConsoleLogFormatter().format(_record(logging.INFO, "Fase 4 · Connessione al drone", phase=True))
    assert "FASE 4 · CONNESSIONE AL DRONE" in out
    assert "----" in out
    assert "──" not in out
    assert out.count("\n") == 1


def test_title_record_is_centered_above_a_rule():
    out = ConsoleLogFormatter().format(_record(logging.INFO, "WORK GUARDIAN", title=True))
    riga_titolo, riga_linea = out.split("\n")
    assert riga_titolo.strip() == "WORK GUARDIAN"
    assert riga_titolo.startswith(" ")
    assert set(riga_linea) == {"-"}


def test_log_title_goes_to_the_phase_logger():
    recs = _collect_logs("drone.phase", lambda: co.log_title("WORK GUARDIAN"))
    assert len(recs) == 1
    assert recs[0].title is True
    assert recs[0].getMessage() == "WORK GUARDIAN"


def test_print_step_goes_to_shell_not_stdout():
    assert _capture(lambda: print_step("OK", "Joystick inizializzato.")) == ""


def test_print_step_format():
    recs = _collect_logs("drone.setup", lambda: print_step("OK", "Joystick inizializzato."))
    assert len(recs) == 1
    out = ConsoleLogFormatter().format(recs[0]).rstrip("\n")
    assert out.endswith("✓  Joystick inizializzato.")
    assert out[2] == ":" and out[5] == ":"
    assert "OK" not in out


def test_log_console_block_is_raw():
    recs = _collect_logs("drone.setup", lambda: log_console_block("Sistema pronto.\nriga 2"))
    assert len(recs) == 1
    out = ConsoleLogFormatter().format(recs[0])
    assert out == "Sistema pronto.\nriga 2"


_AIUTO = (
    "\nComandi del controller\n" + "─" * 20
    + "\nPulsante    Azione\n" + "─" * 20
    + "\nCroce       decolla\n" + "─" * 20
)


def test_ready_banner_keeps_every_word_and_puts_the_title_in_the_rule():
    recs = _collect_logs("drone.setup", lambda: co.log_ready_banner(
        "Tutto pronto", "Il drone è a terra.", _AIUTO, ("Prima riga finale.", "Riga finale."),
    ))
    assert len(recs) == 1
    righe = ConsoleLogFormatter().format(recs[0]).split("\n")
    assert righe[0] == ""
    assert righe[1].startswith("-") and "TUTTO PRONTO" in righe[1]
    assert righe[2] == "Il drone è a terra."
    testo = "\n".join(righe)
    assert "COMANDI DEL CONTROLLER" in testo
    assert "Pulsante    Azione" in testo
    assert "Croce       decolla" in testo
    assert "─" not in testo
    assert righe[-2:] == ["Prima riga finale.", "Riga finale."]


def test_ready_banner_without_help_skips_the_table():
    recs = _collect_logs("drone.setup", lambda: co.log_ready_banner(
        "Tutto pronto", "Messaggio.", "", ("Fine.",),
    ))
    righe = ConsoleLogFormatter().format(recs[0]).split("\n")
    assert righe[2:] == ["Messaggio.", "", "Fine."]


def test_the_help_block_is_colored_only_when_colors_are_on():
    co.set_color_enabled(True)
    try:
        colorato = co._style_help_block(_AIUTO)
    finally:
        co.set_color_enabled(False)
    assert "\033[" in colorato
    assert "\033[" not in co._style_help_block(_AIUTO)


def test_print_event_setup_goes_to_shell_not_panel():
    assert _capture(lambda: print_event("x")) == ""
    assert _capture(lambda: print_event("x", prefix="AVVISO")) == ""
    assert _capture(lambda: print_event("x", prefix="ERRORE")) == ""
    assert _capture(lambda: print_event("x", prefix="RETE")) == ""


def test_print_event_runtime_goes_to_panel_not_shell():
    prev = co._runtime_started
    co._runtime_started = True
    try:
        assert "·" in _capture(lambda: print_event("x"))
        assert "!" in _capture(lambda: print_event("x", prefix="AVVISO"))
        assert "×" in _capture(lambda: print_event("x", prefix="ERRORE"))
        assert "•" in _capture(lambda: print_event("x", prefix="RETE"))
        recs = _collect_logs("drone.event", lambda: print_event("x", prefix="AVVISO"))
        assert recs == []
    finally:
        co._runtime_started = prev


def test_print_event_alert_channel_goes_to_sink_in_flight():
    prev = co._runtime_started
    co._runtime_started = True
    sink_lines = []
    set_alert_sink(sink_lines.append)
    try:
        out = _capture(lambda: print_event("Rilevata la caduta di una persona.",
                                            prefix="AVVISO", channel="alert"))
        assert out == ""
        assert len(sink_lines) == 1
        assert "!" in sink_lines[0]
        assert "caduta di una persona" in sink_lines[0]
    finally:
        set_alert_sink(None)
        co._runtime_started = prev


def test_print_event_safety_net_missing_uses_critical_glyph():
    prev = co._runtime_started
    co._runtime_started = True
    sink_lines = []
    set_alert_sink(sink_lines.append)
    try:
        _capture(lambda: print_event("Rete di sicurezza mancante al waypoint 2",
                                      prefix="ALLERTA", channel="alert"))
        assert len(sink_lines) == 1
        assert "×" in sink_lines[0]
        assert "!" not in sink_lines[0]
    finally:
        set_alert_sink(None)
        co._runtime_started = prev


def test_print_event_alert_channel_falls_back_to_print_without_sink():
    prev = co._runtime_started
    co._runtime_started = True
    try:
        out = _capture(lambda: print_event("Rete di sicurezza presente.",
                                            prefix="RETE", channel="alert"))
        assert "•" in out and "Rete di sicurezza presente." in out
    finally:
        co._runtime_started = prev


def test_print_event_alert_channel_falls_back_when_sink_raises():
    prev = co._runtime_started
    co._runtime_started = True

    def bad_sink(_line):
        raise RuntimeError("pannello rotto")

    set_alert_sink(bad_sink)
    try:
        out = _capture(lambda: print_event("Allerta.", prefix="AVVISO", channel="alert"))
        assert "Allerta." in out
    finally:
        set_alert_sink(None)
        co._runtime_started = prev


def test_print_event_drone_channel_ignores_alert_sink():
    prev = co._runtime_started
    co._runtime_started = True
    sink_lines = []
    set_alert_sink(sink_lines.append)
    try:
        out = _capture(lambda: print_event("Decollo eseguito."))
        assert "Decollo eseguito." in out
        assert sink_lines == []
    finally:
        set_alert_sink(None)
        co._runtime_started = prev


def _collect_logs(logger_name: str, fn):
    logger = logging.getLogger(logger_name)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        _capture(fn)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
    return records


def test_print_event_avviso_logs_warning():
    recs = _collect_logs("drone.event", lambda: print_event("Batteria bassa", prefix="AVVISO"))
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING
    assert "Batteria bassa" in recs[0].getMessage()


def test_print_event_errore_logs_error():
    recs = _collect_logs("drone.event", lambda: print_event("Timeout video", prefix="ERRORE"))
    assert len(recs) == 1 and recs[0].levelno == logging.ERROR


def test_print_event_evento_logs_info_to_shell_during_setup():
    recs = _collect_logs("drone.event", lambda: print_event("Waypoint 2 raggiunto."))
    assert len(recs) == 1 and recs[0].levelno == logging.INFO


def test_print_event_rete_logs_info_to_shell_during_setup():
    recs = _collect_logs("drone.event", lambda: print_event("Rete rilevata", prefix="RETE"))
    assert len(recs) == 1 and recs[0].levelno == logging.INFO


def _in_volo(fn) -> str:
    prev = co._runtime_started
    co._runtime_started = True
    try:
        return _capture(fn)
    finally:
        co._runtime_started = prev


def test_waypoint_reached_logged_once_per_waypoint():
    reset_mission_state()
    out = _in_volo(lambda: (
        log_waypoint_reached({"reached": True}, "7 di 11"),
        log_waypoint_reached({"reached": True}, "7 di 11"),
        log_waypoint_reached({"reached": True}, "8 di 11"),
    ))
    righe = [r for r in out.splitlines() if r.strip()]
    assert len(righe) == 2
    assert "Waypoint 7 di 11 raggiunto" in righe[0]
    assert "Waypoint 8 di 11 raggiunto" in righe[1]
    reset_mission_state()


def test_intermediate_states_are_not_logged():
    reset_mission_state()
    out = _in_volo(lambda: (
        log_waypoint_reached({"reached": False, "reason": "tracking"}, "7 di 11"),
        log_waypoint_reached({}, "7 di 11"),
        log_waypoint_reached(None, "7 di 11"),
    ))
    assert out.strip() == ""
    reset_mission_state()


def test_reset_mission_state_allows_relogging_same_waypoint():
    reset_mission_state()
    out = _in_volo(lambda: (
        log_waypoint_reached({"reached": True}, "7 di 11"),
        reset_mission_state(),
        log_waypoint_reached({"reached": True}, "7 di 11"),
    ))
    assert len([r for r in out.splitlines() if r.strip()]) == 2
    reset_mission_state()


def test_print_step_failure_logs_warning():
    logger = logging.getLogger("drone.setup")
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.WARNING)
    try:
        _capture(lambda: print_step("!!", "Filtro Kalman non disponibile"))
        _capture(lambda: print_step("OK", "Tutto a posto"))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "Filtro Kalman non disponibile" in records[0].getMessage()


def _record_livello(level, message="qualcosa"):
    return logging.LogRecord(
        "drone.test", level, __file__, 1, message, None, None,
    )


def _formatter_pulito():
    ConsoleLogFormatter._errors_section_open = False
    return ConsoleLogFormatter()


def test_errors_section_not_opened_during_setup():
    co._runtime_started = False
    try:
        testo = _formatter_pulito().format(_record_livello(logging.ERROR))
    finally:
        co._runtime_started = False
    assert "ERRORI" not in testo


def test_errors_section_opens_on_first_problem_in_flight():
    co._runtime_started = True
    try:
        testo = _formatter_pulito().format(_record_livello(logging.WARNING, "batteria bassa"))
    finally:
        co._runtime_started = False
    assert "ERRORI" in testo
    assert "batteria bassa" in testo
    assert testo.index("ERRORI") < testo.index("batteria bassa")


def test_errors_section_title_printed_only_once():
    co._runtime_started = True
    try:
        f = _formatter_pulito()
        primo = f.format(_record_livello(logging.ERROR, "primo guaio"))
        secondo = f.format(_record_livello(logging.ERROR, "secondo guaio"))
    finally:
        co._runtime_started = False
    assert "ERRORI" in primo
    assert "ERRORI" not in secondo


def test_errors_section_ignores_informative_lines():
    co._runtime_started = True
    try:
        f = _formatter_pulito()
        assert "ERRORI" not in f.format(_record_livello(logging.INFO, "tutto bene"))
        assert "ERRORI" in f.format(_record_livello(logging.WARNING, "guaio"))
    finally:
        co._runtime_started = False


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
