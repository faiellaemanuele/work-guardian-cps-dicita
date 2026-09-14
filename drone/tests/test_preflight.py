from __future__ import annotations

import contextlib
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.flight import preflight
from drone.config import APP_CONFIG
from drone.surveillance.dpi_monitor import dpi_item_names
from drone.surveillance.person_monitor import _ALARM_FALL, _ALARM_RESTRICTED_AREA
from drone.flight.preflight import Subsystems, arm_mission, run_startup

_SAFETY_NET = APP_CONFIG.safety_net_model_name
_FALL = APP_CONFIG.person_fall_model_name
_AREE = APP_CONFIG.restricted_area_model_name
_DPI = APP_CONFIG.dpi_model_name


class _Screen:
    def copy(self):
        return self


class _Dashboard:
    enabled = False

    def __init__(self, *args, **kwargs):
        self.scenario_name = None
        self.mission = None

    def make_stdout_redirect(self, original):
        return original

    def set_scenario_name(self, name):
        self.scenario_name = name

    def configure_mission(self, waypoints, **kwargs):
        self.mission = (waypoints, kwargs)

    def clear_terminal(self):
        pass

    def clear_alerts(self):
        pass


class _Controller:
    rompe = frozenset()

    def __init__(self):
        self.connected = False
        self.streaming = False

    def connect(self):
        if "connect" in type(self).rompe:
            raise RuntimeError("il drone non risponde")
        self.connected = True

    def start_video_stream(self):
        if "stream" in type(self).rompe:
            raise RuntimeError("nessun flusso video")
        self.streaming = True


class _Autopilot:
    def __init__(self):
        self.waypoints = ["rotta_dell_autopilota"]
        self.home_waypoint_index = 4


class _Path:
    def __init__(self, **overrides):
        campi = dict(
            name="Scenario di prova",
            description="",
            waypoints=[object()],
            supervision_waypoints=[1],
            safety_net_tags_by_stop=None,
            supervision_stop_sec=5.0,
            safety_net_confirm_sec=None,
            home_waypoint=None,
            fall_alarm_after_sec=None,
            restricted_area_alarm_after_sec=None,
            restricted_area_tolerance_px=None,
            dpi_required=None,
            dpi_alarm_after_sec=None,
        )
        campi.update(overrides)
        for chiave, valore in campi.items():
            setattr(self, chiave, valore)


def _detectors(*names):
    return [{"name": n, "color": (0, 0, 255), "detector": object()} for n in names]


class _FakeDisplay:
    def __init__(self, screen):
        self._screen = screen

    def set_caption(self, _title):
        pass

    def get_surface(self):
        return self._screen


class _Esito:
    def __init__(self, ok, subsystems, passi, argomenti_autopilota, modelli_mostrati=None):
        self.ok = ok
        self.subsystems = subsystems
        self.passi = passi
        self.argomenti_autopilota = argomenti_autopilota
        self.modelli_mostrati = modelli_mostrati

    def testo(self, esito=None):
        return " | ".join(t for e, t in self.passi if esito is None or e == esito)


@contextlib.contextmanager
def _sostituisci(**attributi):
    originali = {nome: getattr(preflight, nome) for nome in attributi}
    for nome, valore in attributi.items():
        setattr(preflight, nome, valore)
    try:
        yield
    finally:
        for nome, valore in originali.items():
            setattr(preflight, nome, valore)


