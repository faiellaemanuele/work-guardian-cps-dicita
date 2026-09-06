from __future__ import annotations

import logging
import shutil
import time
from typing import Callable, Optional


_SEP_WIDTH = shutil.get_terminal_size((80, 24)).columns
SEP_THIN  = "─" * _SEP_WIDTH


_RESET = "\033[0m"
_BOLD  = "\033[1m"
_DIM   = "\033[38;5;242m"
_GREEN = "\033[38;5;72m"
_GREY  = "\033[38;5;245m"
_AMBER = "\033[38;5;179m"
_RED   = "\033[38;5;167m"
_SLATE = "\033[38;5;110m"

_COLOR = False


def set_color_enabled(flag: bool) -> None:
    global _COLOR
    _COLOR = bool(flag)


def _c(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _COLOR else text


_STEP_GLYPH = {"OK": "✓", "--": "·", "!!": "!"}
_LEVEL_GLYPH = {
    logging.DEBUG: "·",
    logging.INFO: "·",
    logging.WARNING: "!",
    logging.ERROR: "×",
    logging.CRITICAL: "×",
}
_GLYPH_COLOR = {"✓": _GREEN, "·": _GREY, "!": _AMBER, "×": _RED}

_PHASE_LOGGER = logging.getLogger("drone.phase")


def log_phase(title: str) -> None:
    _PHASE_LOGGER.info(title, extra={"phase": True})


class ConsoleLogFormatter(logging.Formatter):
    _errors_section_open = False

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "phase", False):
            return self._format_phase(record.getMessage())
        prefix = self._open_errors_section(record)
        if getattr(record, "raw", False):
            return record.getMessage()
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        setup_label = getattr(record, "setup_label", None)
        if setup_label is not None:
            glyph = _STEP_GLYPH.get(setup_label, "·")
        else:
            glyph = _LEVEL_GLYPH.get(record.levelno, "·")
        return (
            f"{prefix}{_c(ts, _DIM)}  {_c(glyph, _GLYPH_COLOR.get(glyph, ''))}  "
            f"{record.getMessage()}"
        )

    def _open_errors_section(self, record: logging.LogRecord) -> str:
        if type(self)._errors_section_open or not _runtime_started:
            return ""
        if record.levelno < logging.WARNING:
            return ""
        type(self)._errors_section_open = True
        return self._format_phase("Errori") + "\n"

    @staticmethod
    def _format_phase(title: str) -> str:
        used = len("── ") + len(title) + len(" ")
        fill = "─" * max(4, _SEP_WIDTH - used)
        return (
            f"\n{_c('── ', _DIM)}{_c(title, _SLATE + _BOLD)}"
            f"{_c(' ' + fill, _DIM)}"
        )


_CONSOLE_LINE_GLYPH = {"INFO": "·", "WARN": "!", "ERR": "×", "RETE": "•", "ALLERTA": "×"}


def _console_line(label: str, message: str) -> str:
    glyph = _CONSOLE_LINE_GLYPH.get(label, "·")
    return f"{time.strftime('%H:%M:%S')}  {glyph}  {message}"


_SETUP_LOGGER = logging.getLogger("drone.setup")


def print_step(outcome: str, message: str) -> None:
    level = logging.WARNING if outcome == "!!" else logging.INFO
    _SETUP_LOGGER.log(level, message, extra={"setup_label": outcome})


def log_console_block(text: str) -> None:
    _SETUP_LOGGER.info(text, extra={"raw": True})


_mission_last_reached: str | None = None


def log_waypoint_reached(command, label: str) -> None:
    global _mission_last_reached
    if not command or not command.get("reached", False):
        return
    label = str(label)
    if label == _mission_last_reached:
        return
    _mission_last_reached = label
    if command.get("reason") == "supervision_stop_completed":
        print_event(f"Sosta al waypoint {label} conclusa", channel="drone")
    else:
        print_event(f"Waypoint {label} raggiunto", channel="drone")


def reset_mission_state() -> None:
    global _mission_last_reached
    _mission_last_reached = None


_EVENT_LABELS = {
    "EVENTO": "INFO",
    "RETE": "RETE",
    "AVVISO": "WARN",
    "ERRORE": "ERR",
    "ALLERTA": "ALLERTA",
}

_EVENT_LOGGER = logging.getLogger("drone.event")

_EVENT_LEVEL = {
    "EVENTO": logging.INFO,
    "RETE":   logging.INFO,
    "AVVISO": logging.WARNING,
    "ERRORE": logging.ERROR,
    "ALLERTA": logging.ERROR,
}

_runtime_started = False


def mark_runtime_started() -> None:
    global _runtime_started
    _runtime_started = True


_alert_sink: Optional[Callable[[str], None]] = None


def set_alert_sink(sink: Optional[Callable[[str], None]]) -> None:
    global _alert_sink
    _alert_sink = sink


def print_event(msg: str, *, prefix: str = "EVENTO", channel: str = "drone") -> None:
    if not _runtime_started:
        _EVENT_LOGGER.log(_EVENT_LEVEL.get(prefix, logging.ERROR), msg)
        return

    line = _console_line(_EVENT_LABELS.get(prefix, prefix), msg)
    if channel == "alert" and _alert_sink is not None:
        try:
            _alert_sink(line)
            return
        except Exception:
            pass
    print(line)
