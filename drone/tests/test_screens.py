from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.ui import fonts
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
    sottotitolo = screens.WAYPOINT_SUBTITLE.lower()
    assert "percorso" in sottotitolo
    assert "yolo" in sottotitolo


def test_the_subtitle_fits_the_window_at_every_size():
    for larghezza, altezza in _MISURE_FINESTRA:
        screens._apply_layout_scale(larghezza, altezza)
        font = fonts.sans(screens._scale(screens._SUBTITLE_PX))
        assert font.getlength(screens.WAYPOINT_SUBTITLE) <= larghezza * screens._SUPERSAMPLE, (
            f"{larghezza}x{altezza}"
        )


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
        screens._button_label(screens.BACK_TEXT, m.label_setup_back),
        screens._button_label(screens.EXIT_TEXT, m.label_setup_cancel),
        screens._button_label(screens.NEXT_TEXT, m.label_setup_confirm),
    ]
    assert etichette == ["Indietro (L1)", "Esci (Share)", "Avanti (R1)"]
    for etichetta in etichette:
        assert "(Esc)" not in etichetta
        assert "(Invio)" not in etichetta


def test_the_screen_no_longer_reads_the_keyboard():
    sorgente = pathlib.Path(screens.__file__).read_text(encoding="utf-8")
    assert "KEYDOWN" not in sorgente
    assert "MOUSEBUTTONDOWN" in sorgente


class _Percorso:
    def __init__(self, waypoint, soste, durata):
        self.waypoints = tuple(range(waypoint))
        self.supervision_waypoints = soste
        self.supervision_stop_sec = durata


def test_the_summary_counts_waypoints_and_stops():
    riassunto = screens._path_summary(_Percorso(10, (1, 5, 6, 10), 8.0))
    assert riassunto == ("10 waypoint", "4 soste da 8 s")


def test_the_summary_uses_the_singular_and_the_decimal_comma():
    riassunto = screens._path_summary(_Percorso(3, (2,), 6.5))
    assert riassunto == ("3 waypoint", "1 sosta da 6,5 s")


def test_without_stops_the_summary_has_only_the_waypoints():
    assert screens._path_summary(_Percorso(5, None, None)) == ("5 waypoint", None)


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
        assert annulla.x > 0
        assert annulla.right <= indietro.x
        assert indietro.right <= conferma.x

        tile_h = _waypoint_tile_height([_DESCRIZIONE_LUNGA], larghezza, altezza)
        rects = screens._compute_tile_rects(
            2, larghezza, altezza, cols=screens._WAYPOINT_COLS, tile_h=tile_h, gap=18,
        )
        assert rects[-1].bottom <= indietro.y, f"{larghezza}x{altezza}"


def test_the_tiles_are_centered_between_the_header_and_the_footer():
    descrizioni = [_DESCRIZIONE_LUNGA, "Descrizione breve."]
    for larghezza, altezza in _MISURE_FINESTRA:
        tile_h = _waypoint_tile_height(descrizioni, larghezza, altezza)
        rects = screens._compute_tile_rects(
            len(descrizioni), larghezza, altezza,
            cols=screens._WAYPOINT_COLS, tile_h=tile_h, gap=18,
        )
        k = screens._LAYOUT_SCALE
        sopra = rects[0].top - int(screens._HEADER_BAND_H * k)
        sotto = altezza - int(screens._FOOTER_BAND_H * k) - rects[-1].bottom
        assert abs(sopra - sotto) <= 1, f"{larghezza}x{altezza}: {sopra} sopra, {sotto} sotto"


def test_cancel_sits_on_the_left_and_the_other_two_on_the_right():
    conferma, annulla, indietro = screens.footer_rects(1920, 1080)
    assert annulla.centerx < 1920 / 2
    assert indietro.centerx > 1920 / 2
    assert conferma.centerx > indietro.centerx


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
