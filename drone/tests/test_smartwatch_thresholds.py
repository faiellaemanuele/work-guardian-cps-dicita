from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from drone.config import APP_CONFIG

# Le soglie biometriche le decide il firmware; SmartwatchThresholdsConfig ne
# tiene una copia per i grafici e il pannello dell'orologio. Questi test
# falliscono se le due copie divergono.
_FIRMWARE = Path(__file__).resolve().parents[2] / "wearable" / "smartwatch" / "smartwatch.ino"


def _firmware_constant(name: str) -> int:
    testo = _FIRMWARE.read_text(encoding="utf-8")
    trovata = re.search(rf"const\s+int\s+{name}\s*=\s*(\d+)\s*;", testo)
    assert trovata is not None, f"{name} non compare nel firmware"
    return int(trovata.group(1))


def test_soglie_di_ingresso_uguali_al_firmware():
    soglie = APP_CONFIG.smartwatch_thresholds
    assert soglie.bpm_min_in == _firmware_constant("BPM_MIN_IN")
    assert soglie.bpm_max_in == _firmware_constant("BPM_MAX_IN")
    assert soglie.spo2_min_in == _firmware_constant("SPO2_MIN_IN")


def test_soglie_di_uscita_uguali_al_firmware():
    soglie = APP_CONFIG.smartwatch_thresholds
    assert soglie.bpm_min_out == _firmware_constant("BPM_MIN_OUT")
    assert soglie.bpm_max_out == _firmware_constant("BPM_MAX_OUT")
    assert soglie.spo2_min_out == _firmware_constant("SPO2_MIN_OUT")


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
