from __future__ import annotations

from typing import Optional

import pygame
from PIL import Image, ImageDraw

from drone.config import APP_CONFIG
from drone.hardware.joystick import read_setup_action
from drone.ui import fonts
from drone.ui.setup.effects import (
    CARD_EDGE,
    CARD_EDGE_ON,
    CARD_FILL,
    CARD_FILL_ON,
    CHIP_EDGE,
    CHIP_EDGE_ON,
    CHIP_FILL,
    CHIP_FILL_ON,
    CYAN_BRIGHT,
    CYAN_FILL,
    CYAN_INK,
    CYAN_TEXT,
    CrossfadeBlitter,
    ICON_CYAN,
    LINE_DIM,
    WHITE,
    draw_alert,
    draw_setup_footer,
    fade_screen,
    fit_text,
    flash_button_press,
    focus_window,
    grid_background,
    maximize_window,
    wrap_text,
)
from drone.ui.shapes import (
    corner_brackets,
    draw_centered_label,
    glow_box,
    paint_supersampled,
)


_SUPERSAMPLE = 2


_REFERENCE_WIDTH = 1920
_REFERENCE_HEIGHT = 1080

_LAYOUT_SCALE = 1.0


def _scale(value: float) -> int:
    return int(round(value * _SUPERSAMPLE * _LAYOUT_SCALE))


def _px(value: float) -> int:
    return int(round(value * _SUPERSAMPLE))


def _unit() -> float:
    return _SUPERSAMPLE * _LAYOUT_SCALE


def _base_layout_scale(width: int, height: int) -> float:
    return min(
        1.25,
        max(0.55, min(width / _REFERENCE_WIDTH, height / _REFERENCE_HEIGHT)),
    )


def _apply_layout_scale(width: int, height: int) -> float:
    global _LAYOUT_SCALE
    _LAYOUT_SCALE = _base_layout_scale(width, height)
    return _LAYOUT_SCALE


_HEADER_BAND_H = 140
_FOOTER_BAND_H = 130


def _tile_margin_x(width: int) -> int:
    return max(24, int(width * 0.036))


