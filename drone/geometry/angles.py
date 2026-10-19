"""Operazioni su angoli circolari espresse in gradi."""

from __future__ import annotations

import math
from typing import Iterable


def wrap_angle_deg(angle: float) -> float:
    """Riporta un angolo in gradi nell'intervallo circolare previsto."""
    wrapped = (float(angle) + 180.0) % 360.0 - 180.0
    if wrapped == -180.0:
        return 180.0
    return wrapped


def circular_mean_deg(values: Iterable[float]) -> float:
    """Calcola la media circolare di una sequenza di angoli in gradi."""
    sin_sum = sum(math.sin(math.radians(v)) for v in values)
    cos_sum = sum(math.cos(math.radians(v)) for v in values)
    return math.degrees(math.atan2(sin_sum, cos_sum))
