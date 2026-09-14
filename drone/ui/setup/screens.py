from __future__ import annotations

from typing import Optional

import pygame
from PIL import Image, ImageDraw, ImageFilter

from drone.config import APP_CONFIG
from drone.hardware.joystick import read_setup_action
from drone.ui import fonts
from drone.ui.setup.effects import (
    bg_gradient,
    corner_glow,
    CrossfadeBlitter,
    fade_screen,
    fit_text,
    flash_button_press,
    focus_window,
    gradient_text,
    maximize_window,
    wrap_text,
)


_SUPERSAMPLE = 2


_REFERENCE_WIDTH = 1920
_REFERENCE_HEIGHT = 1080

_LAYOUT_SCALE = 1.0


def _scale(value: float) -> int:
    return int(round(value * _SUPERSAMPLE * _LAYOUT_SCALE))


def _px(value: float) -> int:
    return int(round(value * _SUPERSAMPLE))


def _base_layout_scale(width: int, height: int) -> float:
    return min(
        1.25,
        max(0.55, min(width / _REFERENCE_WIDTH, height / _REFERENCE_HEIGHT)),
    )


def _apply_layout_scale(width: int, height: int) -> float:
    global _LAYOUT_SCALE
    _LAYOUT_SCALE = _base_layout_scale(width, height)
    return _LAYOUT_SCALE


_HEADER_BAND_H = 150
_FOOTER_BAND_H = 130

_ALERT_ZONE_H = 100


def _compute_tile_rects(n, width, height, *, cols, tile_h, gap=20):
    rows = (n + cols - 1) // cols
    margin_x = max(40, int(width * 0.06))
    header_h = int(_HEADER_BAND_H * _LAYOUT_SCALE)
    footer_h = int(_FOOTER_BAND_H * _LAYOUT_SCALE)
    avail_h = height - header_h - footer_h

    grid_h = rows * tile_h + gap * (rows - 1)
    if grid_h > avail_h:
        tile_h = max(72, int((avail_h - gap * (rows - 1)) / rows))
        grid_h = rows * tile_h + gap * (rows - 1)
    alert_zone = int(_ALERT_ZONE_H * _LAYOUT_SCALE)
    reserve = alert_zone if (avail_h - grid_h) >= alert_zone else 0
    top = header_h + max(0, (avail_h - reserve - grid_h) // 2)

    grid_w = width - 2 * margin_x
    tile_w = (grid_w - gap * (cols - 1)) / cols
    rects = []
    for i in range(n):
        r, c = divmod(i, cols)
        x = margin_x + c * (tile_w + gap)
        y = top + r * (tile_h + gap)
        rects.append(pygame.Rect(int(x), int(y), int(tile_w), int(tile_h)))
    return rects


def footer_rects(width: int, height: int):
    k = _base_layout_scale(width, height)
    larghezza = int(round(250 * k))
    altezza = int(round(54 * k))
    margine = int(round(32 * k))
    stacco = int(round(20 * k))
    y = height - altezza - int(round(28 * k))
    confirm_rect = pygame.Rect(width - margine - larghezza, y, larghezza, altezza)
    cancel_rect = pygame.Rect(confirm_rect.x - stacco - larghezza, y, larghezza, altezza)
    back_rect = pygame.Rect(cancel_rect.x - stacco - larghezza, y, larghezza, altezza)
    return confirm_rect, cancel_rect, back_rect


def _draw_dpad_glyph(draw, cx, cy, r):
    S = _scale
    draw.rounded_rectangle(
        (cx - r, cy - r, cx + r, cy + r), radius=S(6),
        fill=(40, 45, 57), outline=(72, 79, 96), width=S(1),
    )
    a = r * 0.55
    punta = (206, 212, 224)
    draw.line((cx, cy - a, cx, cy + a), fill=punta, width=S(2))
    for sy in (-1, 1):
        draw.polygon(
            [
                (cx, cy + sy * a),
                (cx - S(5), cy + sy * (a - S(6))),
                (cx + S(5), cy + sy * (a - S(6))),
            ],
            fill=punta,
        )


def _draw_cross_glyph(draw, cx, cy, r):
    S = _scale
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=(40, 45, 57), outline=(72, 79, 96), width=S(1),
    )
    k = r * 0.44
    draw.line((cx - k, cy - k, cx + k, cy + k), fill=(124, 178, 232), width=S(3))
    draw.line((cx - k, cy + k, cx + k, cy - k), fill=(124, 178, 232), width=S(3))


