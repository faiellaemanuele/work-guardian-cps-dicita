from __future__ import annotations

import logging
from pathlib import Path

from drone.data.flight_report_stats import entries_with_pose

LOGGER = logging.getLogger(__name__)

# Un orologio pubblica due campioni al secondo: con meno di due non c'è una
# linea da disegnare.
_MIN_BIOMETRIC_SAMPLES = 2


def _pyplot():
    try:
        import matplotlib
        if matplotlib.get_backend().lower() != "agg":
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        LOGGER.exception("Non è stato possibile generare i grafici perché manca la libreria matplotlib")
        return None
    return plt


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

    plt = _pyplot()
    if plt is None:
        return []

    from drone.ui.plots.autopilot_plots import save_autopilot_plots
    from drone.ui.plots.kalman_plots import save_kalman_plots

    if has_autopilot:
        saved_paths.extend(save_autopilot_plots(logger, output_dir, plt))
    if has_comparison:
        saved_paths.extend(save_kalman_plots(logger, output_dir, plt))

    return saved_paths


def save_biometric_plots(logger, output_dir: str | Path) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    workers = [
        worker for worker in logger.workers()
        if len(logger.samples(worker)) >= _MIN_BIOMETRIC_SAMPLES
    ]
    if not workers:
        LOGGER.info("Grafici biometrici non generati: campioni insufficienti.")
        return []

    plt = _pyplot()
    if plt is None:
        return []

    from drone.ui.plots.biometric_plots import save_worker_biometric_plots

    saved_paths: list[Path] = []
    # Con un solo orologio i nomi dei file restano quelli fissi; con più
    # orologi ognuno porta l'identificativo dell'operaio.
    tag_files = len(workers) > 1
    for worker in workers:
        saved_paths.extend(
            save_worker_biometric_plots(
                logger, worker, output_dir, plt, tag_files=tag_files,
            )
        )
    return saved_paths
