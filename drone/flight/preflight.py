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
from drone.hardware.joystick import init_joystick, is_joystick_connected
from drone.hardware.tello_controller import RealTelloController
from drone.perception.pose_estimator import CameraPoseEstimator
from drone.ui.video.dashboard import Dashboard
from drone.ui.console import (
    end_startup_transcript,
    print_event,
    log_phase,
    redraw_startup_transcript,
    log_ready_banner,
    log_title,
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
    scenario_change: bool = False


def _announce_phase(title: str) -> None:
    log_phase(title)


_NUMERI_IN_LETTERE = {2: "due", 3: "tre", 4: "quattro", 5: "cinque", 6: "sei"}


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
    _announce_phase("Fase 1 · Controller di pilotaggio")
    screen = init_joystick()
    if is_joystick_connected():
        print_step("OK", "Il controller PS4 è collegato e pronto all'uso")
    else:
        print_step(
            "--",
            "Nessun controller PS4 rilevato: verrà riconosciuto automaticamente "
            "non appena sarà collegato",
        )
    subsystems.clock = pygame.time.Clock()
    return screen


def _phase_welcome(screen) -> bool:
    if not show_welcome_screen(screen):
        print_step("--", "Uscita dalla schermata di presentazione: il programma si chiude")
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
            f"Nessuno dei {len(json_files)} percorsi presenti in "
            f"{APP_CONFIG.waypoint_paths_dir} è valido: il volo autonomo non è "
            "disponibile (i motivi sono indicati negli avvisi precedenti)",
            prefix="ERRORE",
        )
    else:
        print_event(
            f"La cartella {APP_CONFIG.waypoint_paths_dir} non contiene alcun percorso "
            ".json: il volo autonomo non è disponibile",
            prefix="ERRORE",
        )


def _phase_mission_path(screen, *, ritorno=False):
    _announce_phase("Fase 4 · Scenario della missione")
    if ritorno:
        print_step(
            "--",
            "Il pilota è tornato alla scelta dello scenario con il tasto "
            f"{APP_CONFIG.joystick.label_scenario}",
        )
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
        print_step("--", "La scelta dello scenario è stata annullata: il programma si chiude")
        return False, None, screen

    print_step("OK", f"Scenario scelto: {selected_path.name}")
    soste = selected_path.supervision_waypoints
    if not soste:
        dettaglio = "senza soste di supervisione"
    elif len(soste) == 1:
        dettaglio = f"con una sosta di supervisione al waypoint {soste[0]}"
    else:
        dettaglio = f"con soste di supervisione ai waypoint {_elenco_italiano(soste)}"
    print_step(
        "--",
        f"Il percorso prevede {len(selected_path.waypoints)} waypoint, {dettaglio}",
    )
    return True, selected_path, screen


def _phase_connect(subsystems: Subsystems):
    _announce_phase("Fase 2 · Collegamento al drone")

    try:
        subsystems.controller = create_controller()
    except Exception as exc:
        print_step("!!", f"Non è stato possibile inizializzare il collegamento al drone: {exc}")
        return None

    controller = subsystems.controller

    try:
        controller.connect()
    except Exception as exc:
        print_step(
            "!!",
            "Il drone non è raggiungibile: verifica che sia acceso e che il computer "
            f"sia connesso alla sua rete Wi-Fi ({exc})",
        )
        return None
    print_step("OK", "Il drone Tello EDU è collegato al computer")

    try:
        controller.start_video_stream()
    except Exception as exc:
        print_step("!!", f"Non è stato possibile avviare il video della camera: {exc}")
        return None
    print_step("OK", "Le immagini della camera arrivano correttamente")
    return controller


def _build_detectors(model_names) -> list:
    model_names = list(model_names)
    if not model_names:
        print_step("--", "Questo scenario non richiede alcun modello di riconoscimento")
        return []
    quali = "del modello" if len(model_names) == 1 else "dei modelli"
    print_step(
        "--",
        f"Caricamento {quali} di riconoscimento in corso: potrebbe richiedere qualche secondo",
    )
    try:
        detectors = create_detectors(model_names)
    except Exception as exc:
        print_step("!!", f"Non è stato possibile caricare i modelli di riconoscimento: {exc}")
        return []
    if not detectors:
        print_step("!!", "Nessuno dei modelli di riconoscimento dello scenario è utilizzabile")
        return []
    etichette = [e.lower() for e in _model_labels([d["name"] for d in detectors])]
    if len(etichette) == 1:
        print_step("OK", f"È stato caricato un modello: {etichette[0]}")
    else:
        quanti = _NUMERI_IN_LETTERE.get(len(etichette), str(len(etichette)))
        print_step(
            "OK",
            f"Sono stati caricati {quanti} modelli: {_elenco_italiano(etichette)}",
        )
    return detectors


def _phase_localization(subsystems: Subsystems) -> None:
    _announce_phase("Fase 3 · Localizzazione nel cantiere")
    pose_estimator = None
    try:
        pose_estimator = create_pose_estimator()
        if pose_estimator is not None:
            print_step("OK", "Il drone può calcolare la propria posizione dai marker AprilTag")
        else:
            print_step(
                "--",
                "La localizzazione è disattivata nella configurazione: il drone non "
                "calcolerà la propria posizione",
            )
    except Exception as exc:
        print_step(
            "!!",
            f"Il drone non può calcolare la propria posizione dai marker AprilTag: {exc}",
        )
    subsystems.pose_estimator = pose_estimator


