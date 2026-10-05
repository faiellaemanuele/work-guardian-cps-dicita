from __future__ import annotations

import time
from typing import Any, Optional, Sequence

from drone.data.flight_report_stats import (
    column_stats,
    is_circular_yaw_column,
    total_duration_sec,
)

# I file di testo della sessione di volo e di quella biometrica sono tabelle CSV
# con un'intestazione commentata e le statistiche in coda: qui stanno le parti
# comuni, senza sapere cosa ci si scrive dentro.

_RULE = "# =============================================================================\n"


def format_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def safe_text_value(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).replace("\n", " ").replace("\r", " ").strip()
    if s[:1] in ("=", "+", "-", "@"):
        s = "'" + s
    if "," in s or '"' in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def format_optional_float(value: Optional[float], precision: int = 3) -> str:
    if value is None:
        return ""
    return f"{float(value):.{precision}f}"


def format_optional_int(value: Optional[int]) -> str:
    if value is None:
        return ""
    return str(int(value))


def write_header(
    file_obj,
    *,
    title: str,
    description: str,
    columns: list[tuple[str, str]],
    notes: Sequence[str] = (),
):
    file_obj.write(_RULE)
    file_obj.write(f"# {title}\n")
    file_obj.write(_RULE)
    file_obj.write(f"# Descrizione: {description}\n")
    file_obj.write(f"# Generato il: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    file_obj.write("# Formato dati: tabella CSV testuale con separatore ','\n")
    file_obj.write("# Nota: le righe che iniziano con '#' sono commenti descrittivi.\n")
    for note in notes:
        file_obj.write(f"# {note}\n")
    file_obj.write("#\n")
    file_obj.write("# Legenda colonne:\n")
    for column_name, column_description in columns:
        file_obj.write(f"# - {column_name}: {column_description}\n")
    file_obj.write(_RULE)
    file_obj.write("\n")


def write_column_line(file_obj, columns: list[tuple[str, str]]) -> None:
    file_obj.write(",".join(column_name for column_name, _ in columns) + "\n")


def write_stats_footer(
    file_obj,
    *,
    entries: list,
    numeric_columns: list[str],
):
    if not entries:
        return
    durata = total_duration_sec(entries)
    file_obj.write("\n")
    file_obj.write(_RULE)
    file_obj.write(f"# Statistiche sessione  (campioni: {len(entries)})\n")
    if len(entries) >= 2:
        file_obj.write(f"# Durata: {durata:.1f} s\n")
    has_circular_yaw = False
    for col, minimo, massimo, mean_value, _scarto in column_stats(entries, numeric_columns):
        has_circular_yaw = has_circular_yaw or is_circular_yaw_column(col)
        file_obj.write(
            f"# {col}: min={minimo:.4f}"
            f"  max={massimo:.4f}"
            f"  media={mean_value:.4f}\n"
        )
    if has_circular_yaw:
        file_obj.write(
            "# Nota: per le colonne di yaw assoluto min/max sono estremi del "
            "wrap-around +/-180 deg, non l'ampiezza reale; la media e' circolare.\n"
        )
    file_obj.write(_RULE)


def write_section(file_obj, title: str, lines: Sequence[str]) -> None:
    file_obj.write("\n")
    file_obj.write(_RULE)
    file_obj.write(f"# {title}\n")
    file_obj.write(_RULE)
    for line in lines:
        file_obj.write(f"# {line}\n")
    file_obj.write(_RULE)
