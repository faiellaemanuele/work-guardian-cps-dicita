from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from drone.ui import fonts


_AUTOPILOT_REASON_LABELS: dict[str, str] = {
    "idle": "In attesa",
    "tracking": "Navigazione",
    "supervision_stop_tracking": "Sosta: navigazione",
    "z_priority_tracking": "Correzione quota",
    "supervision_stop_z_priority_tracking": "Sosta: correzione quota",
    "waypoint_reached": "Waypoint raggiunto",
    "supervision_stop_started": "Sosta avviata",
    "supervision_stop": "Sosta di supervisione",
    "supervision_stop_completed": "Sosta completata",
    "mission_finished": "Missione completata",
    "pose_missing": "Posa assente (attesa)",
    "pose_timeout": "Posa persa (timeout)",
    "waypoint_timeout": "Waypoint non raggiunto (timeout)",
}


def _renamed_reason(raw: str) -> str:
    return raw.replace("supervision_hold", "supervision_stop")


def humanize_autopilot_reason(reason: str) -> str:
    reason = _renamed_reason(reason)
    if reason in _AUTOPILOT_REASON_LABELS:
        return _AUTOPILOT_REASON_LABELS[reason]
    if reason.startswith("invalid_pose_transient"):
        return "Posa non valida (transitoria)"
    if reason.startswith("invalid_pose"):
        return "Posa non valida"
    return reason


_STATUS_LABEL_WIDTHS: dict = {}


def _status_label_widths(labels: tuple[str, ...], size: int) -> int:
    key = (labels, size)
    max_w = _STATUS_LABEL_WIDTHS.get(key)
    if max_w is None:
        font = fonts.sans(size)
        widths = [int(round(font.getlength(lbl))) for lbl in labels]
        max_w = max(widths) if widths else 0
        _STATUS_LABEL_WIDTHS[key] = max_w
    return max_w


_PANEL_BG = (22, 22, 26)
_PANEL_ALPHA = 160
_PANEL_SUPERSAMPLE = 3
_STATUS_PANEL_SCALE = 1.3

_PANEL_BORDER = (235, 240, 242, 110)

_STATUS_ON = (90, 205, 95)
_STATUS_OFF = (235, 95, 80)
_LABEL_ON = (222, 240, 224)
_LABEL_OFF = (232, 176, 166)
_BATT_SEPARATOR = (78, 78, 82)

_BATT_GREEN = (90, 205, 95)
_BATT_AMBER = (235, 180, 40)
_BATT_RED = (235, 95, 80)
_BATT_UNKNOWN = (130, 130, 130)
_BATT_OUTLINE = (200, 200, 200)


def _battery_color(pct):
    if pct is None:
        return _BATT_UNKNOWN
    if pct > 50:
        return _BATT_GREEN
    if pct >= 20:
        return _BATT_AMBER
    return _BATT_RED


def _lighten(color, factor=0.5):
    return tuple(int(c + (255 - c) * factor) for c in color[:3])


def _icon_stroke(s):
    return max(1, round(1.5 * s))


def _pi_wifi(draw, cx, cy, s, color):
    w = _icon_stroke(s)
    bx, by = cx, cy + 6 * s
    r = max(1, round(1.3 * s))
    draw.ellipse((bx - r, by - r, bx + r, by + r), fill=color)
    for rad, a0, a1 in ((5, 200, 340), (9, 205, 335)):
        r = rad * s
        draw.arc((bx - r, by - r, bx + r, by + r), a0, a1, fill=color, width=w)


def _pi_drone(draw, cx, cy, s, color):
    w = _icon_stroke(s)
    draw.line((cx - 6 * s, cy - 5 * s, cx + 6 * s, cy + 5 * s), fill=color, width=w)
    draw.line((cx + 6 * s, cy - 5 * s, cx - 6 * s, cy + 5 * s), fill=color, width=w)
    for dx, dy in ((-6, -5), (6, -5), (-6, 5), (6, 5)):
        ex, ey, r = cx + dx * s, cy + dy * s, 3 * s
        draw.ellipse((ex - r, ey - r, ex + r, ey + r), outline=color, width=w)
    r = max(1, round(1.8 * s))
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)