def _compute_tile_rects(n, width, height, *, cols, tile_h, gap=20):
    rows = (n + cols - 1) // cols
    margin_x = _tile_margin_x(width)
    header_h = int(_HEADER_BAND_H * _LAYOUT_SCALE)
    footer_h = int(_FOOTER_BAND_H * _LAYOUT_SCALE)
    avail_h = height - header_h - footer_h

    grid_h = rows * tile_h + gap * (rows - 1)
    if grid_h > avail_h:
        tile_h = max(72, int((avail_h - gap * (rows - 1)) / rows))
        grid_h = rows * tile_h + gap * (rows - 1)
    top = header_h + max(0, (avail_h - grid_h) // 2)

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
    altezza = int(round(60 * k))
    margine = int(round(48 * k))
    stacco = int(round(20 * k))
    y = height - altezza - int(round(28 * k))
    confirm_rect = pygame.Rect(width - margine - larghezza, y, larghezza, altezza)
    back_rect = pygame.Rect(confirm_rect.x - stacco - larghezza, y, larghezza, altezza)
    cancel_rect = pygame.Rect(margine, y, larghezza, altezza)
    return confirm_rect, cancel_rect, back_rect


def _paint_icon(img, cx, cy, reach, paint) -> None:
    paint_supersampled(img, (cx - reach, cy - reach, cx + reach, cy + reach), (cx, cy), paint)


_WAYPOINT_COLS = 1

_TILE_TEXT_X = 150
_TILE_NAME_Y = 56
_TILE_DESC_Y = 112
_TILE_DESC_STEP = 40
_TILE_META_GAP = 62
_TILE_DIVIDER_GAP = 36
_TILE_MODELS_GAP = 44
_TILE_BOTTOM_GAP = 46

_TILE_DESC_PX = 29
_SUBTITLE_PX = 28

_BADGE_FILL = (3, 30, 58)


def _tile_offsets(desc_lines: int) -> dict:
    meta = _TILE_DESC_Y + _TILE_DESC_STEP * (max(1, desc_lines) - 1) + _TILE_META_GAP
    divider = meta + _TILE_DIVIDER_GAP
    models = divider + _TILE_MODELS_GAP
    return {"meta": meta, "divider": divider, "models": models, "bottom": models + _TILE_BOTTOM_GAP}


def _waypoint_tile_height(descriptions, width, height=_REFERENCE_HEIGHT) -> int:
    _apply_layout_scale(width, height)
    SS = _SUPERSAMPLE
    tile_w = width - 2 * _tile_margin_x(width)
    text_max_w = tile_w * SS - 2 * _scale(_TILE_TEXT_X)
    f_desc = fonts.sans(_scale(_TILE_DESC_PX))

    max_lines = 1
    for desc in descriptions:
        max_lines = max(max_lines, len(wrap_text(desc, f_desc, text_max_w, 100)))

    needed_ss = _scale(_tile_offsets(max_lines)["bottom"])
    return (needed_ss + SS - 1) // SS + 2


WAYPOINT_TITLE = "Scelta dello scenario"
WAYPOINT_SUBTITLE = (
    "Lo scenario decide il percorso del drone, le soste di supervisione e i modelli "
    "di riconoscimento usati in volo"
)
WAYPOINT_MODELS_LABEL = "MODELLI"

EXIT_TEXT = "Esci"
BACK_TEXT = "Indietro"
NEXT_TEXT = "Avanti"

GO_BACK = object()


def _button_label(testo: str, etichetta: str) -> str:
    return f"{testo} ({etichetta})"


def _path_summary(path) -> tuple[str, Optional[str]]:
    waypoint = f"{len(getattr(path, 'waypoints', None) or ())} waypoint"
    soste = len(getattr(path, "supervision_waypoints", None) or ())
    durata = getattr(path, "supervision_stop_sec", None)
    if not soste or durata is None:
        return waypoint, None
    parola = "sosta" if soste == 1 else "soste"
    secondi = f"{float(durata):g}".replace(".", ",")
    return waypoint, f"{soste} {parola} da {secondi} s"


def _draw_pin_icon(draw, cx, cy, size, color, hole):
    r = size * 0.36
    hy = cy - size * 0.13
    draw.ellipse((cx - r, hy - r, cx + r, hy + r), fill=color)
    draw.polygon(
        [(cx - r * 0.88, hy + r * 0.45), (cx + r * 0.88, hy + r * 0.45), (cx, cy + size * 0.5)],
        fill=color,
    )
    foro = r * 0.42
    draw.ellipse((cx - foro, hy - foro, cx + foro, hy + foro), fill=hole)


def _draw_stopwatch_icon(draw, cx, cy, size, color, u):
    w = max(1, round(2.4 * u))
    r = size * 0.4
    ccy = cy + size * 0.07
    draw.ellipse((cx - r, ccy - r, cx + r, ccy + r), outline=color, width=w)
    draw.line((cx, ccy - r - size * 0.1, cx, ccy - r), fill=color, width=w)
    draw.line((cx - size * 0.13, ccy - r - size * 0.12, cx + size * 0.13, ccy - r - size * 0.12),
              fill=color, width=w)
    draw.line((cx, ccy, cx + r * 0.42, ccy - r * 0.45), fill=color, width=w)


def _draw_ring(draw, cx, cy, r, u):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=CYAN_BRIGHT, width=max(1, round(2.6 * u)))


def _draw_check(draw, cx, cy, r, u):
    _draw_ring(draw, cx, cy, r, u)
    ri = r - 6 * u
    draw.ellipse((cx - ri, cy - ri, cx + ri, cy + ri), fill=CYAN_FILL)
    w = max(1, round(4.6 * u))
    draw.line((cx - ri * 0.45, cy + ri * 0.02, cx - ri * 0.1, cy + ri * 0.38),
              fill=CYAN_INK, width=w, joint="curve")
    draw.line((cx - ri * 0.1, cy + ri * 0.38, cx + ri * 0.5, cy - ri * 0.36),
              fill=CYAN_INK, width=w, joint="curve")


def _draw_tile_badge(img, number, bx0, bcy, half, f_badge):
    u = _unit()
    radius = _scale(12)
    _paint_icon(
        img, bx0 + half, bcy, half + _scale(3),
        lambda d, ax, ay, s: d.rounded_rectangle(
            (ax - half * s, ay - half * s, ax + half * s, ay + half * s), radius=radius * s,
            fill=_BADGE_FILL, outline=CYAN_BRIGHT, width=max(1, round(2.6 * u * s)),
        ),
    )
    draw_centered_label(
        ImageDraw.Draw(img), bx0 + half, bcy, str(number), f_badge, CYAN_BRIGHT,
    )


