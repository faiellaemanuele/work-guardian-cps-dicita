from __future__ import annotations

from dataclasses import dataclass


WINDOW_TITLE: str = "Tello - Pilotaggio manuale"

VIDEO_WINDOW_TITLE: str = "Tello - Volo e supervisione"


@dataclass(frozen=True)
class DashboardConfig:
    enabled: bool = True

    panel_width: int = 940

    log_row_height: int = 262

    gap_px: int = 6

    video_origin: tuple[int, int] = (0, 0)
    video_size: tuple[int, int] = (960, 960)

    map_title: str = "Mappa missione"
    terminal_title: str = "Terminale drone"
    alerts_title: str = "Log degli alert"

    map_info_col_width: int = 270

    max_lines: int = 500