def _pi_gamepad(draw, cx, cy, s, color):
    w = _icon_stroke(s)
    rx, ry = 8 * s, 5 * s
    draw.rounded_rectangle(
        (cx - rx, cy - ry, cx + rx, cy + ry), radius=int(2.6 * s),
        outline=color, width=w,
    )
    draw.line((cx - 5.2 * s, cy, cx - 2.4 * s, cy), fill=color, width=w)
    draw.line((cx - 3.8 * s, cy - 1.4 * s, cx - 3.8 * s, cy + 1.4 * s), fill=color, width=w)
    r = max(1, round(1.15 * s))
    for dx, dy in ((3.0, -1.3), (5.4, 0.6)):
        ex, ey = cx + dx * s, cy + dy * s
        draw.ellipse((ex - r, ey - r, ex + r, ey + r), fill=color)


def _pi_eye(draw, cx, cy, s, color):
    w = _icon_stroke(s)
    rx, ry = 8 * s, 5 * s
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=color, width=w)
    r = max(1, round(3 * s))
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=w)
    r2 = max(1, round(1.3 * s))
    draw.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), fill=color)


def _pi_pin(draw, cx, cy, s, color):
    w = _icon_stroke(s)
    hr = 5 * s
    hcy = cy - 2 * s
    tip_y = cy + 7 * s
    draw.arc((cx - hr, hcy - hr, cx + hr, hcy + hr), 150, 30, fill=color, width=w)
    side, drop = 0.866 * hr, 0.5 * hr
    draw.line((cx - side, hcy + drop, cx, tip_y), fill=color, width=w)
    draw.line((cx + side, hcy + drop, cx, tip_y), fill=color, width=w)
    r2 = max(1, round(1.5 * s))
    draw.ellipse((cx - r2, hcy - r2, cx + r2, hcy + r2), fill=color)


def _pi_battery_gauge(draw, x, cy, w_base, pct, s):
    h = 13 * s
    y1 = cy - h // 2
    body_w = (w_base - 4) * s
    x2 = x + body_w
    ow = max(1, round(1.2 * s))
    draw.rounded_rectangle((x, y1, x2, y1 + h), radius=2 * s, outline=_BATT_OUTLINE, width=ow)
    draw.rectangle((x2 + s, cy - 3 * s, x2 + 3 * s, cy + 3 * s), fill=_BATT_OUTLINE)
    if pct is not None:
        p = max(0, min(100, int(pct)))
        inner = body_w - 4 * s
        fill_w = int(inner * p / 100)
        if fill_w > 0:
            draw.rounded_rectangle(
                (x + 2 * s, y1 + 2 * s, x + 2 * s + fill_w, y1 + h - 2 * s),
                radius=max(1, s), fill=_battery_color(p),
            )


def _composite_rgba(frame, x0, y0, panel):
    fh, fw = frame.shape[:2]
    pw, ph = panel.size
    x1 = min(x0 + pw, fw)
    y1 = min(y0 + ph, fh)
    if x1 <= x0 or y1 <= y0:
        return
    if (x1 - x0, y1 - y0) != (pw, ph):
        panel = panel.crop((0, 0, x1 - x0, y1 - y0))
    region_rgb = np.ascontiguousarray(frame[y0:y1, x0:x1, ::-1])
    base = Image.fromarray(region_rgb).convert("RGBA")
    base.alpha_composite(panel)
    frame[y0:y1, x0:x1] = np.asarray(base.convert("RGB"))[:, :, ::-1]


_PANEL_LABEL_PX = 16
_PANEL_TITLE_PX = 17
_PANEL_TITLE_H = 24
_PANEL_TITLE_GAP = 8
_PANEL_TITLE_COLOR = (236, 242, 246)
_PANEL_X0, _PANEL_Y0 = 10, 10
_PANEL_PX = 14
_PANEL_ICON_W = 18
_PANEL_GAP = 9
_PANEL_ROW_H = 29
_PANEL_SEP_GAP = 6
_PANEL_PAD_TOP, _PANEL_PAD_BOTTOM = 8, 12
_PANEL_GAUGE_W = 36

DRONE_PANEL_TITLE = "Stato drone"
WATCH_PANEL_TITLE = "Stato orologio"

