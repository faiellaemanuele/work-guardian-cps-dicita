from __future__ import annotations

import ast
import os
import pathlib
import sys
import types
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pygame

import drone.hardware.joystick as jt
from drone.config import APP_CONFIG


def _etichette() -> list[str]:
    m = APP_CONFIG.joystick
    return [
        m.label_takeoff, m.label_land, m.label_detection, m.label_autonomy,
        m.label_scenario, m.label_quit, m.label_axis_lr, m.label_axis_fb,
        m.label_axis_ud, m.label_axis_yaw,
    ]


def test_apply_deadzone_zeroes_below_threshold():
    assert jt._apply_deadzone(0.10, 0.15) == 0.0
    assert jt._apply_deadzone(-0.10, 0.15) == 0.0


def test_apply_deadzone_boundary_is_zero():
    assert jt._apply_deadzone(0.15, 0.15) == 0.0
    assert jt._apply_deadzone(-0.15, 0.15) == 0.0


def test_apply_deadzone_full_scale_preserved():
    assert abs(jt._apply_deadzone(1.0, 0.15) - 1.0) < 1e-9
    assert abs(jt._apply_deadzone(-1.0, 0.15) + 1.0) < 1e-9


def test_apply_deadzone_continuous_and_monotonic():
    dz = 0.15
    just_above = jt._apply_deadzone(dz + 1e-6, dz)
    assert 0.0 <= just_above < 1e-4
    a = jt._apply_deadzone(0.5, dz)
    b = jt._apply_deadzone(0.8, dz)
    assert 0.0 < a < b <= 1.0


def test_apply_deadzone_zero_deadzone_passthrough():
    assert abs(jt._apply_deadzone(0.42, 0.0) - 0.42) < 1e-9


def test_axis_to_speed_scales_and_clamps_speed():
    assert jt._axis_to_speed(1.0, 50) == 50
    assert jt._axis_to_speed(-1.0, 50) == -50
    assert jt._axis_to_speed(1.0, 250) == 100


def test_axis_to_speed_deadzone_gives_zero():
    small = jt.APP_CONFIG.joystick.deadzone / 2.0
    assert jt._axis_to_speed(small, 50) == 0


def test_escape_key_does_not_quit_during_flight():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    try:
        pygame.init()
        pygame.display.set_mode((64, 48))
    except Exception:
        return

    try:
        pygame.event.clear()
        pygame.event.post(
            pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
        )
        actions = jt.read_events()
        assert actions["quit"] is False
    finally:
        pygame.quit()


def test_labels_have_no_ambiguous_width_characters():
    for etichetta in _etichette():
        for carattere in etichetta:
            assert unicodedata.east_asian_width(carattere) != "A", (
                f"«{etichetta}» contiene {carattere!r}, di larghezza ambigua"
            )


def test_actions_are_verbs_like_the_onboard_functions():
    testo = " ".join(
        azione for _tasto, azione in jt.joystick_actions() + jt.joystick_axis_actions()
    ).lower()
    for verbo in ("decolla", "atterra", "attiva e disattiva", "chiude il programma",
                  "trasla", "avanza", "sale e scende", "ruota"):
        assert verbo in testo


def test_actions_use_the_words_of_the_program():
    azioni = dict(jt.joystick_actions())
    m = APP_CONFIG.joystick
    assert "riconoscimento" in azioni[m.label_detection]
    assert "volo autonomo" in azioni[m.label_autonomy]
    assert "scelta dello scenario" in azioni[m.label_scenario]
    testo = " ".join(azioni.values()).lower()
    assert "detection" not in testo
    assert "automatico" not in testo



class _JoystickFinto:
    def __init__(self, assi=(), instance_id=3, legacy_id=0):
        self._assi = list(assi)
        self._instance_id = instance_id
        self._legacy_id = legacy_id

    def get_instance_id(self):
        return self._instance_id

    def get_id(self):
        return self._legacy_id

    def get_numaxes(self):
        return len(self._assi)

    def get_axis(self, i):
        return self._assi[i]

    def quit(self):
        pass


def _evento(tipo, **campi):
    return types.SimpleNamespace(type=tipo, **campi)


def _azioni_per(eventi, joystick=None, controller_collegati=1):
    originale_get = pygame.event.get
    originale_count = pygame.joystick.get_count
    precedente = jt._JOYSTICK
    jt._JOYSTICK = joystick if joystick is not None else _JoystickFinto()
    pygame.event.get = lambda: list(eventi)
    pygame.joystick.get_count = lambda: controller_collegati
    try:
        azioni = jt.read_events()
    finally:
        pygame.event.get = originale_get
        pygame.joystick.get_count = originale_count
        jt._JOYSTICK = precedente
    return sorted(k for k, v in azioni.items() if v)


