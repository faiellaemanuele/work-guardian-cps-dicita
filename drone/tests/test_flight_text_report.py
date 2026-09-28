from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from flight_log_samples import (
    logger_with_autopilot_data,
    logger_with_comparison_data,
    logger_with_pose_loss,
)


def test_autopilot_text_has_extended_stats():
    log = logger_with_autopilot_data()
    with tempfile.TemporaryDirectory() as d:
        paths = log.save_all_text_files(d)
        assert paths
        text = Path(paths[0]).read_text(encoding="utf-8")
    assert "Statistiche avanzate autopilota" in text
    assert "RMS distanza XY" in text
    assert "Tempo per waypoint" in text
    assert "W1:" in text and "W2:" in text


def test_comparison_csv_has_outlier_column():
    log = logger_with_comparison_data()
    with tempfile.TemporaryDirectory() as d:
        paths = log.save_all_text_files(d)
        assert paths
        text = Path(paths[0]).read_text(encoding="utf-8")
    assert "outlier_scartato" in text
    assert "true" in text


def test_autopilot_csv_leaves_the_pose_columns_empty_without_pose():
    log = logger_with_pose_loss()
    with tempfile.TemporaryDirectory() as d:
        paths = log.save_all_text_files(d)
        assert paths
        righe = Path(paths[0]).read_text(encoding="utf-8").splitlines()

    fault = [r for r in righe if "pose_timeout" in r]
    assert len(fault) == 1
    campi = fault[0].split(",")
    assert campi[2:6] == ["", "", "", ""]


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
