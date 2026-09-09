from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.hardware.joystick import joystick_actions, joystick_axis_actions
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


def test_the_logo_is_masked_into_a_circle():
    if welcome._logo_file() is None:
        return
    welcome._LOGO_CACHE.clear()
    logo = welcome._logo_image(64)
    assert logo is not None
    assert logo.size == (64, 64)
    assert logo.mode == "RGBA"
    assert logo.getpixel((1, 1))[3] == 0
    assert logo.getpixel((32, 32))[3] == 255


def test_without_the_asset_there_is_no_logo():
    originale = welcome.ASSETS_DIR
    welcome._LOGO_CACHE.clear()
    try:
        with tempfile.TemporaryDirectory() as vuota:
            welcome.ASSETS_DIR = Path(vuota)
            assert welcome._logo_file() is None
            assert welcome._logo_image(64) is None
    finally:
        welcome.ASSETS_DIR = originale
        welcome._LOGO_CACHE.clear()


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
