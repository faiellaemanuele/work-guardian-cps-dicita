from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

from drone.config import APP_CONFIG, AutopilotWaypointConfig

LOGGER = logging.getLogger(__name__)

_MIN_SAFE_Z_M = 0.5


@dataclass(frozen=True, slots=True)
class WaypointPath:
    name: str
    description: str
    waypoints: tuple["AutopilotWaypointConfig", ...]
    supervision_waypoints: "tuple[int, ...] | None"
    source: Path
    safety_net_tags_by_stop: "dict[int, frozenset[int]] | None" = None
    supervision_stop_sec: "float | None" = None
    safety_net_confirm_sec: "float | None" = None
    home_waypoint: "AutopilotWaypointConfig | None" = None
    fall_alarm_after_sec: "float | None" = None
    restricted_area_alarm_after_sec: "float | None" = None
    restricted_area_tolerance_px: "float | None" = None
    dpi_required: "tuple[str, ...] | None" = None
    dpi_alarm_after_sec: "float | None" = None


def _parse_supervision_waypoints(raw, num_waypoints, filename):
    if raw is None:
        return None
    if not isinstance(raw, list):
        LOGGER.warning(
            "Percorso %s: 'supervision_waypoints' ignorato (atteso un elenco di numeri che partono da 1).",
            filename,
        )
        return None

    indices: list[int] = []
    for entry in raw:
        if isinstance(entry, bool) or not isinstance(entry, int):
            LOGGER.warning(
                "Percorso %s: indice di supervisione ignorato (non intero): %r.",
                filename,
                entry,
            )
            continue
        if not (1 <= entry <= num_waypoints):
            LOGGER.warning(
                "Percorso %s: indice di supervisione fuori dall'intervallo 1..%d ignorato: %d.",
                filename,
                num_waypoints,
                entry,
            )
            continue
        indices.append(entry)

    return tuple(sorted(set(indices)))


def _parse_safety_net_tags(raw, num_waypoints, filename):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        LOGGER.warning(
            "Percorso %s: 'safety_net_tags_by_stop' ignorato "
            "(atteso un oggetto {waypoint: [id_tag, ...]}).",
            filename,
        )
        return None

    result: dict[int, frozenset[int]] = {}
    for key, value in raw.items():
        try:
            waypoint_number = int(key)
        except (TypeError, ValueError):
            LOGGER.warning(
                "Percorso %s: chiave 'safety_net_tags_by_stop' non intera ignorata: %r.",
                filename,
                key,
            )
            continue
        if not (1 <= waypoint_number <= num_waypoints):
            LOGGER.warning(
                "Percorso %s: waypoint di 'safety_net_tags_by_stop' fuori dall'intervallo 1..%d ignorato: %d.",
                filename,
                num_waypoints,
                waypoint_number,
            )
            continue
        if not isinstance(value, list):
            LOGGER.warning(
                "Percorso %s: tag del waypoint %d ignorati "
                "(atteso un elenco di ID AprilTag): %r.",
                filename,
                waypoint_number,
                value,
            )
            continue

        tags: set[int] = set()
        for tag in value:
            if isinstance(tag, bool) or not isinstance(tag, int):
                LOGGER.warning(
                    "Percorso %s: ID AprilTag non intero ignorato (waypoint %d): %r.",
                    filename,
                    waypoint_number,
                    tag,
                )
                continue
            if tag < 0:
                LOGGER.warning(
                    "Percorso %s: ID AprilTag negativo ignorato (waypoint %d): %d.",
                    filename,
                    waypoint_number,
                    tag,
                )
                continue
            tags.add(tag)

        if tags:
            result[waypoint_number] = frozenset(tags)

    return result or None


class _PathConfigError(ValueError):
    pass


def _parse_supervision_stop_sec(raw, has_supervision, waypoint_timeout_sec=None):
    if raw is None:
        if has_supervision:
            raise _PathConfigError(
                "manca la durata di supervisione ('supervision_stop_sec') per i "
                "waypoint di supervisione del percorso."
            )
        return None

    if not has_supervision:
        raise _PathConfigError(
            "'supervision_stop_sec' definito ma nessun waypoint di supervisione "
            "('supervision_waypoints' assente o vuoto)."
        )

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _PathConfigError(
            f"'supervision_stop_sec' deve essere un numero di secondi: {raw!r}."
        )
    seconds = float(raw)
    if not math.isfinite(seconds) or seconds <= 0:
        raise _PathConfigError(
            f"'supervision_stop_sec' deve essere positivo: {raw!r}."
        )
    if waypoint_timeout_sec is not None and seconds >= waypoint_timeout_sec:
        raise _PathConfigError(
            f"'supervision_stop_sec' ({seconds:g}s) deve essere minore del timeout di "
            f"waypoint ({float(waypoint_timeout_sec):g}s): una sosta lunga quanto il "
            "timeout anti-stallo verrebbe interrotta da un fault prima di completarsi."
        )
    return seconds


