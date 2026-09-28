from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PIL import Image

from drone.config import APP_CONFIG
from drone.hardware.joystick import (
    joystick_action_groups,
    joystick_actions,
    joystick_axis_actions,
    joystick_axis_details,
)
from drone.ui import fonts
from drone.ui.setup import screens, welcome


def test_the_welcome_screen_is_exported():
    assert callable(welcome.show_welcome_screen)


def test_the_description_names_the_three_parts_of_the_system():
    testo = welcome.PLATFORM_TEXT.lower()
    assert "drone" in testo
    assert "wearable device" in testo
    assert "central control station" in testo


def test_the_notes_explain_the_battery_and_the_saved_data():
    titoli = [titolo for titolo, _ in welcome.NOTES]
    corpi = " ".join(testo for _, testo in welcome.NOTES).lower()
    assert any("batteria" in t.lower() for t in titoli)
    assert any("dati" in t.lower() for t in titoli)
    assert str(APP_CONFIG.battery_rth_pct) in corpi
    assert str(APP_CONFIG.battery_critical_pct) in corpi


def test_every_note_has_its_icon():
    icone = welcome._note_icons()
    assert len(icone) == len(welcome.NOTES)
    assert icone[:2] == ["battery", "save"]


def test_the_note_icons_stay_inside_their_square():
    lato = 80
    for disegna in (welcome._draw_battery_icon, welcome._draw_save_icon):
        img = Image.new("RGB", (200, 200), (0, 0, 0))
        disegna(img, 100, 100, lato, (255, 255, 255))
        riquadro = img.getbbox()
        assert riquadro is not None, disegna.__name__
        assert 100 - lato / 2 <= riquadro[0] and riquadro[2] <= 100 + lato / 2, disegna.__name__
        assert 100 - lato / 2 <= riquadro[1] and riquadro[3] <= 100 + lato / 2, disegna.__name__


def test_the_welcome_has_no_colors_of_its_own():
    sorgente = pathlib.Path(welcome.__file__).read_text(encoding="utf-8")
    colori = re.findall(r"\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)", sorgente)
    assert colori == ["(255, 255, 255)", "(255, 255, 255)"]


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
        tasto: welcome._GLYPH_SHAPES.get(tasto)
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


def test_the_sticks_sit_between_the_face_buttons_and_the_session_keys():
    try:
        inizia, esci = welcome.button_rects(1920, 1080)
        fonts_map, geometria = welcome._fit_layout(1920, 1080, esci, inizia)
        _sinistra, destra = welcome._card_boxes(geometria)
        elementi, _colonne, _ci_sta = welcome._commands_layout(destra, fonts_map)
    finally:
        welcome._LAYOUT_SCALE = 1.0

    sessione = [tasto for tasto, _azione in joystick_action_groups()[-1][1]]
    assi = [lato for lato, _verso, _azione in joystick_axis_details()]
    nomi = [nome for _cy, nome, _linee, _lato in elementi]
    lati = [lato for _cy, _nome, _linee, lato in elementi]
    assert nomi[-len(sessione):] == sessione
    assert lati[-len(sessione) - len(assi):-len(sessione)] == assi
    assert all(lato is None for lato in lati[:-len(sessione) - len(assi)])
    altezze = [cy for cy, _nome, _linee, _lato in elementi]
    assert altezze == sorted(altezze)


def test_the_commands_line_up_with_the_text_and_start_right_after_the_symbols():
    try:
        inizia, esci = welcome.button_rects(1536, 793)
        fonts_map, geometria = welcome._fit_layout(1536, 793, esci, inizia)
        sinistra, destra = welcome._card_boxes(geometria)
        righe, _note, _ci_sta = welcome._platform_layout(sinistra, fonts_map)
        elementi, colonne, _ci_sta = welcome._commands_layout(destra, fonts_map)
        assert elementi[0][0] - destra[1] == righe[0][1] - sinistra[1]
        assert colonne["colonna"] - destra[0] == righe[0][0] - sinistra[0]
        assert colonne["azione_x"] == (
            colonne["colonna"] + colonne["simbolo_w"] + welcome._scale(welcome._ACTION_GAP)
        )
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_the_commands_are_evenly_spaced_and_end_where_the_notes_end():
    try:
        inizia, esci = welcome.button_rects(1536, 793)
        fonts_map, geometria = welcome._fit_layout(1536, 793, esci, inizia)
        sinistra, destra = welcome._card_boxes(geometria)
        _righe, note, _ci_sta = welcome._platform_layout(sinistra, fonts_map)
        elementi, colonne, _ci_sta = welcome._commands_layout(destra, fonts_map)
        assert all(len(linee) == 1 for _cy, _nome, linee, _lato in elementi)
        centri = [cy for cy, _nome, _linee, _lato in elementi]
        passi = [b - a for a, b in zip(centri, centri[1:])]
        assert max(passi) - min(passi) < 1e-6
        fondo_note = note[-1][0][3] - sinistra[3]
        fondo_comandi = centri[-1] + colonne["raggio"] - destra[3]
        assert abs(fondo_note - fondo_comandi) < 1e-6
    finally:
        welcome._LAYOUT_SCALE = 1.0


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
    assert welcome.start_label() == f"Avanti ({m.label_setup_confirm})"
    assert welcome.exit_label() == f"Esci ({m.label_setup_cancel})"
    assert welcome.start_label() == screens._button_label(screens.NEXT_TEXT, m.label_setup_confirm)
    assert welcome.exit_label() == screens._button_label(screens.EXIT_TEXT, m.label_setup_cancel)
    for etichetta in (welcome.start_label(), welcome.exit_label()):
        assert "(Esc)" not in etichetta
        assert "(Invio)" not in etichetta


