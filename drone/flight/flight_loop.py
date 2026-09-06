from __future__ import annotations

import logging
import sys
from typing import Optional

import pygame

from drone.config import APP_CONFIG
from drone.flight.guards import apply_battery_guard, apply_desync_guard
from drone.flight.steps import handle_autonomy_step, handle_dpi_step, handle_person_step
from drone.config.logging_setup import ensure_utf8_console, configure_logging
from drone.flight.postflight import run_postflight
from drone.flight.preflight import Subsystems, run_preflight
from drone.ui.console import (
    print_event,
    mark_runtime_started,
    reset_mission_state,
)
from drone.ui.video.window import enable_high_dpi_awareness, setup_video_window

LOGGER = logging.getLogger(__name__)


def main():
    enable_high_dpi_awareness()

    ensure_utf8_console()

    configure_logging()

    subsystems = Subsystems()
    original_stdout = sys.stdout

    try:
        if not run_preflight(subsystems, original_stdout):
            return

        pilot_commands = subsystems.pilot_commands
        vision_loop = subsystems.vision_loop
        controller = subsystems.controller
        dashboard = subsystems.dashboard
        apriltag_autopilot = subsystems.apriltag_autopilot
        safety_net_monitor = subsystems.safety_net_monitor
        person_monitor = subsystems.person_monitor
        dpi_monitor = subsystems.dpi_monitor
        flight_data_logger = subsystems.flight_data_logger
        comm_bridge = subsystems.comm_bridge
        screen = subsystems.screen
        clock = subsystems.clock

        ground_since: Optional[float] = None
        last_low_battery_warn_at = 0.0
        rth_active = False
        rth_operator_override = False

        setup_video_window(dashboard)

        pygame.display.iconify()

        mark_runtime_started()

        running = True
        while running:
            autonomy_before_step = pilot_commands.is_autonomy_enabled()
            running = pilot_commands.step()
            if not running:
                continue

            if rth_active and autonomy_before_step and not pilot_commands.is_autonomy_enabled():
                rth_active = False
                rth_operator_override = True
                print_event("Rientro alla home annullato", prefix="AVVISO")

            autopilot_forced_detection = (
                pilot_commands.is_autonomy_enabled()
                and vision_loop.autopilot_requests_detection()
            )

            running = vision_loop.step(
                controller,
                run_detection=(
                    pilot_commands.is_detection_enabled()
                    or autopilot_forced_detection
                ),
                autonomy_enabled=pilot_commands.is_autonomy_enabled(),
                dashboard=dashboard,
            )
            if not running:
                continue

            running, rth_active, last_low_battery_warn_at = apply_battery_guard(
                subsystems,
                rth_active=rth_active,
                rth_operator_override=rth_operator_override,
                last_low_battery_warn_at=last_low_battery_warn_at,
            )
            if not running:
                continue

            ground_since = apply_desync_guard(subsystems, ground_since)

            if pilot_commands.is_autonomy_enabled():
                running = handle_autonomy_step(
                    pilot_commands=pilot_commands,
                    apriltag_autopilot=apriltag_autopilot,
                    vision_loop=vision_loop,
                    dashboard=dashboard,
                    flight_data_logger=flight_data_logger,
                    controller=controller,
                    safety_net_monitor=safety_net_monitor,
                )
                if not running:
                    continue
            else:
                vision_loop.clear_autopilot_overlay()
                dashboard.clear_autopilot()
                reset_mission_state()
                manual_command = pilot_commands.send_manual_command()
                dashboard.set_manual_command(manual_command)
                if safety_net_monitor is not None:
                    safety_net_monitor.reset()

            handle_person_step(
                person_monitor=person_monitor,
                vision_loop=vision_loop,
                pilot_commands=pilot_commands,
            )

            handle_dpi_step(
                dpi_monitor=dpi_monitor,
                vision_loop=vision_loop,
                pilot_commands=pilot_commands,
            )

            if rth_active and controller.is_flying and not pilot_commands.is_autonomy_enabled():
                rth_completed = bool(
                    (vision_loop.last_autopilot_command or {}).get("finished", False)
                )
                print_event(
                    "Rientro completato: atterro alla home"
                    if rth_completed
                    else "Rientro interrotto: atterro sul posto",
                    prefix="AVVISO" if rth_completed else "ERRORE",
                )
                vision_loop.clear_autopilot_overlay()
                try:
                    controller.land()
                except Exception:
                    LOGGER.warning("Errore durante l'atterraggio dopo rientro interrotto.", exc_info=True)
                running = False
                continue

            if comm_bridge is not None:
                alarm = comm_bridge.pop_alarm()
                if alarm is not None:
                    level = str(alarm.get("level", "warning"))
                    print_event(
                        f"Allarme da {alarm.get('source', '?')}: {alarm.get('msg', '')}",
                        prefix="ERRORE" if level == "critical" else "AVVISO",
                    )
                comm_bridge.publish_state(
                    controller=controller,
                    vision_loop=vision_loop,
                    pilot_commands=pilot_commands,
                    autopilot=apriltag_autopilot,
                )

            if screen is not None:
                screen.fill((30, 30, 30))
                pygame.display.flip()

            if clock is not None:
                clock.tick(APP_CONFIG.loop_hz)

    except KeyboardInterrupt:
        print_event("Interruzione da tastiera (Ctrl+C)")
    except Exception as exc:
        print_event(f"Errore imprevisto: {exc}", prefix="ERRORE")
        raise
    finally:
        run_postflight(subsystems, original_stdout)
