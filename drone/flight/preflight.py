from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Optional

import pygame

from drone.config import APP_CONFIG
from drone.control.autopilot import AprilTagAutopilot
from drone.control.pilot_commands import PilotCommands
from drone.surveillance.dpi_monitor import DpiMonitor, dpi_item_names
from drone.surveillance.person_monitor import PersonMonitor
from drone.surveillance.safety_net_monitor import SafetyNetMonitor
from drone.perception.vision_loop import VisionLoop
from drone.data.flight_data_logger import FlightDataLogger
from drone.loaders.waypoint_path_loader import (
    load_waypoint_paths,
    required_model_names,
)
from drone.flight.subsystem_builders import (
    create_apriltag_autopilot,
    create_controller,
    create_detectors,
    create_flight_data_logger,
    create_pose_estimator,
    create_pose_filter,
)
from drone.hardware.joystick import (
    format_joystick_help,
    init_joystick,
    is_joystick_connected,
)
from drone.hardware.tello_controller import RealTelloController
from drone.perception.pose_estimator import CameraPoseEstimator
from drone.ui.video.dashboard import Dashboard
from drone.ui.console import (
    SEP_THIN,
    print_event,
    log_console_block,
    log_phase,
    print_step,
    set_alert_sink,
)
from drone.ui.setup.effects import fade_screen
from drone.ui.setup.screens import GO_BACK, select_waypoint_path_interactive
from drone.ui.setup.welcome import show_welcome_screen


@dataclass
class Subsystems:
    screen: Any = None
    clock: Any = None
    controller: Optional[RealTelloController] = None
    flight_data_logger: Optional[FlightDataLogger] = None
    apriltag_autopilot: Optional[AprilTagAutopilot] = None
    pose_estimator: Optional[CameraPoseEstimator] = None
    vision_loop: Optional[VisionLoop] = None
    pilot_commands: Optional[PilotCommands] = None
    safety_net_monitor: Optional[SafetyNetMonitor] = None
    person_monitor: Optional[PersonMonitor] = None
    dpi_monitor: Optional[DpiMonitor] = None
    dashboard: Optional[Dashboard] = None
    scenario_name: Optional[str] = None


def _announce_phase(title: str) -> None:
    log_phase(title)


def _elenco_italiano(voci) -> str:
    voci = [str(v) for v in voci]
    if len(voci) <= 1:
        return "".join(voci)
    return f"{', '.join(voci[:-1])} e {voci[-1]}"


def _model_labels(names) -> list[str]:
    by_name = {m.name: (getattr(m, "label", None) or m.name) for m in APP_CONFIG.yolo_models}
    return [by_name.get(n, n) for n in names]


def _model_label(name: str) -> str:
    return _model_labels([name])[0]


def _scenario_or_config(value, default):
    return default if value is None else value


def _start_dashboard(subsystems: Subsystems, original_stdout) -> Dashboard:
    subsystems.dashboard = Dashboard(
        APP_CONFIG.dashboard,
        render_interval_sec=APP_CONFIG.dashboard_render_interval_sec,
    )
    dashboard = subsystems.dashboard
    if dashboard.enabled:
        sys.stdout = dashboard.make_stdout_redirect(original_stdout)
        set_alert_sink(dashboard.log_alert)
    return dashboard


def _phase_manual_control(subsystems: Subsystems):
    _announce_phase("Fase 1 · Pilotaggio manuale")
    screen = init_joystick()
    if is_joystick_connected():
        print_step("OK", "Il drone si pilota con il controller PS4")
    else:
        print_step("--", "Nessun controller collegato: attendo che ne venga inserito uno")
    subsystems.clock = pygame.time.Clock()
    return screen


def _phase_welcome(screen) -> bool:
    if not show_welcome_screen(screen):
        print_step("--", "Uscita dalla schermata iniziale: il programma si chiude")
        return False
    fade_screen(screen, screen.copy(), fade_in=False)
    return True


def _report_missing_waypoint_paths() -> None:
    try:
        json_files = list(APP_CONFIG.waypoint_paths_dir.glob("*.json"))
    except OSError:
        json_files = []
    if json_files:
        print_event(
            f"Tutti i {len(json_files)} file di percorso in "
            f"{APP_CONFIG.waypoint_paths_dir} sono malformati o privi di "
            "waypoint validi (vedi avvisi sopra): autonomia non disponibile.",
            prefix="ERRORE",
        )
    else:
        print_event(
            f"Nessun file di percorso .json in {APP_CONFIG.waypoint_paths_dir}: "
            "autonomia non disponibile (i waypoint provengono solo dai "
            "percorsi .json).",
            prefix="ERRORE",
        )