def _draw_joystick_hints(draw, hint_groups, *, f_hint, cancel_rect, margin_x):
    S = _scale
    btn_cy = _px(cancel_rect.y + cancel_rect.height / 2)
    x = _px(margin_x)
    r = S(17)

    for gi, (kind, label) in enumerate(hint_groups):
        if gi > 0:
            x += S(16)
            draw.text((x, btn_cy), "·", font=f_hint, fill=(80, 86, 100), anchor="lm")
            x += S(20)
        if kind == "cross":
            _draw_cross_glyph(draw, x + r, btn_cy, r)
        else:
            _draw_dpad_glyph(draw, x + r, btn_cy, r)
        x += 2 * r + S(10)
        draw.text((x, btn_cy), label, font=f_hint, fill=(178, 184, 198), anchor="lm")
        x += int(f_hint.getlength(label))


_ALERT_DOT = {"info": (96, 124, 172), "warn": (212, 156, 66)}


def _draw_alert(draw, W, height, grid_bottom, kind, text, font):
    SS = _SUPERSAMPLE
    S = _scale
    cx = W // 2
    cy = (grid_bottom * SS + _px(height - 108)) // 2
    h = S(48)
    padx = S(24)
    dot_d = S(16)
    gap = S(14)
    w = padx + dot_d + gap + int(font.getlength(text)) + padx
    x0 = cx - w // 2
    y0 = cy - h // 2
    draw.rounded_rectangle(
        [x0, y0, x0 + w, y0 + h], radius=S(12),
        fill=(28, 32, 42), outline=(54, 60, 76), width=S(1),
    )
    dx = x0 + padx
    draw.ellipse([dx, cy - dot_d // 2, dx + dot_d, cy + dot_d // 2], fill=_ALERT_DOT[kind])
    draw.text((dx + dot_d + gap, cy), text, font=font, fill=(206, 212, 224), anchor="lm")


def _draw_screen_backdrop(img, W, H, rects, focus, colors, enabled):
    SS = _SUPERSAMPLE
    S = _scale

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    for r in rects:
        sdraw.rounded_rectangle(
            [r.x * SS, r.y * SS + S(10), r.right * SS, r.bottom * SS + S(10)],
            radius=S(16), fill=(0, 0, 0, 150),
        )
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S(10))))

    if 0 <= focus < len(rects):
        r = rects[focus]
        c = colors[focus]
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(
            [r.x * SS - S(4), r.y * SS - S(4), r.right * SS + S(4), r.bottom * SS + S(4)],
            radius=S(18), fill=(c[0], c[1], c[2], 150 if enabled[focus] else 70),
        )
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S(16))))


