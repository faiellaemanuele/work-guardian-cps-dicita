from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2
import pygame

from drone.config import APP_CONFIG, BASE_DIR
from drone.hardware.joystick import close_joystick
from drone.flight.preflight import Subsystems
from drone.perception.vision_loop import stop_mqtt_client, take_biometric_logger
from drone.ui.console import log_phase, mark_runtime_stopped, print_step, set_alert_sink

LOGGER = logging.getLogger(__name__)


def _project_relative(path) -> str:
    try:
        return str(Path(path).resolve().relative_to(BASE_DIR))
    except (ValueError, OSError):
        return str(path)


def _landed_by_pilot(subsystems: Subsystems) -> bool:
    pilot_commands = subsystems.pilot_commands
    return pilot_commands is not None and pilot_commands.landed_by_pilot()


def _export_biometric_session(biometric_logger) -> None:
    try:
        session_dir = biometric_logger.export_session(
            APP_CONFIG.biometric_sessions_dir, app_config=APP_CONFIG
        )
        if session_dir is not None:
            print_step(
                "OK",
                "La sessione biometrica è stata salvata nella cartella "
                f"{_project_relative(session_dir)}",
            )
        else:
            print_step(
                "!!",
                "Non è stato possibile creare la cartella della sessione biometrica: "
                "i dati dell'orologio non sono stati salvati",
            )
        for riga in biometric_logger.get_summary().splitlines():
            print_step("--", riga)
    except Exception:
        LOGGER.exception("Non è stato possibile salvare i dati dell'orologio")


def _export_flight_session(subsystems: Subsystems) -> None:
    flight_data_logger = subsystems.flight_data_logger
    if flight_data_logger is None:
        return

    if _landed_by_pilot(subsystems):
        print_step(
            "--",
            "Il pilota ha fatto atterrare il drone con il controller: i dati del volo "
            "non vengono salvati",
        )
        return

    try:
        if flight_data_logger.has_data():
            session_dir = flight_data_logger.export_session(
                output_root=APP_CONFIG.flight_sessions_dir,
                app_config=APP_CONFIG,
                path_name=subsystems.scenario_name,
            )

            if session_dir is not None:
                print_step(
                    "OK",
                    "La sessione di volo è stata salvata nella cartella "
                    f"{_project_relative(session_dir)}",
                )
            else:
                print_step(
                    "!!",
                    "Non è stato possibile creare la cartella della sessione: "
                    "i dati del volo non sono stati salvati",
                )

            for riga in flight_data_logger.get_summary().splitlines():
                print_step("--", riga)
        else:
            print_step(
                "--",
                "Non è stata registrata alcuna posizione: nessun file è stato salvato",
            )
    except Exception:
        LOGGER.exception("Non è stato possibile salvare i dati del volo")


def release_mission(subsystems: Subsystems) -> None:
    controller = subsystems.controller
    if controller is not None:
        try:
            controller.send_rc_control(0, 0, 0, 0)
        except Exception:
            pass

    # Il logger sta per essere sostituito da quello del nuovo scenario: i dati
    # di questo volo si salvano adesso, con le stesse regole della chiusura.
    flight_data_logger = subsystems.flight_data_logger
    if flight_data_logger is not None and flight_data_logger.has_data():
        log_phase("Chiusura dello scenario")
        _export_flight_session(subsystems)

    vision_loop = subsystems.vision_loop
    if vision_loop is not None:
        try:
            vision_loop.stop()
        except Exception:
            LOGGER.warning("Il riconoscimento degli oggetti non è stato fermato correttamente", exc_info=True)

    try:
        cv2.destroyAllWindows()
    except cv2.error:
        pass

    subsystems.vision_loop = None
    subsystems.pilot_commands = None
    subsystems.flight_data_logger = None
    subsystems.apriltag_autopilot = None
    subsystems.safety_net_monitor = None
    subsystems.person_monitor = None
    subsystems.dpi_monitor = None
    subsystems.scenario_name = None
    subsystems.scenario_change = True
    mark_runtime_stopped()


def run_postflight(subsystems: Subsystems, original_stdout) -> None:
    sys.stdout = original_stdout
    set_alert_sink(None)

    controller = subsystems.controller
    vision_loop = subsystems.vision_loop
    flight_data_logger = subsystems.flight_data_logger
    dashboard = subsystems.dashboard

    if controller is not None:
        try:
            controller.send_rc_control(0, 0, 0, 0)
        except Exception:
            pass

        try:
            if getattr(controller, "is_flying", False):
                controller.land()
        except Exception:
            LOGGER.warning("L'atterraggio di sicurezza alla chiusura non è riuscito", exc_info=True)

    if vision_loop is not None:
        try:
            vision_loop.stop()
        except Exception:
            LOGGER.warning("Il riconoscimento degli oggetti non è stato fermato correttamente", exc_info=True)

    stop_mqtt_client()
    biometric_logger = take_biometric_logger()

    if controller is not None:
        try:
            controller.end()
        except Exception:
            pass

    has_biometric_data = biometric_logger is not None and biometric_logger.has_data()
    if flight_data_logger is not None or has_biometric_data:
        log_phase("Chiusura della sessione")

    _export_flight_session(subsystems)

    # I dati dell'orologio riguardano la salute dell'operatore, non il volo: si
    # salvano anche quando il pilota scarta i dati del volo atterrando a mano.
    if has_biometric_data:
        _export_biometric_session(biometric_logger)

    if dashboard is not None:
        try:
            dashboard.close()
        except Exception:
            LOGGER.warning("Il cruscotto non è stato chiuso correttamente", exc_info=True)
    cv2.destroyAllWindows()
    close_joystick()
    pygame.quit()
