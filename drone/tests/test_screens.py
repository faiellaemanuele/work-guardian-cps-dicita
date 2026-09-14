from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.ui.setup import screens
from drone.ui.setup.screens import (
    GO_BACK,
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
    assert "controlli" in screens.WAYPOINT_SUBTITLE.lower()


def test_the_tile_leaves_room_for_the_model_chips():
    senza = _waypoint_tile_height(["descrizione breve"], 1900)
    with_chips_row = 44 // screens._SUPERSAMPLE * screens._SUPERSAMPLE
    assert senza > with_chips_row


def test_going_back_is_neither_a_path_nor_a_cancel():
    assert GO_BACK is not None
    assert not isinstance(GO_BACK, bool)


def test_the_buttons_name_the_controller_keys_and_not_the_keyboard():
    m = APP_CONFIG.joystick
    etichette = [
        screens._button_label("Indietro", m.label_setup_back),
        screens._button_label("Annulla", m.label_setup_cancel),
        screens._button_label("Conferma", m.label_setup_confirm),
    ]
    assert etichette == ["Indietro (L1)", "Annulla (Share)", "Conferma (R1)"]
    for etichetta in etichette:
        assert "(Esc)" not in etichetta
        assert "(Invio)" not in etichetta


def test_the_screen_no_longer_reads_the_keyboard():
    sorgente = pathlib.Path(screens.__file__).read_text(encoding="utf-8")
    assert "KEYDOWN" not in sorgente
    assert "MOUSEBUTTONDOWN" in sorgente


_MISURE_FINESTRA = (
    (960, 720),
    (1280, 600),
    (1366, 728),
    (1536, 824),
    (1920, 1032),
    (1920, 1080),
    (2560, 1392),
)

_DESCRIZIONE_LUNGA = (
    "Il drone vola in autonomia lungo il perimetro, con soste di supervisione, per "
    "controllare di ogni persona le protezioni individuali - elmetto, occhiali, gilet "
    "e scarpe antinfortunistiche -, le cadute e il superamento delle aree interdette, "
    "e al termine atterra alla home."
)


def test_the_tiles_show_the_whole_description_at_every_window_size():
    descrizioni = [_DESCRIZIONE_LUNGA, "Descrizione breve."]
    for larghezza, altezza in _MISURE_FINESTRA:
        tile_h = _waypoint_tile_height(descrizioni, larghezza, altezza)
        rects = screens._compute_tile_rects(
            len(descrizioni), larghezza, altezza,
            cols=screens._WAYPOINT_COLS, tile_h=tile_h, gap=18,
        )
        assert rects[0].height == tile_h, f"{larghezza}x{altezza}"


def test_the_footer_buttons_stay_inside_the_window_and_below_the_tiles():
    for larghezza, altezza in _MISURE_FINESTRA:
        conferma, annulla, indietro = screens.footer_rects(larghezza, altezza)
        assert conferma.right <= larghezza
        assert conferma.bottom <= altezza
        assert indietro.x > 0
        assert indietro.right <= annulla.x
        assert annulla.right <= conferma.x

        tile_h = _waypoint_tile_height([_DESCRIZIONE_LUNGA], larghezza, altezza)
        rects = screens._compute_tile_rects(
            2, larghezza, altezza, cols=screens._WAYPOINT_COLS, tile_h=tile_h, gap=18,
        )
        assert rects[-1].bottom <= indietro.y, f"{larghezza}x{altezza}"


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
