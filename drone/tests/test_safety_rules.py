from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.control.safety_rules import battery_guard_action, desync_ground_update


def test_battery_none_returns_none():
    assert battery_guard_action(None, True, 20, 25) is None


def test_battery_critical_when_flying_at_threshold():
    assert battery_guard_action(20, True, 20, 25) == "critical"


def test_battery_critical_strict_below():
    assert battery_guard_action(19, True, 20, 25) == "critical"


def test_battery_not_critical_on_ground_but_warns():
    assert battery_guard_action(18, False, 20, 25) == "warning"


def test_battery_warning_band():
    assert battery_guard_action(22, True, 20, 25) == "warning"


def test_battery_warning_at_boundary():
    assert battery_guard_action(25, True, 20, 25) == "warning"


def test_battery_ok_returns_none():
    assert battery_guard_action(80, True, 20, 25) is None


def test_battery_return_home_when_flying_below_rth():
    assert battery_guard_action(28, True, 20, 25, 30) == "return_home"


def test_battery_return_home_at_rth_boundary():
    assert battery_guard_action(30, True, 20, 25, 30) == "return_home"


def test_battery_critical_has_precedence_over_rth():
    assert battery_guard_action(20, True, 20, 25, 30) == "critical"


def test_battery_return_home_only_when_flying():
    assert battery_guard_action(24, False, 20, 25, 30) == "warning"


def test_battery_rth_disabled_when_pct_none():
    assert battery_guard_action(24, True, 20, 25, None) == "warning"


def test_battery_above_rth_returns_none_when_flying():
    assert battery_guard_action(40, True, 20, 25, 30) is None


def test_desync_not_flying_resets():
    assert desync_ground_update(False, 0, 100.0, 200.0, 10, 3.0) == (None, False)


def test_desync_height_none_resets():
    assert desync_ground_update(True, None, 50.0, 100.0, 10, 3.0) == (None, False)


def test_desync_height_above_ground_resets():
    assert desync_ground_update(True, 80, 50.0, 100.0, 10, 3.0) == (None, False)


def test_desync_starts_window():
    assert desync_ground_update(True, 5, None, 100.0, 10, 3.0) == (100.0, False)


def test_desync_window_in_progress_keeps_start():
    assert desync_ground_update(True, 5, 100.0, 102.0, 10, 3.0) == (100.0, False)


def test_desync_confirmed_after_window():
    assert desync_ground_update(True, 5, 100.0, 103.5, 10, 3.0) == (None, True)


def test_desync_confirmed_at_exact_boundary():
    assert desync_ground_update(True, 5, 100.0, 103.0, 10, 3.0) == (None, True)


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
