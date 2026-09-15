from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_CATALOG_RELATIVE = ("vision", "models", "catalog.json")

_DEFAULT_COLOR = (0, 255, 0)

_DEFAULT_SAFETY_NET_MODEL = "Protezioni_Collettive"
_DEFAULT_PERSON_FALL_MODEL = "Caduta_delle_Persone"
_DEFAULT_RESTRICTED_AREA_MODEL = "Aree_Interdette"
_DEFAULT_DPI_MODEL = "Protezioni_Individuali"


@dataclass(frozen=True)
class YoloModelConfig:
    name: str
    path: Path
    color: tuple[int, int, int] = _DEFAULT_COLOR
    label: str = ""

    def __post_init__(self):
        if not self.label:
            object.__setattr__(self, "label", self.name)


def _name_from_weights(weights: str) -> str:
    return Path(weights).parent.parent.name


def _read_catalog(base_dir):
    catalog_path = Path(base_dir).joinpath(*_CATALOG_RELATIVE)
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        LOGGER.error("Non è stato possibile leggere il catalogo dei modelli YOLO (%s): %s", catalog_path, exc)
        return None
    if not isinstance(data, dict):
        LOGGER.error("Il catalogo dei modelli YOLO non è valido perché non contiene un oggetto JSON: %s", catalog_path)
        return None
    return data


def _coerce_color(raw, name):
    if raw is None:
        return _DEFAULT_COLOR
    if not isinstance(raw, (list, tuple)) or len(raw) != 3 or not all(
        isinstance(c, int) and not isinstance(c, bool) for c in raw
    ):
        LOGGER.warning("Nel catalogo dei modelli YOLO il colore %r del modello '%s' non è valido: viene usato il colore predefinito", raw, name)
        return _DEFAULT_COLOR
    return tuple(int(c) for c in raw)


def _models_from_catalog(data, base_dir) -> tuple[YoloModelConfig, ...]:
    if data is None:
        return ()
    raw_models = data.get("models")
    if not isinstance(raw_models, list):
        LOGGER.error("Nel catalogo dei modelli YOLO la chiave 'models' manca o non è valida")
        return ()

    models_dir = Path(base_dir).joinpath(*_CATALOG_RELATIVE).parent
    models: list[YoloModelConfig] = []
    for entry in raw_models:
        if not isinstance(entry, dict):
            LOGGER.warning("Nel catalogo dei modelli YOLO una voce è stata ignorata perché non è un oggetto: %r", entry)
            continue
        weights = entry.get("weights")
        if not isinstance(weights, str) or not weights:
            LOGGER.warning("Nel catalogo dei modelli YOLO una voce è stata ignorata perché manca la chiave 'weights': %r", entry)
            continue
        explicit = entry.get("name")
        name = explicit if isinstance(explicit, str) and explicit else _name_from_weights(weights)
        if not name:
            LOGGER.warning("Nel catalogo dei modelli YOLO una voce è stata ignorata perché non è possibile ricavarne il nome: %r", entry)
            continue
        raw_label = entry.get("label")
        label = raw_label if isinstance(raw_label, str) and raw_label else name
        models.append(
            YoloModelConfig(
                name=name,
                path=models_dir / weights,
                color=_coerce_color(entry.get("color"), name),
                label=label,
            )
        )

    if not models:
        LOGGER.error("Il catalogo dei modelli YOLO non contiene alcun modello valido")
    return tuple(models)


def _model_name_from_catalog(data, role: str, default: str) -> str:
    if data is None:
        return default
    roles = data.get("roles")
    if not isinstance(roles, dict):
        return default
    name = roles.get(role)
    return name if isinstance(name, str) and name else default


def load_models_registry(base_dir) -> dict:
    data = _read_catalog(base_dir)
    return {
        "models": _models_from_catalog(data, base_dir),
        "safety_net": _model_name_from_catalog(
            data, "safety_net", _DEFAULT_SAFETY_NET_MODEL
        ),
        "person_fall": _model_name_from_catalog(
            data, "person_fall", _DEFAULT_PERSON_FALL_MODEL
        ),
        "restricted_area": _model_name_from_catalog(
            data, "restricted_area", _DEFAULT_RESTRICTED_AREA_MODEL
        ),
        "dpi": _model_name_from_catalog(
            data, "dpi", _DEFAULT_DPI_MODEL
        ),
    }
