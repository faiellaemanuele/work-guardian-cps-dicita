from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable, Optional, Sequence

from drone.surveillance.alarm_latch import AlarmLatch

_ALARM_RESTRICTED_AREA = "restricted_area"
_ALARM_FALL = "fall"


def _box_min_distance(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    dx = max(0.0, bx1 - ax2, ax1 - bx2)
    dy = max(0.0, by1 - ay2, ay1 - by2)
    return math.hypot(dx, dy)


def _bottom_edge(box: Sequence[float]) -> tuple[float, float, float, float]:
    x1, _y1, x2, y2 = box
    return (float(x1), float(y2), float(x2), float(y2))


def _boxes_for(
    detections_by_model: Iterable[dict],
    model_name: str,
    label: Optional[str] = None,
) -> list[tuple[float, float, float, float]]:
    wanted_label = label.casefold() if label is not None else None
    boxes: list[tuple[float, float, float, float]] = []
    for entry in detections_by_model or []:
        if entry.get("name") != model_name:
            continue
        for det in entry.get("detections") or []:
            if wanted_label is not None:
                det_label = det.get("label")
                if det_label is None or str(det_label).casefold() != wanted_label:
                    continue
            bbox = det.get("bbox")
            if bbox is None or len(bbox) != 4:
                continue
            boxes.append(tuple(float(v) for v in bbox))
    return boxes


class PersonMonitor:
    def __init__(
        self,
        *,
        fall_model_name: str = "Caduta_delle_persone",
        person_model_name: str = "Caduta_delle_persone",
        restricted_area_model_name: str = "Aree_interdette",
        person_label: str = "Person",
        fall_label: str = "Fall",
        restricted_area_tolerance_px: Optional[float] = None,
        restricted_area_alarm_after_sec: float = 0.0,
        fall_alarm_after_sec: float = 0.0,
        clear_after_sec: float = 0.0,
        time_source: Optional[Callable[[], float]] = None,
    ):
        self.fall_model_name = str(fall_model_name)
        self.person_model_name = str(person_model_name)
        self.restricted_area_model_name = str(restricted_area_model_name)
        self.person_label = str(person_label)
        self.fall_label = str(fall_label)
        self._restricted_area_tolerance_px = None if restricted_area_tolerance_px is None else max(0.0, float(restricted_area_tolerance_px))
        self._latch = AlarmLatch(
            alarm_after_sec={
                _ALARM_RESTRICTED_AREA: restricted_area_alarm_after_sec,
                _ALARM_FALL: fall_alarm_after_sec,
            },
            clear_after_sec=clear_after_sec,
            time_source=time_source,
        )
        self._now = time_source if time_source is not None else time.monotonic

    def reset(self) -> None:
        self._latch.reset()

    def update(
        self,
        *,
        detections_by_model: Iterable[dict],
        supervision_active: bool,
    ) -> list[dict[str, Any]]:
        now = self._now()
        alarms: list[dict[str, Any]] = []

        crossing_count = None
        if supervision_active and self._restricted_area_tolerance_px is not None:
            crossing_count = self._persons_crossing(detections_by_model)
        if self._latch.update(_ALARM_RESTRICTED_AREA, crossing_count is not None, now):
            alarms.append(self._crossing_alarm(crossing_count))

        fall_count = 0
        if supervision_active:
            fall_count = len(
                _boxes_for(detections_by_model, self.fall_model_name, self.fall_label)
            )
        if self._latch.update(_ALARM_FALL, fall_count > 0, now):
            alarms.append(self._fall_alarm(fall_count))

        return alarms

    def _persons_crossing(self, detections_by_model: Iterable[dict]) -> Optional[int]:
        persons = _boxes_for(detections_by_model, self.person_model_name, self.person_label)
        if not persons:
            return None
        rects = _boxes_for(detections_by_model, self.restricted_area_model_name)
        if not rects:
            return None

        count = 0
        for person in persons:
            feet = _bottom_edge(person)
            for rect in rects:
                if _box_min_distance(feet, rect) <= self._restricted_area_tolerance_px:
                    count += 1
                    break
        return count if count > 0 else None

    def _crossing_alarm(self, person_count: int) -> dict[str, Any]:
        message = (
            "Una persona in un'area vietata"
            if person_count == 1
            else "Più persone in un'area vietata"
        )
        return {
            "type": _ALARM_RESTRICTED_AREA,
            "title": "ALLERTA - superamento area vietata",
            "message": message,
        }

    def _fall_alarm(self, fall_count: int) -> dict[str, Any]:
        quante = "una persona" if fall_count == 1 else f"{fall_count} persone"
        return {
            "type": _ALARM_FALL,
            "title": "ALLERTA - persona caduta",
            "message": f"Rilevata la caduta di {quante}",
        }
