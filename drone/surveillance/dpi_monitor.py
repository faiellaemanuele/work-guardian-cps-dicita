from __future__ import annotations

import time
from typing import Any, Callable, Iterable, Optional

from drone.surveillance.alarm_latch import AlarmLatch


_DPI_ITEMS: dict[str, tuple[str, str, str, str]] = {
    "helmet": (
        "elmetto",
        "Without_Helmet",
        "ALLERTA - elmetto mancante",
        "Manca l'elmetto di protezione",
    ),
    "goggles": (
        "occhiali",
        "Without_Goggles",
        "ALLERTA - occhiali mancanti",
        "Mancano gli occhiali protettivi",
    ),
    "vest": (
        "gilet",
        "Without_Vest",
        "ALLERTA - gilet mancante",
        "Manca il gilet ad alta visibilità",
    ),
    "shoes": (
        "scarpe",
        "Without_Safety_shoes",
        "ALLERTA - scarpe mancanti",
        "Mancano le scarpe antinfortunistiche",
    ),
}


def dpi_item_names(keys=None) -> tuple[str, ...]:
    if keys is None:
        keys = _DPI_ITEMS.keys()
    return tuple(
        _DPI_ITEMS[k][0] if k in _DPI_ITEMS else str(k) for k in keys
    )


def _count_label(detections_by_model: Iterable[dict], model_name: str, label: str) -> int:
    wanted = label.casefold()
    count = 0
    for entry in detections_by_model or []:
        if entry.get("name") != model_name:
            continue
        for det in entry.get("detections") or []:
            det_label = det.get("label")
            if det_label is None or str(det_label).casefold() != wanted:
                continue
            bbox = det.get("bbox")
            if bbox is None or len(bbox) != 4:
                continue
            count += 1
    return count


class DpiMonitor:
    def __init__(
        self,
        *,
        dpi_model_name: str = "Protezioni_individuali",
        required_items: Iterable[str] = (),
        alarm_after_sec: float = 0.0,
        clear_after_sec: float = 0.0,
        time_source: Optional[Callable[[], float]] = None,
    ):
        self.dpi_model_name = str(dpi_model_name)
        self.required_items = tuple(
            key for key in required_items if key in _DPI_ITEMS
        )
        self._latch = AlarmLatch(
            alarm_after_sec=alarm_after_sec,
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
        for key in self.required_items:
            absent_label = _DPI_ITEMS[key][1]
            present = False
            if supervision_active:
                present = _count_label(detections_by_model, self.dpi_model_name, absent_label) > 0
            if self._latch.update(key, present, now):
                alarms.append(self._missing_alarm(key))
        return alarms

    def _missing_alarm(self, key: str) -> dict[str, Any]:
        _nome, _absent_label, title, message = _DPI_ITEMS[key]
        return {
            "type": "dpi_missing",
            "item": key,
            "title": title,
            "message": message,
        }
