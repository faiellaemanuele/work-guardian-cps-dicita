from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.hardware.joystick import (
    joystick_action_groups,
    joystick_actions,
    joystick_axis_actions,
    joystick_axis_details,
)
from drone.ui import fonts
from drone.ui.setup import welcome


def test_the_welcome_screen_is_exported():
    assert callable(welcome.show_welcome_screen)


def test_the_screen_says_what_comes_next():
    testo = " ".join(welcome.PLATFORM_PARAGRAPHS).lower()
    assert "scenario" in testo
    assert "schermata successiva" in testo


def test_the_notes_explain_the_battery_and_the_saved_data():
    titoli = [titolo for titolo, _ in welcome.NOTES]
    corpi = " ".join(testo for _, testo in welcome.NOTES).lower()
    assert any("sicurezza" in t.lower() for t in titoli)
    assert any("dati" in t.lower() for t in titoli)
    assert str(APP_CONFIG.battery_rth_pct) in corpi
    assert str(APP_CONFIG.battery_critical_pct) in corpi


def test_the_command_table_comes_from_the_joystick_module():
    tasti = [tasto for tasto, _ in joystick_actions()]
    assert APP_CONFIG.joystick.label_scenario in tasti
    assert APP_CONFIG.joystick.label_takeoff in tasti
    assert len(joystick_axis_actions()) == 4


def test_the_groups_hold_every_command_of_the_flat_table():
    raggruppate = [riga for _sezione, righe in joystick_action_groups() for riga in righe]
    assert raggruppate == list(joystick_actions())
    assert len(joystick_action_groups()) == 3


def test_every_button_of_the_card_has_a_shape_or_falls_back_to_a_key():
    forme = {
        tasto: welcome._GLYPH_COLORS.get(tasto)
        for tasto, _azione in joystick_actions()
    }
    assert forme[APP_CONFIG.joystick.label_takeoff] is not None
    assert forme[APP_CONFIG.joystick.label_scenario] is None


def test_the_axes_say_which_stick_and_which_way():
    dettagli = joystick_axis_details()
    assert len(dettagli) == len(joystick_axis_actions())
    assert {lato for lato, _verso, _azione in dettagli} == {"L", "R"}
    assert {verso for _lato, verso, _azione in dettagli} == {"orizzontale", "verticale"}
    azioni_dettagli = [azione for _lato, _verso, azione in dettagli]
    assert azioni_dettagli == [azione for _tasto, azione in joystick_axis_actions()]


def test_wrapping_keeps_every_word_within_the_width():
    font = fonts.sans(20)
    testo = " ".join(["parola"] * 40)
    righe = welcome._wrap(testo, font, 200)
    assert " ".join(righe) == testo
    assert all(font.getlength(r) <= 200 for r in righe[:-1] if " " in r)


def test_a_single_word_too_long_is_not_lost():
    font = fonts.sans(20)
    righe = welcome._wrap("interminabile" * 6, font, 40)
    assert righe == ["interminabile" * 6]


_MISURE_FINESTRA = (
    (960, 720),
    (1280, 600),
    (1366, 728),
    (1536, 824),
    (1920, 1032),
    (1920, 1080),
    (2560, 1392),
)


def test_the_buttons_name_the_keys_of_the_mapping():
    m = APP_CONFIG.joystick
    assert welcome.start_label() == f"Inizia ({m.label_setup_confirm})"
    assert welcome.exit_label() == f"Esci ({m.label_setup_cancel})"
    for etichetta in (welcome.start_label(), welcome.exit_label()):
        assert "(Esc)" not in etichetta
        assert "(Invio)" not in etichetta


def test_the_cards_hold_their_text_at_every_window_size():
    try:
        for larghezza, altezza in _MISURE_FINESTRA:
            _inizia, esci = welcome.button_rects(larghezza, altezza)
            fonts_map, geometria = welcome._fit_layout(larghezza, altezza, esci.y)
            assert welcome._layout_fits(geometria, fonts_map), f"{larghezza}x{altezza}"
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_the_buttons_stay_inside_the_window_and_above_the_cards():
    try:
        for larghezza, altezza in _MISURE_FINESTRA:
            inizia, esci = welcome.button_rects(larghezza, altezza)
            assert inizia.right <= larghezza
            assert inizia.bottom <= altezza
            assert esci.right <= inizia.x
            _fonts_map, geometria = welcome._fit_layout(larghezza, altezza, esci.y)
            assert geometria["bottom"] <= esci.y * welcome._SUPERSAMPLE
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_the_banner_keeps_its_proportions_and_is_not_cropped():
    if welcome._logo_file() is None:
        return
    welcome._BANNER_CACHE.clear()
    originale = Image.open(welcome._logo_file())
    banner = welcome._logo_image(300)
    assert banner is not None
    assert banner.width == 300
    atteso = round(300 * originale.height / originale.width)
    assert abs(banner.height - atteso) <= 1
    assert banner.height < banner.width


def test_the_banner_asset_is_the_one_named_in_the_appearance():
    percorso = welcome._logo_file()
    if percorso is None:
        return
    assert "banner" in percorso.name


def test_without_the_asset_there_is_no_banner():
    originale = welcome.ASSETS_DIR
    welcome._BANNER_CACHE.clear()
    try:
        with tempfile.TemporaryDirectory() as vuota:
            welcome.ASSETS_DIR = Path(vuota)
            assert welcome._logo_file() is None
            assert welcome._logo_image(64) is None
    finally:
        welcome.ASSETS_DIR = originale
        welcome._BANNER_CACHE.clear()


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
