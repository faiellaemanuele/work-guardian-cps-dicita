from __future__ import annotations

from typing import Any, Mapping

import numpy as np


def normalize_position_world(position_world: Any) -> np.ndarray:
    if isinstance(position_world, Mapping):
        missing_keys = [
            key
            for key in ("x", "y", "z")
            if key not in position_world or position_world.get(key) is None
        ]
        if missing_keys:
            raise ValueError(
                "position_world in formato Mapping deve contenere x, y, z. "
                f"Chiavi mancanti/non valide: {missing_keys}"
            )
        position_world = [
            position_world["x"],
            position_world["y"],
            position_world["z"],
        ]

    position_array = np.asarray(position_world, dtype=np.float32).reshape(-1)

    if position_array.size != 3:
        raise ValueError(
            "position_world deve contenere esattamente 3 coordinate. "
            f"Ricevuto: {position_world!r}"
        )

    if not np.all(np.isfinite(position_array)):
        raise ValueError(
            "position_world deve contenere solo valori numerici finiti. "
            f"Ricevuto: {position_world!r}"
        )

    return position_array.reshape(3, 1)