def _draw_tile_summary(img, x, cy, summary, on, fonts_map):
    u = _unit()
    waypoint, soste = summary
    font = fonts_map["meta"]
    hole = CARD_FILL_ON if on else CARD_FILL
    pin = _scale(29)
    _paint_icon(
        img, x + _scale(14), cy, pin * 0.62,
        lambda d, ax, ay, s: _draw_pin_icon(d, ax, ay, pin * s, ICON_CYAN, hole),
    )
    draw = ImageDraw.Draw(img)
    tx = x + _scale(46)
    draw.text((tx, cy), waypoint, font=font, fill=CYAN_TEXT, anchor="lm")
    if soste is None:
        return
    bx = tx + font.getlength(waypoint) + _scale(26)
    draw.text((bx, cy), "•", font=font, fill=CYAN_TEXT, anchor="mm")
    sx = bx + _scale(38)
    watch = _scale(30)
    _paint_icon(
        img, sx, cy, watch * 0.62,
        lambda d, ax, ay, s: _draw_stopwatch_icon(d, ax, ay, watch * s, ICON_CYAN, u * s),
    )
    draw.text((sx + _scale(36), cy), soste, font=font, fill=CYAN_TEXT, anchor="lm")


def _draw_tile_models(draw, x, cy, models, on, fonts_map):
    f_label = fonts_map["models_label"]
    f_chip = fonts_map["chip"]
    draw.text((x, cy), WAYPOINT_MODELS_LABEL, font=f_label, fill=CYAN_BRIGHT, anchor="lm")
    cx = x + int(f_label.getlength(WAYPOINT_MODELS_LABEL)) + _scale(26)
    alto = _scale(19)
    for label in models:
        w = int(f_chip.getlength(label)) + _scale(44)
        draw.rounded_rectangle(
            (cx, cy - alto, cx + w, cy + alto), radius=alto,
            fill=CHIP_FILL_ON if on else CHIP_FILL,
            outline=CHIP_EDGE_ON if on else CHIP_EDGE, width=max(1, round(2 * _unit())),
        )
        draw_centered_label(draw, cx + w / 2, cy, label, f_chip, WHITE)
        cx += w + _scale(14)