def _esegui(*, presentazione=True, rilevatori=None, percorso=None, percorsi=None,
            annulla_scenario=False, autopilota=True, stimatore=True,
            controller=None):
    schermo = _Screen()
    passi = []
    rilevatori = _detectors() if rilevatori is None else rilevatori
    if percorsi is None:
        percorsi = [percorso if percorso is not None else _Path()]
    scelta = None if annulla_scenario else (percorsi[0] if percorsi else None)

    finto_pygame = types.SimpleNamespace(
        display=_FakeDisplay(schermo),
        time=types.SimpleNamespace(Clock=lambda: object()),
    )

    argomenti_autopilota = []
    modelli_mostrati = []

    def _scelta_percorso(_schermo, _percorsi, modelli_per_percorso):
        modelli_mostrati.append(modelli_per_percorso)
        return scelta

    def _autopilota(*args, **kwargs):
        argomenti_autopilota.append(args)
        return _Autopilot() if autopilota else None

    subsystems = Subsystems()
    with _sostituisci(
        Dashboard=_Dashboard,
        set_alert_sink=lambda *a, **k: None,
        log_phase=lambda *a, **k: None,
        log_console_block=lambda *a, **k: None,
        format_joystick_help=lambda: "",
        print_step=lambda esito, testo: passi.append((esito, testo)),
        print_event=lambda *a, **k: None,
        init_joystick=lambda: schermo,
        is_joystick_connected=lambda: True,
        pygame=finto_pygame,
        show_welcome_screen=lambda _s: presentazione,
        fade_screen=lambda *a, **k: None,
        load_waypoint_paths=lambda _d: list(percorsi),
        select_waypoint_path_interactive=_scelta_percorso,
        create_controller=(controller or _Controller),
        create_detectors=lambda _n: rilevatori,
        create_pose_estimator=lambda: (object() if stimatore else None),
        create_pose_filter=lambda: object(),
        create_flight_data_logger=lambda: object(),
        create_apriltag_autopilot=_autopilota,
        PilotCommands=lambda **k: types.SimpleNamespace(**k),
        VisionLoop=lambda **k: types.SimpleNamespace(**k),
    ):
        ok = run_startup(subsystems, sys.stdout)
        if ok:
            ok = arm_mission(subsystems)
    return _Esito(
        ok, subsystems, passi,
        argomenti_autopilota[0] if argomenti_autopilota else None,
        modelli_mostrati[0] if modelli_mostrati else None,
    )


def test_returns_false_when_the_welcome_screen_is_cancelled():
    esito = _esegui(presentazione=False)
    assert esito.ok is False
    assert esito.subsystems.controller is None


def test_returns_false_when_scenario_selection_is_cancelled():
    esito = _esegui(annulla_scenario=True)
    assert esito.ok is False


def test_the_scenario_screen_shows_the_models_of_each_scenario():
    esito = _esegui(
        rilevatori=_detectors(_DPI),
        percorsi=[_Path(dpi_required=["helmet"]), _Path()],
    )
    etichette_dpi, etichette_vuote = esito.modelli_mostrati
    assert etichette_dpi and etichette_vuote == []


def test_happy_path_fills_the_subsystems():
    esito = _esegui()
    assert esito.ok is True
    assert esito.subsystems.pilot_commands is not None
    assert esito.subsystems.vision_loop is not None
    assert esito.subsystems.flight_data_logger is not None
    assert esito.subsystems.screen is not None


def test_controller_is_connected_and_video_started():
    esito = _esegui()
    assert esito.subsystems.controller.connected is True
    assert esito.subsystems.controller.streaming is True


def test_scenario_name_reaches_dashboard_and_subsystems():
    esito = _esegui(percorso=_Path(name="Rotta X"))
    assert esito.subsystems.scenario_name == "Rotta X"
    assert esito.subsystems.dashboard.scenario_name == "Rotta X"


def test_safety_net_monitor_built_when_scenario_has_tags_and_model_loaded():
    esito = _esegui(
        rilevatori=_detectors(_SAFETY_NET),
        percorso=_Path(safety_net_tags_by_stop={2: [7, 8]}, safety_net_confirm_sec=3.0),
    )
    monitor = esito.subsystems.safety_net_monitor
    assert monitor is not None
    assert monitor.safety_net_model_name == _SAFETY_NET
    assert monitor._safety_net_confirm_sec == 3.0
    assert monitor._tag_map == {2: frozenset({7, 8})}