def _phase_mission_path(screen):
    _announce_phase("Fase 4 · Scenario della missione")
    waypoint_paths = load_waypoint_paths(APP_CONFIG.waypoint_paths_dir)
    if not waypoint_paths:
        _report_missing_waypoint_paths()
        return True, None, screen

    modelli = [_model_labels(required_model_names(p)) for p in waypoint_paths]
    while True:
        pygame.display.set_caption("Tello - Scelta dello scenario")
        selected_path = select_waypoint_path_interactive(screen, waypoint_paths, modelli)
        pygame.display.set_caption(APP_CONFIG.window_title)
        screen = pygame.display.get_surface()

        if selected_path is not GO_BACK:
            break

        if not _phase_welcome(screen):
            return False, None, pygame.display.get_surface()
        screen = pygame.display.get_surface()

    if selected_path is None:
        print_step("--", "Scelta annullata, chiusura")
        return False, None, screen

    soste = ""
    if selected_path.supervision_waypoints:
        elenco = _elenco_italiano(
            [str(i) for i in selected_path.supervision_waypoints]
        )
        quantificatore = (
            "ai punti" if len(selected_path.supervision_waypoints) > 1 else "al punto"
        )
        soste = f", con sosta {quantificatore} {elenco}"
    print_step(
        "OK",
        f"Rotta «{selected_path.name}»: "
        f"{len(selected_path.waypoints)} waypoint{soste}",
    )
    return True, selected_path, screen


def _phase_connect(subsystems: Subsystems):
    _announce_phase("Fase 2 · Collegamento al drone")

    try:
        subsystems.controller = create_controller()
    except Exception as exc:
        print_step("!!", f"Non riesco a preparare il collegamento al drone: {exc}")
        return None

    controller = subsystems.controller

    try:
        controller.connect()
    except Exception as exc:
        print_step(
            "!!",
            f"Drone non raggiungibile ({exc}). Controlla che sia acceso e che il "
            "computer sia collegato alla sua rete Wi-Fi.",
        )
        return None
    print_step("OK", "Drone Tello EDU collegato")

    try:
        controller.start_video_stream()
    except Exception as exc:
        print_step("!!", f"Flusso video della camera non avviato: {exc}")
        return None
    print_step("OK", "Flusso video della camera avviato")
    return controller


def _build_detectors(model_names) -> list:
    model_names = list(model_names)
    if not model_names:
        print_step("--", "Questo scenario non chiede nessun modello di riconoscimento")
        return []
    try:
        detectors = create_detectors(model_names)
    except Exception as exc:
        print_step("!!", f"Non sono riuscito a caricare i modelli: {exc}")
        return []
    if not detectors:
        print_step("!!", "Nessuno dei modelli dello scenario è stato caricato")
        return []
    caricati = ", ".join(_model_labels([d["name"] for d in detectors])).lower()
    print_step("OK", f"Riconosce nel video: {caricati}")
    return detectors


def _phase_localization(subsystems: Subsystems) -> None:
    _announce_phase("Fase 3 · Localizzazione e canale")
    pose_estimator = None
    try:
        pose_estimator = create_pose_estimator()
        if pose_estimator is not None:
            print_step("OK", "Ricava la propria posizione dai marker AprilTag del cantiere")
        else:
            print_step("--", "Non ricava la propria posizione: la localizzazione è disattivata")
    except Exception as exc:
        print_step("!!", f"Non ricava la propria posizione dai marker AprilTag: {exc}")
    subsystems.pose_estimator = pose_estimator


def _build_pose_filter(subsystems: Subsystems):
    if subsystems.pose_estimator is None:
        return None
    try:
        pose_filter = create_pose_filter()
        print_step("OK", "Stabilizza la posizione stimata con il filtro di Kalman")
        return pose_filter
    except Exception as exc:
        print_step("!!", f"Non stabilizza la posizione stimata: {exc}")
        return None


def _create_autopilot_for(path) -> Optional[AprilTagAutopilot]:
    if path is None:
        return create_apriltag_autopilot(None, None, None, None)
    return create_apriltag_autopilot(
        path.waypoints,
        path.supervision_waypoints,
        path.supervision_stop_sec,
        path.home_waypoint,
    )


def _configure_mission_display(dashboard, *, scenario_name, apriltag_autopilot) -> None:
    dashboard.set_scenario_name(scenario_name)
    if apriltag_autopilot is None:
        return
    dashboard.configure_mission(
        apriltag_autopilot.waypoints,
        home_index=apriltag_autopilot.home_waypoint_index,
        yaw_offset_deg=APP_CONFIG.apriltag_autopilot.yaw_offset_deg,
        site_area=APP_CONFIG.site_area_vertices_m,
        restricted_areas=APP_CONFIG.restricted_areas_vertices_m,
        world_tags=APP_CONFIG.camera_pose.world_tags,
    )


