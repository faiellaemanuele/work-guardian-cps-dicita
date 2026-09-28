from __future__ import annotations

import numpy as np


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += float(dt)


class MapWaypoint:
    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)


def blank_frame() -> np.ndarray:
    return np.zeros((720, 960, 3), dtype=np.uint8)