def test_the_cards_hold_their_text_at_every_window_size():
    try:
        for larghezza, altezza in _MISURE_FINESTRA:
            inizia, esci = welcome.button_rects(larghezza, altezza)
            fonts_map, geometria = welcome._fit_layout(larghezza, altezza, esci, inizia)
            assert welcome._layout_fits(geometria, fonts_map), f"{larghezza}x{altezza}"
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_on_the_pilot_window_the_text_is_not_shrunk():
    try:
        inizia, esci = welcome.button_rects(1536, 793)
        welcome._fit_layout(1536, 793, esci, inizia)
        assert welcome._LAYOUT_SCALE == welcome._base_layout_scale(1536, 793)
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_on_the_pilot_window_every_note_takes_one_line():
    try:
        inizia, esci = welcome.button_rects(1536, 793)
        fonts_map, geometria = welcome._fit_layout(1536, 793, esci, inizia)
        sinistra, _destra = welcome._card_boxes(geometria)
        _righe, note, _ci_sta = welcome._platform_layout(sinistra, fonts_map)
        assert [len(corpo) for _box, _titolo, corpo, _icona in note] == [1] * len(welcome.NOTES)
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_at_the_reference_size_the_text_shrinks_at_most_one_step():
    try:
        inizia, esci = welcome.button_rects(1920, 1080)
        welcome._fit_layout(1920, 1080, esci, inizia)
        assert welcome._LAYOUT_SCALE >= 0.94
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_the_buttons_stay_inside_the_window_and_above_the_cards():
    try:
        for larghezza, altezza in _MISURE_FINESTRA:
            inizia, esci = welcome.button_rects(larghezza, altezza)
            assert inizia.right <= larghezza
            assert inizia.bottom <= altezza
            assert esci.x > 0
            assert esci.right <= inizia.x
            _fonts_map, geometria = welcome._fit_layout(larghezza, altezza, esci, inizia)
            assert geometria["bottom"] <= esci.y * welcome._SUPERSAMPLE
    finally:
        welcome._LAYOUT_SCALE = 1.0


def test_the_buttons_sit_where_the_scenario_screen_puts_them():
    for larghezza, altezza in _MISURE_FINESTRA:
        inizia, esci = welcome.button_rects(larghezza, altezza)
        conferma, annulla, _indietro = screens.footer_rects(larghezza, altezza)
        assert (inizia, esci) == (conferma, annulla), f"{larghezza}x{altezza}"


def test_exit_sits_on_the_left_and_start_on_the_right():
    inizia, esci = welcome.button_rects(1920, 1080)
    assert esci.centerx < 1920 / 2 < inizia.centerx


def test_the_banner_fills_the_requested_band():
    if welcome._logo_file() is None:
        return
    welcome._BANNER_CACHE.clear()
    banner = welcome._banner_image(900, 100)
    assert banner is not None
    assert banner.size == (900, 100)
    piu_scuro, _piu_chiaro = banner.convert("L").getextrema()
    assert piu_scuro < 200


def test_the_banner_is_reused_for_the_same_size():
    if welcome._logo_file() is None:
        return
    welcome._BANNER_CACHE.clear()
    primo = welcome._banner_image(600, 70)
    assert welcome._banner_image(600, 70) is primo
    welcome._banner_image(640, 70)
    assert len(welcome._BANNER_CACHE) == 1
    welcome._BANNER_CACHE.clear()


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
            assert welcome._banner_image(64, 16) is None
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