def _report_autonomy(*, apriltag_autopilot, pose_estimator, waypoints) -> None:
    if apriltag_autopilot is not None and pose_estimator is not None:
        print_step("OK", "Vola da solo lungo il percorso quando attivi l'autonomia")
    elif apriltag_autopilot is not None:
        print_step("!!", "Non può volare da solo: manca la localizzazione")
    elif not waypoints:
        pass
    elif not APP_CONFIG.apriltag_autopilot.enabled:
        print_step("--", "Non volerà da solo: il volo autonomo è disattivato nella configurazione")
    else:
        print_step("!!", "Non può volare da solo: il percorso scelto non è valido")


def _build_flight_logger(subsystems: Subsystems) -> None:
    subsystems.flight_data_logger = create_flight_data_logger()
    print_step("OK", "Registra i dati del volo per l'analisi a terra")


def _build_autopilot(
    subsystems: Subsystems,
    *,
    path,
    pose_estimator,
    dashboard,
) -> Optional[AprilTagAutopilot]:
    apriltag_autopilot = _create_autopilot_for(path)
    scenario_name = path.name if path is not None else None

    subsystems.apriltag_autopilot = apriltag_autopilot
    subsystems.scenario_name = scenario_name

    _configure_mission_display(
        dashboard,
        scenario_name=scenario_name,
        apriltag_autopilot=apriltag_autopilot,
    )
    _report_autonomy(
        apriltag_autopilot=apriltag_autopilot,
        pose_estimator=pose_estimator,
        waypoints=path.waypoints if path is not None else None,
    )
    return apriltag_autopilot


def _build_safety_net_monitor(
    *,
    loaded_model_names,
    path,
) -> Optional[SafetyNetMonitor]:
    safety_net_tags_by_stop = path.safety_net_tags_by_stop if path is not None else None
    if not safety_net_tags_by_stop:
        return None

    safety_net_model_name = APP_CONFIG.safety_net_model_name
    if safety_net_model_name not in loaded_model_names:
        print_step(
            "!!",
            "Non controllerà le reti di sicurezza: manca il modello "
            f"{_model_label(safety_net_model_name)}",
        )
        return None

    monitor = SafetyNetMonitor(
        waypoint_tag_map=safety_net_tags_by_stop,
        safety_net_model_name=safety_net_model_name,
        safety_net_confirm_sec=(path.safety_net_confirm_sec or 0.0),
    )
    print_step("OK", "Controlla la presenza delle reti di sicurezza durante le soste")
    return monitor


def _report_person_watch(*, loaded_model_names, restricted_area_tolerance_px) -> None:
    restricted_area_model_name = APP_CONFIG.restricted_area_model_name
    if restricted_area_model_name not in loaded_model_names:
        print_step(
            "OK",
            "Sorveglia le cadute delle persone; per le aree vietate manca il "
            f"modello {_model_label(restricted_area_model_name)}",
        )
    elif restricted_area_tolerance_px is None:
        print_step(
            "OK",
            "Sorveglia le cadute delle persone; questo percorso non prevede "
            "le aree vietate",
        )
    else:
        print_step(
            "OK",
            "Sorveglia le cadute delle persone e il superamento delle aree vietate",
        )


def _build_person_monitor(
    *,
    loaded_model_names,
    path,
) -> Optional[PersonMonitor]:
    fall_model_name = APP_CONFIG.person_fall_model_name
    if fall_model_name not in loaded_model_names:
        return None

    restricted_area_tolerance_px = path.restricted_area_tolerance_px if path is not None else None
    fall_sec = path.fall_alarm_after_sec if path is not None else None
    restricted_sec = path.restricted_area_alarm_after_sec if path is not None else None

    monitor = PersonMonitor(
        fall_model_name=fall_model_name,
        person_model_name=fall_model_name,
        restricted_area_model_name=APP_CONFIG.restricted_area_model_name,
        person_label=APP_CONFIG.person_class_label,
        fall_label=APP_CONFIG.fall_class_label,
        restricted_area_tolerance_px=restricted_area_tolerance_px,
        restricted_area_alarm_after_sec=_scenario_or_config(
            restricted_sec, APP_CONFIG.restricted_area_alarm_after_sec
        ),
        fall_alarm_after_sec=_scenario_or_config(
            fall_sec, APP_CONFIG.fall_alarm_after_sec
        ),
        clear_after_sec=APP_CONFIG.alarm_clear_after_sec,
    )
    _report_person_watch(
        loaded_model_names=loaded_model_names,
        restricted_area_tolerance_px=restricted_area_tolerance_px,
    )
    return monitor


