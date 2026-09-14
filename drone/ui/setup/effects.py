from __future__ import annotations

import time

import numpy as np
import pygame
from PIL import Image, ImageDraw

from drone.ui.shapes import glow_box


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


def flash_button_press(screen, base_surface, rect,
                        duration_sec: float = 0.09) -> None:
    if base_surface is None:
        return
    pressed = base_surface.copy()
    veil = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    veil.fill((0, 0, 0, 80))
    pressed.blit(veil, rect.topleft)
    screen.blit(pressed, (0, 0))
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
YELLOW = (250, 222, 10)
FOOTER_RULE = (196, 206, 216)

_HOVER_BUTTON_FILL = (3, 20, 40)

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
