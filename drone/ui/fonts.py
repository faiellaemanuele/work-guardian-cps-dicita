from __future__ import annotations

from PIL import ImageFont


_FAMILIES = {
    "sans": (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "DejaVuSans.ttf",
    ),
    "sans_bold": (
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "DejaVuSans-Bold.ttf",
    ),
    "mono": (
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "DejaVuSansMono.ttf",
        "DejaVuSans.ttf",
    ),
}

_CACHE: dict[tuple[str, int], "ImageFont.FreeTypeFont"] = {}


def _load(family: str, size: int):
    key = (family, size)
    font = _CACHE.get(key)
    if font is None:
        for path in _FAMILIES[family]:
            try:
                font = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        if font is None:
            font = sans(size) if family == "sans_bold" else ImageFont.load_default()
        _CACHE[key] = font
    return font


def sans(size: int):
    return _load("sans", size)


def sans_bold(size: int):
    return _load("sans_bold", size)


def mono(size: int):
    return _load("mono", size)
