from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from drone.perception.object_detector import ObjectDetector


class _FakeTensor:
    def __init__(self, value):
        self._value = value

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self._value


class _FakeBox:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = [_FakeTensor(list(xyxy))]
        self.conf = [_FakeTensor(float(conf))]
        self.cls = [_FakeTensor(int(cls))]


class _FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class _FakeModel:
    def __init__(self, boxes, names):
        self._boxes = boxes
        self.names = names

    def __call__(self, frame, conf, imgsz, verbose, device):
        return [_FakeResult(self._boxes)]


def _make_detector(boxes, names=None):
    det = object.__new__(ObjectDetector)
    det.model = _FakeModel(boxes, names if names is not None else {0: "persona", 1: "casco"})
    det.conf = 0.5
    det.imgsz = 640
    det.device = "cpu"
    return det


def _frame(h=100, w=100):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_tensor_to_python_none():
    assert ObjectDetector._tensor_to_python(None) is None


def test_tensor_to_python_unwraps_fake_tensor():
    assert ObjectDetector._tensor_to_python(_FakeTensor([1, 2, 3])) == [1, 2, 3]


def test_tensor_to_python_passes_through_scalar():
    assert ObjectDetector._tensor_to_python(0.87) == 0.87


def test_get_label_dict_names():
    det = _make_detector([], names={0: "persona", 1: "casco"})
    assert det._get_label(0) == "persona"
    assert det._get_label(1) == "casco"


def test_get_label_list_names():
    det = _make_detector([], names=["persona", "casco"])
    assert det._get_label(1) == "casco"


def test_get_label_unknown_index_fallback():
    det = _make_detector([], names={0: "persona"})
    assert det._get_label(9) == "9"


def test_detect_none_frame():
    det = _make_detector([])
    frame, detections = det.detect(None)
    assert frame is None
    assert detections == []


def test_detect_no_boxes_returns_empty():
    det = _make_detector(None)
    frame, detections = det.detect(_frame())
    assert detections == []


def test_detect_clamps_out_of_frame_box():
    det = _make_detector([_FakeBox((-10, -10, 50, 50), 0.9, 0)])
    _, detections = det.detect(_frame(100, 100))
    assert len(detections) == 1
    x1, y1, x2, y2 = detections[0]["bbox"]
    assert (x1, y1) == (0, 0)
    assert x2 <= 99 and y2 <= 99
    assert detections[0]["label"] == "persona"
    assert abs(detections[0]["confidence"] - 0.9) < 1e-6


def test_detect_discards_degenerate_box():
    det = _make_detector([_FakeBox((50, 50, 50, 50), 0.9, 0)])
    _, detections = det.detect(_frame(100, 100))
    assert detections == []


def test_detect_discards_malformed_box():
    det = _make_detector([_FakeBox((10, 10, 20), 0.9, 0)])
    _, detections = det.detect(_frame(100, 100))
    assert detections == []


def test_detect_mixed_valid_and_invalid():
    det = _make_detector([
        _FakeBox((10, 10, 40, 40), 0.8, 1),
        _FakeBox((30, 30, 30, 30), 0.7, 0),
    ])
    _, detections = det.detect(_frame(100, 100))
    assert len(detections) == 1
    assert detections[0]["label"] == "casco"


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
    import sys

    sys.exit(_run_all())
