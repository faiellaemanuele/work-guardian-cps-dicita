from __future__ import annotations

import io
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import DashboardConfig
from drone.ui.video.dashboard import Dashboard
from common_doubles import FakeClock, MapWaypoint as _WP


def _dashboard(**overrides) -> Dashboard:
    config = replace(DashboardConfig(), **overrides)
    return Dashboard(config)


def _dashboard_with_clock(clock, render_interval_sec=0.2):
    return Dashboard(
        DashboardConfig(),
        render_interval_sec=render_interval_sec,
        time_source=clock,
    )


def _command(**overrides) -> dict:
    cmd = {
        "target_index": 2, "distance_xy": 0.37, "xy_tolerance_m": 0.15,
        "xy_ok": False, "z_ok": True, "yaw_ok": True,
        "reason": "tracking",
    }
    cmd.update(overrides)
    return cmd


class _CountingRender:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.original = dashboard._render_to_image
        self.calls = 0

        def counting(total_height):
            self.calls += 1
            return self.original(total_height)

        dashboard._render_to_image = counting


def test_set_autopilot_stores_command_and_marks_active():
    dash = _dashboard()
    assert dash._state_active is False
    dash.set_autopilot(_command())
    assert dash._state_active is True
    assert dash._autopilot_command["reason"] == "tracking"


def test_set_autopilot_copies_command():
    dash = _dashboard()
    cmd = _command()
    dash.set_autopilot(cmd)
    cmd["reason"] = "cambiato"
    assert dash._autopilot_command["reason"] == "tracking"


def test_set_autopilot_noop_when_disabled():
    dash = _dashboard(enabled=False)
    dash.set_autopilot(_command())
    assert dash._state_active is False
    assert dash._autopilot_command == {}


def test_clear_autopilot_marks_inactive_and_resets_command():
    dash = _dashboard()
    dash.set_autopilot(_command())
    assert dash._state_active is True
    dash.clear_autopilot()
    assert dash._state_active is False
    assert dash._autopilot_command == {}


def test_clear_autopilot_noop_when_disabled():
    dash = _dashboard(enabled=False)
    dash.clear_autopilot()
    assert dash._state_active is False


def test_autonomy_engaged_false_until_first_autopilot_command():
    dash = _dashboard()
    assert dash._autonomy_engaged is False
    dash.set_autopilot(_command())
    assert dash._autonomy_engaged is True


def test_autonomy_engaged_is_a_latch_and_survives_manual_control():
    dash = _dashboard()
    dash.set_autopilot(_command())
    dash.clear_autopilot()
    assert dash._state_active is False
    assert dash._autonomy_engaged is True


def test_autonomy_engaged_stays_false_when_disabled():
    dash = _dashboard(enabled=False)
    dash.set_autopilot(_command())
    assert dash._autonomy_engaged is False


def test_panels_buffer_lines_before_autonomy_is_engaged():
    dash = _dashboard()
    dash.log_terminal("19:27:03  ·  Decollo eseguito")
    dash.log_alert("19:27:10  !  AVVISO  Prova")
    assert dash._autonomy_engaged is False
    assert len(dash._terminal_lines) == 1
    assert len(dash._alert_lines) == 1


def test_clear_terminal_empties_buffer():
    dash = _dashboard()
    dash.log_terminal("riga di setup 1")
    dash.log_terminal("riga di setup 2")
    assert len(dash._terminal_lines) == 2
    dash.clear_terminal()
    assert len(dash._terminal_lines) == 0
    dash.log_terminal("Sistema pronto.")
    assert list(dash._terminal_lines) == ["Sistema pronto."]


def test_clear_terminal_noop_when_disabled():
    dash = _dashboard(enabled=False)
    dash.clear_terminal()
    assert len(dash._terminal_lines) == 0


def test_log_alert_appends_and_splits_lines():
    dash = _dashboard()
    dash.log_alert("10:00:00  !  Rilevata la caduta di una persona")
    dash.log_alert("riga uno\nriga due")
    assert len(dash._alert_lines) == 3
    assert dash._alert_lines[0].endswith("caduta di una persona")


def test_clear_alerts_empties_buffer():
    dash = _dashboard()
    dash.log_alert("allerta di setup")
    dash.clear_alerts()
    assert len(dash._alert_lines) == 0


def test_log_alert_noop_when_disabled():
    dash = _dashboard(enabled=False)
    dash.log_alert("allerta")
    assert len(dash._alert_lines) == 0


def test_make_stdout_redirect_never_echoes_to_shell():
    dash = _dashboard()
    buf = io.StringIO()
    redirect = dash.make_stdout_redirect(buf)

    redirect.write("ciao\nmondo\n")

    assert buf.getvalue() == ""
    assert list(dash._terminal_lines) == ["ciao", "mondo"]


class _Tag:
    def __init__(self, position_m):
        self.position_m = position_m


def test_set_visible_tags_lights_the_tags_on_the_map():
    dash = _dashboard()
    dash.configure_mission([_WP(0, 2.1), _WP(0, 0)], world_tags={8: _Tag((-2.04, 0.0, 1.5))})
    dash.set_visible_tags({8})
    assert dash._mission_map.visible_tag_ids() == {8}


def test_set_visible_tags_without_mission_is_ignored():
    dash = _dashboard()
    dash.set_visible_tags({8})
    assert dash._mission_map is None


def test_set_visible_tags_noop_when_disabled():
    dash = _dashboard(enabled=False)
    dash.configure_mission([_WP(0, 2.1), _WP(0, 0)], world_tags={8: _Tag((-2.04, 0.0, 1.5))})
    dash.set_visible_tags({8})
    assert dash._mission_map is None