def _build_pose_filter(subsystems: Subsystems):
    if subsystems.pose_estimator is None:
        print_step("--", "Senza localizzazione il filtro di Kalman non viene attivato")
        return None
    try:
        pose_filter = create_pose_filter()
        print_step("OK", "Il filtro di Kalman stabilizzerà la posizione calcolata dai marker")
        return pose_filter
    except Exception as exc:
        print_step(
            "!!",
            "Il filtro di Kalman non è disponibile: la posizione calcolata dai marker "
            f"non verrà stabilizzata ({exc})",
        )
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
        print_step(
            "OK",
            "Il volo autonomo è disponibile: una volta in aria si attiva con il tasto "
            f"{APP_CONFIG.joystick.label_autonomy}",
        )
    elif apriltag_autopilot is not None:
        print_step("!!", "Il volo autonomo non è disponibile perché manca la localizzazione")
    elif not waypoints:
        print_step("--", "Senza un percorso valido il drone potrà essere pilotato solo manualmente")
    elif not APP_CONFIG.apriltag_autopilot.enabled:
        print_step("--", "Il volo autonomo è disattivato nella configurazione")
    else:
        print_step(
            "!!",
            "Il volo autonomo non è disponibile perché il percorso scelto non è valido",
        )


def _build_flight_logger(subsystems: Subsystems) -> None:
    subsystems.flight_data_logger = create_flight_data_logger()
    print_step("OK", "I dati del volo verranno registrati per l'analisi a terra")


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
            "Il controllo delle reti di sicurezza non è disponibile perché manca il modello "
            f"«{_model_label(safety_net_model_name)}»",
        )
        return None

    monitor = SafetyNetMonitor(
        waypoint_tag_map=safety_net_tags_by_stop,
        safety_net_model_name=safety_net_model_name,
        safety_net_confirm_sec=(path.safety_net_confirm_sec or 0.0),
    )
    print_step("OK", "Durante le soste verrà verificata la presenza delle reti di sicurezza")
    return monitor


def _report_person_watch(*, loaded_model_names, restricted_area_tolerance_px) -> None:
    restricted_area_model_name = APP_CONFIG.restricted_area_model_name
    if restricted_area_model_name not in loaded_model_names:
        print_step(
            "OK",
            "Durante le soste verranno segnalate le cadute delle persone; gli ingressi "
            "nelle aree interdette non saranno controllati perché manca il modello "
            f"«{_model_label(restricted_area_model_name)}»",
        )
    elif restricted_area_tolerance_px is None:
        print_step(
            "OK",
            "Durante le soste verranno segnalate le cadute delle persone; questo "
            "scenario non prevede il controllo delle aree interdette",
        )
    else:
        print_step(
            "OK",
            "Durante le soste verranno segnalate le cadute delle persone e gli "
            "ingressi nelle aree interdette",
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
            "Il controllo dei dispositivi di protezione non è disponibile perché manca "
            f"il modello «{_model_label(dpi_model_name)}»",
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
            "Il controllo dei dispositivi di protezione non è disponibile: nessuno dei "
            f"dispositivi indicati nello scenario è riconosciuto ({', '.join(unknown_items)}); "
            f"quelli ammessi sono {_elenco_italiano(dpi_item_names())}",
        )
        return None

    active_items = _elenco_italiano(dpi_item_names(monitor.required_items))
    print_step(
        "OK",
        f"Durante le soste verrà verificato che gli operatori indossino {active_items}",
    )
    if unknown_items:
        print_step(
            "!!",
            "Questi dispositivi di protezione non sono riconosciuti e verranno ignorati: "
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


def _phase_navigation(subsystems: Subsystems, *, path):
    _announce_phase("Fase 5 · Navigazione autonoma")
    pose_filter = _build_pose_filter(subsystems)
    apriltag_autopilot = _build_autopilot(
        subsystems,
        path=path,
        pose_estimator=subsystems.pose_estimator,
        dashboard=subsystems.dashboard,
    )
    return pose_filter, apriltag_autopilot


def _phase_surveillance(subsystems: Subsystems, *, path) -> list:
    _announce_phase("Fase 6 · Sorveglianza del cantiere")
    detectors = _build_detectors(
        required_model_names(path) if path is not None else ()
    )
    _build_monitors(subsystems, detectors=detectors, path=path)
    return detectors


def _phase_recording(subsystems: Subsystems) -> None:
    _announce_phase("Fase 7 · Registrazione dei dati")
    _build_flight_logger(subsystems)


def _announce_ready(dashboard) -> None:
    dashboard.clear_terminal()
    dashboard.clear_alerts()

    log_ready_banner(
        "Pronto al decollo",
        "Il drone è a terra e attende i comandi del controller",
    )
    _announce_phase("Registro degli errori")


def run_startup(subsystems: Subsystems, original_stdout) -> bool:
    log_title(APP_CONFIG.project_title)
    _start_dashboard(subsystems, original_stdout)

    screen = _phase_manual_control(subsystems)

    if not _phase_welcome(screen):
        return False

    if _phase_connect(subsystems) is None:
        return False

    _phase_localization(subsystems)
    end_startup_transcript()

    subsystems.screen = pygame.display.get_surface()
    return True


def arm_mission(subsystems: Subsystems) -> bool:
    ritorno = subsystems.scenario_change
    subsystems.scenario_change = False
    if ritorno:
        redraw_startup_transcript()

    scelto, selected_path, screen = _phase_mission_path(subsystems.screen, ritorno=ritorno)
    subsystems.screen = screen
    if not scelto:
        return False

    pose_filter, apriltag_autopilot = _phase_navigation(subsystems, path=selected_path)
    detectors = _phase_surveillance(subsystems, path=selected_path)
    _phase_recording(subsystems)

    _build_loops(
        subsystems,
        controller=subsystems.controller,
        detectors=detectors,
        pose_estimator=subsystems.pose_estimator,
        pose_filter=pose_filter,
        apriltag_autopilot=apriltag_autopilot,
    )

    _announce_ready(subsystems.dashboard)
    return True
