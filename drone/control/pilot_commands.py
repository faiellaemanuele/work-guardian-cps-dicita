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

        self._scenario_requested = False

        self._landed_by_pilot = False

    def is_detection_enabled(self) -> bool:
        return self._detection_enabled

    def is_autonomy_enabled(self) -> bool:
        return self._autonomy_enabled

    def is_scenario_change_requested(self) -> bool:
        return self._scenario_requested

    def landed_by_pilot(self) -> bool:
        return self._landed_by_pilot

    def disable_autonomy(self):
        self._autonomy_enabled = False
        try:
            self.controller.send_rc_control(0, 0, 0, 0)
        except Exception:
            LOGGER.warning("Non è stato possibile azzerare i comandi di movimento alla disattivazione del volo autonomo", exc_info=True)

    def step(self) -> bool:
        actions = read_events()

        if actions["takeoff"]:
            if self.controller.is_flying:
                print_event("Il drone è già in volo", prefix="AVVISO")
            else:
                try:
                    if self.controller.takeoff():
                        self._landed_by_pilot = False
                        print_event("Decollo eseguito")
                    else:
                        print_event("Decollo non riuscito", prefix="ERRORE")
                except Exception:
                    print_event("Decollo non riuscito", prefix="ERRORE")
                    LOGGER.warning("Non è stato possibile far decollare il drone", exc_info=True)

        if actions["land"]:
            self.disable_autonomy()
            try:
                if self.controller.land():
                    self._landed_by_pilot = True
                    print_event("Atterraggio eseguito")
                else:
                    print_event("Il drone è già a terra", prefix="AVVISO")
            except Exception:
                print_event("Atterraggio non riuscito", prefix="ERRORE")
                LOGGER.warning("Non è stato possibile far atterrare il drone", exc_info=True)

        if actions["detect"]:
            if not self.detection_available:
                print_event("Riconoscimento non disponibile", prefix="AVVISO")
            else:
                self._detection_enabled = not self._detection_enabled
                stato = "attivato" if self._detection_enabled else "disattivato"
                print_event(f"Riconoscimento {stato}")

        if actions["autonomy"]:
            if not self.autonomy_available:
                print_event("Autopilota non disponibile", prefix="AVVISO")
            elif not self.controller.is_flying:
                print_event("Decolla prima in manuale", prefix="AVVISO")
            else:
                self._autonomy_enabled = not self._autonomy_enabled
                if self._autonomy_enabled:
                    print_event("Autopilota attivato")
                else:
                    print_event("Autopilota disattivato")
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
                        LOGGER.warning("Non è stato possibile azzerare i comandi di movimento al cambio di modalità di volo", exc_info=True)

        if actions["scenario"]:
            if self.controller.is_flying:
                print_event(
                    "Atterra prima del cambio scenario", prefix="AVVISO",
                )
            else:
                self._scenario_requested = True
                print_event("Si torna a scegliere lo scenario")
                return False

        if actions["quit"]:
            try:
                self.controller.send_rc_control(0, 0, 0, 0)
            except Exception:
                LOGGER.warning("Non è stato possibile azzerare i comandi di movimento all'uscita dal programma", exc_info=True)
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
            LOGGER.warning("Non è stato possibile inviare al drone i comandi del controller", exc_info=True)
        return command
