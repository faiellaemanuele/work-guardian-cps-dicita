from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.control import pilot_commands


class FakeAutopilot:
    def __init__(self, finished: bool, waypoint_index: int = 5):
        self.finished = finished
        self.current_waypoint_index = waypoint_index
        self.reset_called = False

    def reset(self):
        self.reset_called = True
        self.finished = False
        self.current_waypoint_index = 0

    def cancel_supervision_stop(self):
        pass


class FakeController:
    def __init__(self, flying: bool = True):
        self.is_flying = flying
        self.rc_calls = []
        self.azioni = []

    def send_rc_control(self, lr, fb, ud, yaw):
        self.rc_calls.append((lr, fb, ud, yaw))
        self.azioni.append("rc")
        return True

    def land(self):
        self.azioni.append("land")
        if not self.is_flying:
            return False
        self.is_flying = False
        return True

    def takeoff(self):
        self.azioni.append("takeoff")
        self.is_flying = True
        return True


def _events(**overrides):
    actions = {
        "quit": False, "takeoff": False, "land": False, "detect": False,
        "autonomy": False, "scenario": False,
    }
    actions.update(overrides)
    return actions


def _make_pilot_commands(autopilot, *, flying=True):
    return pilot_commands.PilotCommands(
        controller=FakeController(flying=flying),
        manual_speed_pct=50,
        detection_available=True,
        autonomy_available=True,
        autopilot=autopilot,
    )


def _step_with(loop, **events):
    original = pilot_commands.read_events
    pilot_commands.read_events = lambda: _events(**events)
    try:
        return loop.step()
    finally:
        pilot_commands.read_events = original


def test_enabling_autonomy_resets_when_mission_finished():
    ap = FakeAutopilot(finished=True, waypoint_index=5)
    loop = _make_pilot_commands(ap, flying=True)

    _step_with(loop, autonomy=True)

    assert loop.is_autonomy_enabled() is True
    assert ap.reset_called is True
    assert ap.current_waypoint_index == 0


def test_enabling_autonomy_does_not_reset_mid_mission():
    ap = FakeAutopilot(finished=False, waypoint_index=3)
    loop = _make_pilot_commands(ap, flying=True)

    _step_with(loop, autonomy=True)

    assert loop.is_autonomy_enabled() is True
    assert ap.reset_called is False
    assert ap.current_waypoint_index == 3


def test_autonomy_ignored_when_not_flying():
    ap = FakeAutopilot(finished=True, waypoint_index=5)
    loop = _make_pilot_commands(ap, flying=False)

    _step_with(loop, autonomy=True)

    assert loop.is_autonomy_enabled() is False
    assert ap.reset_called is False



def test_l_atterraggio_da_joystick_disinnesca_l_autonomia():
    ap = FakeAutopilot(finished=False)
    loop = _make_pilot_commands(ap, flying=True)
    _step_with(loop, autonomy=True)
    assert loop.is_autonomy_enabled() is True

    _step_with(loop, land=True)

    assert loop.is_autonomy_enabled() is False


def test_l_atterraggio_azzera_i_comandi_prima_di_atterrare():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=True)

    _step_with(loop, land=True)

    azioni = loop.controller.azioni
    assert azioni.index("rc") < azioni.index("land")
    assert loop.controller.rc_calls[0] == (0, 0, 0, 0)


def test_atterrare_da_terra_non_rompe_niente():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=False)

    assert _step_with(loop, land=True) is True
    assert loop.is_autonomy_enabled() is False


def test_uscire_azzera_i_comandi_e_ferma_il_ciclo():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=True)

    assert _step_with(loop, quit=True) is False
    assert loop.controller.rc_calls[-1] == (0, 0, 0, 0)


def test_il_decollo_non_tocca_l_autonomia():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=False)

    _step_with(loop, takeoff=True)

    assert loop.controller.is_flying is True
    assert loop.is_autonomy_enabled() is False


def test_il_ritorno_allo_scenario_ferma_il_ciclo_solo_da_terra():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=False)
    assert _step_with(loop, scenario=True) is False
    assert loop.is_scenario_change_requested() is True


def test_in_volo_il_ritorno_allo_scenario_viene_ignorato():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=True)
    assert _step_with(loop, scenario=True) is True
    assert loop.is_scenario_change_requested() is False


def test_l_atterraggio_da_joystick_resta_segnato():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=True)
    assert loop.landed_by_pilot() is False
    _step_with(loop, land=True)
    assert loop.landed_by_pilot() is True


def test_un_nuovo_decollo_cancella_l_atterraggio_del_pilota():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=True)
    _step_with(loop, land=True)
    _step_with(loop, takeoff=True)
    assert loop.landed_by_pilot() is False


def test_l_atterraggio_non_riuscito_non_viene_segnato():
    loop = _make_pilot_commands(FakeAutopilot(finished=False), flying=False)
    _step_with(loop, land=True)
    assert loop.landed_by_pilot() is False


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