def _parse_safety_net_confirm_sec(raw, has_safety_net, supervision_stop_sec):
    if raw is None:
        if has_safety_net:
            raise _PathConfigError(
                "manca la durata minima di detection rete "
                "('safety_net_confirm_sec') richiesta dal controllo rete "
                "('safety_net_tags_by_stop')."
            )
        return None

    if not has_safety_net:
        raise _PathConfigError(
            "'safety_net_confirm_sec' definito ma nessun controllo rete "
            "('safety_net_tags_by_stop' assente o vuoto)."
        )

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _PathConfigError(
            f"'safety_net_confirm_sec' deve essere un numero di secondi: {raw!r}."
        )
    seconds = float(raw)
    if not math.isfinite(seconds) or seconds < 0:
        raise _PathConfigError(
            f"'safety_net_confirm_sec' deve essere >= 0: {raw!r}."
        )
    if supervision_stop_sec is not None and seconds >= supervision_stop_sec:
        raise _PathConfigError(
            f"'safety_net_confirm_sec' ({seconds:g}s) deve essere minore della "
            f"sosta di supervisione ({float(supervision_stop_sec):g}s): altrimenti la sosta "
            "finirebbe prima di accumulare la detection continuativa richiesta."
        )
    return seconds


def _parse_home_waypoint(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _PathConfigError(
            f"'home_waypoint' deve essere un oggetto {{x, y, z, yaw_deg}}: {raw!r}."
        )
    try:
        x = float(raw["x"])
        y = float(raw["y"])
        z = float(raw["z"])
        yaw_deg = float(raw.get("yaw_deg", 0.0))
    except (TypeError, KeyError, ValueError) as exc:
        raise _PathConfigError(
            f"'home_waypoint' malformato ({exc}): servono x, y, z numerici."
        ) from exc
    if not all(math.isfinite(v) for v in (x, y, z, yaw_deg)):
        raise _PathConfigError(
            "'home_waypoint' con coordinate non finite (nan/inf)."
        )
    if z < _MIN_SAFE_Z_M:
        raise _PathConfigError(
            f"'home_waypoint' con z ({z:g}) < {_MIN_SAFE_Z_M:g} m: nel frame mondo z=0 è il "
            "pavimento, la home deve avere una quota di sicurezza."
        )
    return AutopilotWaypointConfig(x=x, y=y, z=z, yaw_deg=yaw_deg)


def _parse_optional_number(raw, key_name: str):
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _PathConfigError(f"'{key_name}' deve essere un numero: {raw!r}.")
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise _PathConfigError(f"'{key_name}' deve essere un numero >= 0: {raw!r}.")
    return value


def _parse_dpi_required(raw, has_supervision, filename):
    if raw is None:
        return None
    if not isinstance(raw, list):
        LOGGER.warning(
            "Percorso %s: 'dpi_required' ignorato (atteso un elenco di dispositivi).",
            filename,
        )
        return None

    keys: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            LOGGER.warning(
                "Percorso %s: dispositivo DPI ignorato (non è una stringa): %r.",
                filename,
                entry,
            )
            continue
        keys.append(entry.strip().casefold())

    if not keys:
        return None
    if not has_supervision:
        raise _PathConfigError(
            "'dpi_required' definito ma nessun waypoint di supervisione "
            "('supervision_waypoints' assente o vuoto): il controllo DPI agisce "
            "solo durante le soste."
        )
    return tuple(sorted(set(keys)))


def _parse_dpi_alarm_after_sec(raw, has_dpi, supervision_stop_sec):
    if raw is None:
        if has_dpi:
            raise _PathConfigError(
                "manca la durata minima di assenza DPI ('dpi_alarm_after_sec') "
                "richiesta dal controllo DPI ('dpi_required')."
            )
        return None

    if not has_dpi:
        raise _PathConfigError(
            "'dpi_alarm_after_sec' definito ma nessun controllo DPI "
            "('dpi_required' assente o vuoto)."
        )

    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _PathConfigError(
            f"'dpi_alarm_after_sec' deve essere un numero di secondi: {raw!r}."
        )
    seconds = float(raw)
    if not math.isfinite(seconds) or seconds < 0:
        raise _PathConfigError(
            f"'dpi_alarm_after_sec' deve essere >= 0: {raw!r}."
        )
    if supervision_stop_sec is not None and seconds >= supervision_stop_sec:
        raise _PathConfigError(
            f"'dpi_alarm_after_sec' ({seconds:g}s) deve essere minore della sosta "
            f"di supervisione ({float(supervision_stop_sec):g}s): altrimenti la sosta "
            "finirebbe prima di accumulare l'assenza continuativa richiesta."
        )
    return seconds


_RENAMED_KEYS = {
    "hazard_min_consecutive_sec": "fall_alarm_after_sec",
    "supervision_hold_sec": "supervision_stop_sec",
    "dpc_tags": "safety_net_tags_by_stop",
    "dpc_min_consecutive_sec": "safety_net_confirm_sec",
    "fall_min_consecutive_sec": "fall_alarm_after_sec",
    "restricted_area_min_consecutive_sec": "restricted_area_alarm_after_sec",
    "restricted_area_proximity_px": "restricted_area_tolerance_px",
    "dpi_min_consecutive_sec": "dpi_alarm_after_sec",
}


def _warn_renamed_keys(data, filename) -> None:
    for old_key, new_key in _RENAMED_KEYS.items():
        if old_key in data:
            LOGGER.warning(
                "Percorso %s: '%s' si chiama ora '%s'; il valore vecchio viene ignorato.",
                filename,
                old_key,
                new_key,
            )


def _read_path_file(f) -> "dict | None":
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOGGER.warning("File di percorso ignorato (JSON non valido): %s | %s", f.name, exc)
        return None

    if not isinstance(data, dict):
        LOGGER.warning(
            "File di percorso ignorato (atteso un oggetto JSON con chiave 'waypoints'): %s",
            f.name,
        )
        return None

    if not isinstance(data.get("waypoints"), list):
        LOGGER.warning(
            "File di percorso ignorato (chiave 'waypoints' mancante o non valida): %s",
            f.name,
        )
        return None

    _warn_renamed_keys(data, f.name)

    return data


def _parse_waypoints(raw_waypoints, filename) -> "tuple[AutopilotWaypointConfig, ...] | None":
    waypoints: list[AutopilotWaypointConfig] = []
    for item in raw_waypoints:
        try:
            x = float(item["x"])
            y = float(item["y"])
            z = float(item["z"])
            yaw_deg = float(item.get("yaw_deg", 0.0))
            if not all(math.isfinite(v) for v in (x, y, z, yaw_deg)):
                LOGGER.warning("File di percorso ignorato (waypoint malformati): %s", filename)
                return None
            if z < _MIN_SAFE_Z_M:
                LOGGER.error(
                    "File di percorso ignorato (waypoint sotto la quota di sicurezza: "
                    "z=%.2f m, minimo %.2f m; nel frame mondo z=0 è il pavimento): %s",
                    z,
                    _MIN_SAFE_Z_M,
                    filename,
                )
                return None
            waypoints.append(
                AutopilotWaypointConfig(x=x, y=y, z=z, yaw_deg=yaw_deg)
            )
        except (TypeError, KeyError, ValueError):
            LOGGER.warning("File di percorso ignorato (waypoint malformati): %s", filename)
            return None

    if not waypoints:
        LOGGER.warning("File di percorso ignorato (nessun waypoint): %s", filename)
        return None

    return tuple(waypoints)


def _prune_unreachable_safety_net_tags(safety_net_tags_by_stop, supervision, filename):
    if safety_net_tags_by_stop is None:
        return None, []

    supervision_set = set(supervision or ())
    unreachable = sorted(w for w in safety_net_tags_by_stop if w not in supervision_set)
    for w in unreachable:
        LOGGER.warning(
            "Percorso %s: 'safety_net_tags_by_stop' del waypoint %d ignorati "
            "(non \u00e8 un waypoint di supervisione).",
            filename,
            w,
        )
    if unreachable:
        safety_net_tags_by_stop = {
            w: tags
            for w, tags in safety_net_tags_by_stop.items()
            if w in supervision_set
        } or None
    return safety_net_tags_by_stop, unreachable


def _parse_scenario(
    data,
    *,
    filename,
    supervision,
    safety_net_tags_by_stop,
    unreachable_safety_net,
    waypoint_timeout_sec,
) -> dict:
    if safety_net_tags_by_stop is None and data.get("safety_net_tags_by_stop") is not None:
        if unreachable_safety_net:
            raise _PathConfigError(
                "'safety_net_tags_by_stop' fa riferimento solo a waypoint che non sono "
                f"di supervisione ({', '.join(str(w) for w in unreachable_safety_net)}): "
                "il controllo rete non potrebbe mai concludersi. Aggiungili a "
                "'supervision_waypoints' oppure correggi i numeri."
            )
        raise _PathConfigError(
            "'safety_net_tags_by_stop' non associa nessun waypoint a ID AprilTag validi: "
            "il controllo rete non potrebbe mai concludersi."
        )

    supervision_stop_sec = _parse_supervision_stop_sec(
        data.get("supervision_stop_sec"), bool(supervision), waypoint_timeout_sec,
    )
    safety_net_confirm_sec = _parse_safety_net_confirm_sec(
        data.get("safety_net_confirm_sec"),
        safety_net_tags_by_stop is not None,
        supervision_stop_sec,
    )
    home_waypoint = _parse_home_waypoint(data.get("home_waypoint"))
    fall_alarm_after_sec = _parse_optional_number(
        data.get("fall_alarm_after_sec"), "fall_alarm_after_sec"
    )
    restricted_area_alarm_after_sec = _parse_optional_number(
        data.get("restricted_area_alarm_after_sec"),
        "restricted_area_alarm_after_sec",
    )
    restricted_area_tolerance_px = _parse_optional_number(
        data.get("restricted_area_tolerance_px"), "restricted_area_tolerance_px"
    )
    dpi_required = _parse_dpi_required(
        data.get("dpi_required"), bool(supervision), filename
    )
    dpi_alarm_after_sec = _parse_dpi_alarm_after_sec(
        data.get("dpi_alarm_after_sec"),
        dpi_required is not None,
        supervision_stop_sec,
    )

    return {
        "supervision_stop_sec": supervision_stop_sec,
        "safety_net_confirm_sec": safety_net_confirm_sec,
        "home_waypoint": home_waypoint,
        "fall_alarm_after_sec": fall_alarm_after_sec,
        "restricted_area_alarm_after_sec": restricted_area_alarm_after_sec,
        "restricted_area_tolerance_px": restricted_area_tolerance_px,
        "dpi_required": dpi_required,
        "dpi_alarm_after_sec": dpi_alarm_after_sec,
    }


def load_waypoint_paths(directory) -> list["WaypointPath"]:
    try:
        directory = Path(directory)
        files = sorted(directory.glob("*.json")) if directory.is_dir() else []
    except OSError:
        files = []

    autopilot_config = APP_CONFIG.apriltag_autopilot
    waypoint_timeout_sec = (
        float(autopilot_config.waypoint_timeout_sec)
        if autopilot_config.waypoint_timeout_enabled
        else None
    )

    paths: list[WaypointPath] = []
    for f in files:
        data = _read_path_file(f)
        if data is None:
            continue

        waypoints = _parse_waypoints(data["waypoints"], f.name)
        if waypoints is None:
            continue

        supervision = _parse_supervision_waypoints(
            data.get("supervision_waypoints"), len(waypoints), f.name
        )
        safety_net_tags_by_stop, unreachable_safety_net = _prune_unreachable_safety_net_tags(
            _parse_safety_net_tags(data.get("safety_net_tags_by_stop"), len(waypoints), f.name),
            supervision,
            f.name,
        )

        try:
            scenario = _parse_scenario(
                data,
                filename=f.name,
                supervision=supervision,
                safety_net_tags_by_stop=safety_net_tags_by_stop,
                unreachable_safety_net=unreachable_safety_net,
                waypoint_timeout_sec=waypoint_timeout_sec,
            )
        except _PathConfigError as exc:
            LOGGER.error(
                "File di percorso ignorato (configurazione incoerente): %s | %s",
                f.name,
                exc,
            )
            continue

        paths.append(
            WaypointPath(
                str(data.get("name") or f.stem),
                str(data.get("description") or ""),
                waypoints,
                supervision,
                f,
                safety_net_tags_by_stop=safety_net_tags_by_stop,
                **scenario,
            )
        )

    return paths
