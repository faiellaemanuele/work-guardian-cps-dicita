from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

from drone.ui import fonts
from drone.ui.shapes import glow_box, paint_supersampled
from drone.ui.video.mission_map import (
    LEGEND_SCENE,
    LEGEND_WAYPOINTS,
    draw_mission_map,
)


_FONT_SIZE = 18
_LINE_H = 21
_LOG_FONT_SIZE = 17
_LOG_LINE_H = 24
_HEADER_TOP = 8
_HEADER_H = 46
_PAD = 8

BG = (3, 27, 51)

_HEADER_SEPARATOR = (4, 110, 170)
_TITLE_ACCENT = (150, 238, 252)
_ACCENT = (110, 238, 252)
_TEXT = (232, 242, 250)
_LABEL = (206, 244, 252)
_MUTED = (140, 162, 182)
_WHITE = (248, 251, 252)
_POS = (88, 226, 120)
_NEG = (252, 98, 88)
_WARN = (252, 190, 16)

_MESSAGE_COLUMN = 13

_MAP_LEFT = 20
_MAP_BORDER = (150, 166, 186)
_RAIL_RIGHT = 13
_RAIL_MAP_GAP = 12
_RAIL_GAP = 12
_TIMER_H = 61

_CARD_FILL = (3, 26, 50)
_CARD_EDGE = (6, 160, 230)
_CARD_RADIUS = 9
_CARD_EDGE_W = 2
_CARD_GLOW = 5
_CARD_GLOW_ALPHA = 120
_CARD_PAD_X = 18
_DIVIDER = (26, 96, 146)

_LOG_FILL = (3, 27, 48)
_LOG_EDGE = (4, 150, 225)
_LOG_RULE = (4, 104, 156)
_LOG_TITLE_Y = 23
_LOG_RULE_Y = 43
_LOG_TEXT_TOP = 51
_LOG_TEXT_PAD = 11

LOG_INSET_LEFT = (_MAP_LEFT, 2, 5, 14)
LOG_INSET_RIGHT = (5, 2, _RAIL_RIGHT, 14)

_AXIS_BLOCK_H = 126
_AXIS_NAME_Y = 33
_AXIS_LINE_Y = (73, 103)
_PILL_TOP = 16
_PILL_H = 34
_PILL_PAD_X = 20
_PILL_OK_BG = (5, 68, 50)
_PILL_OK_EDGE = (24, 172, 102)
_PILL_OK_TEXT = (156, 246, 188)
_PILL_BAD_BG = (54, 30, 44)
_PILL_BAD_EDGE = (214, 52, 58)
_PILL_BAD_TEXT = (252, 142, 124)

_FONT_HEADER = 21
_FONT_CARD_TITLE = 22
_FONT_AXIS = 23
_FONT_PILL = 19
_FONT_KV = 20

_DISCLAIMER_FONT = 17
_DISCLAIMER_LINE_H = 20
_DISCLAIMER_GAP = 10

_LEGEND_FONT = 16
_LEGEND_SWATCH = 16
_LEGEND_SWATCH_GAP = 10
_LEGEND_ROW_H = 27
_LEGEND_PAD_X = 16
_LEGEND_PAD_Y = 15
_LEGEND_COL_GAP = 14

TOLERANCE_PILL_OK = "waypoint raggiunto"
TOLERANCE_PILL_BAD = "correzione in corso"
TOLERANCE_PILL_UNKNOWN = "--"

TOLERANCE_ERROR_LABELS = {
    "XY": "errore di posizione",
    "Z": "errore di quota",
    "Yaw": "errore di orientamento",
}
TOLERANCE_ERROR_LABEL_DEFAULT = "errore"
TOLERANCE_THRESHOLD_LABEL = "soglia di tolleranza *"

SUPERVISION_LABEL = "Timer di supervisione"
MISSION_FINISHED_LABEL = "Missione completata"

MAP_DISCLAIMER = (
    "* soglia di tolleranza: soglia in metri o gradi al di sotto della quale "
    "il waypoint è considerato raggiunto"
)

_NO_MISSION_NOTE = "Nessun percorso caricato: non c'è una rotta da mostrare, il volo prosegue in manuale."