def _draw_screen_heading(img, draw, W, title, subtitle, f_title, f_sub):
    S = _scale
    gt = gradient_text(title, f_title, (255, 255, 255), (174, 191, 224))
    img.alpha_composite(gt, (W // 2 - gt.width // 2, S(52) - gt.height // 2))
    draw.text(
        (W // 2, S(102)), subtitle,
        font=f_sub, fill=(176, 182, 194), anchor="mm",
    )


def _draw_tile_frame(img, draw, r, color, on, is_focus):
    SS = _SUPERSAMPLE
    S = _scale
    x0, y0, x1, y1 = r.x * SS, r.y * SS, r.right * SS, r.bottom * SS

    if on:
        bg = (min(40, 23 + color[0] // 12), min(44, 26 + color[1] // 12),
              min(52, 34 + color[2] // 12), 255)
    else:
        bg = (23, 26, 34, 255)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=S(14), fill=bg)
    if on:
        img.alpha_composite(
            corner_glow(r.width * SS, r.height * SS, color, S(14)), (x0, y0)
        )
    border_col = color if (on or is_focus) else (40, 44, 54)
    draw.rounded_rectangle(
        [x0, y0, x1, y1], radius=S(14), outline=border_col,
        width=S(2) if (on or is_focus) else S(1),
    )
    return x0, y0, x1, y1


def _draw_tile_badge(draw, number, bx0, by0, bcy, bsz, color, f_badge):
    S = _scale
    badge_bg = (color[0] // 6 + 8, color[1] // 6 + 8, color[2] // 6 + 8, 255)
    draw.rounded_rectangle(
        [bx0, by0, bx0 + bsz, by0 + bsz], radius=S(11),
        fill=badge_bg, outline=color, width=S(1),
    )
    num = str(number)
    ax, ay = bx0 + bsz // 2, bcy
    nl, nt, nr, nb = draw.textbbox((ax, ay), num, font=f_badge, anchor="mm")
    draw.text(
        (2 * ax - (nl + nr) / 2, 2 * ay - (nt + nb) / 2), num,
        font=f_badge, fill=color, anchor="mm",
    )


def _draw_tile_toggle(draw, x1, bcy, pad, on, color):
    S = _scale
    tw, th = S(60), S(34)
    tgx1 = x1 - pad
    tgx0 = tgx1 - tw
    tgy0 = bcy - th // 2
    draw.rounded_rectangle(
        [tgx0, tgy0, tgx1, tgy0 + th], radius=th // 2,
        fill=color if on else (52, 57, 68),
    )
    knob_r = th // 2 - S(3)
    knob_cx = tgx1 - knob_r - S(3) if on else tgx0 + knob_r + S(3)
    knob_col = (255, 255, 255) if on else (150, 155, 165)
    draw.ellipse([knob_cx - knob_r, bcy - knob_r, knob_cx + knob_r, bcy + knob_r], fill=knob_col)


_WAYPOINT_COLS = 1


def _waypoint_tile_height(descriptions, width, height=_REFERENCE_HEIGHT) -> int:
    _apply_layout_scale(width, height)
    S = _scale
    SS = _SUPERSAMPLE
    margin_x = max(40, int(width * 0.06))
    tile_w = width - 2 * margin_x

    text_max_w = tile_w * SS - 2 * S(18) - S(100) - S(140)
    f_name = fonts.sans_bold(S(34))
    f_desc = fonts.sans(S(24))
    name_lh = sum(f_name.getmetrics())
    desc_lh = sum(f_desc.getmetrics())

    max_lines = 1
    for desc in descriptions:
        max_lines = max(max_lines, len(wrap_text(desc, f_desc, text_max_w, 100)))

    needed_ss = 2 * S(16) + name_lh + S(6) + max_lines * desc_lh + S(44)
    return (needed_ss + SS - 1) // SS + 4


_WAYPOINT_PALETTE = (
    (255, 122, 69),
    (255, 199, 0),
    (124, 230, 70),
    (255, 86, 156),
    (60, 200, 255),
    (191, 124, 255),
)


WAYPOINT_TITLE = "Scelta dello scenario"
WAYPOINT_SUBTITLE = "Il percorso che esegue il drone, i controlli delle soste di supervisione e i modelli di detection che si caricano"
WAYPOINT_MODELS_LABEL = "MODELLI"

GO_BACK = object()


def _button_label(testo: str, etichetta: str) -> str:
    return f"{testo} ({etichetta})"


def _draw_tile_models(draw, x, y, models, color, on):
    S = _scale
    f_label = fonts.sans_bold(S(15))
    f_chip = fonts.sans_bold(S(19))
    draw.text(
        (x, y), WAYPOINT_MODELS_LABEL, font=f_label,
        fill=(140, 146, 160) if on else (110, 115, 128), anchor="lm",
    )
    cx = x + int(f_label.getlength(WAYPOINT_MODELS_LABEL)) + S(14)
    for label in models:
        w = int(f_chip.getlength(label)) + S(26)
        draw.rounded_rectangle(
            (cx, y - S(15), cx + w, y + S(15)), radius=S(15),
            fill=(*color, 46) if on else (44, 48, 58),
            outline=(*color, 190) if on else (70, 75, 88), width=S(1),
        )
        draw.text(
            (cx + w // 2, y), label, font=f_chip,
            fill=(238, 240, 245) if on else (150, 155, 168), anchor="mm",
        )
        cx += w + S(10)


def _render_waypoint_screen(width, height, names, descriptions, colors, enabled,
                            focus, focused, rects, confirm_rect, cancel_rect, back_rect,
                            cancel_hover, confirm_hover, back_hover, models):
    _apply_layout_scale(width, height)
    SS = _SUPERSAMPLE
    W, H = width * SS, height * SS
    margin_x = max(40, int(width * 0.06))

    S = _scale

    f_title  = fonts.sans_bold(S(44))
    f_sub    = fonts.sans(S(26))
    f_name   = fonts.sans_bold(S(34))
    f_desc   = fonts.sans(S(24))
    f_badge  = fonts.sans_bold(S(30))
    f_hint   = fonts.sans(S(20))
    f_btn    = fonts.sans_bold(S(23))
    f_msg    = fonts.sans_bold(S(28))

    img = bg_gradient(W, H).convert("RGBA")

    _draw_screen_backdrop(img, W, H, rects, focus, colors, enabled)

    draw = ImageDraw.Draw(img)

    _draw_screen_heading(
        img, draw, W,
        WAYPOINT_TITLE,
        WAYPOINT_SUBTITLE,
        f_title, f_sub,
    )

    for i, r in enumerate(rects):
        on, color = enabled[i], colors[i]
        x0, y0, x1, y1 = _draw_tile_frame(img, draw, r, color, on, i == focus)

        pad = S(18)
        bsz = S(56)
        bcy = (y0 + y1) // 2
        bx0 = x0 + pad
        tx = bx0 + bsz + S(64)
        text_max_w = r.width * SS - 2 * pad - S(100) - S(140)
        name_color = (238, 240, 245) if on else (176, 181, 192)
        desc_color = (198, 203, 214) if on else (160, 165, 177)
        name_text = fit_text(names[i], f_name, text_max_w)

        asc_n, desc_n = f_name.getmetrics()
        name_lh = asc_n + desc_n
        asc_d, desc_d = f_desc.getmetrics()
        desc_lh = asc_d + desc_d

        tile_models = models[i]
        chip_h = S(34) if tile_models else 0

        pad_v = S(16)
        avail_desc_h = (y1 - y0) - 2 * pad_v - name_lh - S(6) - chip_h
        max_desc_lines = max(1, int(avail_desc_h // desc_lh))
        desc_lines = wrap_text(descriptions[i], f_desc, text_max_w, max_desc_lines)

        gap_nd = S(6) if desc_lines else 0
        total_h = name_lh + gap_nd + len(desc_lines) * desc_lh + chip_h
        ty = bcy - total_h // 2

        by0 = bcy - bsz // 2
        _draw_tile_badge(draw, i + 1, bx0, by0, bcy, bsz, color, f_badge)

        draw.text((tx, ty), name_text, font=f_name, fill=name_color, anchor="lt")
        ly = ty + name_lh + gap_nd
        for line in desc_lines:
            draw.text((tx, ly), line, font=f_desc, fill=desc_color, anchor="lt")
            ly += desc_lh

        if tile_models:
            _draw_tile_models(draw, tx, ly + S(16), tile_models, color, on)

        _draw_tile_toggle(draw, x1, bcy, pad, on, color)

    if not focused and rects:
        _draw_alert(draw, W, height, max(r.bottom for r in rects), "info",
                    "La finestra non è attiva, clicca per usarla", f_msg)

    linea = _px(back_rect.y - 14)
    draw.line(
        [(_px(margin_x), linea), (W - _px(margin_x), linea)],
        fill=(32, 35, 43), width=S(1),
    )

    hint_groups = [
        ("dpad", "naviga"),
        ("cross", "seleziona"),
    ]
    _draw_joystick_hints(
        draw, hint_groups, f_hint=f_hint, cancel_rect=cancel_rect, margin_x=margin_x,
    )

    mapping = APP_CONFIG.joystick
    for rect, testo, etichetta, hover in (
        (back_rect, "Indietro", mapping.label_setup_back, back_hover),
        (cancel_rect, "Annulla", mapping.label_setup_cancel, cancel_hover),
    ):
        draw.rounded_rectangle(
            [rect.x * SS, rect.y * SS, rect.right * SS, rect.bottom * SS], radius=S(9),
            fill=(30, 34, 42) if hover else (22, 25, 32), outline=(70, 76, 90), width=S(1),
        )
        draw.text(
            ((rect.x + rect.width / 2) * SS, (rect.y + rect.height / 2) * SS),
            _button_label(testo, etichetta), font=f_btn, fill=(205, 209, 218), anchor="mm",
        )

    qb = confirm_rect
    draw.rounded_rectangle(
        [qb.x * SS, qb.y * SS, qb.right * SS, qb.bottom * SS], radius=S(9),
        fill=(80, 210, 130) if confirm_hover else (61, 200, 132),
    )
    draw.text(
        ((qb.x + qb.width / 2) * SS, (qb.y + qb.height / 2) * SS),
        _button_label("Conferma", mapping.label_setup_confirm),
        font=f_btn, fill=(8, 19, 12), anchor="mm",
    )

    final = img.convert("RGB").resize((width, height), Image.LANCZOS)
    return pygame.image.frombytes(final.tobytes(), final.size, "RGB").convert()


def select_waypoint_path_interactive(screen, paths, models=()):
    n = len(paths)
    names = [p.name for p in paths]
    descriptions = [getattr(p, "description", "") or "" for p in paths]
    models = [list(models[i]) if i < len(models) else [] for i in range(n)]
    colors = [_WAYPOINT_PALETTE[i % len(_WAYPOINT_PALETTE)] for i in range(n)]

    selected = 0
    focus = 0

    focus_window()
    maximize_window()
    pygame.event.clear()

    clock = pygame.time.Clock()

    cache_sig = None
    cached_surf = None
    faded_in = False
    crossfade = CrossfadeBlitter()

    while True:
        width, height = screen.get_size()
        focused = pygame.key.get_focused()
        tile_h = _waypoint_tile_height(descriptions, width, height)
        rects = _compute_tile_rects(
            n, width, height, cols=_WAYPOINT_COLS, tile_h=tile_h, gap=18,
        )

        confirm_rect, cancel_rect, back_rect = footer_rects(width, height)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                continue
            comando = read_setup_action(event)
            if comando == "confirm":
                return paths[selected]
            if comando == "cancel":
                return None
            if comando == "back":
                return GO_BACK
            if comando == "select":
                selected = focus
                continue
            if comando == "up":
                focus = max(0, focus - 1)
            elif comando == "down":
                focus = min(n - 1, focus + 1)
            if event.type == pygame.MOUSEMOTION:
                for i, r in enumerate(rects):
                    if r.collidepoint(event.pos):
                        focus = i
                        break
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if confirm_rect.collidepoint(event.pos):
                    flash_button_press(screen, cached_surf, confirm_rect)
                    return paths[selected]
                if cancel_rect.collidepoint(event.pos):
                    flash_button_press(screen, cached_surf, cancel_rect)
                    return None
                if back_rect.collidepoint(event.pos):
                    flash_button_press(screen, cached_surf, back_rect)
                    return GO_BACK
                for i, r in enumerate(rects):
                    if r.collidepoint(event.pos):
                        selected = i
                        focus = i
                        break

        mouse_pos = pygame.mouse.get_pos()
        cancel_hover = cancel_rect.collidepoint(mouse_pos)
        confirm_hover = confirm_rect.collidepoint(mouse_pos)
        back_hover = back_rect.collidepoint(mouse_pos)
        enabled = [i == selected for i in range(n)]
        sig = (
            width, height, selected, focus,
            bool(focused), cancel_hover, confirm_hover, back_hover,
        )
        if sig != cache_sig:
            cached_surf = _render_waypoint_screen(
                width, height, names, descriptions, colors, enabled,
                focus, focused, rects, confirm_rect, cancel_rect, back_rect,
                cancel_hover, confirm_hover, back_hover, models,
            )
            cache_sig = sig

        if not faded_in:
            fade_screen(screen, cached_surf, fade_in=True)
            faded_in = True

        crossfade.draw(screen, cached_surf)
        pygame.display.flip()
        clock.tick(30)
