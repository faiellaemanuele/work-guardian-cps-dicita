from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from drone.ui import fonts
from drone.ui.video.mission_map import (
    LEGEND_COLORS,
    draw_mission_map,
)


_FONT_SIZE = 18
_LINE_H = 21
_LOG_FONT_SIZE = 17
_LOG_LINE_H = 21
_HEADER_H = 32
_PAD = 8
_PANEL_TEXT_PAD = 16

BG = (20, 23, 30)

_HEADER_BG = (38, 40, 46)
_ACCENT = (120, 210, 230)
_TEXT = (208, 212, 220)
_MUTED = (140, 146, 158)
_FRAME = (70, 74, 84)
_POS = (61, 200, 132)
_NEG = (235, 95, 80)

_WARN = (235, 180, 40)

_MESSAGE_COLUMN = 13

_MAP_PAD = 12
_FLOAT_INSET = 14
_FLOAT_BG = (17, 19, 25)
_FLOAT_BORDER = (44, 44, 51)
_FLOAT_RADIUS = 9
_FLOAT_DIVIDER = (35, 35, 41)

_SHADOW_COLOR = (0, 0, 0)
_SHADOW_OFFSET_Y = 6
_SHADOW_BLUR = 9
_SHADOW_ALPHA = 105

_RAIL_GAP = 24
_TIMER_H = 54

_CARD_PAD_X = _PANEL_TEXT_PAD
_CARD_PAD_Y = 5
_AXIS_PAD_Y = 14
_AXIS_NAME_H = 28
_AXIS_NAME_GAP = 10
_AXIS_LINE_H = 26

_AXIS_NAME = (237, 239, 240)
_PILL_OK_BG = (24, 45, 37)
_PILL_BAD_BG = (50, 29, 29)
_PILL_PAD_X = 11
_PILL_H = 26

_FONT_MAP = 18

_LEGEND_FONT = 18
_LEGEND_DOT = 12
_LEGEND_ROW_H = 27
_LEGEND_PAD_X = _PANEL_TEXT_PAD
_LEGEND_PAD_Y = 12

_NO_MISSION_NOTE = "Nessun percorso caricato: non c'è una rotta da mostrare, il volo prosegue in manuale."

_IDLE_NOTE = "Questo pannello si attiva con il volo autonomo."


_SHADOW_CACHE: dict[tuple, "Image.Image"] = {}


def _shadow_mask(size: tuple[int, int], radius: int, blur: int, offset_y: int, alpha: int):
    key = (size, radius, blur, offset_y, alpha)
    mask = _SHADOW_CACHE.get(key)
    if mask is None:
        box_w, box_h = size
        pad = blur * 3
        layer = Image.new("L", (box_w + 2 * pad, box_h + 2 * pad + offset_y), 0)
        ImageDraw.Draw(layer).rounded_rectangle(
            (pad, pad + offset_y, pad + box_w, pad + offset_y + box_h),
            radius=radius, fill=alpha,
        )
        mask = layer.filter(ImageFilter.GaussianBlur(blur))
        _SHADOW_CACHE[key] = mask
    return mask


def _finalize(img: "Image.Image") -> np.ndarray:
    return np.array(img)[:, :, ::-1].copy()


def _new_canvas(config, title: str, height: int, secondary: Optional[str] = None,
                title_x: Optional[int] = None, width: Optional[int] = None):
    w = int(width) if width else int(getattr(config, "panel_width", 940))
    h = int(height)
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, _HEADER_H], fill=_HEADER_BG)
    font = fonts.sans(_FONT_SIZE)

    x, y = (_PAD if title_x is None else int(title_x)), _HEADER_H / 2
    draw.text((x, y), title, font=font, fill=_ACCENT, anchor="lm")
    if secondary:
        sep = "  |  "
        x += draw.textlength(title, font=font)
        draw.text((x, y), sep, font=font, fill=_FRAME, anchor="lm")
        x += draw.textlength(sep, font=font)
        secondary = _truncate_to_width(secondary, font, w - _PAD - x)
        draw.text((x, y), secondary, font=font, fill=_TEXT, anchor="lm")
    return img, draw


