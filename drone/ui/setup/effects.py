from __future__ import annotations

import time

import numpy as np
import pygame
from PIL import Image, ImageDraw

from drone.ui import fonts
from drone.ui.shapes import glow_box, paint_supersampled


_SW_MAXIMIZE = 3
_SW_RESTORE = 9


def _show_pygame_window(show_command: int) -> None:
    try:
        info = pygame.display.get_wm_info()
    except Exception:
        return
    hwnd = info.get("window", 0) if isinstance(info, dict) else 0
    if not hwnd:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, show_command)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def focus_window() -> None:
    _show_pygame_window(_SW_RESTORE)


def maximize_window() -> None:
    _show_pygame_window(_SW_MAXIMIZE)


_SCREEN_FADE_SEC = 0.4


def fade_screen(screen, base_surface, *, fade_in: bool,
                        duration_sec: float = _SCREEN_FADE_SEC) -> None:
    if base_surface is None:
        return
    size = screen.get_size()
    if base_surface.get_size() != size:
        base_surface = pygame.transform.smoothscale(base_surface, size)
    veil = pygame.Surface(size)
    veil.fill((0, 0, 0))
    clock = pygame.time.Clock()
    fps = 60
    steps = max(1, int(round(duration_sec * fps)))
    for i in range(steps + 1):
        frac = i / steps
        alpha = (1.0 - frac) if fade_in else frac
        screen.blit(base_surface, (0, 0))
        veil.set_alpha(int(255 * alpha))
        screen.blit(veil, (0, 0))
        pygame.event.pump()
        pygame.display.flip()
        clock.tick(fps)


_STATE_CROSSFADE_SEC = 0.2


class CrossfadeBlitter:
    def __init__(self, duration_sec: float = _STATE_CROSSFADE_SEC):
        self._duration_sec = float(duration_sec)
        self._current = None
        self._previous = None
        self._started_at = 0.0

    def draw(self, screen, surface) -> None:
        if surface is not self._current:
            if self._current is not None and self._current.get_size() == surface.get_size():
                self._previous = self._current
                self._started_at = time.monotonic()
            else:
                self._previous = None
            self._current = surface

        if self._previous is not None:
            frac = (time.monotonic() - self._started_at) / self._duration_sec
            if frac >= 1.0:
                self._previous = None
            else:
                screen.blit(self._previous, (0, 0))
                surface.set_alpha(int(255 * frac))
                screen.blit(surface, (0, 0))
                surface.set_alpha(None)
                return
        screen.blit(surface, (0, 0))


_BUTTON_PRESS_SEC = 0.15


def flash_button_press(screen, pressed_surface,
                       duration_sec: float = _BUTTON_PRESS_SEC) -> None:
    if pressed_surface is None:
        return
    screen.blit(pressed_surface, (0, 0))
    pygame.display.flip()
    pygame.time.wait(int(duration_sec * 1000))


NAVY_CENTER = (6, 38, 68)
NAVY_EDGE = (2, 16, 32)
GRID_LINE = (6, 33, 58)
GRID_CROSS = (16, 68, 112)

CYAN_BRIGHT = (16, 226, 250)
CYAN_TEXT = (128, 232, 252)
CYAN_FILL = (3, 201, 255)
CYAN_INK = (4, 36, 60)
WHITE = (248, 251, 252)
LINE_DIM = (4, 68, 116)
FOOTER_RULE = (196, 206, 216)

CARD_FILL = (3, 31, 55)
CARD_FILL_ON = (4, 36, 62)
CARD_EDGE = (4, 108, 172)
CARD_EDGE_ON = (8, 214, 246)
CHIP_FILL = (3, 39, 69)
CHIP_FILL_ON = (3, 45, 75)
CHIP_EDGE = (8, 132, 196)
CHIP_EDGE_ON = (4, 236, 252)
ICON_CYAN = (80, 208, 252)
PAD_KEY_FILL = (6, 22, 44)
PAD_BUTTON_FILL = (4, 16, 40)

_HOVER_BUTTON_FILL = (3, 20, 40)
_ALERT_FILL = (4, 30, 54)
_ALERT_EDGE = (4, 112, 176)

_BACKGROUND_CACHE: dict = {}