_PANEL_LABELS = ("Connesso", "Joystick", "In volo", "Supervisione", "Autopilota")
_WATCH_LABELS = ("Connessione",)


def _panel_base_width(labels: tuple[str, ...], title: str, batt_text: str) -> int:
    text_x = _PANEL_PX + _PANEL_ICON_W + _PANEL_GAP
    max_label_w = _status_label_widths(labels, _PANEL_LABEL_PX)
    pct_w = int(round(fonts.sans(_PANEL_LABEL_PX + 2).getlength(batt_text)))
    title_w = int(round(fonts.sans_bold(_PANEL_TITLE_PX).getlength(title)))
    body_row_w = text_x + max_label_w + _PANEL_PX
    batt_row_w = _PANEL_PX + _PANEL_GAUGE_W + _PANEL_GAP + pct_w + _PANEL_PX
    title_row_w = 2 * _PANEL_PX + title_w
    return max(body_row_w, batt_row_w, title_row_w)


def _panels_base_width(batt_text: str = "100%") -> int:
    return max(
        _panel_base_width(_PANEL_LABELS, DRONE_PANEL_TITLE, batt_text),
        _panel_base_width(_WATCH_LABELS, WATCH_PANEL_TITLE, batt_text),
    )


def _panel_base_height(rows: int) -> int:
    return (
        _PANEL_PAD_TOP + _PANEL_TITLE_H + _PANEL_TITLE_GAP
        + rows * _PANEL_ROW_H + _PANEL_SEP_GAP + _PANEL_ROW_H + _PANEL_PAD_BOTTOM
    )


def status_panel_right_edge() -> int:
    width = _panels_base_width() * _STATUS_PANEL_SCALE
    return _PANEL_X0 + int(round(width))


def watch_panel_left_edge(frame_width: int) -> int:
    width = _panels_base_width() * _STATUS_PANEL_SCALE
    return int(frame_width) - _PANEL_X0 - int(round(width))


_STATUS_PANEL_CACHE: dict[tuple, "Image.Image"] = {}
_WATCH_PANEL_CACHE: dict[tuple, "Image.Image"] = {}


def _build_status_panel(
    connected, joystick, flying, detection_enabled, autonomy_enabled, batt_v,
):
    return _build_panel(
        DRONE_PANEL_TITLE,
        [
            ("Connesso",     connected,                _pi_wifi),
            ("Joystick",     bool(joystick),           _pi_gamepad),
            ("In volo",      flying,                   _pi_drone),
            ("Supervisione", bool(detection_enabled),  _pi_eye),
            ("Autopilota",   bool(autonomy_enabled),   _pi_pin),
        ],
        batt_v,
    )


def _build_watch_panel(connected, batt_v):
    return _build_panel(
        WATCH_PANEL_TITLE,
        [("Connessione", bool(connected), _pi_wifi)],
        batt_v,
    )