def test_safety_net_min_consecutive_defaults_to_zero_when_scenario_omits_it():
    esito = _esegui(
        rilevatori=_detectors(_SAFETY_NET),
        percorso=_Path(safety_net_tags_by_stop={1: [4]}, safety_net_confirm_sec=None),
    )
    assert esito.subsystems.safety_net_monitor._safety_net_confirm_sec == 0.0


def test_no_safety_net_monitor_without_the_model_but_it_is_reported():
    esito = _esegui(rilevatori=_detectors(), percorso=_Path(safety_net_tags_by_stop={1: [4]}))
    assert esito.subsystems.safety_net_monitor is None
    assert "reti di sicurezza" in esito.testo("!!")


def test_no_safety_net_monitor_when_scenario_has_no_tags():
    esito = _esegui(rilevatori=_detectors(_SAFETY_NET), percorso=_Path(safety_net_tags_by_stop=None))
    assert esito.subsystems.safety_net_monitor is None
    assert "reti di sicurezza" not in esito.testo()


def test_person_monitor_built_when_fall_model_loaded():
    esito = _esegui(
        rilevatori=_detectors(_FALL), percorso=_Path(fall_alarm_after_sec=4.0),
    )
    monitor = esito.subsystems.person_monitor
    assert monitor is not None
    assert monitor.fall_model_name == _FALL
    assert monitor.person_model_name == _FALL
    assert monitor.restricted_area_model_name == _AREE
    assert monitor.person_label == APP_CONFIG.person_class_label
    assert monitor.fall_label == APP_CONFIG.fall_class_label
    assert monitor._latch._release_grace_sec == APP_CONFIG.alarm_clear_after_sec


def test_no_person_monitor_without_the_fall_model():
    esito = _esegui(rilevatori=_detectors(_AREE))
    assert esito.subsystems.person_monitor is None


def test_surveillance_thresholds_come_from_the_scenario_when_present():
    esito = _esegui(
        rilevatori=_detectors(_FALL),
        percorso=_Path(fall_alarm_after_sec=1.5, restricted_area_alarm_after_sec=2.5),
    )
    latch = esito.subsystems.person_monitor._latch
    assert latch._threshold(_ALARM_FALL) == 1.5
    assert latch._threshold(_ALARM_RESTRICTED_AREA) == 2.5


def test_surveillance_thresholds_fall_back_to_config_when_scenario_omits_them():
    esito = _esegui(
        rilevatori=_detectors(_FALL), percorso=_Path(restricted_area_tolerance_px=3),
    )
    latch = esito.subsystems.person_monitor._latch
    assert latch._threshold(_ALARM_FALL) == APP_CONFIG.fall_alarm_after_sec
    assert latch._threshold(_ALARM_RESTRICTED_AREA) == APP_CONFIG.restricted_area_alarm_after_sec
    assert esito.subsystems.person_monitor._restricted_area_tolerance_px == 3.0


def test_restricted_area_proximity_comes_from_the_scenario():
    esito = _esegui(
        rilevatori=_detectors(_FALL, _AREE),
        percorso=_Path(restricted_area_tolerance_px=12),
    )
    assert esito.subsystems.person_monitor._restricted_area_tolerance_px == 12.0
    assert "aree vietate" in esito.testo("OK")


def test_restricted_area_proximity_none_when_scenario_omits_it():
    esito = _esegui(
        rilevatori=_detectors(_FALL, _AREE), percorso=_Path(fall_alarm_after_sec=2.0),
    )
    assert esito.subsystems.person_monitor._restricted_area_tolerance_px is None
    assert "non prevede" in esito.testo("OK")


def test_reports_the_missing_restricted_area_model():
    esito = _esegui(rilevatori=_detectors(_FALL), percorso=_Path(restricted_area_tolerance_px=5))
    assert esito.subsystems.person_monitor is not None
    assert "manca il modello" in esito.testo("OK")