def _build_dpi_monitor(
    *,
    loaded_model_names,
    path,
) -> Optional[DpiMonitor]:
    required_items = path.dpi_required if path is not None else None
    if not required_items:
        return None

    dpi_model_name = APP_CONFIG.dpi_model_name
    if dpi_model_name not in loaded_model_names:
        print_step(
            "!!",
            "Non verificherà i dispositivi di protezione: manca il modello "
            f"{_model_label(dpi_model_name)}",
        )
        return None

    monitor = DpiMonitor(
        dpi_model_name=dpi_model_name,
        required_items=required_items,
        alarm_after_sec=(path.dpi_alarm_after_sec or 0.0),
        clear_after_sec=APP_CONFIG.alarm_clear_after_sec,
    )
    unknown_items = [
        key for key in required_items
        if key not in monitor.required_items
    ]

    if not monitor.required_items:
        print_step(
            "!!",
            "Non verificherà i dispositivi di protezione: nel percorso non "
            f"ne riconosco nessuno ({', '.join(unknown_items)}). "
            f"Sono previsti: {', '.join(dpi_item_names())}.",
        )
        return None

    active_items = ", ".join(dpi_item_names(monitor.required_items))
    print_step("OK", f"Verifica i dispositivi di protezione: {active_items}")
    if unknown_items:
        print_step(
            "!!",
            "Non riconosco questi dispositivi nel percorso e li ignoro: "
            f"{', '.join(unknown_items)}",
        )
    return monitor


def _build_monitors(subsystems: Subsystems, *, detectors, path) -> None:
    loaded_model_names = {item["name"] for item in detectors}

    subsystems.safety_net_monitor = _build_safety_net_monitor(
        loaded_model_names=loaded_model_names,
        path=path,
    )
    subsystems.person_monitor = _build_person_monitor(
        loaded_model_names=loaded_model_names,
        path=path,
    )
    subsystems.dpi_monitor = _build_dpi_monitor(
        loaded_model_names=loaded_model_names,
        path=path,
    )


def _build_loops(
    subsystems: Subsystems,
    *,
    controller,
    detectors,
    pose_estimator,
    pose_filter,
    apriltag_autopilot,
) -> None:
    subsystems.pilot_commands = PilotCommands(
        controller=controller,
        manual_speed_pct=APP_CONFIG.manual_speed_pct,
        detection_available=len(detectors) > 0,
        autonomy_available=apriltag_autopilot is not None and pose_estimator is not None,
        autopilot=apriltag_autopilot,
    )

    subsystems.vision_loop = VisionLoop(
        config=APP_CONFIG,
        detectors=detectors,
        pose_estimator=pose_estimator,
        flight_data_logger=subsystems.flight_data_logger,
        pose_filter=pose_filter,
    )


def _phase_onboard(subsystems: Subsystems, *, path) -> None:
    _announce_phase("Fase 5 · Funzioni di bordo")

    detectors = _build_detectors(
        required_model_names(path) if path is not None else ()
    )
    pose_filter = _build_pose_filter(subsystems)
    _build_flight_logger(subsystems)

    apriltag_autopilot = _build_autopilot(
        subsystems,
        path=path,
        pose_estimator=subsystems.pose_estimator,
        dashboard=subsystems.dashboard,
    )

    _build_monitors(subsystems, detectors=detectors, path=path)

    _build_loops(
        subsystems,
        controller=subsystems.controller,
        detectors=detectors,
        pose_estimator=subsystems.pose_estimator,
        pose_filter=pose_filter,
        apriltag_autopilot=apriltag_autopilot,
    )


def _announce_ready(dashboard) -> None:
    dashboard.clear_terminal()
    dashboard.clear_alerts()

    ready_banner = (
        f"\n{SEP_THIN}\n"
        "Tutto pronto. Il drone è a terra e risponde al controller: "
        "puoi decollare quando vuoi.\n"
        f"{format_joystick_help()}\n"
        "\nDa qui in avanti il volo si segue nella finestra del drone.\n"
        "Su questa console restano soltanto gli errori, se ce ne saranno."
    )
    log_console_block(ready_banner)


def run_startup(subsystems: Subsystems, original_stdout) -> bool:
    _start_dashboard(subsystems, original_stdout)

    screen = _phase_manual_control(subsystems)

    if not _phase_welcome(screen):
        return False

    if _phase_connect(subsystems) is None:
        return False

    _phase_localization(subsystems)

    subsystems.screen = pygame.display.get_surface()
    return True


def arm_mission(subsystems: Subsystems) -> bool:
    scelto, selected_path, screen = _phase_mission_path(subsystems.screen)
    subsystems.screen = screen
    if not scelto:
        return False

    _phase_onboard(subsystems, path=selected_path)

    _announce_ready(subsystems.dashboard)
    return True