_IDLE_NOTE = "Questo pannello si attiva con il volo autonomo."


def _finalize(img: "Image.Image") -> np.ndarray:
    return np.array(img)[:, :, ::-1].copy()


def _new_canvas(width: int, height: int):
    img = Image.new("RGB", (int(width), int(height)), BG)
    return img, ImageDraw.Draw(img)


def _card_box(img, box, fill=_CARD_FILL, edge=_CARD_EDGE) -> None:
    glow_box(
        img, box, radius=_CARD_RADIUS, edge=edge, width=_CARD_EDGE_W, fill=fill,
        glow=_CARD_GLOW, glow_alpha=_CARD_GLOW_ALPHA,
    )


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


def _wrap_px(text: str, font, max_px: float) -> list[str]:
    righe: list[str] = []
    riga = ""
    for parola in text.split():
        prova = f"{riga} {parola}".strip()
        if font.getlength(prova) <= max_px or not riga:
            riga = prova
        else:
            righe.append(riga)
            riga = parola
    if riga:
        righe.append(riga)
    return righe


def _layout_log_line(line: str, max_chars: int) -> list[tuple[str, bool]]:
    line = str(line)
    if len(line) <= max_chars:
        return [(line, False)]
    width = max_chars - _MESSAGE_COLUMN
    if width < 8:
        return [
            (piece, index > 0)
            for index, piece in enumerate(_wrap_text(line, max_chars))
        ]
    head, message = line[:_MESSAGE_COLUMN], line[_MESSAGE_COLUMN:]
    pieces = _wrap_text(message, width)
    return [(head + pieces[0], False)] + [(piece, True) for piece in pieces[1:]]