def test_dpi_monitor_built_with_required_items():
    esito = _esegui(
        rilevatori=_detectors(_DPI),
        percorso=_Path(dpi_required=["helmet", "vest"], dpi_alarm_after_sec=2.0),
    )
    monitor = esito.subsystems.dpi_monitor
    assert monitor is not None
    assert monitor.dpi_model_name == _DPI
    assert monitor.required_items == ("helmet", "vest")
    assert monitor._latch._threshold("x") == 2.0
    assert monitor._latch._release_grace_sec == APP_CONFIG.alarm_clear_after_sec


def test_dpi_monitor_dropped_when_no_item_is_recognized():
    esito = _esegui(rilevatori=_detectors(_DPI), percorso=_Path(dpi_required=["cappello"]))
    assert esito.subsystems.dpi_monitor is None
    assert "cappello" in esito.testo("!!")
    assert dpi_item_names()[0] in esito.testo("!!")


def test_dpi_unknown_items_are_ignored_and_reported():
    esito = _esegui(
        rilevatori=_detectors(_DPI),
        percorso=_Path(dpi_required=["helmet", "cappello"]),
    )
    assert esito.subsystems.dpi_monitor.required_items == ("helmet",)
    assert "cappello" in esito.testo("!!")


def test_no_dpi_monitor_without_the_model_but_it_is_reported():
    esito = _esegui(rilevatori=_detectors(), percorso=_Path(dpi_required=["helmet"]))
    assert esito.subsystems.dpi_monitor is None
    assert "dispositivi di protezione" in esito.testo("!!")


def test_no_dpi_monitor_when_scenario_requires_nothing():
    esito = _esegui(rilevatori=_detectors(_DPI), percorso=_Path(dpi_required=None))
    assert esito.subsystems.dpi_monitor is None
    assert "dispositivi di protezione" not in esito.testo()


def test_autopilot_receives_the_route_of_the_chosen_scenario():
    casa = {"x": 1.0, "y": 2.0, "z": 1.5, "yaw_deg": 0.0}
    esito = _esegui(percorso=_Path(
        waypoints=["w1", "w2"],
        supervision_waypoints=[2],
        supervision_stop_sec=7.0,
        home_waypoint=casa,
    ))
    assert esito.argomenti_autopilota == (["w1", "w2"], [2], 7.0, casa)


def test_mission_is_configured_on_the_dashboard():
    esito = _esegui()
    assert esito.subsystems.dashboard.mission is not None
    _waypoints, opzioni = esito.subsystems.dashboard.mission
    assert opzioni["site_area"] == APP_CONFIG.site_area_vertices_m
    assert opzioni["restricted_areas"] == APP_CONFIG.restricted_areas_vertices_m
    assert opzioni["world_tags"] == APP_CONFIG.camera_pose.world_tags


def test_no_mission_configured_without_autopilot():
    esito = _esegui(autopilota=False)
    assert esito.subsystems.dashboard.mission is None


def test_supervision_stops_are_named_in_the_route_message():
    esito = _esegui(percorso=_Path(supervision_waypoints=[2, 5]))
    assert "con sosta ai punti 2 e 5" in esito.testo("OK")


def test_a_single_supervision_stop_is_said_in_the_singular():
    esito = _esegui(percorso=_Path(supervision_waypoints=[3]))
    assert "con sosta al punto 3" in esito.testo("OK")


def test_no_paths_available_leaves_the_mission_empty():
    esito = _esegui(percorsi=[], rilevatori=_detectors(_SAFETY_NET, _FALL, _AREE, _DPI))
    assert esito.ok is True
    assert esito.argomenti_autopilota == (None, None, None, None)
    assert esito.subsystems.scenario_name is None
    assert esito.subsystems.safety_net_monitor is None
    assert esito.subsystems.dpi_monitor is None


def test_no_scenario_available_means_manual_flight_without_models():
    esito = _esegui(percorsi=[], rilevatori=_detectors(_FALL, _AREE))
    assert esito.ok is True
    assert esito.subsystems.person_monitor is None
    assert esito.subsystems.vision_loop.detectors == []
    assert esito.subsystems.pilot_commands.detection_available is False


