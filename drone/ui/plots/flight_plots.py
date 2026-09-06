from __future__ import annotations

import logging
from pathlib import Path

from drone.data.flight_report_stats import entries_with_pose

LOGGER = logging.getLogger(__name__)


def save_plots(logger, output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []

    autopilot_with_pose = len(entries_with_pose(logger.autopilot_entries))
    has_autopilot = autopilot_with_pose >= 2
    has_comparison = len(logger.comparison_entries) >= 2

    if not has_autopilot and not has_comparison:
        LOGGER.info(
            "Grafici non generati: campioni insufficienti "
            "(autopilot=%d, comparison=%d).",
            autopilot_with_pose,
            len(logger.comparison_entries),
        )
        return saved_paths

    try:
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        LOGGER.exception("matplotlib non installato: impossibile generare i grafici.")
        return []

    from drone.ui.plots.autopilot_plots import save_autopilot_plots
    from drone.ui.plots.kalman_plots import save_kalman_plots

    if has_autopilot:
        saved_paths.extend(save_autopilot_plots(logger, output_dir, plt))
    if has_comparison:
        saved_paths.extend(save_kalman_plots(logger, output_dir, plt))

    return saved_paths