def _premuto(pulsante, instance_id=3):
    return _evento(pygame.JOYBUTTONDOWN, button=pulsante, instance_id=instance_id)


def test_ogni_pulsante_accende_solo_la_sua_azione():
    m = APP_CONFIG.joystick
    atteso = {
        m.button_takeoff: "takeoff",
        m.button_land: "land",
        m.button_detection: "detect",
        m.button_autonomy: "autonomy",
        m.button_quit: "quit",
    }
    for pulsante, azione in atteso.items():
        assert _azioni_per([_premuto(pulsante)]) == [azione], azione


def test_senza_eventi_non_si_accende_niente():
    assert _azioni_per([]) == []


def test_un_pulsante_non_mappato_non_fa_niente():
    assert _azioni_per([_premuto(99)]) == []


def test_con_un_solo_controller_gli_eventi_si_accettano_comunque():
    m = APP_CONFIG.joystick
    assert _azioni_per([_premuto(m.button_takeoff, instance_id=7)]) == ["takeoff"]


def test_con_due_controller_gli_eventi_dell_altro_vengono_ignorati():
    m = APP_CONFIG.joystick
    azioni = _azioni_per(
        [_premuto(m.button_takeoff, instance_id=7)], controller_collegati=2,
    )
    assert azioni == []


def test_con_due_controller_gli_eventi_del_nostro_valgono():
    m = APP_CONFIG.joystick
    azioni = _azioni_per(
        [_premuto(m.button_takeoff, instance_id=3)], controller_collegati=2,
    )
    assert azioni == ["takeoff"]


def test_due_pulsanti_insieme_accendono_due_azioni():
    m = APP_CONFIG.joystick
    azioni = _azioni_per([_premuto(m.button_takeoff), _premuto(m.button_detection)])
    assert azioni == ["detect", "takeoff"]


def test_chiudere_la_finestra_chiede_di_uscire():
    assert _azioni_per([_evento(pygame.QUIT)]) == ["quit"]


def test_staccare_il_joystick_chiede_di_uscire():
    assert _azioni_per([_evento(pygame.JOYDEVICEREMOVED, instance_id=3)]) == ["quit"]


def test_staccare_un_altro_controller_non_chiede_di_uscire():
    azioni = _azioni_per(
        [_evento(pygame.JOYDEVICEREMOVED, instance_id=7)], controller_collegati=2,
    )
    assert azioni == []


def _comando_con(assi, speed_pct=50):
    m = APP_CONFIG.joystick
    valori = [0.0] * 8
    for asse, valore in zip((m.axis_lr, m.axis_fb, m.axis_ud, m.axis_yaw), assi):
        valori[asse] = valore
    precedente = jt._JOYSTICK
    originale_pump = pygame.event.pump
    jt._JOYSTICK = _JoystickFinto(assi=valori)
    pygame.event.pump = lambda: None
    try:
        return jt.get_command(speed_pct)
    finally:
        pygame.event.pump = originale_pump
        jt._JOYSTICK = precedente


def test_il_joystick_fermo_da_un_comando_nullo():
    assert _comando_con((0.0, 0.0, 0.0, 0.0)) == {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}


def test_la_zona_morta_non_produce_comandi():
    assert _comando_con((0.05, 0.05, 0.05, 0.05)) == {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}


def test_ogni_asse_comanda_il_suo_canale():
    assert _comando_con((1.0, 0.0, 0.0, 0.0)) == {"lr": 50, "fb": 0, "ud": 0, "yaw": 0}
    assert _comando_con((0.0, -1.0, 0.0, 0.0)) == {"lr": 0, "fb": 50, "ud": 0, "yaw": 0}
    assert _comando_con((0.0, 0.0, -1.0, 0.0)) == {"lr": 0, "fb": 0, "ud": 50, "yaw": 0}
    assert _comando_con((0.0, 0.0, 0.0, 1.0)) == {"lr": 0, "fb": 0, "ud": 0, "yaw": 50}


def test_avanti_e_indietro_hanno_segni_opposti():
    avanti = _comando_con((0.0, -1.0, 0.0, 0.0))["fb"]
    indietro = _comando_con((0.0, 1.0, 0.0, 0.0))["fb"]
    assert avanti == -indietro > 0


def test_la_velocita_massima_scala_il_comando():
    assert _comando_con((1.0, 0.0, 0.0, 0.0), speed_pct=100)["lr"] == 100
    assert _comando_con((1.0, 0.0, 0.0, 0.0), speed_pct=20)["lr"] == 20


def test_l_asse_oltre_corsa_resta_al_massimo():
    assert _comando_con((2.0, 0.0, 0.0, 0.0))["lr"] == 50


