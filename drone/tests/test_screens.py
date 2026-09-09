from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.ui.setup import screens
from drone.ui.setup.screens import (
    WAYPOINT_TITLE,
    _waypoint_tile_height,
    select_waypoint_path_interactive,
)


def test_waypoint_selector_is_exported():
    assert callable(select_waypoint_path_interactive)


def test_the_models_screen_is_gone():
    assert not hasattr(screens, "select_yolo_models_interactive")


def test_the_screen_is_about_the_scenario():
    assert "scenario" in WAYPOINT_TITLE.lower()
    sottotitolo = screens.WAYPOINT_SUBTITLE.lower()
    assert "percorso" in sottotitolo
    assert "modelli" in sottotitolo


def test_the_tile_leaves_room_for_the_model_chips():
    senza = _waypoint_tile_height(["descrizione breve"], 1900)
    with_chips_row = 44 // screens._SUPERSAMPLE * screens._SUPERSAMPLE
    assert senza > with_chips_row


def test_the_tile_grows_with_a_longer_description():
    breve = _waypoint_tile_height(["riga corta"], 1900)
    lunga = _waypoint_tile_height([" ".join(["parola"] * 120)], 1900)
    assert lunga > breve


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
