from __future__ import annotations

import math
from typing import Any, Callable, Optional


def join_tag_ids(tag_ids: Any, separator: str) -> str:
    if not tag_ids:
        return ""
    return separator.join(str(int(tag_id)) for tag_id in tag_ids)


def values_of(entries, key: str) -> list[float]:
    return [float(e[key]) for e in entries if e.get(key) is not None]


def entries_with_pose(entries) -> list:
    return [e for e in entries if e.get("x") is not None]


def rms(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return math.sqrt(sum(v * v for v in values) / len(values))


def percent_within(entries, predicate: Callable, is_applicable: Callable) -> Optional[float]:
    applicable = [e for e in entries if is_applicable(e)]
    if not applicable:
        return None
    within = sum(1 for e in applicable if predicate(e))
    return 100.0 * within / len(applicable)


def duration_key(entries) -> str:
    if entries and all("monotonic" in e for e in entries):
        return "monotonic"
    return "timestamp"


def elapsed_seconds(entries) -> list[float]:
    if not entries:
        return []
    chiave = duration_key(entries)
    base = float(entries[0][chiave])
    return [float(e[chiave]) - base for e in entries]


def total_duration_sec(entries) -> float:
    tempi = elapsed_seconds(entries)
    return tempi[-1] if tempi else 0.0


def waypoint_groups(entries) -> list[dict[str, Any]]:
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
