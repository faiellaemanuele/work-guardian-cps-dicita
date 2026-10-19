"""Calcola statistiche e indicatori sintetici a partire dai dati registrati durante il volo."""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

from drone.geometry import circular_mean_deg


def is_circular_yaw_column(col: str) -> bool:
    """Indica se la colonna rappresenta uno yaw da trattare come grandezza circolare."""
    return "yaw" in col and "error" not in col


def _std(values: list[float], mean_value: float) -> Optional[float]:
    if not values:
        return None
    return math.sqrt(sum((v - mean_value) ** 2 for v in values) / len(values))


def _circular_std_deg(values: list[float]) -> Optional[float]:
    if not values:
        return None
    rad = [math.radians(v) for v in values]
    cos_sum = sum(math.cos(r) for r in rad) / len(rad)
    sin_sum = sum(math.sin(r) for r in rad) / len(rad)
    resultant = math.hypot(cos_sum, sin_sum)
    if resultant <= 0.0:
        return None
    return math.degrees(math.sqrt(max(0.0, -2.0 * math.log(resultant))))


def column_stats(entries, columns: list[str]) -> list[tuple[str, float, float, float, Optional[float]]]:
    """Calcola le statistiche descrittive di una colonna numerica."""
    out: list[tuple[str, float, float, float, Optional[float]]] = []
    for col in columns:
        values = values_of(entries, col)
        if not values:
            continue
        if is_circular_yaw_column(col):
            mean_value = circular_mean_deg(values)
            std_value = _circular_std_deg(values)
        else:
            mean_value = sum(values) / len(values)
            std_value = _std(values, mean_value)
        out.append((col, min(values), max(values), mean_value, std_value))
    return out


def join_tag_ids(tag_ids: Any, separator: str) -> str:
    """Converte una raccolta di ID AprilTag in una rappresentazione testuale compatta."""
    if not tag_ids:
        return ""
    return separator.join(str(int(tag_id)) for tag_id in tag_ids)


def values_of(entries, key: str) -> list[float]:
    """Estrae i valori validi associati a una chiave dalle righe disponibili."""
    return [float(e[key]) for e in entries if e.get(key) is not None]


def entries_with_pose(entries) -> list:
    """Seleziona le righe che contengono una stima di posa utilizzabile."""
    return [e for e in entries if e.get("x") is not None]


def rms(values: list[float]) -> Optional[float]:
    """Calcola il valore quadratico medio di una sequenza numerica."""
    if not values:
        return None
    return math.sqrt(sum(v * v for v in values) / len(values))


def percent_within(entries, predicate: Callable, is_applicable: Callable) -> Optional[float]:
    """Calcola la percentuale di valori compresi entro una soglia."""
    applicable = [e for e in entries if is_applicable(e)]
    if not applicable:
        return None
    within = sum(1 for e in applicable if predicate(e))
    return 100.0 * within / len(applicable)


def duration_key(entries) -> str:
    """Restituisce la durata associata a una riga usando il campo temporale disponibile."""
    if entries and all("monotonic" in e for e in entries):
        return "monotonic"
    return "timestamp"


def elapsed_seconds(entries) -> list[float]:
    """Calcola i secondi trascorsi rispetto al riferimento temporale indicato."""
    if not entries:
        return []
    chiave = duration_key(entries)
    base = float(entries[0][chiave])
    return [float(e[chiave]) - base for e in entries]


def total_duration_sec(entries) -> float:
    """Calcola la durata complessiva coperta dalle righe del report."""
    tempi = elapsed_seconds(entries)
    return tempi[-1] if tempi else 0.0


def waypoint_groups(entries) -> list[dict[str, Any]]:
    """Raggruppa le righe dell'autopilota per waypoint di destinazione."""
    groups: list[dict[str, Any]] = []
    for e, ti in zip(entries, elapsed_seconds(entries)):
        idx = e.get("target_index")
        d3 = e.get("distance_3d")
        reached = bool(e.get("reached", False))
        if groups and groups[-1]["index"] == idx:
            g = groups[-1]
            g["end"] = ti
            if d3 is not None:
                d3f = float(d3)
                g["min_d3"] = d3f if g["min_d3"] is None else min(g["min_d3"], d3f)
            g["reached"] = g["reached"] or reached
        else:
            groups.append({
                "index": idx,
                "start": ti,
                "end": ti,
                "min_d3": (float(d3) if d3 is not None else None),
                "reached": reached,
            })
    return groups


def filter_divergence(entries, margin_m: float) -> list[dict[str, Any]]:
    """Individua campioni in cui posa grezza e filtrata divergono oltre le soglie previste."""
    diverging: list[dict[str, Any]] = []
    for axis in ("x", "y", "z"):
        raws = [float(e[f"raw_{axis}"]) for e in entries if e.get(f"raw_{axis}") is not None]
        filtereds = [float(e[f"filtered_{axis}"]) for e in entries if e.get(f"filtered_{axis}") is not None]
        if not raws or not filtereds:
            continue
        excess = max(max(filtereds) - max(raws), min(raws) - min(filtereds))
        if excess > margin_m:
            diverging.append({
                "axis": axis.upper(),
                "raw_min": min(raws),
                "raw_max": max(raws),
                "filtered_min": min(filtereds),
                "filtered_max": max(filtereds),
                "excess": excess,
            })
    return diverging
