from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from drone.geometry.positions import normalize_position_world


def _assert_value_error(fn) -> None:
    raised = False
    try:
        fn()
    except ValueError:
        raised = True
    assert raised is True


def test_normalize_from_mapping_shape_and_values():
    out = normalize_position_world({"x": 1.0, "y": 2.0, "z": 3.0})
    assert out.shape == (3, 1)
    assert [float(v) for v in out.flatten()] == [1.0, 2.0, 3.0]


def test_normalize_sequence_matches_mapping():
    a = normalize_position_world([1.0, 2.0, 3.0])
    b = normalize_position_world({"x": 1.0, "y": 2.0, "z": 3.0})
    assert np.allclose(a, b)


def test_normalize_rejects_missing_key():
    _assert_value_error(lambda: normalize_position_world({"x": 1.0, "y": 2.0}))


def test_normalize_rejects_none_value_in_mapping():
    _assert_value_error(lambda: normalize_position_world({"x": 1.0, "y": None, "z": 3.0}))


def test_normalize_rejects_wrong_size():
    _assert_value_error(lambda: normalize_position_world([1.0, 2.0]))
    _assert_value_error(lambda: normalize_position_world([1.0, 2.0, 3.0, 4.0]))


def test_normalize_rejects_non_finite():
    _assert_value_error(lambda: normalize_position_world([1.0, float("inf"), 3.0]))
    _assert_value_error(lambda: normalize_position_world([1.0, float("nan"), 3.0]))


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
