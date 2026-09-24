from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.ui import fonts


def test_le_tre_famiglie_rispondono():
    for font in (fonts.sans(18), fonts.sans_bold(18), fonts.mono(18)):
        assert font is not None
        assert font.getlength("prova") > 0


def test_stessa_dimensione_stesso_oggetto():
    assert fonts.sans(20) is fonts.sans(20)
    assert fonts.mono(20) is fonts.mono(20)
    assert fonts.sans(20) is not fonts.sans(21)


def test_le_famiglie_non_si_confondono():
    assert fonts.sans(24).path != fonts.sans_bold(24).path
    assert fonts.sans(24).path != fonts.mono(24).path


def test_il_grassetto_e_piu_largo_del_tondo():
    assert fonts.sans_bold(40).getlength("Waypoint") > fonts.sans(40).getlength("Waypoint")


def test_il_monospazio_ha_caratteri_di_pari_larghezza():
    font = fonts.mono(18)
    assert font.getlength("0") == font.getlength("W")


def test_una_famiglia_sconosciuta_non_e_ammessa():
    try:
        fonts._load("corsivo", 18)
    except KeyError:
        return
    raise AssertionError("una famiglia inesistente dovrebbe fallire subito")


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
