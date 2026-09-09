from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.flight import postflight
from drone.flight.postflight import release_mission, run_postflight
from drone.flight.preflight import Subsystems


class _Registro:
    def __init__(self):
        self.passi: list[str] = []


class _Controller:
    def __init__(self, registro, *, flying=True, rompe=frozenset()):
        self._registro = registro
        self.is_flying = flying
        self._rompe = rompe

    def _passo(self, nome):
        self._registro.passi.append(nome)
        if nome in self._rompe:
            raise RuntimeError(nome)

    def send_rc_control(self, lr, fb, ud, yaw):
        self._passo("rc_zero" if (lr, fb, ud, yaw) == (0, 0, 0, 0) else "rc")

    def land(self):
        self._passo("land")
        self.is_flying = False

    def end(self):
        self._passo("end")


class _VisionLoop:
    def __init__(self, registro):
        self._registro = registro

    def stop(self):
        self._registro.passi.append("vision_stop")


class _PilotCommands:
    def __init__(self, *, atterrato_dal_pilota=False):
        self._atterrato = atterrato_dal_pilota

    def landed_by_pilot(self):
        return self._atterrato


class _Dashboard:
    def __init__(self, registro):
        self._registro = registro

    def close(self):
        self._registro.passi.append("dashboard_close")


class _Logger:
    def __init__(self, registro, *, dati=False):
        self._registro = registro
        self._dati = dati

    def has_data(self):
        return self._dati

    def export_session(self, **kwargs):
        self._registro.passi.append("export")
        return None

    def get_summary(self):
        return "riassunto"


def _esegui(subsystems) -> _Registro:
    registro = subsystems._registro
    originali = (postflight.cv2, postflight.pygame, postflight.close_joystick)
    stdout_originale = sys.stdout
    postflight.cv2 = type("_Cv2", (), {"destroyAllWindows": staticmethod(lambda: None)})
    postflight.pygame = type("_Pygame", (), {"quit": staticmethod(lambda: None)})
    postflight.close_joystick = lambda: None
    try:
        run_postflight(subsystems, io.StringIO())
    finally:
        postflight.cv2, postflight.pygame, postflight.close_joystick = originali
        sys.stdout = stdout_originale
    return registro


def _subsystems(**over) -> Subsystems:
    registro = _Registro()
    s = Subsystems()
    s.controller = _Controller(registro, flying=over.get("flying", True))
    s.vision_loop = _VisionLoop(registro)
    s.dashboard = _Dashboard(registro)
    s.flight_data_logger = _Logger(registro, dati=over.get("dati", False))
    s.pilot_commands = _PilotCommands(
        atterrato_dal_pilota=over.get("atterrato_dal_pilota", False)
    )
    s._registro = registro
    return s


def test_prima_si_mette_in_sicurezza_il_drone_poi_si_fermano_i_thread():
    registro = _esegui(_subsystems())

    passi = registro.passi
    assert passi.index("rc_zero") < passi.index("vision_stop")
    assert passi.index("land") < passi.index("vision_stop")


def test_i_comandi_si_azzerano_prima_di_atterrare():
    registro = _esegui(_subsystems())

    assert registro.passi.index("rc_zero") < registro.passi.index("land")


def test_la_connessione_si_chiude_solo_alla_fine():
    registro = _esegui(_subsystems())

    passi = registro.passi
    assert passi.index("vision_stop") < passi.index("end")


def test_a_terra_non_si_atterra_di_nuovo():
    registro = _esegui(_subsystems(flying=False))

    assert "land" not in registro.passi
    assert "rc_zero" in registro.passi
    assert "end" in registro.passi


def test_un_atterraggio_che_fallisce_non_ferma_la_chiusura():
    registro = _Registro()
    s = Subsystems()
    s.controller = _Controller(registro, rompe={"land"})
    s.vision_loop = _VisionLoop(registro)
    s.dashboard = _Dashboard(registro)
    s._registro = registro

    _esegui(s)

    assert "vision_stop" in registro.passi
    assert "end" in registro.passi
    assert "dashboard_close" in registro.passi


def test_senza_sottosistemi_la_chiusura_non_esplode():
    s = Subsystems()
    s._registro = _Registro()

    _esegui(s)


def test_i_dati_di_volo_si_salvano_dopo_aver_messo_in_sicurezza_il_drone():
    registro = _esegui(_subsystems(dati=True))

    passi = registro.passi
    assert "export" in passi
    assert passi.index("land") < passi.index("export")


def test_senza_dati_non_si_esporta_niente():
    registro = _esegui(_subsystems(dati=False))

    assert "export" not in registro.passi


def test_un_atterraggio_del_pilota_chiude_senza_salvare():
    registro = _esegui(_subsystems(dati=True, atterrato_dal_pilota=True, flying=False))

    assert "export" not in registro.passi
    assert "end" in registro.passi


def test_il_rilascio_ferma_il_riconoscimento_e_azzera_i_comandi():
    s = _subsystems(flying=False, dati=True)
    registro = s._registro
    originale = postflight.cv2
    postflight.cv2 = type(
        "_Cv2", (), {"destroyAllWindows": staticmethod(lambda: None), "error": Exception},
    )
    try:
        release_mission(s)
    finally:
        postflight.cv2 = originale

    assert registro.passi == ["rc_zero", "vision_stop"]
    assert "export" not in registro.passi


def test_il_rilascio_non_atterra_e_non_chiude_il_drone():
    s = _subsystems(flying=False)
    registro = s._registro
    originale = postflight.cv2
    postflight.cv2 = type(
        "_Cv2", (), {"destroyAllWindows": staticmethod(lambda: None), "error": Exception},
    )
    try:
        release_mission(s)
    finally:
        postflight.cv2 = originale

    assert "land" not in registro.passi
    assert "end" not in registro.passi
    assert s.controller is not None


def test_il_rilascio_svuota_i_sottosistemi_della_missione():
    s = _subsystems(flying=False)
    originale = postflight.cv2
    postflight.cv2 = type(
        "_Cv2", (), {"destroyAllWindows": staticmethod(lambda: None), "error": Exception},
    )
    try:
        release_mission(s)
    finally:
        postflight.cv2 = originale

    assert s.vision_loop is None
    assert s.pilot_commands is None
    assert s.flight_data_logger is None
    assert s.apriltag_autopilot is None
    assert s.scenario_name is None


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
