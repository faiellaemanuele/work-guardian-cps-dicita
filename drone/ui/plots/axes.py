from __future__ import annotations

from pathlib import Path

from matplotlib.transforms import blended_transform_factory

from drone.ui.plots.palette import PALETTE


_WP_LABEL_ROW_PT = 11.0

SAT_DASHES = (0, (7, 3))


def style_axis(ax, xlabel: str, ylabel: str, title: str, grid_color: str = "#cccccc"):
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
    ax.grid(True, which="major", linestyle="-", linewidth=0.5, alpha=0.45, color=grid_color)
    ax.minorticks_on()
    ax.grid(True, which="minor", linestyle=":", linewidth=0.3, alpha=0.22, color=grid_color)
    ax.tick_params(axis="both", labelsize=10)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_linewidth(0.8)


def add_session_subtitle(ax, meta: str, *, title_pad: int = 26, meta_offset: int = 7):
    ax.set_title(ax.get_title(), fontsize=13, fontweight="bold", pad=title_pad)
    ax.annotate(
        meta,
        xy=(0.5, 1.0), xycoords="axes fraction",
        xytext=(0, meta_offset), textcoords="offset points",
        ha="center", va="bottom", fontsize=9, color=PALETTE["sottotitolo"],
        annotation_clip=False,
    )


def add_tolerance_tick(ax, tol: float) -> None:
    limits = ax.get_ylim()
    too_close = 0.5 * tol
    ticks = [
        v for v in ax.get_yticks()
        if v == 0 or abs(abs(v) - tol) >= too_close
    ]
    ticks = sorted(set(ticks + [tol, -tol]))
    ax.set_yticks([v for v in ticks if limits[0] <= v <= limits[1]])


def plain_number(value, _pos=None) -> str:
    return f"{value:g}".replace("-", "−")


def add_wp_change_markers(axes, times, labels, duration, color):
    for ax in axes:
        for wt in times:
            ax.axvline(wt, color=color, linewidth=1.1,
                       linestyle="--", alpha=0.75, zorder=5)

    if not len(times):
        return 7

    label_width = duration * 0.030
    row_last_time: list[float] = []
    row_of_label: list[int] = []
    for wt in times:
        row = 0
        while row < len(row_last_time) and wt - row_last_time[row] < label_width:
            row += 1
        if row == len(row_last_time):
            row_last_time.append(wt)
        else:
            row_last_time[row] = wt
        row_of_label.append(row)

    top = axes[0]
    label_transform = blended_transform_factory(top.transData, top.transAxes)
    for wt, wlbl, row in zip(times, labels, row_of_label):
        top.annotate(
            wlbl, xy=(wt, 1.0), xycoords=label_transform,
            xytext=(0, 3 + row * _WP_LABEL_ROW_PT), textcoords="offset points",
            ha="center", va="bottom", fontsize=8.5, fontweight="bold",
            color=color, annotation_clip=False,
        )

    return int(3 + len(row_last_time) * _WP_LABEL_ROW_PT + 4)


def ordered_legend(ax, priority: dict, **legend_kwargs):
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    pairs = sorted(zip(handles, labels), key=lambda hl: priority.get(hl[1], 99))
    ax.legend([h for h, _ in pairs], [l for _, l in pairs], **legend_kwargs)


def figure_saver(output_dir: Path, save_dpi: int, saved_paths: list, plt):
    def save_figure(fig, filename: str) -> Path:
        path = output_dir / filename
        fig.savefig(path, dpi=save_dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        saved_paths.append(path)
        return path
    return save_figure
