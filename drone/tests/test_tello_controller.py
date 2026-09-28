from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.hardware.tello_controller import (
    RealTelloController,
    _DjiDecodeNoiseFilter,
    _silence_djitellopy_logging,
)


class FakeTello:
    def __init__(self, battery: int = 100, height=0):
        self._battery = battery
        self._height = height
        self.takeoff_called = False
        self.land_called = False
        self.battery_reads = 0
        self.height_reads = 0

    @staticmethod
    def _next(value):
        if isinstance(value, list):
            return value.pop(0) if len(value) > 1 else value[0]
        return value

    def get_battery(self):
        self.battery_reads += 1
        return self._next(self._battery)

    def get_height(self):
        self.height_reads += 1
        height = self._next(self._height)
        if height is None:
            return None
        return height

    def takeoff(self):
        self.takeoff_called = True

    def land(self):
        self.land_called = True

    def send_rc_control(self, lr, fb, ud, yaw):
        self.last_rc = (lr, fb, ud, yaw)


def make_controller(*, connected=True, flying=False, min_batt=0, battery=100, height=0):
    c = object.__new__(RealTelloController)
    c.tello = FakeTello(battery=battery, height=height)
    c.frame_reader = None
    c.is_connected = connected
    c.is_flying = flying
    c.min_takeoff_battery_pct = min_batt
    return c


def _decode_error() -> UnicodeDecodeError:
    try:
        b"\xcc\x01\x02".decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc
    raise AssertionError("la decodifica avrebbe dovuto fallire")


