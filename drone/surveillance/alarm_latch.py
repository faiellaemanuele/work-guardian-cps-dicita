from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Union


@dataclass
class _KeyState:
    true_elapsed: float = 0.0
    last_true_at: Optional[float] = None
    last_was_true: bool = False
    alarm_active: bool = False


class AlarmLatch:
    def __init__(
        self,
        *,
        alarm_after_sec: Union[float, Mapping[str, float]] = 0.0,
        clear_after_sec: float = 0.0,
        time_source: Optional[Callable[[], float]] = None,
    ):
        if isinstance(alarm_after_sec, Mapping):
            self._min_consecutive: Union[float, dict[str, float]] = {
                str(key): max(0.0, float(value))
                for key, value in alarm_after_sec.items()
            }
        else:
            self._min_consecutive = max(0.0, float(alarm_after_sec))
        self._release_grace_sec = max(0.0, float(clear_after_sec))
        self._now = time_source if time_source is not None else time.monotonic
        self._states: dict[str, _KeyState] = {}

    def _threshold(self, key: str) -> float:
        if isinstance(self._min_consecutive, dict):
            return self._min_consecutive.get(key, 0.0)
        return self._min_consecutive

    def update(self, key: str, condition: bool, now: Optional[float] = None) -> bool:
        if now is None:
            now = self._now()
        state = self._states.get(key)
        if state is None:
            state = _KeyState()
            self._states[key] = state

        if condition:
            if state.last_true_at is not None and state.last_was_true:
                state.true_elapsed += float(now) - state.last_true_at
            state.last_true_at = float(now)
            state.last_was_true = True
            if state.true_elapsed >= self._threshold(key) and not state.alarm_active:
                state.alarm_active = True
                return True
            return False

        state.last_was_true = False
        if (
            state.last_true_at is not None
            and (float(now) - state.last_true_at) < self._release_grace_sec
        ):
            return False
        state.true_elapsed = 0.0
        state.last_true_at = None
        state.alarm_active = False
        return False

    def reset(self) -> None:
        self._states.clear()
