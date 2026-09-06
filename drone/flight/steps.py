from __future__ import annotations

import logging

from drone.config import APP_CONFIG
from drone.ui.console import print_event, log_waypoint_reached
from drone.ui.video.overlay import humanize_autopilot_reason

LOGGER = logging.getLogger(__name__)


def _waypoint_label(command, apriltag_autopilot) -> str:
    target_index = command.get("target_index")
    if target_index is None:
        return "--"
    home_index = getattr(apriltag_autopilot, "home_waypoint_index", None)
    if home_index is not None and int(target_index) == int(home_index):
        return "home"
    total = len(getattr(apriltag_autopilot, "waypoints", ()) or ())
    numero = int(target_index) + 1
    return f"{numero} di {total}" if total else str(numero)


def _emit_safety_net_verdict(verdict: dict) -> None:
    waypoint = verdict.get("waypoint")
    outcome = verdict.get("outcome")

    if outcome == "present":
        print_event(
            f"Rete presente al waypoint {waypoint}",
            prefix="RETE",
            channel="alert",
        )
    elif outcome == "missing":
        print_event(
            f"Rete mancante al waypoint {waypoint}",
            prefix="ALLERTA",
            channel="alert",
        )
    elif outcome == "no_tags":
        print_event(
            f"Rete non verificata al waypoint {waypoint}",
            prefix="RETE",
            channel="alert",
        )


def _emit_surveillance_alert(alert: dict) -> None:
    message = str(alert.get("message") or alert.get("title") or "Pericolo rilevato")
    print_event(message, prefix="AVVISO", channel="alert")


def handle_person_step(*, person_monitor, vision_loop, pilot_commands) -> None:
    if person_monitor is None:
        return
    command = vision_loop.last_autopilot_command or {}
    supervision_active = (
        pilot_commands.is_autonomy_enabled()
        and bool(command.get("supervision_stop_active", False))
    )
    alarms = person_monitor.update(
        detections_by_model=vision_loop.get_cached_detections_snapshot(),
        supervision_active=supervision_active,
    )
    for alarm in alarms:
        _emit_surveillance_alert(alarm)


def handle_dpi_step(*, dpi_monitor, vision_loop, pilot_commands) -> None:
    if dpi_monitor is None:
        return
    command = vision_loop.last_autopilot_command or {}
    supervision_active = (
        pilot_commands.is_autonomy_enabled()
        and bool(command.get("supervision_stop_active", False))
    )
    alarms = dpi_monitor.update(
        detections_by_model=vision_loop.get_cached_detections_snapshot(),
        supervision_active=supervision_active,
    )
    for alarm in alarms:
        _emit_surveillance_alert(alarm)


def handle_autonomy_step(
    *,
    pilot_commands,
    apriltag_autopilot,
    vision_loop,
    dashboard,
    flight_data_logger,
    controller,
    safety_net_monitor=None,
) -> bool:
    if apriltag_autopilot is None:
        print_event("Autopilota assente: autonomia disattivata", prefix="AVVISO")
        vision_loop.clear_autopilot_overlay()
        pilot_commands.disable_autonomy()
        return True

    pose_estimate = vision_loop.get_latest_pose_estimate()

    current_target = apriltag_autopilot.get_current_waypoint()
    autopilot_command = apriltag_autopilot.compute_command(pose_estimate)
    vision_loop.update_autopilot_overlay(autopilot_command)

    if safety_net_monitor is not None:
        safety_net_verdict = safety_net_monitor.update(
            target_index=autopilot_command.get("target_index"),
            supervision_stop_active=bool(autopilot_command.get("supervision_stop_active")),
            reason=str(autopilot_command.get("reason", "")),
            fault=bool(autopilot_command.get("fault", False)),
            visible_tag_ids=vision_loop.get_visible_tag_ids(),
            safety_net_detected=(
                safety_net_monitor.safety_net_model_name
                in vision_loop.get_detected_model_names()
            ),
        )
        if safety_net_verdict is not None:
            _emit_safety_net_verdict(safety_net_verdict)
            vision_loop.set_safety_net_verdict(safety_net_verdict)

    log_waypoint_reached(autopilot_command, _waypoint_label(autopilot_command, apriltag_autopilot))
    dashboard.set_autopilot(autopilot_command)
    rc_lr = autopilot_command.get("lr", 0)
    rc_fb = autopilot_command.get("fb", 0)
    rc_ud = autopilot_command.get("ud", 0)
    rc_yaw = autopilot_command.get("yaw", 0)

    if flight_data_logger is not None:
        flight_data_logger.log_autopilot_step(
            pose_estimate=pose_estimate,
            command=autopilot_command,
            target=current_target,
        )

    try:
        controller.send_rc_control(rc_lr, rc_fb, rc_ud, rc_yaw)
    except Exception:
        LOGGER.warning("Errore durante l'invio dei comandi RC dell'autopilota.", exc_info=True)

    if autopilot_command.get("fault", False):
        reason = str(autopilot_command.get("reason", "fault"))
        fault_details = {
            "waypoint_timeout": "il waypoint non è stato raggiunto entro il tempo massimo",
            "pose_timeout": "posizione persa troppo a lungo (marker AprilTag non visibili)",
        }
        detail = fault_details.get(reason, humanize_autopilot_reason(reason))
        print_event(f"Autopilota disattivato: {detail}", prefix="ERRORE")
        pilot_commands.disable_autonomy()

    elif autopilot_command.get("reason") == "supervision_stop_started":
        remaining = autopilot_command.get("supervision_stop_remaining_sec", 0.0)
        print_event(
            f"Waypoint {_waypoint_label(autopilot_command, apriltag_autopilot)}: "
            f"sosta di {float(remaining):.0f} s"
        )

    elif autopilot_command.get("reached", False):
        if autopilot_command.get("finished", False):
            print_event("Missione autonoma completata")
            pilot_commands.disable_autonomy()

            if APP_CONFIG.apriltag_autopilot.auto_land_on_finish:
                print_event("Atterraggio di fine missione")
                try:
                    controller.land()
                except Exception:
                    LOGGER.warning(
                        "Errore durante l'atterraggio automatico finale.",
                        exc_info=True,
                    )
                print_event("Chiusura: salvataggio dei dati")
                return False

    return True
