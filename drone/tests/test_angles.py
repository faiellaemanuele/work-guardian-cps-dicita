from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.geometry.angles import circular_mean_deg, wrap_angle_deg


def test_wrap_angle_boundaries_map_to_180():
    assert wrap_angle_deg(180.0) == 180.0
    assert wrap_angle_deg(-180.0) == 180.0
    assert wrap_angle_deg(540.0) == 180.0
    assert wrap_angle_deg(-540.0) == 180.0


def test_wrap_angle_in_range_values():
    assert wrap_angle_deg(0.0) == 0.0
    assert abs(wrap_angle_deg(190.0) - (-170.0)) < 1e-9
    assert abs(wrap_angle_deg(-190.0) - 170.0) < 1e-9
    assert abs(wrap_angle_deg(359.0) - (-1.0)) < 1e-9


def test_wrap_angle_idempotent():
    for a in (-179.0, -90.0, 0.0, 90.0, 179.0, 180.0, 720.0):
        once = wrap_angle_deg(a)
        assert abs(wrap_angle_deg(once) - once) < 1e-9


def test_wrap_angle_non_finite_propagates_nan():
    assert math.isnan(wrap_angle_deg(float("nan")))
    assert math.isnan(wrap_angle_deg(float("inf")))
    assert math.isnan(wrap_angle_deg(float("-inf")))


def test_circular_mean_of_single_value_is_that_value():
    assert abs(circular_mean_deg([42.0]) - 42.0) < 1e-9


def test_circular_mean_crosses_the_180_discontinuity():
    assert abs(abs(circular_mean_deg([170.0, -170.0])) - 180.0) < 1e-9


def test_circular_mean_averages_within_range():
    assert abs(circular_mean_deg([-10.0, 10.0])) < 1e-9
    assert abs(circular_mean_deg([80.0, 100.0]) - 90.0) < 1e-9


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
    import sys

    sys.exit(_run_all())
