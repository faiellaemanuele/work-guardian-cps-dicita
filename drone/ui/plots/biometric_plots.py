"""Genera i grafici di frequenza cardiaca, SpO2, stati e allarmi dello smartwatch."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MultipleLocator
from matplotlib.transforms import blended_transform_factory

from drone.config import APP_CONFIG
from drone.data.biometric_report_stats import (
    MAX_GAP_SEC as _MAX_GAP_SEC,
    NOMINAL_STEP_SEC as _NOMINAL_STEP_SEC,
    STATE_LABELS as _STATE_LABELS,
    alarm_causes,
    format_duration as _format_duration,
)
from drone.data.flight_report_stats import duration_key
from drone.ui.plots.axes import (
    SAT_DASHES,
    add_session_subtitle,
    add_wp_change_markers,
    draw_each,
    figure_saver,
)
from drone.ui.plots.palette import PALETTE

LOGGER = logging.getLogger(__name__)

_SAVE_DPI = 300

_FILENAMES = {
    "hr_comparison":   "biometric_raw_and_filtered_heart_rate.png",
    "spo2_comparison": "biometric_raw_and_filtered_spo2.png",
    "vitals":          "biometric_heart_rate_and_spo2_trend.png",
    "states":          "biometric_watch_state.png",
}

# La scala del battito nel confronto grezzo/filtrato: le letture grezze che ne
# escono vengono tagliate al bordo, così pochi valori estremi non schiacciano
# la linea filtrata.
_HR_SCALE = (30.0, 200.0)

# L'evento di allarme può arrivare dal broker poco dopo il primo campione in
# ALLARME: entro questo margine il campione è già attribuito all'evento.
_EVENT_TOLERANCE_SEC = 1.0

_DRONE_ALARM = "ALLARME_DRONE"

# Nella legenda del grafico degli stati ogni stato porta anche il suo
# significato, che i report della sessione non ripetono.
_STATE_MEANINGS = {
    "MISSIONE_NON_AVVIATA": "Missione non avviata: battito e SpO2 non vengono controllati",
    "RICERCA_SEGNALE":      "Ricerca segnale del sensore: nessuna lettura valida",
    "NORMALE":              "Normale: lettura valida, valori entro le soglie",
    "VERIFICA":             "Verifica: valore oltre soglia, in attesa di conferma",
    "ALLARME":              "Allarme biometrico",
    _DRONE_ALARM:           "Allarme dal drone: DPI mancanti o area interdetta",
    "SILENZIATO":           "Allarme silenziato dall'operatore",
    "GUASTO":               "Guasto del sensore",
}

_SUBTITLE_LINE_PT = 12

# Posizione e altezza delle due strisce nel grafico dell'orologio.
_STATE_ROW = (0.0, 1.0)
_LINK_ROW = (1.25, 0.5)

# Il colore di ogni stato dell'automa del firmware; le etichette e l'ordine in
# cui compaiono in legenda stanno in biometric_report_stats, gli stessi che
# usano i report della sessione.
_STATE_COLORS = {
    "MISSIONE_NON_AVVIATA": PALETTE["stato_non_avviata"],
    "RICERCA_SEGNALE":      PALETTE["stato_ricerca"],
    "NORMALE":              PALETTE["stato_normale"],
    "VERIFICA":             PALETTE["stato_verifica"],
    "ALLARME":              PALETTE["stato_allarme"],
    "SILENZIATO":           PALETTE["stato_silenziato"],
    "GUASTO":               PALETTE["stato_guasto"],
}


@dataclass
class _Data:
    plt: object
    save_figure: Callable
    t: np.ndarray
    hr_raw: np.ndarray
    hr_filtered: np.ndarray
    spo2_raw: np.ndarray
    spo2_filtered: np.ndarray
    bpm: np.ndarray
    spo2: np.ndarray
    states: list
    step: float
    hr_alarm_times: np.ndarray
    spo2_alarm_times: np.ndarray
    duration: float
    meta: str


def _series(samples, key: str) -> np.ndarray:
    return np.array(
        [np.nan if s.get(key) is None else float(s[key]) for s in samples],
        dtype=np.float64,
    )


def _break_gaps(t: np.ndarray, columns: list, states: list):
    # Dove manca un tratto di telemetria si inserisce un punto vuoto: NaN
    # spezza le linee, None lascia bianca la striscia degli stati.
    cuts = np.flatnonzero(np.diff(t) > _MAX_GAP_SEC)
    if not cuts.size:
        return t, columns, states
    positions = cuts + 1
    midpoints = (t[cuts] + t[positions]) / 2.0
    t = np.insert(t, positions, midpoints)
    columns = [np.insert(col, positions, np.nan) for col in columns]
    states = list(states)
    for pos in reversed(positions.tolist()):
        states.insert(pos, None)
    return t, columns, states


def _alarm_causes(event) -> tuple[bool, bool]:
    # Senza valori leggibili l'allarme resta su entrambi i grafici.
    return alarm_causes(event, APP_CONFIG.smartwatch_thresholds)


def _alarm_labels(prefix: str, count: int) -> list[str]:
    # Un allarme solo porta il nome del parametro; con due o più ciascuno ha
    # accanto il suo numero d'ordine.
    if count == 1:
        return [prefix]
    return [f"{prefix} {i}" for i in range(1, count + 1)]


def _alarm_legend_label(parameter: str, labels: list[str]) -> str:
    if len(labels) == 1:
        return f"Allarme {parameter} ({labels[0]})"
    shown = ", ".join(labels) if len(labels) <= 3 else f"{labels[0]}, {labels[1]}, …"
    return f"Allarmi {parameter} ({shown})"


def _prepare(logger, output_dir: Path, plt, saved_paths: list) -> _Data:
    samples = logger.samples()
    events = logger.events()

    key = duration_key(list(samples) + list(events))
    base = float(samples[0][key])
    t = np.array([float(s[key]) - base for s in samples], dtype=np.float64)

    steps = np.diff(t)
    steps = steps[(steps > 0) & (steps <= _MAX_GAP_SEC)]
    step = float(np.median(steps)) if steps.size else _NOMINAL_STEP_SEC

    duration = float(t[-1])
    meta = f"{len(samples)} campioni · durata {_format_duration(duration)}"

    columns = [
        _series(samples, "hr_grezzo"),
        _series(samples, "hr_filtrato"),
        _series(samples, "spo2_grezzo"),
        _series(samples, "spo2_filtrato"),
        _series(samples, "bpm"),
        _series(samples, "spo2"),
    ]
    states = [s.get("stato") for s in samples]
    t, columns, states = _break_gaps(t, columns, states)
    hr_raw, hr_filtered, spo2_raw, spo2_filtered, bpm, spo2 = columns

    hr_alarm_times, spo2_alarm_times = [], []
    for event in events:
        if key not in event:
            continue
        hr_cause, spo2_cause = _alarm_causes(event)
        when = float(event[key]) - base
        if hr_cause:
            hr_alarm_times.append(when)
        if spo2_cause:
            spo2_alarm_times.append(when)

    return _Data(
        plt=plt,
        save_figure=figure_saver(output_dir, _SAVE_DPI, saved_paths, plt),
        t=t,
        hr_raw=hr_raw, hr_filtered=hr_filtered,
        spo2_raw=spo2_raw, spo2_filtered=spo2_filtered,
        bpm=bpm, spo2=spo2,
        states=states, step=step,
        hr_alarm_times=np.array(hr_alarm_times, dtype=np.float64),
        spo2_alarm_times=np.array(spo2_alarm_times, dtype=np.float64),
        duration=duration,
        meta=meta,
    )


def _style_panel(ax, ylabel: str) -> None:
    ax.set_ylabel(ylabel, fontsize=10.5)
    ax.grid(True, linestyle="-", linewidth=0.5, alpha=0.40, color=PALETTE["griglia"])
    ax.minorticks_on()
    ax.grid(True, which="minor", linestyle=":", linewidth=0.3,
            alpha=0.20, color=PALETTE["griglia"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=9)


def _subtitle(data: _Data) -> str:
    return f"Sessione biometrica  ·  {data.meta}"


def _mean_gap(raw: np.ndarray, filtered: np.ndarray) -> Optional[float]:
    both = np.isfinite(raw) & np.isfinite(filtered)
    if not np.any(both):
        return None
    return float(np.mean(np.abs(raw[both] - filtered[both])))


def _with_unit(value: str, unit: str) -> str:
    # Il simbolo di percentuale va attaccato al numero, le altre unità sono
    # separate da uno spazio.
    return f"{value}{unit}" if unit == "%" else f"{value} {unit}"


def _clock(value, _pos=None) -> str:
    minutes, seconds = divmod(int(round(abs(value))), 60)
    return f"{'−' if value < 0 else ''}{minutes}:{seconds:02d}"


def _time_axis(ax, data: _Data) -> None:
    # Le tacche cadono su minuti interi, o su frazioni di minuto nelle sessioni
    # brevi, in modo che l'asse non mostri più di una dozzina di etichette.
    duration = data.duration
    for major, minor in ((1, 0.5), (5, 1), (10, 2), (30, 10), (60, 15),
                         (120, 30), (300, 60), (600, 120), (900, 300)):
        if duration / major <= 12:
            break
    # I limiti dipendono solo dalla durata della sessione, così i grafici della
    # stessa sessione hanno l'asse del tempo allineato e si possono affiancare.
    margin = max(0.02 * duration, data.step)
    ax.set_xlim(-margin, duration + margin)
    ax.xaxis.set_major_locator(MultipleLocator(major))
    ax.xaxis.set_minor_locator(MultipleLocator(minor))
    ax.xaxis.set_major_formatter(FuncFormatter(_clock))
    ax.set_xlabel("Tempo dall'avvio [min:s]", fontsize=11)


def _plot_series(ax, t: np.ndarray, values: np.ndarray, *, color: str,
                 linewidth: float) -> None:
    # Un valore isolato fra due buchi non forma una linea: si disegna come
    # punto, altrimenti non comparirebbe nel grafico.
    ax.plot(t, values, color=color, linewidth=linewidth, zorder=3)
    finite = np.isfinite(values)
    alone = (finite
             & ~np.concatenate(([False], finite[:-1]))
             & ~np.concatenate((finite[1:], [False])))
    if np.any(alone):
        ax.scatter(t[alone], values[alone], s=linewidth * 7, color=color,
                   edgecolors="none", zorder=3)


def _heading(ax, title: str, lines: list, meta_offset: int = 7) -> None:
    # Titolo e sottotitolo stanno centrati sopra il grafico; ogni riga in più
    # del sottotitolo alza il titolo dello spazio di una riga.
    pad = meta_offset + 19 + _SUBTITLE_LINE_PT * (len(lines) - 1)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=pad)
    add_session_subtitle(ax, "\n".join(lines), title_pad=pad, meta_offset=meta_offset)


def _legend_below(fig, columns: list, labelspacing: float = 0.5) -> None:
    # Un'unica legenda centrata sotto i grafici, con una colonna per ogni
    # gruppo di voci. Matplotlib riempie le colonne in modo uniforme, e l'ultima
    # può avere una voce in meno delle altre: le colonne più corte si
    # completano con righe vuote fino a quella misura, altrimenti le voci di un
    # gruppo scivolerebbero nella colonna accanto.
    columns = [column for column in columns if column]
    if not columns:
        return
    rows = max(len(column) for column in columns)
    handles = []
    for i, column in enumerate(columns):
        size = rows if i < len(columns) - 1 else max(len(column), rows - 1)
        handles += column
        handles += [Line2D([], [], linestyle="none", label=" ")] * (size - len(column))
    fig.legend(handles=handles, loc="outside lower center", ncol=len(columns),
               fontsize=8.5, frameon=True, framealpha=0.95, columnspacing=2.5,
               labelspacing=labelspacing)


def _comparison(data: _Data, *, raw, filtered, scale, ylabel, unit, title,
                filename) -> None:
    plt, t = data.plt, data.t
    low, high = scale

    fig, ax = plt.subplots(figsize=(11, 5.5), constrained_layout=True)

    # Le letture grezze sono unite da una linea sottile, che lascia leggibile
    # il valore filtrato; quelle oltre la scala escono dal bordo del grafico.
    finite = np.isfinite(raw)
    above = finite & (raw > high)
    below = finite & (raw < low)
    if np.any(finite):
        ax.plot(t, raw, linewidth=0.9, alpha=0.8, color=PALETTE["grezza"], zorder=2)
    else:
        ax.text(0.5, 0.92, "Valori grezzi non ricevuti dall'orologio",
                transform=ax.transAxes, ha="center", va="top",
                fontsize=9, color=PALETTE["sottotitolo"])
    if np.any(np.isfinite(filtered)):
        _plot_series(ax, t, filtered, color=PALETTE["filtrata"], linewidth=1.8)
    ax.set_ylim(low, high)
    _style_panel(ax, ylabel)
    _time_axis(ax, data)

    details = []
    gap = _mean_gap(raw, filtered)
    if gap is not None:
        details.append("differenza media fra lettura grezza e valore filtrato "
                       + _with_unit(f"{gap:.1f}", unit))
    n_out = int(above.sum() + below.sum())
    if n_out:
        share = 100.0 * n_out / int(finite.sum())
        share_text = f"{share:.0f}%" if share >= 1.0 else "meno dell'1%"
        bounds = (f"sopra {high:g} o sotto {low:g}" if above.any() and below.any()
                  else f"sopra {high:g}" if above.any() else f"sotto {low:g}")
        details.append(f"{n_out} letture grezze su {int(finite.sum())} ({share_text}) "
                       f"fuori dal grafico, " + _with_unit(bounds, unit))

    _legend_below(fig, [
        [Line2D([0], [0], color=PALETTE["filtrata"], linewidth=1.8,
                label="Valore filtrato, usato dall'orologio per gli allarmi")],
        [Line2D([0], [0], color=PALETTE["grezza"], linewidth=0.9, alpha=0.8,
                label="Lettura grezza del sensore, prima del filtro")],
    ])
    lines = [_subtitle(data)]
    if details:
        lines.append("  ·  ".join(details))
    _heading(ax, title, lines)
    data.save_figure(fig, filename)


def _hr_comparison(data: _Data) -> None:
    _comparison(
        data, raw=data.hr_raw, filtered=data.hr_filtered, scale=_HR_SCALE,
        ylabel="Battito [bpm]", unit="bpm",
        title="Battito cardiaco: lettura grezza e valore filtrato",
        filename=_FILENAMES["hr_comparison"],
    )


def _spo2_comparison(data: _Data) -> None:
    # La scala parte poco sotto la soglia di allarme, o più in basso se ci
    # arriva il valore filtrato: le letture grezze inferiori vanno fuori scala.
    thr = APP_CONFIG.smartwatch_thresholds
    finite = data.spo2_filtered[np.isfinite(data.spo2_filtered)]
    lowest = float(finite.min()) if finite.size else float(thr.spo2_min_in)
    low = float(np.floor(min(thr.spo2_min_in, lowest) - 2.0))
    _comparison(
        data, raw=data.spo2_raw, filtered=data.spo2_filtered, scale=(low, 100.5),
        ylabel="SpO2 [%]", unit="%",
        title="Saturazione (SpO2): lettura grezza e valore filtrato",
        filename=_FILENAMES["spo2_comparison"],
    )


def _state_segments(data: _Data, states: Optional[list] = None) -> list[tuple[str, float, float]]:
    # Ogni campione vale fino al successivo; l'ultimo prima di un buco o della
    # fine della sessione vale un passo di pubblicazione.
    t = data.t
    states = data.states if states is None else states
    segments: list[tuple[str, float, float]] = []
    for i, state in enumerate(states):
        if state is None:
            continue
        has_next = i + 1 < len(states) and states[i + 1] is not None
        end = float(t[i + 1]) if has_next else float(t[i]) + data.step
        start = float(t[i])
        if segments and segments[-1][0] == state and abs(segments[-1][2] - start) < 1e-9:
            segments[-1] = (state, segments[-1][1], end)
        else:
            segments.append((state, start, end))
    return segments


def _state_codes(data: _Data) -> list:
    # Lo stato ALLARME dell'orologio scatta anche per gli allarmi inviati dal
    # drone (DPI mancanti, area interdetta), che la telemetria non distingue da
    # quelli biometrici. Un allarme è biometrico dall'arrivo del suo evento
    # finché il valore che lo ha causato non torna entro la soglia di rientro,
    # come nel firmware; il resto del tempo in ALLARME si attribuisce al drone.
    thr = APP_CONFIG.smartwatch_thresholds
    events = sorted(
        [(float(when), True, False) for when in data.hr_alarm_times]
        + [(float(when), False, True) for when in data.spo2_alarm_times]
    )
    hr_active = spo2_active = False
    next_event = 0
    last_event = -np.inf
    codes = []
    for when, state, bpm, spo2 in zip(data.t, data.states, data.bpm, data.spo2):
        while (next_event < len(events)
               and events[next_event][0] <= when + _EVENT_TOLERANCE_SEC):
            last_event, hr_cause, spo2_cause = events[next_event]
            hr_active |= hr_cause
            spo2_active |= spo2_cause
            next_event += 1
        # Un campione arrivato prima dell'evento, anche se rientra nel margine,
        # non chiude l'allarme: i suoi valori precedono la conferma.
        closing = when >= last_event
        if (closing and hr_active and np.isfinite(bpm)
                and thr.bpm_min_out <= bpm <= thr.bpm_max_out):
            hr_active = False
        if closing and spo2_active and np.isfinite(spo2) and spo2 >= thr.spo2_min_out:
            spo2_active = False
        if state == "ALLARME" and not (hr_active or spo2_active):
            state = _DRONE_ALARM
        codes.append(state)
    return codes


def _state_color(code: str) -> str:
    if code == _DRONE_ALARM:
        return PALETTE["stato_allarme_drone"]
    return _STATE_COLORS.get(code, PALETTE["percorso"])


def _zone_bands(ax, *, unit, low_alarm, low_back, high_back=None, high_alarm=None) -> None:
    # Le fasce di sfondo: verde entro le soglie di rientro, arancione fra la
    # soglia di rientro e quella di allarme, rosso oltre la soglia di allarme.
    ok, warn, bad = PALETTE["tolleranza"], PALETTE["fuori_tol"], PALETTE["allarme_biometrico"]
    ax.axhspan(-1000.0, low_alarm, color=bad, alpha=0.07, zorder=0)
    ax.axhspan(low_alarm, low_back, color=warn, alpha=0.14, zorder=0)
    if high_back is None:
        ax.axhspan(low_back, 1000.0, color=ok, alpha=0.10, zorder=0)
        alarm_lines = (low_alarm,)
    else:
        ax.axhspan(low_back, high_back, color=ok, alpha=0.10, zorder=0)
        ax.axhspan(high_back, high_alarm, color=warn, alpha=0.14, zorder=0)
        ax.axhspan(high_alarm, 1000.0, color=bad, alpha=0.07, zorder=0)
        alarm_lines = (low_alarm, high_alarm)
    # Il valore della soglia si scrive dentro il grafico, sopra la linea, in
    # modo che nulla sporga dal bordo destro.
    label_transform = blended_transform_factory(ax.transAxes, ax.transData)
    for y in alarm_lines:
        ax.axhline(y, linewidth=1.0, color=bad, linestyle=SAT_DASHES, alpha=0.7, zorder=1)
        ax.annotate("soglia di allarme " + _with_unit(f"{y:g}", unit), xy=(1.0, y),
                    xycoords=label_transform, xytext=(-4, 2),
                    textcoords="offset points", ha="right", va="bottom",
                    fontsize=8, color=bad, zorder=4)


def _padded_limits(values: np.ndarray, low: float, high: float, pad: float,
                   cap: Optional[float] = None) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    lo = min(low, float(finite.min())) if finite.size else low
    hi = max(high, float(finite.max())) if finite.size else high
    top = hi + pad if cap is None else min(cap, hi + pad)
    return lo - pad, top


def _state_strip(ax, data: _Data) -> tuple[list, list]:
    # Le due strisce dell'orologio: in basso lo stato del firmware, in alto il
    # collegamento con il PC. Ritorna le voci di legenda dei due gruppi, con
    # quanto è durato ciascun tratto.
    durations: dict[str, float] = {}
    for state, start, end in _state_segments(data, _state_codes(data)):
        ax.broken_barh([(start, end - start)], _STATE_ROW,
                       facecolors=_state_color(state), edgecolor="none")
        durations[state] = durations.get(state, 0.0) + (end - start)

    # Il PC non riceve lo stato della rete dell'orologio: il collegamento si
    # ricava dall'arrivo della telemetria, e un buco della telemetria è un
    # tratto in cui dall'orologio non è arrivato nulla.
    received = 0.0
    link = [None if state is None else "COLLEGATO" for state in data.states]
    for _, start, end in _state_segments(data, link):
        ax.broken_barh([(start, end - start)], _LINK_ROW,
                       facecolors=PALETTE["collegamento"], edgecolor="none")
        received += end - start
    missing = 0.0
    for i, state in enumerate(data.states):
        if state is not None:
            continue
        start, end = float(data.t[i - 1]) + data.step, float(data.t[i + 1])
        ax.broken_barh([(start, end - start)], _LINK_ROW, facecolors="white",
                       edgecolor=PALETTE["nessun_dato"], hatch="////", linewidth=0)
        missing += end - start

    ax.set_ylim(0, _LINK_ROW[0] + _LINK_ROW[1])
    ax.set_yticks([_STATE_ROW[0] + _STATE_ROW[1] / 2, _LINK_ROW[0] + _LINK_ROW[1] / 2])
    ax.set_yticklabels(["Stato", "Collegamento"], fontsize=10)
    ax.tick_params(axis="y", length=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", labelsize=9)

    known = list(_STATE_LABELS)
    known.insert(known.index("ALLARME") + 1, _DRONE_ALARM)
    present = [code for code in known if code in durations]
    present += sorted(code for code in durations if code not in known)
    state_handles = [
        Patch(facecolor=_state_color(code),
              label=f"{_STATE_MEANINGS.get(code, _STATE_LABELS.get(code, code))}"
                    f"  ·  {_format_duration(durations[code])}")
        for code in present
    ]
    link_handles = [
        Patch(facecolor=PALETTE["collegamento"],
              label=f"Dati ricevuti dall'orologio  ·  {_format_duration(received)}"),
    ]
    if missing > 0:
        link_handles.append(Patch(facecolor="white", edgecolor=PALETTE["nessun_dato"],
                                  hatch="////",
                                  label=f"Nessun dato ricevuto dall'orologio  ·  "
                                        f"{_format_duration(missing)}"))
    return state_handles, link_handles


def _alarm_markers(data: _Data, axes: list) -> tuple[int, list]:
    # Gli allarmi biometrici, segnati con lo stesso nome nei due grafici della
    # sessione: ritorna lo spazio occupato dalle etichette e le voci di legenda.
    hr_labels = _alarm_labels("BPM", len(data.hr_alarm_times))
    spo2_labels = _alarm_labels("SpO2", len(data.spo2_alarm_times))
    markers = sorted(zip(
        np.concatenate([data.hr_alarm_times, data.spo2_alarm_times]).tolist(),
        hr_labels + spo2_labels,
    ))
    meta_offset = add_wp_change_markers(
        axes,
        np.array([when for when, _ in markers], dtype=np.float64),
        [label for _, label in markers],
        max(data.duration, 1.0), PALETTE["allarme_biometrico"],
    )
    handles = [
        Line2D([0], [0], color=PALETTE["allarme_biometrico"], linestyle="--",
               linewidth=1.1, label=_alarm_legend_label(subject, labels))
        for labels, subject in ((hr_labels, "sul battito"), (spo2_labels, "sulla saturazione"))
        if labels
    ]
    return meta_offset, handles


def _session_title(ax, data: _Data, title: str, meta_offset: int,
                   detail: Optional[str] = None) -> None:
    # Un allarme che riguarda sia il battito sia la saturazione ha un segno su
    # ciascuno, ma nel conteggio vale una volta sola.
    n_alarms = np.union1d(data.hr_alarm_times, data.spo2_alarm_times).size
    alarms_text = (
        "nessun allarme biometrico" if n_alarms == 0
        else "1 allarme biometrico" if n_alarms == 1
        else f"{n_alarms} allarmi biometrici"
    )
    lines = [f"{_subtitle(data)}  ·  {alarms_text}"]
    if detail:
        lines.append(detail)
    _heading(ax, title, lines, meta_offset)


def _stats_text(name: str, values: np.ndarray, unit: str) -> str:
    return (f"{name}: media {np.mean(values):.0f}, minimo {np.min(values):.0f}, "
            f"massimo " + _with_unit(f"{np.max(values):.0f}", unit))


def _vitals(data: _Data) -> None:
    plt, thr = data.plt, APP_CONFIG.smartwatch_thresholds

    fig, (ax_hr, ax_spo2) = plt.subplots(
        2, 1, figsize=(11, 8), sharex=True, constrained_layout=True,
        gridspec_kw={"height_ratios": [3, 2]},
    )

    # A missione non avviata l'orologio misura ma non genera allarmi: quei
    # tratti restano grigi e non entrano nelle statistiche.
    mission = np.array([state not in (None, "MISSIONE_NON_AVVIATA") for state in data.states])
    panels = (
        (ax_hr, data.hr_filtered, data.bpm, "battito", "bpm", "Battito [bpm]",
         dict(low_alarm=thr.bpm_min_in, low_back=thr.bpm_min_out,
              high_back=thr.bpm_max_out, high_alarm=thr.bpm_max_in),
         _padded_limits(data.hr_filtered, thr.bpm_min_in, thr.bpm_max_in, 8.0)),
        (ax_spo2, data.spo2_filtered, data.spo2, "SpO2", "%", "SpO2 [%]",
         dict(low_alarm=thr.spo2_min_in, low_back=thr.spo2_min_out),
         _padded_limits(data.spo2_filtered, thr.spo2_min_in, 100.0, 1.0, cap=100.6)),
    )
    has_mission = has_idle = False
    stats = []
    for ax, values, rounded, name, unit, ylabel, zones, ylim in panels:
        _zone_bands(ax, unit=unit, **zones)
        finite = np.isfinite(values)
        has_mission |= bool(np.any(finite & mission))
        has_idle |= bool(np.any(finite & ~mission))
        _plot_series(ax, data.t, np.where(mission, np.nan, values),
                     color=PALETTE["grezza"], linewidth=1.4)
        _plot_series(ax, data.t, np.where(mission, values, np.nan),
                     color=PALETTE["filtrata"], linewidth=1.7)
        # Media, minimo e massimo usano il valore arrotondato all'intero, lo
        # stesso che il firmware confronta con le soglie.
        shown = rounded[mission & np.isfinite(rounded)]
        if shown.size:
            stats.append(_stats_text(name, shown, unit))
        ax.set_ylim(*ylim)
        _style_panel(ax, ylabel)
    _time_axis(ax_spo2, data)
    meta_offset, alarm_handles = _alarm_markers(data, [ax_hr, ax_spo2])

    # La legenda ha due colonne: a sinistra le linee e gli allarmi, a destra
    # le fasce di sfondo con i valori delle soglie.
    series = []
    if has_mission:
        series.append(Line2D([0], [0], color=PALETTE["filtrata"], linewidth=1.7,
                             label="Valore misurato durante la missione"))
    if has_idle:
        series.append(Line2D([0], [0], color=PALETTE["grezza"], linewidth=1.4,
                             label="Valore a missione non avviata (soglie non controllate)"))
    series += alarm_handles
    # Ogni fascia occupa due righe, il nome e poi i valori, così le voci della
    # colonna hanno tutte la stessa forma.
    zones = [
        Patch(facecolor=PALETTE["tolleranza"], alpha=0.25,
              label=f"Valori normali\nbattito {thr.bpm_min_out}–{thr.bpm_max_out} bpm, "
                    f"SpO2 dal {thr.spo2_min_out}% in su"),
        Patch(facecolor=PALETTE["fuori_tol"], alpha=0.35,
              label=f"Zona di rientro: l'allarme non scatta, ma uno già scattato resta attivo\n"
                    f"battito {thr.bpm_min_in}–{thr.bpm_min_out} o "
                    f"{thr.bpm_max_out}–{thr.bpm_max_in} bpm, "
                    f"SpO2 {thr.spo2_min_in}–{thr.spo2_min_out}%"),
        Patch(facecolor=PALETTE["allarme_biometrico"], alpha=0.2,
              label=f"Oltre la soglia di allarme\nbattito sotto {thr.bpm_min_in} o "
                    f"sopra {thr.bpm_max_in} bpm, SpO2 sotto {thr.spo2_min_in}%"),
    ]
    _legend_below(fig, [series, zones], labelspacing=1.1)

    detail = f"A missione avviata  ·  {'  ·  '.join(stats)}" if stats else None
    _session_title(ax_hr, data, "Battito cardiaco e saturazione (SpO2) durante la sessione",
                   meta_offset, detail)
    data.save_figure(fig, _FILENAMES["vitals"])


def _states(data: _Data) -> None:
    fig, ax = data.plt.subplots(figsize=(11, 4.2), constrained_layout=True)
    state_handles, link_handles = _state_strip(ax, data)
    _time_axis(ax, data)
    meta_offset, alarm_handles = _alarm_markers(data, [ax])
    _legend_below(fig, [state_handles, link_handles + alarm_handles])
    _session_title(ax, data, "Stato e collegamento dell'orologio durante la sessione",
                   meta_offset)
    data.save_figure(fig, _FILENAMES["states"])


def save_watch_biometric_plots(logger, output_dir: Path, plt) -> list[Path]:
    """Genera e salva i grafici relativi ai dati biometrici dello smartwatch."""
    saved_paths: list[Path] = []
    data = _prepare(logger, output_dir, plt, saved_paths)

    draw_each((_hr_comparison, _spo2_comparison, _vitals, _states), data, plt, LOGGER)

    LOGGER.info("Grafici biometrici salvati in %s", output_dir)
    return saved_paths