def test_detectors_and_perception_reach_the_two_loops():
    rilevatori = _detectors(_DPI)
    esito = _esegui(rilevatori=rilevatori, percorso=_Path(dpi_required=["helmet"]))
    assert esito.subsystems.vision_loop.detectors is rilevatori
    assert esito.subsystems.vision_loop.pose_estimator is esito.subsystems.pose_estimator
    assert esito.subsystems.vision_loop.pose_filter is not None
    assert esito.subsystems.pilot_commands.detection_available is True
    assert esito.subsystems.pilot_commands.autonomy_available is True


def test_autonomy_unavailable_without_autopilot():
    esito = _esegui(autopilota=False)
    assert esito.subsystems.pilot_commands.autonomy_available is False


def test_detection_unavailable_without_detectors():
    esito = _esegui(rilevatori=_detectors())
    assert esito.subsystems.pilot_commands.detection_available is False


def test_autonomy_unavailable_without_pose_estimator():
    esito = _esegui(stimatore=False)
    assert esito.subsystems.pose_estimator is None
    assert esito.subsystems.pilot_commands.autonomy_available is False
    assert "manca la localizzazione" in esito.testo("!!")


def test_no_pose_filter_without_pose_estimator():
    esito = _esegui(stimatore=False)
    assert esito.subsystems.vision_loop.pose_filter is None


def test_autopilot_is_registered_in_the_subsystems():
    esito = _esegui()
    autopilota = esito.subsystems.apriltag_autopilot
    assert autopilota is not None
    assert esito.subsystems.pilot_commands.autopilot is autopilota


def test_mission_map_gets_the_autopilot_route_and_home():
    esito = _esegui()
    waypoints, opzioni = esito.subsystems.dashboard.mission
    autopilota = esito.subsystems.apriltag_autopilot
    assert waypoints is autopilota.waypoints
    assert opzioni["home_index"] == autopilota.home_waypoint_index
    assert opzioni["yaw_offset_deg"] == APP_CONFIG.apriltag_autopilot.yaw_offset_deg


def test_says_the_route_is_invalid_when_the_autopilot_cannot_be_built():
    esito = _esegui(autopilota=False)
    assert "percorso scelto non è valido" in esito.testo("!!")


def test_says_nothing_about_flying_alone_without_a_route():
    esito = _esegui(autopilota=False, percorsi=[])
    assert "volare da solo" not in esito.testo()
    assert "volerà da solo" not in esito.testo()




def _con_controller_rotto(cosa):
    class _Rotto(_Controller):
        rompe = frozenset({cosa})

    originale = _Controller.rompe
    try:
        return _esegui(controller=_Rotto)
    finally:
        _Controller.rompe = originale


def test_un_drone_non_raggiungibile_ferma_il_preflight_senza_traccia_di_errore():
    esito = _con_controller_rotto("connect")

    assert esito.ok is False
    assert any(
        stato == "!!" and "non raggiungibile" in testo.lower()
        for stato, testo in esito.passi
    ), esito.passi
    assert esito.subsystems.vision_loop is None


def test_un_flusso_video_che_non_parte_ferma_il_preflight():
    esito = _con_controller_rotto("stream")

    assert esito.ok is False
    assert any(
        stato == "!!" and "flusso video" in testo.lower()
        for stato, testo in esito.passi
    ), esito.passi


def test_col_drone_collegato_il_preflight_arriva_in_fondo():
    esito = _esegui()

    assert esito.ok is True
    assert esito.subsystems.controller.connected is True
    assert esito.subsystems.controller.streaming is True


def _run_all() -> int:
    tests = sorted(
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((name, exc))
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[ OK ] {name}")

    print("-" * 60)
    print(f"Totale: {len(tests)}  |  passati: {passed}  |  falliti: {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
