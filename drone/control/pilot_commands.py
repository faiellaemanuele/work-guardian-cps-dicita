from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from drone.hardware.joystick import get_command, read_events
from drone.ui.console import print_event

if TYPE_CHECKING:
    from drone.control.autopilot import AprilTagAutopilot
    from drone.hardware.tello_controller import RealTelloController

LOGGER = logging.getLogger(__name__)


class PilotCommands:
    def __init__(
        self,
        controller: RealTelloController,
        manual_speed_pct: int,
        detection_available: bool = True,
        autonomy_available: bool = False,
        autopilot: Optional[AprilTagAutopilot] = None,
    ):
        self.controller = controller

        self.manual_speed_pct = manual_speed_pct

        self.detection_available = detection_available
        self.autonomy_available = autonomy_available

        self.autopilot = autopilot

        self._detection_enabled = False

        self._autonomy_enabled = False

    def is_detection_enabled(self) -> bool:
        return self._detection_enabled

    def is_autonomy_enabled(self) -> bool:
        return self._autonomy_enabled

    def disable_autonomy(self):
        self._autonomy_enabled = False
        try:
            self.controller.send_rc_control(0, 0, 0, 0)
        except Exception:
            LOGGER.warning("Impossibile azzerare i comandi RC alla disattivazione dell'autonomia.", exc_info=True)

    def step(self) -> bool:
        actions = read_events()

        if actions["takeoff"]:
            try:
                if self.controller.takeoff():
                    print_event("Decollo eseguito")
                else:
                    print_event("Decollo non riuscito: controlla il drone", prefix="AVVISO")
            except Exception as exc:
                print_event(f"Errore durante il decollo: {exc}", prefix="ERRORE")

        if actions["land"]:
            self.disable_autonomy()
            try:
                if self.controller.land():
                    print_event("Atterraggio eseguito")
                else:
                    print_event("Atterraggio ignorato: il drone è a terra", prefix="AVVISO")
            except Exception as exc:
                print_event(f"Errore durante l'atterraggio: {exc}", prefix="ERRORE")

        if actions["detect"]:
            if not self.detection_available:
                print_event("Riconoscimento non disponibile", prefix="AVVISO")
            else:
                self._detection_enabled = not self._detection_enabled
                stato = "attivato" if self._detection_enabled else "disattivato"
                print_event(f"Riconoscimento {stato}")

        if actions["autonomy"]:
            if not self.autonomy_available:
                print_event("Volo autonomo non disponibile", prefix="AVVISO")
            elif not self.controller.is_flying:
                print_event("Decolla prima in manuale", prefix="AVVISO")
            else:
                self._autonomy_enabled = not self._autonomy_enabled
                if self._autonomy_enabled:
                    print_event("Volo autonomo attivato")
                else:
                    print_event("Volo autonomo disattivato")
                if self._autonomy_enabled:
                    if self.autopilot is not None:
                        if self.autopilot.finished:
                            self.autopilot.reset()
                        else:
                            self.autopilot.cancel_supervision_stop()
                else:
                    try:
                        self.controller.send_rc_control(0, 0, 0, 0)
                    except Exception:
                        LOGGER.warning("Impossibile azzerare i comandi RC dopo il cambio di stato dell'autonomia.", exc_info=True)

        if actions["quit"]:
            try:
                self.controller.send_rc_control(0, 0, 0, 0)
            except Exception:
                LOGGER.warning("Impossibile azzerare i comandi RC all'uscita.", exc_info=True)
            print_event("Uscita richiesta")
            return False

        return True

    def send_manual_command(self):
        command = get_command(self.manual_speed_pct)
        try:
            self.controller.send_rc_control(
                command["lr"],
                command["fb"],
                command["ud"],
                command["yaw"],
            )
        except Exception:
            LOGGER.warning("Errore durante l'invio dei comandi RC manuali.", exc_info=True)
        return command
