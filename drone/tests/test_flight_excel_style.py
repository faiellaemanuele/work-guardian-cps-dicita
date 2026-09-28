from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.data.flight_excel_style import translate_reason


def test_a_known_reason_is_translated():
    assert translate_reason("supervision_stop_started") == "Supervisione avviata"
    assert translate_reason("waypoint_reached") == "Waypoint raggiunto"


def test_the_old_reason_code_of_a_past_session_is_still_translated():
    assert translate_reason("supervision_hold_started") == "Supervisione avviata"
    assert translate_reason("supervision_hold_completed") == "Supervisione completata"
    assert translate_reason("supervision_hold_tracking") == "Supervisione: assestamento"


def test_an_invalid_pose_reason_is_translated_by_prefix():
    assert translate_reason("invalid_pose_transient_3") == "Posizione non valida (temporanea)"
    assert translate_reason("invalid_pose_xy") == "Posizione non valida"


def test_an_unknown_reason_is_returned_as_is():
    assert translate_reason("boh") == "boh"


def test_none_becomes_an_empty_cell():
    assert translate_reason(None) == ""


def test_surrounding_spaces_are_ignored():
    assert translate_reason("  waypoint_reached  ") == "Waypoint raggiunto"


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