def _draw_lines(draw, lines, *, left: int, right: int, top: int, bottom: int,
                line_color=None) -> None:
    max_visible = max(0, int((bottom - top) // _LOG_LINE_H))
    if max_visible <= 0:
        return
    font = fonts.mono(_LOG_FONT_SIZE)

    char_w = _mono_char_width(font)
    max_chars = max(1, int((right - left) / char_w)) if char_w > 0 else len(max(lines, key=len, default=""))
    indent_px = int(round(_MESSAGE_COLUMN * char_w))

    visible: deque[tuple[str, int, tuple]] = deque()
    for line in reversed(lines):
        line = str(line)
        text_color = _TEXT if line_color is None else line_color(line)
        for piece, indented in reversed(_layout_log_line(line, max_chars)):
            visible.appendleft((piece, left + (indent_px if indented else 0), text_color))
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


def _draw_note(draw, text: str, *, x: int, y: int, right: int) -> None:
    font = fonts.mono(_FONT_SIZE)
    char_w = _mono_char_width(font)
    max_chars = max(1, int((right - x) / char_w)) if char_w > 0 else 60
    for piece in _wrap_text(text, max_chars):
        draw.text((x, y), piece, font=font, fill=_MUTED)
        y += _LINE_H


def text_panel(config, title: str, lines, height: int, *, engaged: bool,
               line_color=None, width: Optional[int] = None,
               inset=(_PAD, 2, _PAD, 14)) -> np.ndarray:
    w = int(width) if width else int(getattr(config, "panel_width", 940))
    h = int(height)
    img, draw = _new_canvas(w, h)
    left, top, right, bottom = inset
    x0, y0, x1, y1 = left, top, w - right, h - bottom
    if x1 - x0 < 60 or y1 - y0 < _LOG_TEXT_TOP:
        return _finalize(img)

    _card_box(img, (x0, y0, x1, y1), fill=_LOG_FILL, edge=_LOG_EDGE)
    draw = ImageDraw.Draw(img)
    draw.text((x0 + 13, y0 + _LOG_TITLE_Y), title, font=fonts.sans_bold(_FONT_CARD_TITLE),
              fill=_WHITE, anchor="lm")
    draw.line((x0 + 10, y0 + _LOG_RULE_Y, x1 - 10, y0 + _LOG_RULE_Y), fill=_LOG_RULE, width=2)

    if not engaged:
        _draw_note(draw, _IDLE_NOTE, x=x0 + _LOG_TEXT_PAD, y=y0 + _LOG_TEXT_TOP + 6,
                   right=x1 - _LOG_TEXT_PAD)
        return _finalize(img)
    _draw_lines(
        draw, lines, left=x0 + _LOG_TEXT_PAD, right=x1 - _LOG_TEXT_PAD,
        top=y0 + _LOG_TEXT_TOP, bottom=y1 - 6, line_color=line_color,
    )
    return _finalize(img)


def _x_height_middle(font) -> float:
    _left, top, _right, bottom = font.getbbox("x", anchor="lm")
    return (top + bottom) / 2


def _draw_map_header(img, box, title: str, secondary: Optional[str]) -> None:
    x0, y0, x1, y1 = box
    _card_box(img, box)
    draw = ImageDraw.Draw(img)
    font = fonts.sans(_FONT_HEADER)
    cy = (y0 + y1) / 2 - _x_height_middle(font)
    x = x0 + _CARD_PAD_X
    draw.text((x, cy), title, font=font, fill=_TITLE_ACCENT, anchor="lm")
    if secondary:
        x += draw.textlength(title, font=font) + 12
        draw.text((x, cy), "|", font=font, fill=_HEADER_SEPARATOR, anchor="lm")
        x += draw.textlength("|", font=font) + 12
        secondary = _truncate_to_width(secondary, font, x1 - _CARD_PAD_X - x)
        draw.text((x, cy), secondary, font=font, fill=_LABEL, anchor="lm")


def _format_measure(value, decimals: int, unit: str) -> str:
    if value is None:
        return "--"
    sep = "" if unit == "°" else " "
    return f"{value:.{decimals}f}{sep}{unit}"


def _axis_block_h() -> int:
    return _AXIS_BLOCK_H


def _tolerance_card_h() -> int:
    return 3 * _axis_block_h()


def _draw_pill(draw, x_right: int, y_top: int, ok, font) -> None:
    if ok is None:
        draw.text((x_right, y_top + _PILL_H / 2), TOLERANCE_PILL_UNKNOWN,
                  font=font, fill=_MUTED, anchor="rm")
        return
    if ok:
        text, fg, bg, edge = TOLERANCE_PILL_OK, _PILL_OK_TEXT, _PILL_OK_BG, _PILL_OK_EDGE
    else:
        text, fg, bg, edge = TOLERANCE_PILL_BAD, _PILL_BAD_TEXT, _PILL_BAD_BG, _PILL_BAD_EDGE
    text_w = draw.textlength(text, font=font)
    x0 = x_right - text_w - 2 * _PILL_PAD_X
    draw.rounded_rectangle(
        (x0, y_top, x_right, y_top + _PILL_H), radius=_PILL_H // 2,
        fill=bg, outline=edge, width=2,
    )
    draw.text(((x0 + x_right) / 2, y_top + _PILL_H / 2), text, font=font, fill=fg, anchor="mm")


def _draw_kv_line(draw, x0: int, x1: int, y_center: int, label: str, value: str) -> None:
    font = fonts.sans(_FONT_KV)
    draw.text((x0, y_center), label, font=font, fill=_LABEL, anchor="lm")
    draw.text((x1, y_center), value, font=font, fill=_WHITE, anchor="rm")


def _draw_tolerance_card(img, x0: int, y0: int, width: int, axes) -> None:
    _card_box(img, (x0, y0, x0 + width, y0 + _tolerance_card_h()))
    draw = ImageDraw.Draw(img)
    font_axis = fonts.sans_bold(_FONT_AXIS)
    font_pill = fonts.sans(_FONT_PILL)
    inner_x0 = x0 + _CARD_PAD_X
    inner_x1 = x0 + width - _CARD_PAD_X

    for index, (name, err, tol, ok, unit, decimals) in enumerate(axes):
        top = y0 + index * _axis_block_h()
        if index:
            draw.line([(inner_x0, top), (inner_x1, top)], fill=_DIVIDER, width=1)
        draw.text((inner_x0, top + _AXIS_NAME_Y), name, font=font_axis, fill=_WHITE, anchor="lm")
        _draw_pill(draw, inner_x1, top + _PILL_TOP, ok, font_pill)
        _draw_kv_line(
            draw, inner_x0, inner_x1, top + _AXIS_LINE_Y[0],
            TOLERANCE_ERROR_LABELS.get(name, TOLERANCE_ERROR_LABEL_DEFAULT),
            _format_measure(err, decimals, unit),
        )
        _draw_kv_line(
            draw, inner_x0, inner_x1, top + _AXIS_LINE_Y[1],
            TOLERANCE_THRESHOLD_LABEL, _format_measure(tol, decimals, unit),
        )


def _draw_timer_box(img, x0: int, y0: int, width: int, mission_map) -> None:
    _card_box(img, (x0, y0, x0 + width, y0 + _TIMER_H))
    draw = ImageDraw.Draw(img)
    font = fonts.sans_bold(_FONT_CARD_TITLE)
    y_center = y0 + _TIMER_H / 2

    badge = mission_map.badge() if mission_map is not None else None
    if badge is not None and badge.kind == "finished":
        draw.text(
            (x0 + width / 2, y_center), MISSION_FINISHED_LABEL,
            font=font, fill=_POS, anchor="mm",
        )
        return

    remaining = (
        mission_map.supervision_remaining_sec() if mission_map is not None else None
    )
    value = "--" if remaining is None else f"{remaining:.1f} s"
    draw.text(
        (x0 + _CARD_PAD_X, y_center), SUPERVISION_LABEL,
        font=font, fill=_WHITE, anchor="lm",
    )
    draw.text(
        (x0 + width - _CARD_PAD_X, y_center), value,
        font=font, anchor="rm",
        fill=_WHITE if remaining is not None else _MUTED,
    )


def _map_legend_h() -> int:
    rows = max(len(LEGEND_WAYPOINTS), len(LEGEND_SCENE))
    return 2 * _LEGEND_PAD_Y + _LEGEND_ROW_H * rows


def _legend_font():
    return fonts.sans(_LEGEND_FONT)


def _legend_column_width(entries, font) -> int:
    text_w = max(font.getlength(name) for name, _kind, _fill, _border in entries)
    return int(text_w) + _LEGEND_SWATCH + _LEGEND_SWATCH_GAP


def _paint_legend_swatch(draw, cx: float, cy: float, k: int, kind: str, fill, border) -> None:
    half = _LEGEND_SWATCH / 2 * k
    if kind == "dot":
        draw.ellipse((cx - half, cy - half, cx + half, cy + half), fill=fill)
        return
    inset = 0 if kind == "square" else 2 * k
    draw.rectangle(
        (cx - half, cy - half + inset, cx + half, cy + half - inset),
        fill=fill, outline=border, width=2 * k,
    )


def _draw_legend_column(img, x0: int, y0: int, entries, font) -> None:
    draw = ImageDraw.Draw(img)
    text_dy = _x_height_middle(font)
    cx = x0 + _LEGEND_SWATCH / 2
    reach = _LEGEND_SWATCH / 2 + 2
    y = y0 + _LEGEND_ROW_H / 2
    for name, kind, fill, border in entries:
        paint_supersampled(
            img, (cx - reach, y - reach, cx + reach, y + reach), (cx, y),
            lambda d, ax, ay, k, kind=kind, fill=fill, border=border:
                _paint_legend_swatch(d, ax, ay, k, kind, fill, border),
        )
        draw.text(
            (x0 + _LEGEND_SWATCH + _LEGEND_SWATCH_GAP, y - text_dy), name,
            font=font, fill=_LABEL, anchor="lm",
        )
        y += _LEGEND_ROW_H


def _draw_map_legend(img, x0: int, y0: int, width: int) -> None:
    font = _legend_font()
    _card_box(img, (x0, y0, x0 + width, y0 + _map_legend_h()))

    left_x = x0 + _LEGEND_PAD_X
    right_x = left_x + _legend_column_width(LEGEND_WAYPOINTS, font) + _LEGEND_COL_GAP
    top = y0 + _LEGEND_PAD_Y
    _draw_legend_column(img, left_x, top, LEGEND_WAYPOINTS, font)
    _draw_legend_column(img, right_x, top, LEGEND_SCENE, font)


def _disclaimer_lines(width: int) -> list[str]:
    font = fonts.sans(_DISCLAIMER_FONT)
    return _wrap_px(MAP_DISCLAIMER, font, width - _MAP_LEFT - _RAIL_RIGHT)


def _disclaimer_block_h(width: int) -> int:
    return _DISCLAIMER_GAP + _DISCLAIMER_LINE_H * len(_disclaimer_lines(width)) + _PAD


def _draw_disclaimer(draw, width: int, y: int) -> None:
    font = fonts.sans(_DISCLAIMER_FONT)
    for piece in _disclaimer_lines(width):
        draw.text(
            (_MAP_LEFT, y + _DISCLAIMER_LINE_H / 2), piece,
            font=font, fill=_LABEL, anchor="lm",
        )
        y += _DISCLAIMER_LINE_H


def _rail_h() -> int:
    return _TIMER_H + _RAIL_GAP + _tolerance_card_h() + _RAIL_GAP + _map_legend_h()


def _content_top() -> int:
    return _HEADER_TOP + _HEADER_H + _RAIL_GAP


def map_panel_height(config) -> int:
    width = int(getattr(config, "panel_width", 940))
    return _content_top() + _rail_h() + _disclaimer_block_h(width)


def _map_layout(config, height: int) -> dict:
    width = int(getattr(config, "panel_width", 940))
    rail_w = max(80, int(getattr(config, "map_info_col_width", 440)))
    rail_x0 = width - _RAIL_RIGHT - rail_w
    top = _content_top()
    map_w = max(60, rail_x0 - _RAIL_MAP_GAP - _MAP_LEFT)
    map_h = max(60, min(_rail_h(), int(height) - top - _disclaimer_block_h(width)))
    return {
        "header": (_MAP_LEFT, _HEADER_TOP, width - _RAIL_RIGHT, _HEADER_TOP + _HEADER_H),
        "map": (_MAP_LEFT, top, _MAP_LEFT + map_w, top + map_h),
        "rail": (rail_x0, top, rail_x0 + rail_w, top + _rail_h()),
        "disclaimer_y": top + map_h + _DISCLAIMER_GAP,
    }


def map_panel(config, height: int, *, mission_map, scenario_name: Optional[str],
              drone_xy, drone_heading_deg: float, drone_pose_fresh: bool,
              axes) -> np.ndarray:
    width = int(getattr(config, "panel_width", 940))
    height = int(height)
    img, _draw = _new_canvas(width, height)
    layout = _map_layout(config, height)
    _draw_map_header(
        img, layout["header"], getattr(config, "map_title", "Mappa missione"), scenario_name,
    )

    if mission_map is None:
        _draw_note(ImageDraw.Draw(img), _NO_MISSION_NOTE, x=_MAP_LEFT,
                   y=_content_top() + 6, right=width - _RAIL_RIGHT)
        return _finalize(img)

    map_x0, map_y0, map_x1, map_y1 = layout["map"]
    map_img = draw_mission_map(
        mission_map, map_x1 - map_x0, map_y1 - map_y0 - 1,
        drone_xy=drone_xy,
        drone_heading_deg=drone_heading_deg,
        drone_pose_fresh=drone_pose_fresh,
    )
    img.paste(map_img, (map_x0, map_y0 + 1))
    ImageDraw.Draw(img).rectangle((map_x0 - 1, map_y0, map_x1, map_y1), outline=_MAP_BORDER)

    rail_x0, y, rail_x1, _rail_bottom = layout["rail"]
    rail_w = rail_x1 - rail_x0
    _draw_timer_box(img, rail_x0, y, rail_w, mission_map)
    y += _TIMER_H + _RAIL_GAP
    _draw_tolerance_card(img, rail_x0, y, rail_w, axes)
    y += _tolerance_card_h() + _RAIL_GAP
    _draw_map_legend(img, rail_x0, y, rail_w)

    _draw_disclaimer(ImageDraw.Draw(img), width, layout["disclaimer_y"])
    return _finalize(img)
