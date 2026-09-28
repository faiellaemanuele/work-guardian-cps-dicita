from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter


_GLOW_CACHE: dict[tuple, "Image.Image"] = {}
_GLOW_CACHE_MAX = 64

ICON_SUPERSAMPLE = 4


def draw_centered_label(draw, cx, cy, text, font, fill) -> None:
    sinistra, _alto, destra, _basso = font.getbbox(text, anchor="ls")
    _sx, cima, _dx, base = font.getbbox("H", anchor="ls")
    draw.text((cx - (sinistra + destra) / 2, cy - (cima + base - 1) / 2), text, font=font,
              fill=fill, anchor="ls")


def _blend(img, color, mask, x: int, y: int) -> None:
    x, y = int(x), int(y)
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(mask.width - sx0, img.width - dx0)
    h = min(mask.height - sy0, img.height - dy0)
    if w <= 0 or h <= 0:
        return
    mask = mask.crop((sx0, sy0, sx0 + w, sy0 + h))
    if img.mode == "RGBA":
        layer = Image.new("RGBA", (w, h), tuple(color[:3]) + (0,))
        layer.putalpha(mask)
        img.alpha_composite(layer, (dx0, dy0))
    else:
        img.paste(Image.new(img.mode, (w, h), tuple(color[:3])), (dx0, dy0), mask)


def _glow_mask(w: int, h: int, radius: int, width: float, glow: float, alpha: int):
    key = (w, h, radius, width, glow, alpha)
    mask = _GLOW_CACHE.get(key)
    if mask is None:
        margin = int(round(glow * 3))
        mask = Image.new("L", (w + 2 * margin, h + 2 * margin), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (margin, margin, margin + w, margin + h), radius=radius,
            outline=alpha, width=max(1, int(round(width * 2.2))),
        )
        mask = mask.filter(ImageFilter.GaussianBlur(glow / 1.6))
        if len(_GLOW_CACHE) >= _GLOW_CACHE_MAX:
            _GLOW_CACHE.clear()
        _GLOW_CACHE[key] = mask
    return mask


def glow_box(img, box, *, radius, edge=None, width=0.0, fill=None, glow=0.0, glow_alpha=0) -> None:
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    radius = max(0, int(round(radius)))
    if edge is not None and glow > 0 and glow_alpha > 0:
        margin = int(round(glow * 3))
        mask = _glow_mask(x1 - x0, y1 - y0, radius, width, glow, glow_alpha)
        _blend(img, edge, mask, x0 - margin, y0 - margin)
    if fill is not None:
        if len(fill) == 4:
            mask = Image.new("L", (x1 - x0 + 1, y1 - y0 + 1), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, x1 - x0, y1 - y0), radius=radius, fill=fill[3],
            )
            _blend(img, fill, mask, x0, y0)
        else:
            ImageDraw.Draw(img).rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=fill)
    if edge is not None and width > 0:
        ImageDraw.Draw(img).rounded_rectangle(
            (x0, y0, x1, y1), radius=radius, outline=tuple(edge[:3]),
            width=max(1, int(round(width))),
        )


def _paste_layer(img, layer, x: int, y: int) -> None:
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(layer.width - sx0, img.width - dx0)
    h = min(layer.height - sy0, img.height - dy0)
    if w <= 0 or h <= 0:
        return
    layer = layer.crop((sx0, sy0, sx0 + w, sy0 + h))
    if img.mode == "RGBA":
        img.alpha_composite(layer, (dx0, dy0))
    else:
        img.paste(layer, (dx0, dy0), layer)


def paint_supersampled(img, box, anchor, paint, *, factor: int = ICON_SUPERSAMPLE) -> None:
    x0, y0 = int(math.floor(box[0])), int(math.floor(box[1]))
    x1, y1 = int(math.ceil(box[2])), int(math.ceil(box[3]))
    if x1 <= x0 or y1 <= y0:
        return
    k = max(1, int(factor))
    layer = Image.new("RGBA", ((x1 - x0) * k, (y1 - y0) * k), (0, 0, 0, 0))
    paint(ImageDraw.Draw(layer), (anchor[0] - x0) * k, (anchor[1] - y0) * k, k)
    if k > 1:
        layer = layer.resize((x1 - x0, y1 - y0), Image.BOX)
    _paste_layer(img, layer, x0, y0)


def corner_brackets(draw, box, *, arm, width, color) -> None:
    x0, y0, x1, y1 = box
    w = max(1, int(round(width)))
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        draw.line((cx, cy, cx + sx * arm, cy), fill=color, width=w)
        draw.line((cx, cy, cx, cy + sy * arm), fill=color, width=w)
