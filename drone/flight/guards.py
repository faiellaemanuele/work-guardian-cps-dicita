from __future__ import annotations

import logging
import time
from typing import Optional

from drone.config import APP_CONFIG
from drone.control.safety_rules import battery_guard_action, desync_ground_update
from drone.flight.preflight import Subsystems
from drone.ui.console import print_event

LOGGER = logging.getLogger(__name__)


def apply_battery_guard(
    subsystems: Subsystems,
    *,
    rth_active: bool,
    rth_operator_override: bool,
    last_low_battery_warn_at: float,
) -> tuple[bool, bool, float]:
    controller = subsystems.controller
    pilot_commands = subsystems.pilot_commands
    vision_loop = subsystems.vision_loop

    battery = vision_loop.cached_status.get("battery")
    battery_action = battery_guard_action(
        battery,
        controller.is_flying,
        APP_CONFIG.battery_critical_pct,
        APP_CONFIG.battery_warning_pct,
        APP_CONFIG.battery_rth_pct,
    )
    if battery_action == "critical":
        print_event(
            f"Batteria al {battery}%: atterro per sicurezza",
            prefix="ERRORE",
        )
        if pilot_commands.is_autonomy_enabled():
            vision_loop.clear_autopilot_overlay()
            pilot_commands.disable_autonomy()
        try:
            controller.land()
        except Exception:
            LOGGER.warning("Errore durante l'atterraggio per batteria critica.", exc_info=True)
        return False, rth_active, last_low_battery_warn_at

    def _warn_low_battery(last_at: float) -> float:
        now_warn = time.monotonic()
        if now_warn - last_at >= 15.0:
            print_event(f"Batteria al {battery}%: conviene atterrare", prefix="AVVISO")
            return now_warn
        return last_at

    if battery_action == "return_home":
        if (
            pilot_commands.is_autonomy_enabled()
            and not rth_active
            and not rth_operator_override
        ):
            rth_prerequisites_ok = (
                subsystems.apriltag_autopilot is not None
                and subsystems.pose_estimator is not None
                and subsystems.apriltag_autopilot.home_waypoint_index is not None
            )
            can_return_home = False
            if rth_prerequisites_ok:
                can_return_home = subsystems.apriltag_autopilot.engage_return_home()
            if can_return_home:
                rth_active = True
                print_event(
                    f"Batteria bassa ({battery}%): rientro automatico alla home "
                    "per l'atterraggio",
                    prefix="AVVISO",
                )
                return True, rth_active, last_low_battery_warn_at
            print_event(
                f"Batteria bassa ({battery}%): rientro alla home non disponibile, "
                "atterraggio di sicurezza sul posto",
                prefix="ERRORE",
            )
            vision_loop.clear_autopilot_overlay()
            pilot_commands.disable_autonomy()
            try:
                controller.land()
            except Exception:
                LOGGER.warning("Errore durante l'atterraggio per batteria bassa.", exc_info=True)
            return False, rth_active, last_low_battery_warn_at
        if not rth_active:
            last_low_battery_warn_at = _warn_low_battery(last_low_battery_warn_at)
    elif battery_action == "warning":
        last_low_battery_warn_at = _warn_low_battery(last_low_battery_warn_at)

    return True, rth_active, last_low_battery_warn_at


def apply_desync_guard(subsystems: Subsystems, ground_since: Optional[float]) -> Optional[float]:
    controller = subsystems.controller
    pilot_commands = subsystems.pilot_commands
    vision_loop = subsystems.vision_loop

    height_cm = controller.get_height_cm() if controller.is_flying else None
    ground_since, landed_confirmed = desync_ground_update(
        controller.is_flying,
        height_cm,
        ground_since,
        time.monotonic(),
        APP_CONFIG.ground_height_max_cm,
        APP_CONFIG.ground_confirm_after_sec,
    )
    if landed_confirmed:
        print_event(
            "Drone rilevato a terra mentre risultava in volo: "
            "autonomia disattivata e stato riallineato",
            prefix="AVVISO",
        )
        if pilot_commands.is_autonomy_enabled():
            vision_loop.clear_autopilot_overlay()
            pilot_commands.disable_autonomy()
        controller.notify_landed_externally()
    return ground_since