def _draw_tile(img, r, index, name, description, summary, models, on, is_focus, fonts_map):
    SS = _SUPERSAMPLE
    u = _unit()
    x0, y0, x1, y1 = r.x * SS, r.y * SS, r.right * SS, r.bottom * SS
    acceso = on or is_focus

    glow_box(
        img, (x0, y0, x1, y1), radius=12 * u,
        edge=CARD_EDGE_ON if acceso else CARD_EDGE, width=(2.4 if acceso else 1.8) * u,
        fill=CARD_FILL_ON if on else CARD_FILL,
        glow=(9 if acceso else 4) * u, glow_alpha=170 if acceso else 70,
    )
    draw = ImageDraw.Draw(img)
    if is_focus:
        rientro = 9 * u
        corner_brackets(
            draw, (x0 + rientro, y0 + rientro, x1 - rientro, y1 - rientro),
            arm=22 * u, width=4 * u, color=CYAN_BRIGHT,
        )

    cy = (y0 + y1) / 2
    _draw_tile_badge(img, index + 1, x0 + _scale(32), cy, _scale(36), fonts_map["badge"])

    tx = x0 + _scale(_TILE_TEXT_X)
    text_max_w = (x1 - x0) - 2 * _scale(_TILE_TEXT_X)
    fisso = _scale(_tile_offsets(1)["bottom"])
    righe_max = 1 + max(0, ((y1 - y0) - fisso) // _scale(_TILE_DESC_STEP))
    righe = wrap_text(description, fonts_map["desc"], text_max_w, righe_max)
    offsets = _tile_offsets(len(righe))
    top = y0 + max(0, ((y1 - y0) - _scale(offsets["bottom"])) // 2)

    draw.text((tx, top + _scale(_TILE_NAME_Y)), fit_text(name, fonts_map["name"], text_max_w),
              font=fonts_map["name"], fill=WHITE, anchor="lm")
    for n, riga in enumerate(righe):
        draw.text((tx, top + _scale(_TILE_DESC_Y + _TILE_DESC_STEP * n)), riga,
                  font=fonts_map["desc"], fill=CYAN_TEXT, anchor="lm")

    _draw_tile_summary(img, tx, top + _scale(offsets["meta"]), summary, on, fonts_map)
    dy = top + _scale(offsets["divider"])
    draw.line((tx, dy, x1 - _scale(_TILE_TEXT_X), dy), fill=LINE_DIM, width=max(1, round(1.5 * u)))
    if models:
        _draw_tile_models(draw, tx, top + _scale(offsets["models"]), models, on, fonts_map)

    ix = x1 - _scale(60)
    raggio = _scale(32)
    simbolo = _draw_check if on else _draw_ring
    _paint_icon(
        img, ix, cy, raggio + _scale(4),
        lambda d, ax, ay, s: simbolo(d, ax, ay, raggio * s, u * s),
    )


def _render_waypoint_screen(width, height, names, descriptions, summaries, enabled,
                            focus, focused, rects, confirm_rect, cancel_rect, back_rect,
                            cancel_hover, confirm_hover, back_hover, models):
    _apply_layout_scale(width, height)
    SS = _SUPERSAMPLE
    W, H = width * SS, height * SS
    S = _scale
    u = _unit()

    fonts_map = {
        "title": fonts.sans_bold(S(62)),
        "subtitle": fonts.sans(S(_SUBTITLE_PX)),
        "name": fonts.sans_bold(S(35)),
        "desc": fonts.sans(S(_TILE_DESC_PX)),
        "meta": fonts.sans(S(23)),
        "badge": fonts.sans_bold(S(40)),
        "models_label": fonts.sans_bold(S(20)),
        "chip": fonts.sans(S(22)),
        "message": fonts.sans_bold(S(28)),
    }

    img = grid_background(W, H, S(64), S(6))
    draw = ImageDraw.Draw(img)
    draw.text((W // 2, S(52)), WAYPOINT_TITLE, font=fonts_map["title"], fill=WHITE, anchor="mm")
    draw.text((W // 2, S(111)), WAYPOINT_SUBTITLE, font=fonts_map["subtitle"],
              fill=CYAN_TEXT, anchor="mm")

    for i, r in enumerate(rects):
        _draw_tile(
            img, r, i, names[i], descriptions[i], summaries[i], models[i],
            enabled[i], i == focus, fonts_map,
        )

    if not focused and rects:
        cy = (max(r.bottom for r in rects) * SS + _px(height - 108)) // 2
        draw_alert(ImageDraw.Draw(img), W // 2, cy,
                   "La finestra non è attiva, clicca per usarla", fonts_map["message"], unit=u)

    mapping = APP_CONFIG.joystick
    draw_setup_footer(
        img,
        [
            (cancel_rect, _button_label(EXIT_TEXT, mapping.label_setup_cancel), cancel_hover),
            (back_rect, _button_label(BACK_TEXT, mapping.label_setup_back), back_hover),
            (confirm_rect, _button_label(NEXT_TEXT, mapping.label_setup_confirm), confirm_hover),
        ],
        [("dpad", "naviga"), ("cross", "seleziona")],
        supersample=SS, unit=u,
    )

    final = img.resize((width, height), Image.LANCZOS)
    return pygame.image.frombytes(final.tobytes(), final.size, "RGB").convert()


def select_waypoint_path_interactive(screen, paths, models=()):
    n = len(paths)
    names = [p.name for p in paths]
    descriptions = [getattr(p, "description", "") or "" for p in paths]
    summaries = [_path_summary(p) for p in paths]
    models = [list(models[i]) if i < len(models) else [] for i in range(n)]

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
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for rect, pulsante in (
                    (confirm_rect, "confirm"), (cancel_rect, "cancel"), (back_rect, "back"),
                ):
                    if rect.collidepoint(event.pos):
                        comando = pulsante
            if comando in ("confirm", "cancel", "back"):
                flash_button_press(screen, _render_waypoint_screen(
                    width, height, names, descriptions, summaries,
                    [i == selected for i in range(n)], focus, focused, rects,
                    confirm_rect, cancel_rect, back_rect,
                    comando == "cancel", comando == "confirm", comando == "back", models,
                ))
                if comando == "confirm":
                    return paths[selected]
                return None if comando == "cancel" else GO_BACK
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
                width, height, names, descriptions, summaries, enabled,
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