def _truncate_to_width(text: str, font, max_px: float) -> str:
    if max_px <= 0:
        return ""
    if font.getlength(text) <= max_px:
        return text
    ell = "…"
    while text and font.getlength(text + ell) > max_px:
        text = text[:-1]
    return (text + ell) if text else ell


def _mono_char_width(font) -> float:
    try:
        return float(font.getlength("0"))
    except AttributeError:
        left, _, right, _ = font.getbbox("0")
        return float(right - left)


def _wrap_text(text: str, max_chars: int) -> list[str]:
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    out: list[str] = []
    cur = ""
    for word in text.split(" "):
        while len(word) > max_chars:
            if cur:
                out.append(cur)
                cur = ""
            out.append(word[:max_chars])
            word = word[max_chars:]
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= max_chars:
            cur += " " + word
        else:
            out.append(cur)
            cur = word
    out.append(cur)
    return out


def _layout_log_line(line: str, max_chars: int) -> list[tuple[str, bool]]:
    line = str(line)
    if len(line) <= max_chars:
        return [(line, False)]
    return [(line[: max(1, max_chars - 1)] + "…", False)]


def _draw_lines(draw, lines, top: int, panel_h: int, panel_w: int,
                color=None, line_color=None) -> None:
    bottom = panel_h - _PAD
    max_visible = max(0, (bottom - top) // _LOG_LINE_H)
    if max_visible <= 0:
        return
    default_color = color if color is not None else _TEXT
    font = fonts.mono(_LOG_FONT_SIZE)

    left = _PANEL_TEXT_PAD
    avail_px = int(panel_w) - left - _PAD
    char_w = _mono_char_width(font)
    max_chars = max(1, int(avail_px / char_w)) if char_w > 0 else len(max(lines, key=len, default=""))
    indent_px = int(round(_MESSAGE_COLUMN * char_w))

    visible: deque[tuple[str, int, tuple]] = deque()
    for line in reversed(lines):
        line = str(line)
        text_color = default_color if line_color is None else line_color(line)
        for piece, indented in reversed(_layout_log_line(line, max_chars)):
            x = left + (indent_px if indented else 0)
            visible.appendleft((piece, x, text_color))
            if len(visible) >= max_visible:
                break
        if len(visible) >= max_visible:
            break

    y = top

    for piece, x, text_color in visible:
        draw.text((x, y + _LOG_LINE_H / 2), piece, font=font, fill=text_color, anchor="lm")
        y += _LOG_LINE_H


def _severity_glyph(line: str) -> str:
    return line[10] if len(line) > 10 else ""


def terminal_line_color(line: str):
    glyph = _severity_glyph(line)
    if glyph == "×":
        return _NEG
    if glyph == "!":
        return _WARN
    return _TEXT


def alert_line_color(line: str):
    glyph = _severity_glyph(line)
    if glyph == "×":
        return _NEG
    if glyph == "!":
        return _WARN
    if glyph == "•":
        return _ACCENT
    return _TEXT


def _draw_note(img, draw, text: str, x: Optional[int] = None) -> None:
    x0 = _PAD if x is None else int(x)
    font = fonts.mono(_FONT_SIZE)
    char_w = _mono_char_width(font)
    max_chars = max(1, int((img.width - _PAD - x0) / char_w)) if char_w > 0 else 60
    y = _HEADER_H + _PAD + 6
    for piece in _wrap_text(text, max_chars):
        draw.text((x0, y), piece, font=font, fill=_MUTED)
        y += _LINE_H


def text_panel(config, title: str, lines, height: int, *, engaged: bool,
               line_color=None, width: Optional[int] = None) -> np.ndarray:
    img, draw = _new_canvas(
        config, title, height, title_x=_PANEL_TEXT_PAD, width=width,
    )
    if not engaged:
        _draw_note(img, draw, _IDLE_NOTE, x=_PANEL_TEXT_PAD)
        return _finalize(img)
    top = _HEADER_H + _PAD
    _draw_lines(
        draw, lines, top=top, panel_h=img.height, panel_w=img.width,
        line_color=line_color,
    )
    return _finalize(img)


def _format_measure(value, decimals: int, unit: str) -> str:
    if value is None:
        return "--"
    sep = "" if unit == "°" else " "
    return f"{value:.{decimals}f}{sep}{unit}"


def _axis_block_h() -> int:
    return (
        2 * _AXIS_PAD_Y + _AXIS_NAME_H
        + _AXIS_NAME_GAP + 2 * _AXIS_LINE_H
    )


def _tolerance_card_h() -> int:
    return 2 * _CARD_PAD_Y + 3 * _axis_block_h()


def _draw_float_box(img, draw, box) -> None:
    x0, y0, x1, y1 = (int(v) for v in box)
    mask = _shadow_mask(
        (x1 - x0, y1 - y0), _FLOAT_RADIUS,
        _SHADOW_BLUR, _SHADOW_OFFSET_Y, _SHADOW_ALPHA,
    )
    pad = _SHADOW_BLUR * 3
    img.paste(
        Image.new("RGB", mask.size, _SHADOW_COLOR),
        (x0 - pad, y0 - pad), mask=mask,
    )
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=_FLOAT_RADIUS,
        fill=_FLOAT_BG, outline=_FLOAT_BORDER, width=1,
    )


