from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.ui.video import window
from drone.ui.video.window import enable_high_dpi_awareness, monitor_work_origin_for_window


def test_returns_false_off_windows():
    original = window.sys.platform
    try:
        window.sys.platform = "linux"
        assert enable_high_dpi_awareness() is False
    finally:
        window.sys.platform = original


def test_returns_bool_and_never_raises():
    result = enable_high_dpi_awareness()
    assert isinstance(result, bool)


def test_monitor_origin_none_for_invalid_handle():
    assert monitor_work_origin_for_window(None) is None
    assert monitor_work_origin_for_window(0) is None


def test_monitor_origin_none_off_windows():
    original = window.sys.platform
    try:
        window.sys.platform = "linux"
        assert monitor_work_origin_for_window(12345) is None
    finally:
        window.sys.platform = original


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