def grid_background(w: int, h: int, step: int, arm: int, *,
                    line=GRID_LINE, cross=GRID_CROSS) -> "Image.Image":
    key = (w, h, step, arm, line, cross)
    img = _BACKGROUND_CACHE.get(key)
    if img is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d = np.sqrt(((xx - w * 0.5) / (w * 0.75)) ** 2 + ((yy - h * 0.35) / (h * 0.95)) ** 2)
        d = np.clip(d, 0.0, 1.0)[..., None]
        centro = np.array(NAVY_CENTER, np.float32)
        bordo = np.array(NAVY_EDGE, np.float32)
        arr = centro * (1.0 - d) + bordo * d
        img = Image.fromarray(arr.astype("uint8"), "RGB")
        if step > 0:
            draw = ImageDraw.Draw(img)
            for x in range(step // 2, w, step):
                draw.line((x, 0, x, h), fill=line)
            for y in range(step // 2, h, step):
                draw.line((0, y, w, y), fill=line)
            spessore = max(1, arm // 6)
            for x in range(step // 2, w, step):
                for y in range(step // 2, h, step):
                    draw.line((x - arm, y, x + arm, y), fill=cross, width=spessore)
                    draw.line((x, y - arm, x, y + arm), fill=cross, width=spessore)
        _BACKGROUND_CACHE.clear()
        _BACKGROUND_CACHE[key] = img
    return img.copy()


def draw_hover_button(img, box, label, font, *, unit: float, hover: bool = False) -> None:
    glow_box(
        img, box, radius=10 * unit, edge=CYAN_BRIGHT, width=(2.2 if hover else 1.8) * unit,
        fill=CYAN_FILL if hover else _HOVER_BUTTON_FILL,
        glow=7 * unit if hover else 0, glow_alpha=150 if hover else 0,
    )
    x0, y0, x1, y1 = box
    ImageDraw.Draw(img).text(
        ((x0 + x1) / 2, (y0 + y1) / 2), label, font=font,
        fill=CYAN_INK if hover else WHITE, anchor="mm",
    )


def _units(value: float, unit: float) -> int:
    return int(round(value * unit))


def draw_pad_button(draw, kind, cx, cy, r, unit) -> None:
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=PAD_BUTTON_FILL, outline=CYAN_BRIGHT, width=max(1, round(2.4 * unit)),
    )
    w = max(1, round(r * 0.13))
    k = r * 0.44
    if kind == "cross":
        q = k * 0.9
        draw.line((cx - q, cy - q, cx + q, cy + q), fill=CYAN_TEXT, width=w)
        draw.line((cx - q, cy + q, cx + q, cy - q), fill=CYAN_TEXT, width=w)
    elif kind == "circle":
        q = k * 0.92
        draw.ellipse((cx - q, cy - q, cx + q, cy + q), outline=CYAN_TEXT, width=w)
    elif kind == "square":
        q = k * 0.8
        draw.rectangle((cx - q, cy - q, cx + q, cy + q), outline=CYAN_TEXT, width=w)
    elif kind == "triangle":
        q = k * 1.06
        dy = q * 0.12
        draw.polygon(
            [
                (cx, cy - q + dy),
                (cx + q * 0.87, cy + q * 0.5 + dy),
                (cx - q * 0.87, cy + q * 0.5 + dy),
            ],
            outline=CYAN_TEXT, width=w,
        )


def draw_pad_arrow(draw, verso, cx, cy, r, unit) -> None:
    w = max(1, round(r * 0.13))
    lungo = r * 0.86
    testa = r * 0.34
    larga = r * 0.3
    orizzontale = verso == "orizzontale"
    if orizzontale:
        draw.line((cx - lungo + testa / 2, cy, cx + lungo - testa / 2, cy), fill=CYAN_TEXT, width=w)
    else:
        draw.line((cx, cy - lungo + testa / 2, cx, cy + lungo - testa / 2), fill=CYAN_TEXT, width=w)
    for segno in (-1, 1):
        if orizzontale:
            punta = cx + segno * lungo
            testa_xy = [(punta, cy), (punta - segno * testa, cy - larga),
                        (punta - segno * testa, cy + larga)]
        else:
            punta = cy + segno * lungo
            testa_xy = [(cx, punta), (cx - larga, punta - segno * testa),
                        (cx + larga, punta - segno * testa)]
        draw.polygon(testa_xy, fill=CYAN_TEXT)


def draw_pad_key(draw, cx, cy, w, h, unit) -> None:
    draw.rounded_rectangle(
        (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), radius=h / 2,
        fill=PAD_KEY_FILL, outline=CYAN_BRIGHT, width=max(1, round(2.4 * unit)),
    )


def draw_pad_dpad(draw, cx, cy, r, unit) -> None:
    draw.rounded_rectangle(
        (cx - r, cy - r, cx + r, cy + r), radius=7 * unit,
        fill=PAD_KEY_FILL, outline=CYAN_BRIGHT, width=max(1, round(1.6 * unit)),
    )
    braccio = r * 0.34
    lato = r * 0.2
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        px, py = cx + dx * braccio, cy + dy * braccio
        draw.rounded_rectangle(
            (px - lato, py - lato, px + lato, py + lato), radius=2 * unit, fill=WHITE,
        )
    centro = r * 0.13
    draw.rectangle((cx - centro, cy - centro, cx + centro, cy + centro), fill=WHITE)


def draw_joystick_hints(img, hints, *, font, start_x, cy, unit) -> None:
    r = _units(24, unit)
    x = start_x
    draw = ImageDraw.Draw(img)
    for indice, (kind, label) in enumerate(hints):
        if indice:
            x += _units(22, unit)
            draw.text((x, cy), "•", font=font, fill=WHITE, anchor="mm")
            x += _units(22, unit)
        cx = x + r
        reach = r + _units(3, unit)
        paint_supersampled(
            img, (cx - reach, cy - reach, cx + reach, cy + reach), (cx, cy),
            lambda d, ax, ay, s, kind=kind: (
                draw_pad_dpad(d, ax, ay, r * s, unit * s) if kind == "dpad"
                else draw_pad_button(d, kind, ax, ay, r * s, unit * s)
            ),
        )
        x += 2 * r + _units(18, unit)
        draw.text((x, cy), label, font=font, fill=WHITE, anchor="lm")
        x += int(font.getlength(label))


def draw_alert(draw, cx, cy, text, font, *, unit) -> None:
    h = _units(48, unit)
    padx = _units(24, unit)
    dot_d = _units(16, unit)
    gap = _units(14, unit)
    w = padx + dot_d + gap + int(font.getlength(text)) + padx
    x0 = cx - w // 2
    y0 = cy - h // 2
    draw.rounded_rectangle(
        [x0, y0, x0 + w, y0 + h], radius=_units(12, unit),
        fill=_ALERT_FILL, outline=_ALERT_EDGE, width=_units(1, unit),
    )
    dx = x0 + padx
    draw.ellipse([dx, cy - dot_d // 2, dx + dot_d, cy + dot_d // 2], fill=ICON_CYAN)
    draw.text((dx + dot_d + gap, cy), text, font=font, fill=WHITE, anchor="lm")


def footer_rule_y(button_top: int, *, supersample: int, unit: float) -> int:
    return int(round(button_top * supersample)) - _units(28, unit)


def draw_setup_footer(img, buttons, hints, *, supersample: int, unit: float) -> None:
    def px(value):
        return int(round(value * supersample))

    rects = [rect for rect, _label, _hover in buttons]
    sinistro = min(rects, key=lambda rect: rect.x)
    linea = footer_rule_y(sinistro.y, supersample=supersample, unit=unit)
    ImageDraw.Draw(img).line(
        [(px(sinistro.x), linea), (px(max(rect.right for rect in rects)), linea)],
        fill=FOOTER_RULE, width=max(1, round(1.3 * unit)),
    )
    if hints:
        draw_joystick_hints(
            img, hints, font=fonts.sans(_units(24, unit)),
            start_x=px(sinistro.right) + _units(50, unit), cy=px(sinistro.centery), unit=unit,
        )
    font = fonts.sans_bold(_units(25, unit))
    for rect, label, hover in buttons:
        draw_hover_button(
            img, (px(rect.x), px(rect.y), px(rect.right), px(rect.bottom)),
            label, font, unit=unit, hover=hover,
        )


def fit_text(text, font, max_w) -> str:
    if font.getlength(text) <= max_w:
        return text
    ell = "…"
    while text and font.getlength(text + ell) > max_w:
        text = text[:-1]
    return text.rstrip() + ell


def wrap_text(text, font, max_w, max_lines) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = word if not current else current + " " + word
        if font.getlength(candidate) <= max_w or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return lines
    head = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1:])
    head.append(fit_text(tail, font, max_w))
    return head