def test_configure_mission_forwards_the_restricted_areas():
    dash = _dashboard()
    dash.configure_mission(
        [_WP(0, 2.1), _WP(0, 0)],
        restricted_areas=(((0.1, -0.12), (0.5, -0.12), (0.5, 0.18), (0.1, 0.18)),),
    )
    assert dash._mission_map.restricted_areas == (
        ((0.1, -0.12), (0.5, -0.12), (0.5, 0.18), (0.1, 0.18)),
    )


def test_render_to_image_has_requested_geometry():
    dash = _dashboard()
    dash.configure_mission(
        [_WP(0, 2.1), _WP(1.35, 0.3), _WP(0, 0)], home_index=2, yaw_offset_deg=180.0,
        site_area=((-0.9, 1.0), (0.9, 1.0), (0.9, -3.0), (-0.9, -3.0)),
        restricted_areas=(((0.1, -0.12), (0.5, -0.12), (0.5, 0.18), (0.1, 0.18)),),
        world_tags={
            0: _Tag((0.0, 0.0, 0.0)),
            8: _Tag((-2.04, 0.0, 1.5)),
            16: _Tag((0.6, 2.96, 1.5)),
        },
    )
    dash.set_autopilot(_command())
    dash.set_pose({"position_world": [[0.5], [0.5], [2.0]], "yaw_world_deg": 45.0}, fresh=True)
    dash.log_terminal("10:00:00  ·  Autopilota attivato")
    dash.log_alert("10:00:05  !  Rilevata la caduta di una persona")

    column = dash._render_to_image(960)
    assert column is not None
    assert column.shape == (960, dash.config.panel_width, 3)


def test_render_to_image_without_mission_shows_note_and_keeps_geometry():
    dash = _dashboard()
    column = dash._render_to_image(720)
    assert column is not None
    assert column.shape == (720, dash.config.panel_width, 3)


def test_render_to_image_survives_a_very_short_window():
    dash = _dashboard()
    column = dash._render_to_image(300)
    assert column is not None
    assert column.shape == (300, dash.config.panel_width, 3)


def test_set_scenario_name_stores_value():
    dash = _dashboard()
    assert dash._scenario_name is None
    dash.set_scenario_name("Verifica della sicurezza collettiva")
    assert dash._scenario_name == "Verifica della sicurezza collettiva"
    dash.set_scenario_name("")
    assert dash._scenario_name is None


def test_set_scenario_name_noop_when_disabled():
    dash = _dashboard(enabled=False)
    dash.set_scenario_name("Qualsiasi")
    assert dash._scenario_name is None


def test_render_map_header_with_scenario_keeps_geometry():
    dash = _dashboard()
    dash.set_scenario_name("Verifica della sicurezza collettiva")
    column = dash._render_to_image(720)
    assert column is not None
    assert column.shape == (720, dash.config.panel_width, 3)


def test_terminal_buffer_respects_maxlen():
    dash = _dashboard(max_lines=3)
    for i in range(10):
        dash.log_terminal(f"riga {i}")
    assert len(dash._terminal_lines) == 3
    assert dash._terminal_lines[-1] == "riga 9"
    assert dash._terminal_lines[0] == "riga 7"


def test_cruscotto_riusa_i_pannelli_entro_la_cadenza():
    clock = FakeClock()
    dash = _dashboard_with_clock(clock)
    contatore = _CountingRender(dash)

    primo = dash._panels_for_height(960)
    for _ in range(10):
        clock.advance(0.01)
        successivo = dash._panels_for_height(960)

    assert contatore.calls == 1, f"ridisegnato {contatore.calls} volte invece di 1"
    assert successivo is primo, "non è stata riusata la stessa immagine"


def test_cruscotto_ridisegna_scaduta_la_cadenza():
    clock = FakeClock()
    dash = _dashboard_with_clock(clock)
    contatore = _CountingRender(dash)

    dash._panels_for_height(960)
    clock.advance(0.25)
    dash._panels_for_height(960)
    assert contatore.calls == 2


def test_cruscotto_ridisegna_subito_se_cambia_altezza():
    clock = FakeClock()
    dash = _dashboard_with_clock(clock)
    contatore = _CountingRender(dash)

    dash._panels_for_height(960)
    clock.advance(0.01)
    pannelli = dash._panels_for_height(720)
    assert contatore.calls == 2
    assert pannelli.shape[0] == 720


def test_cruscotto_senza_cadenza_ridisegna_sempre():
    clock = FakeClock()
    dash = _dashboard_with_clock(clock, render_interval_sec=0.0)
    contatore = _CountingRender(dash)

    for _ in range(5):
        dash._panels_for_height(960)
    assert contatore.calls == 5



def test_una_riga_che_arriva_mentre_si_disegna_non_rompe_il_pannello():
    from drone.ui.video import panels

    dash = _dashboard()
    dash.set_autopilot(_command())
    for i in range(5):
        dash.log_terminal(f"riga {i}")

    originale = panels.terminal_line_color

    def _colore_che_scrive(line):
        dash.log_terminal("riga dal thread di riconoscimento")
        return originale(line)

    panels.terminal_line_color = _colore_che_scrive
    try:
        colonna = dash._render_to_image(720)
    finally:
        panels.terminal_line_color = originale

    assert colonna is not None
    assert colonna.shape == (720, dash.config.panel_width, 3)


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
