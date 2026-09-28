from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.ui.video.stdout_redirect import StdoutRedirect


def test_redirect_with_echo_forwards_to_original():
    righe: list[str] = []
    buf = io.StringIO()
    redirect = StdoutRedirect(buf, righe.append, echo_to_original=True)

    redirect.write("ciao\nmon")
    redirect.write("do\n")

    assert buf.getvalue() == "ciao\nmondo\n"
    assert righe == ["ciao", "mondo"]


def test_redirect_without_echo_keeps_the_original_untouched():
    righe: list[str] = []
    buf = io.StringIO()
    redirect = StdoutRedirect(buf, righe.append, echo_to_original=False)

    redirect.write("ciao\nmondo\n")

    assert buf.getvalue() == ""
    assert righe == ["ciao", "mondo"]


def test_redirect_echo_survives_non_utf8_console():
    raw = io.BytesIO()
    original = io.TextIOWrapper(raw, encoding="cp1252", newline="")
    righe: list[str] = []
    redirect = StdoutRedirect(original, righe.append, echo_to_original=True)

    redirect.write("═══ Sistema pronto ═══\n")
    original.flush()

    assert any("═══ Sistema pronto ═══" == line for line in righe)
    assert "Sistema pronto" in raw.getvalue().decode("cp1252")


def test_redirect_holds_partial_line_until_newline():
    righe: list[str] = []
    redirect = StdoutRedirect(io.StringIO(), righe.append, echo_to_original=False)

    redirect.write("senza newline")
    assert righe == []

    redirect.write("\n")
    assert righe == ["senza newline"]


def test_redirect_survives_a_failing_sink():
    def sink(line):
        raise RuntimeError("il pannello non c'è più")

    buf = io.StringIO()
    redirect = StdoutRedirect(buf, sink, echo_to_original=True)

    redirect.write("una riga\n")

    assert buf.getvalue() == "una riga\n"


def test_redirect_delegates_unknown_attributes_to_original():
    righe: list[str] = []
    buf = io.StringIO()
    redirect = StdoutRedirect(buf, righe.append, echo_to_original=True)
    redirect.write("x\n")
    assert redirect.getvalue() == "x\n"


def test_redirect_write_returns_length():
    righe: list[str] = []
    redirect = StdoutRedirect(io.StringIO(), righe.append)
    assert redirect.write("abc") == 3


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
