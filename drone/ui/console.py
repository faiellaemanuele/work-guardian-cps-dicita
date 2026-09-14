from __future__ import annotations

import logging
import re
import shutil
import time
from typing import Callable, Optional


_SEP_WIDTH = shutil.get_terminal_size((80, 24)).columns
SEP_THIN  = "-" * _SEP_WIDTH


_RESET = "\033[0m"
_BOLD  = "\033[1m"


def _rgb(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"


_TITLE    = _BOLD + _rgb(36, 196, 230)
_RULE     = _rgb(28, 150, 196)
_RULE_DIM = _rgb(22, 100, 136)
_TIME     = _rgb(200, 212, 222)
_TEXT     = _rgb(232, 238, 244)
_TABLE    = _BOLD + _rgb(140, 210, 234)
_READY    = _BOLD + _rgb(88, 226, 120)
_GREEN    = _rgb(88, 226, 120)
_GREY     = _rgb(140, 150, 162)
_AMBER    = _rgb(242, 186, 64)
_RED      = _rgb(242, 98, 90)

_COLOR = False


def set_color_enabled(flag: bool) -> None:
    global _COLOR
    _COLOR = bool(flag)


def _c(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _COLOR and code else text


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


def log_title(title: str) -> None:
    _PHASE_LOGGER.info(title, extra={"title": True})


def _rule(label: str) -> str:
    fill = "-" * max(4, _SEP_WIDTH - len(label) - 1)
    return f"{_c(label, _TITLE)} {_c(fill, _RULE)}"


def _centered_rule(label: str) -> str:
    label = f" {label} "
    left = max(4, (_SEP_WIDTH - len(label)) // 2)
    right = max(4, _SEP_WIDTH - left - len(label))
    return f"{_c('-' * left, _RULE)}{_c(label, _READY)}{_c('-' * right, _RULE)}"


class ConsoleLogFormatter(logging.Formatter):
    _errors_section_open = False

    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "phase", False):
            return self._format_phase(record.getMessage())
        if getattr(record, "title", False):
            return self._format_title(record.getMessage())
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
            f"{prefix}{_c(ts, _TIME)}  {_c(glyph, _GLYPH_COLOR.get(glyph, ''))}  "
            f"{_c(record.getMessage(), _TEXT)}"
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
        return f"\n{_rule(title.upper())}"

    @staticmethod
    def _format_title(title: str) -> str:
        left = " " * max(0, (_SEP_WIDTH - len(title)) // 2)
        return f"{left}{_c(title, _TITLE)}\n{_c(SEP_THIN, _RULE)}"


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


_TABLE_ROW = re.compile(r"^(\S.*?)(\s{2,})(\S.*)$")


def _is_rule_line(line: str) -> bool:
    return bool(line) and set(line) <= {"─", "-"}


def _style_help_block(text: str) -> str:
    righe = text.split("\n")
    stilizzate = []
    for indice, riga in enumerate(righe):
        prima = righe[indice - 1] if indice > 0 else ""
        dopo = righe[indice + 1] if indice + 1 < len(righe) else ""
        if not riga.strip():
            stilizzate.append(riga)
        elif _is_rule_line(riga):
            stilizzate.append(_c("-" * len(riga), _RULE_DIM))
        elif _is_rule_line(prima) and _is_rule_line(dopo):
            stilizzate.append(_c(riga, _TABLE))
        elif _is_rule_line(dopo) and not prima.strip():
            stilizzate.append(_c(riga.upper(), _TITLE))
        else:
            celle = _TABLE_ROW.match(riga)
            if celle is None:
                stilizzate.append(_c(riga, _TEXT))
            else:
                chiave, spazi, valore = celle.groups()
                stilizzate.append(f"{_c(chiave, _TEXT)}{spazi}{_c(valore, _TIME)}")
    return "\n".join(stilizzate)


def log_ready_banner(title: str, message: str, help_text: str, closing_lines) -> None:
    parti = ["", _centered_rule(title.upper()), _c(message, _TEXT)]
    if help_text:
        parti.append(_style_help_block(help_text))
    parti.append("")
    parti.extend(_c(riga, _TEXT) for riga in closing_lines)
    log_console_block("\n".join(parti))


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
