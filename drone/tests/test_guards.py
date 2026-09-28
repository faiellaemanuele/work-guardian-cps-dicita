from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.flight.guards import Subsystems, apply_battery_guard
from drone.config import APP_CONFIG


class FakeController:
    def __init__(self, is_flying=True):
        self.is_flying = is_flying
        self.land_calls = 0

    def land(self):
        self.land_calls += 1
        self.is_flying = False
        return True


class FakeControlLoop:
    def __init__(self, autonomy=False):
        self._autonomy = autonomy
        self.disable_calls = 0

    def is_autonomy_enabled(self):
        return self._autonomy

    def disable_autonomy(self):
        self._autonomy = False
        self.disable_calls += 1


class FakeVisionLoop:
    def __init__(self, battery):
        self.cached_status = {"battery": battery}

    def clear_autopilot_overlay(self):
        pass


class FakeAutopilot:
    def __init__(self, home_index=0, engage_result=True):
        self.home_waypoint_index = home_index
        self._engage_result = engage_result
        self.engage_calls = 0

    def engage_return_home(self):
        self.engage_calls += 1
        return self._engage_result


def _make_subsystems(*, battery, autonomy, autopilot=None, pose_estimator=None, is_flying=True):
    s = Subsystems()
    s.controller = FakeController(is_flying=is_flying)
    s.pilot_commands = FakeControlLoop(autonomy=autonomy)
    s.vision_loop = FakeVisionLoop(battery)
    s.apriltag_autopilot = autopilot
    s.pose_estimator = pose_estimator
    return s


def _call(s, *, rth_active=False, rth_operator_override=False):
    return apply_battery_guard(
        s,
        rth_active=rth_active,
        rth_operator_override=rth_operator_override,
        last_low_battery_warn_at=0.0,
    )


_RTH = APP_CONFIG.battery_rth_pct
_CRIT = APP_CONFIG.battery_critical_pct
_BELOW_RTH = (_RTH + _CRIT) // 2
_BELOW_CRIT = _CRIT - 1


def test_manual_below_rth_does_not_land():
    s = _make_subsystems(battery=_BELOW_RTH, autonomy=False, autopilot=None)
    running, rth_active, last_warn = _call(s)
    assert running is True
    assert rth_active is False
    assert s.controller.land_calls == 0
    assert last_warn > 0.0


def test_manual_below_rth_with_autopilot_does_not_engage_rth():
    ap = FakeAutopilot(home_index=2, engage_result=True)
    s = _make_subsystems(battery=_BELOW_RTH, autonomy=False, autopilot=ap, pose_estimator=object())
    running, rth_active, last_warn = _call(s)
    assert running is True
    assert rth_active is False
    assert ap.engage_calls == 0
    assert s.controller.land_calls == 0
    assert last_warn > 0.0


def test_autonomous_below_rth_engages_rth():
    ap = FakeAutopilot(home_index=2, engage_result=True)
    s = _make_subsystems(battery=_BELOW_RTH, autonomy=True, autopilot=ap, pose_estimator=object())
    running, rth_active, _ = _call(s)
    assert running is True
    assert rth_active is True
    assert ap.engage_calls == 1
    assert s.controller.land_calls == 0


def test_autonomous_below_rth_without_home_lands_on_spot():
    ap = FakeAutopilot(home_index=None)
    s = _make_subsystems(battery=_BELOW_RTH, autonomy=True, autopilot=ap, pose_estimator=object())
    running, rth_active, _ = _call(s)
    assert running is False
    assert s.controller.land_calls == 1
    assert s.pilot_commands.disable_calls == 1


def test_critical_lands_in_manual():
    s = _make_subsystems(battery=_BELOW_CRIT, autonomy=False, autopilot=None)
    running, _, _ = _call(s)
    assert running is False
    assert s.controller.land_calls == 1


def test_critical_lands_in_autonomy():
    s = _make_subsystems(battery=_BELOW_CRIT, autonomy=True, autopilot=FakeAutopilot())
    running, _, _ = _call(s)
    assert running is False
    assert s.controller.land_calls == 1
    assert s.pilot_commands.disable_calls == 1


def test_manual_after_override_still_warns():
    s = _make_subsystems(battery=_BELOW_RTH, autonomy=False, autopilot=None)
    running, rth_active, last_warn = _call(s, rth_operator_override=True)
    assert running is True
    assert rth_active is False
    assert s.controller.land_calls == 0
    assert last_warn > 0.0


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
