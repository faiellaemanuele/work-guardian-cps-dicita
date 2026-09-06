from __future__ import annotations

import logging
import sys

import cv2
import pygame

from drone.config import APP_CONFIG
from drone.hardware.joystick import close_joystick
from drone.flight.preflight import Subsystems
from drone.ui.console import SEP_THIN, print_event, set_alert_sink

LOGGER = logging.getLogger(__name__)


def run_postflight(subsystems: Subsystems, original_stdout) -> None:
    sys.stdout = original_stdout
    set_alert_sink(None)

    controller = subsystems.controller
    vision_loop = subsystems.vision_loop
    flight_data_logger = subsystems.flight_data_logger
    dashboard = subsystems.dashboard
    comm_bridge = subsystems.comm_bridge

    if controller is not None:
        try:
            controller.send_rc_control(0, 0, 0, 0)
        except Exception:
            pass

        try:
            if getattr(controller, "is_flying", False):
                controller.land()
        except Exception:
            LOGGER.warning("Atterraggio di sicurezza non riuscito durante la chiusura.", exc_info=True)

    if comm_bridge is not None:
        try:
            comm_bridge.stop()
        except Exception:
            LOGGER.warning("Errore durante la chiusura del canale di comunicazione.", exc_info=True)

    if vision_loop is not None:
        try:
            vision_loop.stop()
        except Exception:
            LOGGER.warning("Errore durante l'arresto del thread di riconoscimento.", exc_info=True)

    if controller is not None:
        try:
            controller.end()
        except Exception:
            pass

    if flight_data_logger is not None:
        try:
            if flight_data_logger.has_data():
                session_dir = flight_data_logger.export_session(
                    output_root=APP_CONFIG.flight_sessions_dir,
                    app_config=APP_CONFIG,
                    path_name=subsystems.scenario_name,
                )

                if session_dir is not None:
                    print(f"\n{SEP_THIN}")
                    print("La sessione di volo è stata salvata in:")
                    print(session_dir)
                    print(SEP_THIN)
                else:
                    print_event(
                        "Non è stato possibile creare la cartella della sessione",
                        prefix="ERRORE",
                    )

                print(flight_data_logger.get_summary())
            else:
                print_event(
                    "Nessuna posizione valida registrata: non è stato generato alcun file"
                )
        except Exception:
            LOGGER.exception("Errore durante il salvataggio finale dei dati di volo.")

    if dashboard is not None:
        try:
            dashboard.close()
        except Exception:
            LOGGER.warning("Errore durante la chiusura del cruscotto.", exc_info=True)
    cv2.destroyAllWindows()
    close_joystick()
    pygame.quit()
