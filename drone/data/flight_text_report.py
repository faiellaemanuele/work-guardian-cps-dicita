from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from drone.data.flight_report_stats import (
    elapsed_seconds,
    filter_divergence,
    join_tag_ids,
    percent_within,
    rms,
    total_duration_sec,
    values_of,
    waypoint_groups,
)
from drone.geometry import circular_mean_deg


def _format_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _safe_text_value(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).replace("\n", " ").replace("\r", " ").strip()
    if s[:1] in ("=", "+", "-", "@"):
        s = "'" + s
    if "," in s or '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def _format_optional_float(value: Optional[float], precision: int = 3) -> str:
    if value is None:
        return ""
    return f"{float(value):.{precision}f}"


def _format_optional_int(value: Optional[int]) -> str:
    if value is None:
        return ""
    return str(int(value))


def _write_text_header(
    file_obj,
    *,
    title: str,
    description: str,
    columns: list[tuple[str, str]],
    tag_ids_separator: str,
):
    file_obj.write("# =============================================================================\n")
    file_obj.write(f"# {title}\n")
    file_obj.write("# =============================================================================\n")
    file_obj.write(f"# Descrizione: {description}\n")
    file_obj.write(f"# Generato il: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    file_obj.write("# Formato dati: tabella CSV testuale con separatore ','\n")
    file_obj.write("# Nota: le righe che iniziano con '#' sono commenti descrittivi.\n")
    file_obj.write(f"# Separatore degli ID AprilTag multipli: '{tag_ids_separator}'\n")
    file_obj.write("#\n")
    file_obj.write("# Legenda colonne:\n")
    for column_name, column_description in columns:
        file_obj.write(f"# - {column_name}: {column_description}\n")
    file_obj.write("# =============================================================================\n")
    file_obj.write("\n")


def _write_text_footer(
    file_obj,
    *,
    entries: list,
    numeric_columns: list[str],
):
    if not entries:
        return
    durata = total_duration_sec(entries)
    file_obj.write("\n")
    file_obj.write("# =============================================================================\n")
    file_obj.write(f"# Statistiche sessione  (campioni: {len(entries)})\n")
    if len(entries) >= 2:
        file_obj.write(f"# Durata: {durata:.1f} s\n")
    has_circular_yaw = False
    for col in numeric_columns:
        values = [
            float(e[col]) for e in entries
            if col in e and e[col] is not None
        ]
        if not values:
            continue
        if "yaw" in col and "error" not in col:
            mean_value = circular_mean_deg(values)
            has_circular_yaw = True
        else:
            mean_value = sum(values) / len(values)
        file_obj.write(
            f"# {col}: min={min(values):.4f}"
            f"  max={max(values):.4f}"
            f"  media={mean_value:.4f}\n"
        )
    if has_circular_yaw:
        file_obj.write(
            "# Nota: per le colonne di yaw assoluto min/max sono estremi del "
            "wrap-around +/-180 deg, non l'ampiezza reale; la media e' circolare.\n"
        )
    file_obj.write("# =============================================================================\n")


def _write_autopilot_extended_stats(
    file_obj,
    entries: list,
    *,
    xy_tolerance_m: Optional[float],
    z_tolerance_m: Optional[float],
    yaw_tolerance_deg: Optional[float],
) -> None:
    if not entries:
        return

    file_obj.write("\n")
    file_obj.write("# =============================================================================\n")
    file_obj.write("# Statistiche avanzate autopilota (per la taratura)\n")
    file_obj.write("# =============================================================================\n")

    rms_xy = rms(values_of(entries, "distance_xy"))
    rms_3d = rms(values_of(entries, "distance_3d"))
    rms_yaw = rms(values_of(entries, "yaw_error_deg"))
    if rms_xy is not None:
        file_obj.write(f"# RMS distanza XY: {rms_xy:.4f} m\n")
    if rms_3d is not None:
        file_obj.write(f"# RMS distanza 3D: {rms_3d:.4f} m\n")
    if rms_yaw is not None:
        file_obj.write(f"# RMS errore yaw: {rms_yaw:.4f} deg\n")

    if xy_tolerance_m is not None:
        pct = percent_within(
            entries,
            lambda e: float(e["distance_xy"]) <= xy_tolerance_m,
            lambda e: e.get("distance_xy") is not None,
        )
        if pct is not None:
            file_obj.write(
                f"# Tempo entro tolleranza XY (<= {xy_tolerance_m:.3f} m): "
                f"{pct:.1f}%\n"
            )
    if z_tolerance_m is not None:
        pct = percent_within(
            entries,
            lambda e: abs(float(e["z"]) - float(e["target_z"])) <= z_tolerance_m,
            lambda e: e.get("z") is not None and e.get("target_z") is not None,
        )
        if pct is not None:
            file_obj.write(
                f"# Tempo entro tolleranza Z (<= {z_tolerance_m:.3f} m): "
                f"{pct:.1f}%\n"
            )
    if yaw_tolerance_deg is not None:
        pct = percent_within(
            entries,
            lambda e: abs(float(e["yaw_error_deg"])) <= yaw_tolerance_deg,
            lambda e: e.get("yaw_error_deg") is not None,
        )
        if pct is not None:
            file_obj.write(
                f"# Tempo entro tolleranza yaw (<= {yaw_tolerance_deg:.1f} deg): "
                f"{pct:.1f}%\n"
            )

    groups = waypoint_groups(entries)

    file_obj.write("#\n# Tempo per waypoint (W = indice 1-based, durata come target attivo):\n")
    for g in groups:
        label = "--" if g["index"] is None else str(int(g["index"]) + 1)
        duration = g["end"] - g["start"]
        min_d3 = "--" if g["min_d3"] is None else f"{g['min_d3']:.3f} m"
        reached_str = "si" if g["reached"] else "no"
        file_obj.write(
            f"#   W{label}: durata {duration:.1f}s  min_dist {min_d3}  raggiunto {reached_str}\n"
        )
    file_obj.write("# =============================================================================\n")


def _write_filter_divergence_note(file_obj, entries: list, *, margin_m: float) -> None:
    if not entries:
        return
    flagged = [
        f"{d['axis']} (filtrata [{d['filtered_min']:.3f}, {d['filtered_max']:.3f}] m "
        f"oltre grezza [{d['raw_min']:.3f}, {d['raw_max']:.3f}] m di {d['excess']:.3f} m)"
        for d in filter_divergence(entries, margin_m)
    ]
    if not flagged:
        return
    file_obj.write("\n")
    file_obj.write("# =============================================================================\n")
    file_obj.write("# AVVISO divergenza filtro Kalman\n")
    file_obj.write(
        f"# La posa filtrata esce dai valori della grezza oltre {margin_m:.2f} m "
        "su uno o più assi:\n"
    )
    for item in flagged:
        file_obj.write(f"#   - {item}\n")
    file_obj.write(
        "# Possibile correzione divergente, oppure una misura sbagliata che il "
        "controllo del filtro non ha scartato (verifica process_noise, "
        "measurement_noise e outlier_gate_threshold).\n"
    )
    file_obj.write("# =============================================================================\n")


def save_comparison_data_to_file(logger, output_path: Path) -> Path:
    columns = [
        ("timestamp_s", "timestamp assoluto UNIX del campione [s]"),
        ("tempo_relativo_s", "tempo trascorso dal primo campione del file [s]"),
        ("raw_x_m", "coordinata X della posa grezza AprilTag [m]"),
        ("raw_y_m", "coordinata Y della posa grezza AprilTag [m]"),
        ("raw_z_m", "coordinata Z della posa grezza AprilTag [m]"),
        ("raw_yaw_deg", "yaw associato alla posa grezza AprilTag [deg]"),
        ("kalman_x_m", "coordinata X dopo filtraggio di Kalman [m]"),
        ("kalman_y_m", "coordinata Y dopo filtraggio di Kalman [m]"),
        ("kalman_z_m", "coordinata Z dopo filtraggio di Kalman [m]"),
        ("kalman_yaw_deg", "yaw filtrato da Kalman se yaw_filter_enabled=True, altrimenti corrisponde a quello grezzo [deg]"),
        ("errore_x_m", "differenza kalman_x_m - raw_x_m [m]"),
        ("errore_y_m", "differenza kalman_y_m - raw_y_m [m]"),
        ("errore_z_m", "differenza kalman_z_m - raw_z_m [m]"),
        ("norma_errore_m", "norma euclidea della correzione introdotta dal filtro [m]"),
        ("tag_ids", "ID degli AprilTag usati per la stima, separati dal carattere indicato sopra"),
        ("sorgente_raw", "descrizione della sorgente della posa grezza"),
        ("sorgente_kalman", "descrizione della sorgente della posa filtrata"),
        ("outlier_scartato", "true se il filtro di Kalman ha scartato la misura grezza: la posa filtrata e' solo la previsione"),
    ]

    entries = logger.comparison_entries
    separator = logger.TAG_IDS_SEPARATOR
    tempi_relativi = dict(zip((id(e) for e in entries), elapsed_seconds(entries)))

    with output_path.open("w", encoding="utf-8") as f:
        _write_text_header(
            f,
            title="CONFRONTO POSE APRILTAG RAW E POSE FILTRATE KALMAN",
            description=(
                "tabella per valutare quanto il filtro di Kalman modifica la posa stimata "
                "a partire dalle misure grezze degli AprilTag."
            ),
            columns=columns,
            tag_ids_separator=separator,
        )

        f.write(",".join(column_name for column_name, _ in columns) + "\n")

        for entry in entries:
            tag_ids_str = join_tag_ids(entry["tag_ids"], separator)
            relative_time = tempi_relativi[id(entry)]

            line = (
                f"{entry['timestamp']:.3f},"
                f"{relative_time:.3f},"
                f"{entry['raw_x']:.3f},"
                f"{entry['raw_y']:.3f},"
                f"{entry['raw_z']:.3f},"
                f"{entry['raw_yaw_deg']:.3f},"
                f"{entry['filtered_x']:.3f},"
                f"{entry['filtered_y']:.3f},"
                f"{entry['filtered_z']:.3f},"
                f"{entry['filtered_yaw_deg']:.3f},"
                f"{entry['error_x']:.3f},"
                f"{entry['error_y']:.3f},"
                f"{entry['error_z']:.3f},"
                f"{entry['error_norm']:.3f},"
                f"{tag_ids_str},"
                f"{_safe_text_value(entry['raw_source'])},"
                f"{_safe_text_value(entry['filtered_source'])},"
                f"{_format_bool(entry.get('outlier_rejected', False))}\n"
            )
            f.write(line)

        _write_text_footer(
            f,
            entries=entries,
            numeric_columns=[
                "raw_x", "raw_y", "raw_z", "raw_yaw_deg",
                "filtered_x", "filtered_y", "filtered_z", "filtered_yaw_deg",
                "error_norm",
            ],
        )

        _write_filter_divergence_note(f, entries, margin_m=logger.FILTER_DIVERGENCE_MARGIN_M)

    return output_path


def save_autopilot_data_to_file(logger, output_path: Path) -> Path:
    columns = [
        ("timestamp_s", "timestamp assoluto UNIX del campione [s]"),
        ("tempo_relativo_s", "tempo trascorso dal primo campione del file [s]"),
        ("x_mondo_m", "coordinata X della posa usata dall'autopilota nel frame mondo [m]"),
        ("y_mondo_m", "coordinata Y della posa usata dall'autopilota nel frame mondo [m]"),
        ("z_mondo_m", "coordinata Z della posa usata dall'autopilota nel frame mondo [m]"),
        ("yaw_mondo_deg", "yaw della posa usata dall'autopilota [deg]"),
        ("waypoint_x_m", "coordinata X del waypoint attivo [m]"),
        ("waypoint_y_m", "coordinata Y del waypoint attivo [m]"),
        ("waypoint_z_m", "coordinata Z del waypoint attivo [m]"),
        ("waypoint_yaw_deg", "yaw desiderato del waypoint attivo [deg]"),
        ("comando_lr", "comando RC laterale left/right inviato o calcolato dall'autopilota"),
        ("comando_fb", "comando RC forward/backward inviato o calcolato dall'autopilota"),
        ("comando_ud", "comando RC up/down inviato o calcolato dall'autopilota"),
        ("comando_yaw", "comando RC di rotazione yaw inviato o calcolato dall'autopilota"),
        ("distanza_xy_m", "distanza planare dal waypoint attivo [m]"),
        ("distanza_3d_m", "distanza spaziale dal waypoint attivo [m]"),
        ("errore_yaw_deg", "errore di orientamento rispetto al waypoint [deg]"),
        ("indice_waypoint", "indice del waypoint attivo nella sequenza"),
        ("waypoint_raggiunto", "true se il waypoint è stato considerato raggiunto in quel campione"),
        ("missione_finita", "true se la sequenza di waypoint risulta completata"),
        ("fault", "true se il controllore segnala una condizione anomala"),
        ("motivo", "motivo diagnostico restituito dall'autopilota"),
        ("tag_ids", "ID degli AprilTag usati per la stima, separati dal carattere indicato sopra"),
        ("sorgente_posa", "descrizione della sorgente della posa usata dall'autopilota"),
    ]

    entries = logger.autopilot_entries
    separator = logger.TAG_IDS_SEPARATOR
    tempi_relativi = dict(zip((id(e) for e in entries), elapsed_seconds(entries)))

    with output_path.open("w", encoding="utf-8") as f:
        _write_text_header(
            f,
            title="LOG MISSIONE AUTOPILOTA APRILTAG",
            description=(
                "campioni registrati durante il volo autonomo; include posa stimata, "
                "waypoint attivo, distanze dal target, comandi RC e stato della missione."
            ),
            columns=columns,
            tag_ids_separator=separator,
        )

        f.write(",".join(column_name for column_name, _ in columns) + "\n")

        for entry in entries:
            tag_ids_str = join_tag_ids(entry["tag_ids"], separator)
            relative_time = tempi_relativi[id(entry)]

            line = (
                f"{entry['timestamp']:.3f},"
                f"{relative_time:.3f},"
                f"{_format_optional_float(entry['x'])},"
                f"{_format_optional_float(entry['y'])},"
                f"{_format_optional_float(entry['z'])},"
                f"{_format_optional_float(entry['yaw_deg'], precision=3)},"
                f"{_format_optional_float(entry['target_x'])},"
                f"{_format_optional_float(entry['target_y'])},"
                f"{_format_optional_float(entry['target_z'])},"
                f"{_format_optional_float(entry['target_yaw_deg'], precision=3)},"
                f"{entry['lr']},"
                f"{entry['fb']},"
                f"{entry['ud']},"
                f"{entry['yaw_cmd']},"
                f"{_format_optional_float(entry['distance_xy'])},"
                f"{_format_optional_float(entry['distance_3d'])},"
                f"{_format_optional_float(entry['yaw_error_deg'], precision=3)},"
                f"{_format_optional_int(entry['target_index'])},"
                f"{_format_bool(entry['reached'])},"
                f"{_format_bool(entry['finished'])},"
                f"{_format_bool(entry['fault'])},"
                f"{_safe_text_value(entry['reason'])},"
                f"{tag_ids_str},"
                f"{_safe_text_value(entry['pose_source'])}\n"
            )
            f.write(line)

        _write_text_footer(
            f,
            entries=entries,
            numeric_columns=["x", "y", "z", "yaw_deg", "distance_xy", "distance_3d", "yaw_error_deg"],
        )

        _write_autopilot_extended_stats(
            f,
            entries,
            xy_tolerance_m=logger.autopilot_xy_tolerance_m,
            z_tolerance_m=logger.autopilot_z_tolerance_m,
            yaw_tolerance_deg=logger.autopilot_yaw_tolerance_deg,
        )

    return output_path