def _build_panel(title, status_rows, batt_v):
    batt_text = "--" if batt_v is None else f"{int(batt_v)}%"

    label_px = _PANEL_LABEL_PX
    px     = _PANEL_PX
    icon_w = _PANEL_ICON_W
    gap    = _PANEL_GAP
    rh     = _PANEL_ROW_H
    sep_gap = _PANEL_SEP_GAP
    text_x = px + icon_w + gap
    pad_top, pad_bottom = _PANEL_PAD_TOP, _PANEL_PAD_BOTTOM
    gauge_w = _PANEL_GAUGE_W

    bg_w = _panels_base_width(batt_text)
    bg_h = _panel_base_height(len(status_rows))

    ss = _PANEL_SUPERSAMPLE
    img = Image.new("RGBA", (bg_w * ss, bg_h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_label = fonts.sans(label_px * ss)

    radius = 10 * ss
    draw.rounded_rectangle(
        (0, 0, bg_w * ss - 1, bg_h * ss - 1), radius=radius,
        fill=(*_PANEL_BG, _PANEL_ALPHA),
    )

    icon_cx = (px + icon_w // 2) * ss
    text_x_hi = text_x * ss
    y = pad_top

    draw.text(
        (px * ss, (y + _PANEL_TITLE_H // 2) * ss), title,
        font=fonts.sans_bold(_PANEL_TITLE_PX * ss),
        fill=_PANEL_TITLE_COLOR, anchor="lm",
    )
    y += _PANEL_TITLE_H + _PANEL_TITLE_GAP

    for label, active, draw_icon in status_rows:
        cy = (y + rh // 2) * ss
        draw_icon(draw, icon_cx, cy, ss, _STATUS_ON if active else _STATUS_OFF)
        draw.text(
            (text_x_hi, cy), label, font=font_label,
            fill=_LABEL_ON if active else _LABEL_OFF, anchor="lm",
        )
        y += rh

    sep_y = (y + sep_gap // 2) * ss
    draw.line((px * ss, sep_y, (bg_w - px) * ss, sep_y), fill=_BATT_SEPARATOR, width=max(1, ss))
    y += sep_gap
    cy = (y + rh // 2) * ss
    gauge_x = px * ss
    _pi_battery_gauge(draw, gauge_x, cy, gauge_w, batt_v, ss)
    draw.text(
        ((px + gauge_w + gap) * ss, cy),
        batt_text, font=fonts.sans((label_px + 2) * ss),
        fill=_lighten(_battery_color(batt_v), 0.45), anchor="lm",
    )

    draw.rounded_rectangle(
        (0, 0, bg_w * ss - 1, bg_h * ss - 1), radius=radius,
        outline=_PANEL_BORDER, width=max(1, ss),
    )

    return img.resize(
        (round(bg_w * _STATUS_PANEL_SCALE), round(bg_h * _STATUS_PANEL_SCALE)),
        Image.LANCZOS,
    )


def draw_status_overlay(
    frame, cached_status, detection_enabled=False, autonomy_enabled=False,
):
    connected = bool(cached_status.get("connected", False))
    joystick  = bool(cached_status.get("joystick",  False))
    flying    = bool(cached_status.get("flying",    False))
    batt_v    = cached_status.get("battery")

    key = (
        connected,
        joystick,
        flying,
        bool(detection_enabled),
        bool(autonomy_enabled),
        None if batt_v is None else int(batt_v),
    )
    panel = _STATUS_PANEL_CACHE.get(key)
    if panel is None:
        panel = _build_status_panel(
            connected, joystick, flying, detection_enabled, autonomy_enabled, batt_v,
        )
        _STATUS_PANEL_CACHE.clear()
        _STATUS_PANEL_CACHE[key] = panel

    _composite_rgba(frame, _PANEL_X0, _PANEL_Y0, panel)


SCENARIO_HINT_TEXT = "torna alla scelta dello scenario"

_HINT_SS = 2
_HINT_H = 42
_HINT_PAD = 16
_HINT_GAP = 12
_HINT_BOTTOM_GAP = 26
_HINT_BG = (18, 20, 27, 226)
_HINT_KEY_BG = (224, 154, 16, 255)
_HINT_KEY_TEXT = (20, 16, 6)
_HINT_TEXT = (232, 235, 242)

_HINT_CACHE: dict[tuple, "Image.Image"] = {}


def _build_scenario_hint(key_label: str, text: str):
    ss = _HINT_SS
    font_key = fonts.sans_bold(17 * ss)
    font_text = fonts.sans(17 * ss)
    pad = _HINT_PAD * ss
    key_w = max(int(font_key.getlength(key_label)) + 14 * ss, 26 * ss)
    text_w = int(font_text.getlength(text))
    w = pad + key_w + _HINT_GAP * ss + text_w + pad
    h = _HINT_H * ss

    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle(
        (0, 0, w - 1, h - 1), radius=h // 2,
        fill=_HINT_BG, outline=(*_HINT_KEY_BG[:3], 235), width=ss,
    )
    cy = h // 2
    draw.rounded_rectangle(
        (pad, cy - 13 * ss, pad + key_w, cy + 13 * ss), radius=7 * ss,
        fill=_HINT_KEY_BG,
    )
    draw.text((pad + key_w // 2, cy), key_label, font=font_key, fill=_HINT_KEY_TEXT, anchor="mm")
    draw.text(
        (pad + key_w + _HINT_GAP * ss, cy), text,
        font=font_text, fill=_HINT_TEXT, anchor="lm",
    )
    return panel.resize((w // ss, h // ss), Image.LANCZOS)


def draw_scenario_hint(frame, key_label: str):
    key = (key_label, SCENARIO_HINT_TEXT)
    panel = _HINT_CACHE.get(key)
    if panel is None:
        panel = _build_scenario_hint(key_label, SCENARIO_HINT_TEXT)
        _HINT_CACHE.clear()
        _HINT_CACHE[key] = panel

    h, w = frame.shape[:2]
    x0 = (w - panel.width) // 2
    y0 = h - panel.height - _HINT_BOTTOM_GAP
    if x0 < 0 or y0 < 0:
        return
    _composite_rgba(frame, x0, y0, panel)


def draw_watch_overlay(frame, watch_status=None):
    watch_status = watch_status or {}
    connected = bool(watch_status.get("connected", False))
    batt_v = watch_status.get("battery")

    key = (connected, None if batt_v is None else int(batt_v))
    panel = _WATCH_PANEL_CACHE.get(key)
    if panel is None:
        panel = _build_watch_panel(connected, batt_v)
        _WATCH_PANEL_CACHE.clear()
        _WATCH_PANEL_CACHE[key] = panel

    x0 = frame.shape[1] - _PANEL_X0 - panel.width
    _composite_rgba(frame, max(0, x0), _PANEL_Y0, panel)


_TITLE_PX = 34
_TITLE_TRACKING_PX = 6
_TITLE_Y = 16
_TITLE_COLOR = (243, 247, 250)
_TITLE_SHADOW_ALPHA = 150
_TITLE_SHADOW_BLUR = 5
_TITLE_BAND_H = int(_TITLE_PX * 1.55) + 2 * _TITLE_SHADOW_BLUR
_TITLE_CACHE: dict[str, "Image.Image"] = {}


def project_title_bottom_edge() -> int:
    return _TITLE_Y + _TITLE_BAND_H


def _build_project_title(title: str):
    ss = _PANEL_SUPERSAMPLE
    font = fonts.sans_bold(_TITLE_PX * ss)
    tracking = _TITLE_TRACKING_PX * ss
    widths = [font.getlength(ch) for ch in title]
    text_w = int(round(sum(widths) + tracking * max(0, len(title) - 1)))
    pad = _TITLE_SHADOW_BLUR * 3 * ss
    img = Image.new("RGBA", (text_w + 2 * pad, _TITLE_BAND_H * ss), (0, 0, 0, 0))

    glyphs = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glyphs)
    x = pad
    cy = img.height // 2
    for ch, w in zip(title, widths):
        draw.text((x, cy), ch, font=font, fill=(*_TITLE_COLOR, 255), anchor="lm")
        x += w + tracking

    shadow = glyphs.split()[3].point(lambda a: a * _TITLE_SHADOW_ALPHA // 255)
    shadow = shadow.filter(ImageFilter.GaussianBlur(_TITLE_SHADOW_BLUR * ss))
    img.paste(Image.new("RGBA", img.size, (0, 0, 0, 255)), (0, 0), mask=shadow)
    img.alpha_composite(glyphs)

    return img.resize((img.width // ss, _TITLE_BAND_H), Image.LANCZOS)


def draw_project_title(frame, title: str):
    if not title:
        return
    panel = _TITLE_CACHE.get(title)
    if panel is None:
        panel = _build_project_title(title)
        _TITLE_CACHE.clear()
        _TITLE_CACHE[title] = panel
    x0 = (frame.shape[1] - panel.width) // 2
    _composite_rgba(frame, max(0, x0), _TITLE_Y, panel)


_BANNER_GAP = 8
_SAFETY_NET_BANNER_W = 500
_SAFETY_NET_BANNER_H = 68
_SAFETY_NET_BANNER_H_ALERT = 76


def _banner_x(w, bw):
    left = status_panel_right_edge()
    right = watch_panel_left_edge(w)
    bx = left + (right - left - bw) // 2
    return max(10, min(bx, w - bw - 10))


def _banner_y_clamped(by, bh, h):
    return max(10, min(by, h - bh - 10))


_SAFETY_NET_BANNER_SS = _PANEL_SUPERSAMPLE
_SAFETY_NET_BANNER_RADIUS = 17
_SAFETY_NET_BANNER_FONT_MAX = 30
_SAFETY_NET_BANNER_FONT_MIN = 16
_SAFETY_NET_BANNER_TEXT_X = 92
_SAFETY_NET_BANNER_TEXT_PAD = 18
_SAFETY_NET_BANNER_ICON_CX = 42
_SAFETY_NET_BANNER_ICON_R = 18


def _draw_safety_net_banner_icon(draw, kind, cx, cy, r, w, fill_rgb):
    white = (255, 255, 255, 255)
    if kind == "check":
        ww = int(w * 1.7)
        draw.line((cx - r * 0.62, cy + r * 0.02, cx - r * 0.12, cy + r * 0.55),
                  fill=white, width=ww, joint="curve")
        draw.line((cx - r * 0.12, cy + r * 0.55, cx + r * 0.72, cy - r * 0.55),
                  fill=white, width=ww, joint="curve")
    elif kind == "warn":
        draw.polygon(
            [(cx, cy - r * 0.98), (cx - r * 1.12, cy + r * 0.98), (cx + r * 1.12, cy + r * 0.98)],
            fill=white,
        )
        ex = max(2, int(w * 1.2))
        draw.line((cx, cy - r * 0.24, cx, cy + r * 0.34), fill=(*fill_rgb, 255), width=ex)
        draw.ellipse((cx - ex * 0.7, cy + r * 0.50, cx + ex * 0.7, cy + r * 0.50 + ex * 1.5),
                     fill=(*fill_rgb, 255))
    else:
        _draw_banner_text_vcentered(
            draw, cx, cy, "?", fonts.sans_bold(int(r * 2.1)), anchor="mm",
        )


def _fit_safety_net_banner_font(draw, text, max_width):
    ss = _SAFETY_NET_BANNER_SS
    for size in range(_SAFETY_NET_BANNER_FONT_MAX, _SAFETY_NET_BANNER_FONT_MIN - 1, -1):
        font = fonts.sans_bold(size * ss)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return fonts.sans_bold(_SAFETY_NET_BANNER_FONT_MIN * ss)


def _draw_banner_text_vcentered(draw, x, cy, text, font, anchor):
    box = draw.textbbox((x, cy), text, font=font, anchor=anchor)
    ink_cy = (box[1] + box[3]) / 2.0
    draw.text((x, cy + (cy - ink_cy)), text, font=font, fill=(255, 255, 255, 255), anchor=anchor)


_SAFETY_NET_BANNER_TITLES = {
    "present": "Rete di sicurezza presente",
    "missing": "Rete di sicurezza mancante",
    "no_tags": "Controllo non concludente",
}

_SAFETY_NET_BANNER_STYLE = {
    "present": ((46, 160, 84),  (158, 226, 176), "check"),
    "missing": ((214, 60, 55),  (255, 214, 210), "warn"),
    "no_tags": ((84, 94, 110),  (176, 188, 205), "quest"),
}


def draw_safety_net_verdict_banner(frame, verdict):
    if not verdict:
        return

    outcome = str(verdict.get("outcome", ""))
    style = _SAFETY_NET_BANNER_STYLE.get(outcome)
    if style is None:
        return
    fill, edge, icon = style
    title = _SAFETY_NET_BANNER_TITLES.get(outcome, "")

    h, w = frame.shape[:2]
    bw = min(_SAFETY_NET_BANNER_W, w - 20)
    is_alert = (outcome == "missing")
    bh = _SAFETY_NET_BANNER_H_ALERT if is_alert else _SAFETY_NET_BANNER_H
    bx = _banner_x(w, bw)
    by = _banner_y_clamped(project_title_bottom_edge() + _BANNER_GAP, bh, h)

    _render_safety_net_banner(frame, bx, by, bw, bh, fill, edge, icon, title, is_alert)


def _render_safety_net_banner(frame, bx, by, bw, bh, fill, edge, icon, title, is_alert):
    h, w = frame.shape[:2]
    ss = _SAFETY_NET_BANNER_SS
    pad = 18
    x0, y0 = max(0, bx - pad), max(0, by - pad)
    x1, y1 = min(w, bx + bw + pad), min(h, by + bh + pad)
    ox, oy = bx - x0, by - y0

    region = Image.fromarray(
        cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)
    ).convert("RGBA")

    shadow = Image.new("RGBA", region.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.rounded_rectangle(
        (ox + 2, oy + 6, ox + bw + 2, oy + bh + 6),
        radius=_SAFETY_NET_BANNER_RADIUS, fill=(0, 0, 0, 130),
    )
    region = Image.alpha_composite(region, shadow.filter(ImageFilter.GaussianBlur(7)))

    tile = Image.new("RGBA", (bw * ss, bh * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    rad = _SAFETY_NET_BANNER_RADIUS * ss
    draw.rounded_rectangle((0, 0, bw * ss - 1, bh * ss - 1), radius=rad, fill=(*fill, 240))
    draw.rounded_rectangle(
        (0, 0, bw * ss - 1, bh * ss - 1), radius=rad,
        outline=(*edge, 255), width=(3 if is_alert else 2) * ss,
    )
    icon_cy = (bh // 2) * ss
    _draw_safety_net_banner_icon(
        draw, icon, _SAFETY_NET_BANNER_ICON_CX * ss, icon_cy,
        _SAFETY_NET_BANNER_ICON_R * ss, max(1, round(2.6 * ss)), fill,
    )
    avail = (bw - _SAFETY_NET_BANNER_TEXT_X - _SAFETY_NET_BANNER_TEXT_PAD) * ss
    font = _fit_safety_net_banner_font(draw, title, avail)
    _draw_banner_text_vcentered(draw, _SAFETY_NET_BANNER_TEXT_X * ss, icon_cy, title, font, anchor="lm")

    region.alpha_composite(tile.resize((bw, bh), Image.LANCZOS), (ox, oy))
    frame[y0:y1, x0:x1] = cv2.cvtColor(np.array(region.convert("RGB")), cv2.COLOR_RGB2BGR)


def draw_cached_detections(frame, cached):
    for entry in cached:
        color = entry["color"]
        model_name = entry["name"]
        for det in entry["detections"]:
            x1, y1, x2, y2 = det["bbox"]
            label = f"{model_name}: {det['label']} {det['confidence']:.2f}"

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            cv2.putText(
                frame,
                label,
                (x1, max(20, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
                cv2.LINE_AA,
            )


def draw_axes(frame, R, t, camera_matrix, dist_coeffs) -> None:
    axis_3d = np.float32(
        [
            [0.0, 0.0, 0.0],
            [0.05, 0.0, 0.0],
            [0.0, 0.05, 0.0],
            [0.0, 0.0, -0.05],
        ]
    )

    rvec, _ = cv2.Rodrigues(R)

    imgpts, _ = cv2.projectPoints(axis_3d, rvec, t, camera_matrix, dist_coeffs)
    imgpts = imgpts.reshape(-1, 2).astype(int)

    origin = tuple(imgpts[0])
    x_axis = tuple(imgpts[1])
    y_axis = tuple(imgpts[2])
    z_axis = tuple(imgpts[3])

    cv2.arrowedLine(frame, origin, x_axis, (0, 0, 255), 2)
    cv2.arrowedLine(frame, origin, y_axis, (0, 255, 0), 2)
    cv2.arrowedLine(frame, origin, z_axis, (255, 0, 0), 2)


def draw_tag_outline(frame, *, corners, center, tag_id) -> None:
    if corners is not None:
        corners = np.asarray(corners, dtype=np.int32).reshape(-1, 1, 2)
        if len(corners) >= 4:
            cv2.polylines(frame, [corners], True, (0, 255, 0), 2, cv2.LINE_AA)

    if center is not None:
        center_xy = np.asarray(center, dtype=np.int32).reshape(-1)
        if center_xy.size >= 2:
            center_point = (int(center_xy[0]), int(center_xy[1]))
            cv2.circle(frame, center_point, 5, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.putText(
                frame,
                str(tag_id),
                center_point,
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (255, 0, 0),
                2,
                cv2.LINE_AA,
            )