def test_senza_joystick_il_comando_e_nullo():
    precedente = jt._JOYSTICK
    originale_pump = pygame.event.pump
    jt._JOYSTICK = None
    pygame.event.pump = lambda: None
    try:
        assert jt.get_command() == {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}
        assert jt.is_joystick_connected() is False
    finally:
        pygame.event.pump = originale_pump
        jt._JOYSTICK = precedente


def test_se_pygame_non_e_pronto_il_comando_e_nullo():
    precedente = jt._JOYSTICK
    originale_pump = pygame.event.pump

    def _rompe():
        raise pygame.error("video system not initialized")

    jt._JOYSTICK = _JoystickFinto(assi=[1.0] * 8)
    pygame.event.pump = _rompe
    try:
        assert jt.get_command() == {"lr": 0, "fb": 0, "ud": 0, "yaw": 0}
    finally:
        pygame.event.pump = originale_pump
        jt._JOYSTICK = precedente



_COPIE_NELLO_STRUMENTO = (
    "_get_event_controller_ids",
    "_event_matches_active_joystick",
)


def _definizione(percorso, nome):
    albero = ast.parse(pathlib.Path(percorso).read_text(encoding="utf-8"))
    return next(
        n for n in albero.body
        if isinstance(n, ast.FunctionDef) and n.name == nome
    )


def test_lo_strumento_di_diagnostica_tiene_una_copia_identica():
    radice = pathlib.Path(__file__).resolve().parent.parent.parent
    modulo = radice / "drone" / "hardware" / "joystick.py"
    strumento = radice / "drone" / "scripts" / "joystick_diagnostics.py"

    for nome in _COPIE_NELLO_STRUMENTO:
        assert ast.dump(_definizione(strumento, nome)) == ast.dump(_definizione(modulo, nome)), nome


def test_the_scenario_button_has_its_own_index():
    m = APP_CONFIG.joystick
    indici = [
        m.button_takeoff, m.button_land, m.button_detection,
        m.button_autonomy, m.button_scenario, m.button_quit,
    ]
    assert len(set(indici)) == len(indici)


def test_the_setup_buttons_do_not_collide_with_one_another():
    m = APP_CONFIG.joystick
    indici = [
        m.button_setup_select, m.button_setup_back,
        m.button_setup_confirm, m.button_setup_cancel,
        m.button_setup_up, m.button_setup_down,
    ]
    assert len(set(indici)) == len(indici)


def test_the_pad_does_not_collide_with_the_flight_buttons():
    m = APP_CONFIG.joystick
    volo = {
        m.button_takeoff, m.button_land, m.button_detection,
        m.button_autonomy, m.button_scenario, m.button_quit,
    }
    assert m.button_setup_up not in volo
    assert m.button_setup_down not in volo


def test_going_back_in_the_screens_is_the_same_button_as_the_scenario():
    m = APP_CONFIG.joystick
    assert m.button_setup_back == m.button_scenario
    assert m.label_setup_back == m.label_scenario


def _azione_setup(evento, controller_collegati=1):
    originale_count = pygame.joystick.get_count
    precedente = jt._JOYSTICK
    jt._JOYSTICK = _JoystickFinto()
    pygame.joystick.get_count = lambda: controller_collegati
    try:
        return jt.read_setup_action(evento)
    finally:
        pygame.joystick.get_count = originale_count
        jt._JOYSTICK = precedente


def test_the_setup_screens_read_their_own_buttons():
    m = APP_CONFIG.joystick
    atteso = {
        m.button_setup_confirm: "confirm",
        m.button_setup_cancel: "cancel",
        m.button_setup_back: "back",
        m.button_setup_select: "select",
        m.button_setup_up: "up",
        m.button_setup_down: "down",
    }
    for indice, azione in atteso.items():
        assert _azione_setup(_premuto(indice)) == azione, azione

    assert _azione_setup(_premuto(max(atteso) + 7)) is None


def test_the_setup_screens_navigate_with_the_hat():
    def hat(valore):
        return _evento(pygame.JOYHATMOTION, value=valore, instance_id=3)

    assert _azione_setup(hat((0, 1))) == "up"
    assert _azione_setup(hat((0, -1))) == "down"
    assert _azione_setup(hat((1, 0))) is None


def test_the_stick_no_longer_moves_the_focus():
    asse = APP_CONFIG.joystick.axis_fb

    def spinta(valore):
        return _evento(pygame.JOYAXISMOTION, axis=asse, value=valore, instance_id=3)

    assert _azione_setup(spinta(0.9)) is None
    assert _azione_setup(spinta(-0.9)) is None


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
