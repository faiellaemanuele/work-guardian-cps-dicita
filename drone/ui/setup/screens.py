from __future__ import annotations

import pygame
from PIL import Image, ImageDraw, ImageFilter

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


def _scale(value: float) -> int:
    return int(round(value * _SUPERSAMPLE))


_HEADER_BAND_H = 150
_FOOTER_BAND_H = 130

_ALERT_ZONE_H = 100


def _compute_tile_rects(n, width, height, *, cols, tile_h, gap=20):
    rows = (n + cols - 1) // cols
    margin_x = max(40, int(width * 0.06))
    header_h = _HEADER_BAND_H
    footer_h = _FOOTER_BAND_H
    avail_h = height - header_h - footer_h

    grid_h = rows * tile_h + gap * (rows - 1)
    if grid_h > avail_h:
        tile_h = max(72, int((avail_h - gap * (rows - 1)) / rows))
        grid_h = rows * tile_h + gap * (rows - 1)
    reserve = _ALERT_ZONE_H if (avail_h - grid_h) >= _ALERT_ZONE_H else 0
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


def _draw_keyboard_hints(draw, key_groups, *, f_kbd, f_hint, cancel_rect, margin_x):
    S = _scale
    asc_k, desc_k = f_kbd.getmetrics()
    kbd_h = asc_k + desc_k + S(7) * 2
    btn_cy = S(cancel_rect.y + cancel_rect.height / 2)
    ky = btn_cy - kbd_h // 2
    kx = S(margin_x)

    def kbd(label, x):
        w_ = max(int(f_kbd.getlength(label)) + S(9) * 2, kbd_h)
        draw.rounded_rectangle(
            [x, ky, x + w_, ky + kbd_h], radius=S(7),
            fill=(40, 45, 57), outline=(72, 79, 96), width=S(1),
        )
        draw.line(
            [(x + S(4), ky + kbd_h - S(2)), (x + w_ - S(4), ky + kbd_h - S(2))],
            fill=(72, 79, 96), width=S(2),
        )
        draw.text((x + w_ // 2, btn_cy), label, font=f_kbd, fill=(231, 234, 241), anchor="mm")
        return w_

    for gi, (keys, label) in enumerate(key_groups):
        if gi > 0:
            kx += S(14)
            draw.text((kx, btn_cy), "·", font=f_hint, fill=(80, 86, 100), anchor="lm")
            kx += S(18)
        for key in keys:
            kx += kbd(key, kx) + S(7)
        if label:
            kx += S(6)
            draw.text((kx, btn_cy), label, font=f_hint, fill=(178, 184, 198), anchor="lm")
            kx += int(f_hint.getlength(label))


_ALERT_DOT = {"info": (96, 124, 172), "warn": (212, 156, 66)}


def _draw_alert(draw, W, height, grid_bottom, kind, text, font):
    SS = _SUPERSAMPLE
    S = _scale
    cx = W // 2
    cy = (grid_bottom * SS + S(height - 108)) // 2
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
        color = colors[focus]
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.rounded_rectangle(
            [r.x * SS - S(4), r.y * SS - S(4), r.right * SS + S(4), r.bottom * SS + S(4)],
            radius=S(18), fill=(*color, 150 if enabled[focus] else 70),
        )
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(S(16))))