def _draw_pill(draw, x_right: int, y_center: int, ok, font) -> None:
    if ok is None:
        text, fg, bg = "--", _MUTED, None
    elif ok:
        text, fg, bg = "in tolleranza", _POS, _PILL_OK_BG
    else:
        text, fg, bg = "fuori tolleranza", _NEG, _PILL_BAD_BG
    text_w = int(draw.textlength(text, font=font))
    x0 = x_right - text_w - 2 * _PILL_PAD_X
    if bg is not None:
        draw.rounded_rectangle(
            (x0, y_center - _PILL_H // 2, x_right, y_center + _PILL_H // 2),
            radius=_PILL_H // 2, fill=bg,
        )
    draw.text((x0 + _PILL_PAD_X, y_center), text, font=font, fill=fg, anchor="lm")


def _draw_kv_line(draw, x0: int, x1: int, y_center: int, label: str, value: str, color) -> None:
    draw.text(
        (x0, y_center), label,
        font=fonts.mono(_FONT_MAP), fill=_MUTED, anchor="lm",
    )
    draw.text(
        (x1, y_center), value,
        font=fonts.mono(_FONT_MAP), fill=color, anchor="rm",
    )


def _draw_tolerance_card(img, draw, x0: int, y0: int, width: int, axes) -> None:
    _draw_float_box(img, draw, (x0, y0, x0 + width, y0 + _tolerance_card_h()))
    font_axis = fonts.mono(_FONT_MAP)
    font_pill = fonts.mono(_FONT_MAP)
    inner_x0 = x0 + _CARD_PAD_X
    inner_x1 = x0 + width - _CARD_PAD_X

    y = y0 + _CARD_PAD_Y
    for index, (name, err, tol, ok, unit, decimals) in enumerate(axes):
        if index:
            draw.line([(inner_x0, y), (inner_x1, y)], fill=_FLOAT_DIVIDER, width=1)
        name_y = y + _AXIS_PAD_Y
        draw.text(
            (inner_x0, name_y + _AXIS_NAME_H // 2), name,
            font=font_axis, fill=_AXIS_NAME, anchor="lm",
        )
        _draw_pill(draw, inner_x1, name_y + _AXIS_NAME_H // 2, ok, font_pill)

        line_y = name_y + _AXIS_NAME_H + _AXIS_NAME_GAP + _AXIS_LINE_H // 2
        _draw_kv_line(
            draw, inner_x0, inner_x1, line_y,
            "errore", _format_measure(err, decimals, unit), (255, 255, 255),
        )
        _draw_kv_line(
            draw, inner_x0, inner_x1, line_y + _AXIS_LINE_H,
            "soglia", _format_measure(tol, decimals, unit), (141, 141, 141),
        )
        y += _axis_block_h()


def _draw_timer_box(img, draw, x0: int, y0: int, width: int, mission_map) -> None:
    badge = mission_map.badge() if mission_map is not None else None
    if badge is None:
        return

    _draw_float_box(img, draw, (x0, y0, x0 + width, y0 + _TIMER_H))
    font = fonts.mono(_FONT_MAP)
    y_center = y0 + _TIMER_H // 2

    if badge.kind == "finished":
        draw.text(
            (x0 + width // 2, y_center), badge.text,
            font=font, fill=_POS, anchor="mm",
        )
        return

    remaining = mission_map.supervision_remaining_sec()
    value = "--" if remaining is None else f"{remaining:.1f} s"
    draw.text(
        (x0 + _CARD_PAD_X, y_center), "Supervisione",
        font=font, fill=_AXIS_NAME, anchor="lm",
    )
    draw.text(
        (x0 + width - _CARD_PAD_X, y_center), value,
        font=font, anchor="rm",
        fill=(255, 255, 255) if remaining is not None else _MUTED,
    )


def _map_legend_size(draw) -> tuple[int, int]:
    font = fonts.mono(_LEGEND_FONT)
    text_w = max(int(draw.textlength(name, font=font)) for name, _ in LEGEND_COLORS)
    width = 2 * _LEGEND_PAD_X + _LEGEND_DOT + 10 + text_w
    height = 2 * _LEGEND_PAD_Y + _LEGEND_ROW_H * len(LEGEND_COLORS)
    return width, height


def _draw_map_legend(img, draw, x0: int, y_bottom: int) -> None:
    font = fonts.mono(_LEGEND_FONT)
    width, height = _map_legend_size(draw)
    y0 = y_bottom - height
    _draw_float_box(img, draw, (x0, y0, x0 + width, y_bottom))

    y = y0 + _LEGEND_PAD_Y + _LEGEND_ROW_H // 2
    for name, color in LEGEND_COLORS:
        r = _LEGEND_DOT // 2
        cx = x0 + _LEGEND_PAD_X + r
        draw.ellipse((cx - r, y - r, cx + r, y + r), fill=color)
        draw.text(
            (x0 + _LEGEND_PAD_X + _LEGEND_DOT + 10, y), name,
            font=font, fill=(196, 198, 200), anchor="lm",
        )
        y += _LEGEND_ROW_H


def map_panel(config, height: int, *, mission_map, scenario_name: Optional[str],
              drone_xy, drone_heading_deg: float, drone_pose_fresh: bool,
              drone_command, axes) -> np.ndarray:
    img, draw = _new_canvas(
        config, getattr(config, "map_title", "Mappa missione"), height,
        secondary=scenario_name, title_x=_PANEL_TEXT_PAD,
    )

    if mission_map is None:
        _draw_note(img, draw, _NO_MISSION_NOTE, x=_PANEL_TEXT_PAD)
        return _finalize(img)

    pad = _MAP_PAD
    top = _HEADER_H + pad
    map_w = max(60, img.width - 2 * pad)
    map_h = max(60, img.height - top - pad)
    rail_w = max(80, int(getattr(config, "map_info_col_width", 252)))
    reserved_right = rail_w + 2 * _FLOAT_INSET
    legend_w, _ = _map_legend_size(draw)
    reserved_left = legend_w + 2 * _FLOAT_INSET

    map_img = draw_mission_map(
        mission_map, map_w, map_h,
        drone_xy=drone_xy,
        drone_heading_deg=drone_heading_deg,
        drone_pose_fresh=drone_pose_fresh,
        drone_command=drone_command,
        reserved_right_px=reserved_right,
        reserved_left_px=reserved_left,
    )
    img.paste(map_img, (pad, top))

    rail_x0 = img.width - pad - _FLOAT_INSET - rail_w
    rail_h = _tolerance_card_h() + _RAIL_GAP + _TIMER_H
    rail_y0 = top + max(0, (map_h - rail_h) // 2)
    _draw_tolerance_card(img, draw, rail_x0, rail_y0, rail_w, axes)
    _draw_timer_box(
        img, draw, rail_x0, rail_y0 + _tolerance_card_h() + _RAIL_GAP, rail_w,
        mission_map,
    )

    _draw_map_legend(
        img, draw, pad + _FLOAT_INSET, top + map_h - _FLOAT_INSET,
    )
    return _finalize(img)
