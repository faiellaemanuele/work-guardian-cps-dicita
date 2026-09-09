from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG
from drone.ui import fonts
from drone.ui.video import panels
from drone.ui.video.mission_map import LEGEND_SCENE, LEGEND_WAYPOINTS


def test_log_line_short_enough_is_left_alone():
    riga = "10:06:19  !  Una persona in un'area vietata"
    assert panels._layout_log_line(riga, 60) == [(riga, False)]


def test_log_line_too_long_wraps_instead_of_truncating():
    riga = "10:06:19  !  " + ("molto lunga " * 5).strip()
    righe = panels._layout_log_line(riga, 30)
    assert len(righe) > 1
    assert all(len(testo) <= 30 for testo, _ in righe)
    assert not any(testo.endswith("…") for testo, _ in righe)
    assert righe[0][1] is False
    assert all(rientrata for _, rientrata in righe[1:])


def test_wrapped_log_line_keeps_the_whole_message():
    riga = "10:06:42  ×  Rete di sicurezza mancante al waypoint 11"
    righe = panels._layout_log_line(riga, 25)
    assert righe[0][0].startswith("10:06:42  ×  Rete")
    ricomposta = " ".join(testo for testo, _ in righe)
    assert ricomposta == riga


def test_wrap_text_short_line_unchanged():
    assert panels._wrap_text("riga corta", 40) == ["riga corta"]


def test_wrap_text_wraps_on_spaces_within_limit():
    pieces = panels._wrap_text("alfa beta gamma delta", 10)
    assert all(len(p) <= 10 for p in pieces)
    assert " ".join(pieces) == "alfa beta gamma delta"


def test_wrap_text_hard_breaks_long_token():
    path = "C:/Users/faiel/Desktop/DJI_volo_2/drone/flight_sessions/log.txt"
    pieces = panels._wrap_text(path, 12)
    assert all(len(p) <= 12 for p in pieces)
    assert "".join(pieces) == path


def test_alert_line_color_by_glyph():
    def line(glyph):
        return f"12:00:00  {glyph}  messaggio"

    assert panels.alert_line_color(line("×")) == panels._NEG
    assert panels.alert_line_color(line("!")) == panels._WARN
    assert panels.alert_line_color(line("•")) == panels._ACCENT
    assert panels.alert_line_color(line("·")) == panels._TEXT


def test_terminal_line_color_ignores_the_alert_glyph():
    def line(glyph):
        return f"12:00:00  {glyph}  messaggio"

    assert panels.terminal_line_color(line("×")) == panels._NEG
    assert panels.terminal_line_color(line("!")) == panels._WARN
    assert panels.terminal_line_color(line("•")) == panels._TEXT


def test_truncate_to_width_adds_ellipsis_and_fits():
    font = fonts.mono(16)
    truncated = panels._truncate_to_width("x" * 500, font, 100)
    assert truncated.endswith("…")
    assert font.getlength(truncated) <= 100
    assert panels._truncate_to_width("breve", font, 1000) == "breve"
    assert panels._truncate_to_width("x", font, 0) == ""


def test_the_legend_fits_the_information_column():
    font = fonts.mono(panels._LEGEND_FONT)
    larghezza = (
        2 * panels._LEGEND_PAD_X + panels._LEGEND_COL_GAP
        + panels._legend_column_width(LEGEND_WAYPOINTS, font)
        + panels._legend_column_width(LEGEND_SCENE, font)
    )
    assert larghezza <= APP_CONFIG.dashboard.map_info_col_width


def test_the_information_column_fits_the_map_panel():
    config = APP_CONFIG.dashboard
    altezza_pannello = config.video_size[1] - config.gap_px - config.log_row_height
    altezza_mappa = (
        altezza_pannello - panels._HEADER_H - 2 * panels._MAP_PAD
        - panels._disclaimer_h(config.panel_width)
    )
    altezza_colonna = (
        panels._TIMER_H + panels._RAIL_GAP + panels._tolerance_card_h()
        + panels._RAIL_GAP + panels._map_legend_h()
    )
    assert altezza_colonna <= altezza_mappa


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
