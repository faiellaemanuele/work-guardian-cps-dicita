from __future__ import annotations

import logging
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
_TIME     = _rgb(200, 212, 222)
_TEXT     = _rgb(232, 238, 244)
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
    def format(self, record: logging.LogRecord) -> str:
        if getattr(record, "phase", False):
            return self._format_phase(record.getMessage())
        if getattr(record, "title", False):
            return self._format_title(record.getMessage())
        if getattr(record, "raw", False):
            return record.getMessage()
        ts = _c(time.strftime("%H:%M:%S", time.localtime(record.created)), _TIME)
        message = _c(record.getMessage(), _TEXT)
        setup_label = getattr(record, "setup_label", None)
        if setup_label is None and _runtime_started and record.levelno >= logging.WARNING:
            return f"{ts}  {message}"
        if setup_label is not None:
            glyph = _STEP_GLYPH.get(setup_label, "·")
        else:
            glyph = _LEVEL_GLYPH.get(record.levelno, "·")
        return f"{ts}  {_c(glyph, _GLYPH_COLOR.get(glyph, ''))}  {message}"

    @staticmethod
    def _format_phase(title: str) -> str:
        return f"\n{_rule(title.upper())}"

    @staticmethod
    def _format_title(title: str) -> str:
        left = " " * max(0, (_SEP_WIDTH - len(title)) // 2)
        return f"{left}{_c(title, _TITLE)}\n{_c(SEP_THIN, _RULE)}"


class RepeatedErrorFilter(logging.Filter):
    def __init__(
        self,
        repeat_after_sec: float,
        time_source: Callable[[], float] = time.monotonic,
    ):
        super().__init__()
        self._repeat_after_sec = float(repeat_after_sec)
        self._time_source = time_source
        self._last_shown_at: dict[tuple[str, str], float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING or getattr(record, "setup_label", None) is not None:
            return True
        key = (record.name, str(record.msg))
        now = self._time_source()
        last = self._last_shown_at.get(key)
        if last is not None and now - last < self._repeat_after_sec:
            return False
        self._last_shown_at[key] = now
        return True


_CLEAR_SCREEN = "\033[2J\033[3J\033[H"


class ConsoleHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        super().__init__(stream)
        self._startup_lines: list[str] = []
        self._keeping_startup = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            if self._keeping_startup:
                self._startup_lines.append(text)
            self.stream.write(text + self.terminator)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

    def end_startup(self) -> None:
        self._keeping_startup = False

    def redraw_startup(self) -> None:
        if not _COLOR:
            return
        self.acquire()
        try:
            self.stream.write(_CLEAR_SCREEN)
            for text in self._startup_lines:
                self.stream.write(text + self.terminator)
            self.flush()
        finally:
            self.release()


_console_handler: Optional[ConsoleHandler] = None


def install_console_handler(handler: ConsoleHandler) -> None:
    global _console_handler
    _console_handler = handler


def end_startup_transcript() -> None:
    if _console_handler is not None:
        _console_handler.end_startup()


def redraw_startup_transcript() -> None:
    if _console_handler is not None:
        _console_handler.redraw_startup()


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


def log_ready_banner(title: str, message: str) -> None:
    parti = ["", _centered_rule(title.upper()), _c(message, _TEXT)]
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
        print_event(f"Fine sosta al waypoint {label}", channel="drone")
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


def mark_runtime_stopped() -> None:
    global _runtime_started
    _runtime_started = False


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