def _draw_screen_heading(img, draw, W, title, subtitle, f_title, f_sub):
    S = _scale
    title_img = gradient_text(title, f_title, (255, 255, 255), (174, 191, 224))
    img.alpha_composite(title_img, ((W - title_img.width) // 2, S(52) - title_img.height // 2))
    draw.text((W // 2, S(102)), subtitle, font=f_sub,
              fill=(176, 182, 194), anchor="mm")


def _draw_tile_frame(img, draw, r, color, on, is_focus):
    SS = _SUPERSAMPLE
    S = _scale
    x0, y0, x1, y1 = r.x * SS, r.y * SS, r.right * SS, r.bottom * SS

    if on:
        c0, c1, c2 = color
        bg = (min(40, 23 + c0 // 12), min(44, 26 + c1 // 12), min(52, 34 + c2 // 12), 255)
    else:
        bg = (23, 26, 34, 255)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=S(14), fill=bg)
    if on:
        img.alpha_composite(corner_glow(x1 - x0, y1 - y0, color, S(14)), (x0, y0))
    border_col = color if on or is_focus else (40, 44, 54)
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
    sw_w, sw_h = S(60), S(34)
    sx1 = x1 - pad
    sx0 = sx1 - sw_w
    sy0, sy1 = bcy - sw_h // 2, bcy + sw_h // 2
    draw.rounded_rectangle(
        [sx0, sy0, sx1, sy1], radius=sw_h // 2,
        fill=color if on else (52, 57, 68),
    )
    knob_r = S(13)
    knob_cx = sx1 - sw_h // 2 if on else sx0 + sw_h // 2
    draw.ellipse(
        [knob_cx - knob_r, bcy - knob_r, knob_cx + knob_r, bcy + knob_r],
        fill=(255, 255, 255) if on else (150, 155, 165),
    )


_WAYPOINT_COLS = 1


def _waypoint_tile_height(descriptions, width) -> int:
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
WAYPOINT_SUBTITLE = "Il percorso che esegue il drone e i modelli di detection attivi quando si passa in volo automatico"
WAYPOINT_MODELS_LABEL = "MODELLI"


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
                            focus, focused, rects, confirm_rect, cancel_rect,
                            cancel_hover, confirm_hover, models):
    SS = _SUPERSAMPLE
    W, H = width * SS, height * SS
    margin_x = max(40, int(width * 0.06))

    S = _scale

    f_title  = fonts.sans_bold(S(44))
    f_sub    = fonts.sans(S(26))
    f_name   = fonts.sans_bold(S(34))
    f_desc   = fonts.sans(S(24))
    f_badge  = fonts.sans_bold(S(30))
    f_kbd    = fonts.sans_bold(S(20))
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

        pad_v = S(16)
        avail_desc_h = (y1 - y0) - 2 * pad_v - name_lh - S(6)
        max_desc_lines = max(1, int(avail_desc_h // desc_lh))
        desc_lines = wrap_text(descriptions[i], f_desc, text_max_w, max_desc_lines)

        tile_models = models[i]
        chip_h = S(34) if tile_models else 0
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

    draw.line(
        [(S(margin_x), S(height - 108)), (W - S(margin_x), S(height - 108))],
        fill=(32, 35, 43), width=S(1),
    )

    key_groups = [
        (["↑", "↓", "←", "→"], "naviga"),
        (["Spazio"], "seleziona"),
    ]
    _draw_keyboard_hints(
        draw, key_groups,
        f_kbd=f_kbd, f_hint=f_hint, cancel_rect=cancel_rect, margin_x=margin_x,
    )

    draw.rounded_rectangle(
        [S(cancel_rect.x), S(cancel_rect.y), S(cancel_rect.right), S(cancel_rect.bottom)],
        radius=S(10),
        fill=(30, 34, 42) if cancel_hover else (22, 25, 32),
        outline=(70, 76, 90), width=S(1),
    )
    draw.text(
        (S(cancel_rect.centerx), S(cancel_rect.centery)), "Annulla (Esc)",
        font=f_btn, fill=(205, 209, 218), anchor="mm",
    )
    draw.rounded_rectangle(
        [S(confirm_rect.x), S(confirm_rect.y), S(confirm_rect.right), S(confirm_rect.bottom)],
        radius=S(10),
        fill=(80, 210, 130) if confirm_hover else (61, 200, 132),
        outline=(61, 200, 132), width=S(1),
    )
    draw.text(
        (S(confirm_rect.centerx), S(confirm_rect.centery)), "Conferma (Invio)",
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
    number_keys = [getattr(pygame, f"K_{i + 1}") for i in range(min(9, n))]

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
        tile_h = _waypoint_tile_height(descriptions, width)
        rects = _compute_tile_rects(
            n, width, height, cols=_WAYPOINT_COLS, tile_h=tile_h, gap=18,
        )

        confirm_rect = pygame.Rect(width - 282, height - 82, 250, 54)
        cancel_rect = pygame.Rect(width - 552, height - 82, 250, 54)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return None
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return paths[selected]
                if event.key == pygame.K_SPACE:
                    selected = focus
                    continue
                cols = _WAYPOINT_COLS
                if event.key == pygame.K_LEFT:
                    focus = max(0, focus - 1)
                elif event.key == pygame.K_RIGHT:
                    focus = min(n - 1, focus + 1)
                elif event.key == pygame.K_UP:
                    focus = max(0, focus - cols)
                elif event.key == pygame.K_DOWN:
                    focus = min(n - 1, focus + cols)
                for i, k in enumerate(number_keys):
                    if event.key == k:
                        selected = i
                        focus = i
                        break
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
                for i, r in enumerate(rects):
                    if r.collidepoint(event.pos):
                        selected = i
                        focus = i
                        break

        mouse_pos = pygame.mouse.get_pos()
        cancel_hover = cancel_rect.collidepoint(mouse_pos)
        confirm_hover = confirm_rect.collidepoint(mouse_pos)
        enabled = [i == selected for i in range(n)]
        sig = (
            width, height, selected, focus,
            bool(focused), cancel_hover, confirm_hover,
        )
        if sig != cache_sig:
            cached_surf = _render_waypoint_screen(
                width, height, names, descriptions, colors, enabled,
                focus, focused, rects, confirm_rect, cancel_rect,
                cancel_hover, confirm_hover, models,
            )
            cache_sig = sig

        if not faded_in:
            fade_screen(screen, cached_surf, fade_in=True)
            faded_in = True

        crossfade.draw(screen, cached_surf)
        pygame.display.flip()
        clock.tick(30)