def _record(msg) -> logging.LogRecord:
    return logging.LogRecord(
        name="djitellopy", level=logging.ERROR, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


def test_takeoff_blocked_when_battery_below_threshold():
    c = make_controller(connected=True, flying=False, min_batt=20, battery=15, height=0)
    assert c.takeoff() is False
    assert c.is_flying is False
    assert c.tello.takeoff_called is False


def test_takeoff_allowed_when_battery_sufficient():
    c = make_controller(connected=True, flying=False, min_batt=20, battery=50, height=0)
    assert c.takeoff() is True
    assert c.is_flying is True
    assert c.tello.takeoff_called is True


def test_takeoff_blocked_when_not_connected():
    c = make_controller(connected=False, flying=False, min_batt=20, battery=50)
    assert c.takeoff() is False
    assert c.tello.takeoff_called is False


def test_takeoff_threshold_zero_disables_battery_check():
    c = make_controller(connected=True, flying=False, min_batt=0, battery=1, height=0)
    assert c.takeoff() is True
    assert c.tello.takeoff_called is True


def test_takeoff_resyncs_state_when_already_airborne():
    c = make_controller(connected=True, flying=False, min_batt=20, battery=10, height=100)
    assert c.takeoff() is True
    assert c.is_flying is True
    assert c.tello.takeoff_called is False


def test_takeoff_proceeds_when_airborne_reading_not_confirmed():
    c = make_controller(connected=True, flying=False, min_batt=0, battery=50, height=[100, 0])
    assert c.takeoff() is True
    assert c.is_flying is True
    assert c.tello.takeoff_called is True


def test_takeoff_blocked_when_battery_read_fails():
    c = make_controller(connected=True, flying=False, min_batt=20, battery=50, height=0)

    def _raise():
        raise RuntimeError("batteria non leggibile")

    c.tello.get_battery = _raise
    assert c.takeoff() is False
    assert c.is_flying is False
    assert c.tello.takeoff_called is False


def test_takeoff_allowed_when_battery_read_recovers():
    c = make_controller(connected=True, flying=False, min_batt=20, battery=50, height=0)
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("timeout SDK transitorio")
        return 50

    c.tello.get_battery = _flaky
    assert c.takeoff() is True
    assert c.tello.takeoff_called is True


def test_takeoff_noop_when_already_flying():
    c = make_controller(connected=True, flying=True, min_batt=20, battery=50, height=80)
    assert c.takeoff() is False
    assert c.tello.takeoff_called is False


def test_get_height_cm_returns_int():
    c = make_controller(connected=True, height=42)
    assert c.get_height_cm() == 42


def test_get_height_cm_none_when_disconnected():
    c = make_controller(connected=False, height=42)
    assert c.get_height_cm() is None


def test_get_height_cm_none_on_unreadable_value():
    c = make_controller(connected=True, height=None)
    assert c.get_height_cm() is None


def test_land_resyncs_state_when_telemetry_says_airborne():
    c = make_controller(connected=True, flying=False, height=100)

    assert c.land() is True
    assert c.tello.land_called is True
    assert c.is_flying is False


def test_land_still_refused_when_really_grounded():
    c = make_controller(connected=True, flying=False, height=0)

    assert c.land() is False
    assert c.tello.land_called is False


def test_notify_landed_resyncs_flying_flag():
    c = make_controller(connected=True, flying=True)
    c.notify_landed_externally()
    assert c.is_flying is False


def test_notify_landed_idempotent_when_already_grounded():
    c = make_controller(connected=True, flying=False)
    c.notify_landed_externally()
    assert c.is_flying is False


def test_filter_drops_unicode_decode_error():
    assert _DjiDecodeNoiseFilter().filter(_record(_decode_error())) is False


def test_filter_keeps_real_string_error():
    assert _DjiDecodeNoiseFilter().filter(_record("Errore reale di connessione")) is True


def test_silence_installs_filter_and_suppresses_noise():
    captured: list[str] = []

    class _Probe(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    root = logging.getLogger()
    probe = _Probe()
    root.addHandler(probe)
    previous_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        _silence_djitellopy_logging()
        dji = logging.getLogger("djitellopy")
        dji.error(_decode_error())
        dji.error("Errore reale di connessione")
    finally:
        root.removeHandler(probe)
        root.setLevel(previous_level)

    assert all("codec" not in m for m in captured)
    assert any("Errore reale" in m for m in captured)


def test_silence_is_idempotent():
    _silence_djitellopy_logging()
    _silence_djitellopy_logging()
    dji = logging.getLogger("djitellopy")
    assert sum(isinstance(f, _DjiDecodeNoiseFilter) for f in dji.filters) == 1



def test_la_batteria_esattamente_alla_soglia_rifiuta_il_decollo():
    c = make_controller(min_batt=30, battery=30)

    assert c.takeoff() is False
    assert c.is_flying is False
    assert c.tello.takeoff_called is False


def test_la_batteria_appena_sopra_la_soglia_fa_decollare():
    c = make_controller(min_batt=30, battery=31)

    assert c.takeoff() is True
    assert c.is_flying is True
    assert c.tello.takeoff_called is True


def test_senza_soglia_la_batteria_non_viene_nemmeno_letta():
    c = make_controller(min_batt=0, battery=5)

    assert c.takeoff() is True
    assert c.tello.takeoff_called is True
    assert c.tello.battery_reads == 0


def test_l_altezza_esattamente_alla_soglia_non_conta_come_in_volo():
    c = make_controller(height=RealTelloController._AIRBORNE_HEIGHT_CM)

    assert c.takeoff() is True
    assert c.tello.takeoff_called is True
    assert c.tello.height_reads == 1


def test_l_altezza_appena_sopra_la_soglia_riallinea_lo_stato():
    c = make_controller(height=RealTelloController._AIRBORNE_HEIGHT_CM + 1)

    assert c.takeoff() is True
    assert c.is_flying is True
    assert c.tello.takeoff_called is False


def test_i_comandi_rc_fuori_scala_vengono_tosati():
    c = make_controller(flying=True)

    c.send_rc_control(500, -500, 101, -101)

    assert c.tello.last_rc == (100, -100, 100, -100)


def test_i_comandi_rc_dentro_la_scala_passano_intatti():
    c = make_controller(flying=True)

    c.send_rc_control(50, -50, 20, -20)

    assert c.tello.last_rc == (50, -50, 20, -20)


def test_gli_estremi_della_scala_restano_gli_estremi():
    c = make_controller(flying=True)

    c.send_rc_control(100, -100, 0, 0)

    assert c.tello.last_rc == (100, -100, 0, 0)


def test_da_disconnesso_non_si_inviano_comandi_rc():
    c = make_controller(connected=False, flying=True)

    c.send_rc_control(50, 50, 50, 50)

    assert not hasattr(c.tello, "last_rc")


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
