from __future__ import annotations

import logging
import os
import sys

from drone.config import APP_CONFIG
from drone.ui.console import (
    ConsoleLogFormatter,
    print_step,
    set_color_enabled,
)


def _resolve_log_level(default: int = logging.WARNING) -> int:
    level_name = str(APP_CONFIG.log_level).upper()
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level_name not in valid_levels:
        print_step(
            "!!",
            f"log_level '{APP_CONFIG.log_level}' non riconosciuto "
            f"(valori ammessi: {', '.join(sorted(valid_levels))}). Uso WARNING.",
        )
        return default
    return getattr(logging, level_name, default)


def ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _enable_ansi_colors() -> bool:
    stream = sys.stderr
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-12)
            mode = ctypes.c_uint()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            return False
    return True


def configure_logging():
    set_color_enabled(_enable_ansi_colors())

    log_level = _resolve_log_level()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ConsoleLogFormatter())
    logging.basicConfig(level=log_level, handlers=[console_handler], force=True)

    logging.getLogger("djitellopy").setLevel(logging.ERROR)
    logging.getLogger("djitellopy.tello").setLevel(logging.ERROR)
    logging.getLogger("ultralytics").setLevel(logging.ERROR)

    logging.getLogger("drone.phase").setLevel(logging.INFO)

    logging.getLogger("drone.setup").setLevel(logging.INFO)

    logging.getLogger("drone.event").setLevel(logging.INFO)
