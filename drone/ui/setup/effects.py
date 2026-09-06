from __future__ import annotations

import time

import numpy as np
import pygame
from PIL import Image, ImageDraw


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


_BG_GRADIENT_CACHE: dict = {}


def bg_gradient(w: int, h: int) -> "Image.Image":
    key = (w, h)
    img = _BG_GRADIENT_CACHE.get(key)
    if img is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = w * 0.5, -h * 0.28
        rx, ry = w * 0.62, h * 1.0
        d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
        d = np.clip(d, 0.0, 1.0)[..., None]
        inner = np.array([26, 31, 43], np.float32)
        outer = np.array([9, 10, 13], np.float32)
        arr = inner * (1.0 - d) + outer * d
        img = Image.fromarray(arr.astype("uint8"), "RGB")
        _BG_GRADIENT_CACHE[key] = img
    return img.copy()


def gradient_text(text, font, c_left, c_right) -> "Image.Image":
    w = max(1, int(font.getlength(text)) + 4)
    asc, desc = font.getmetrics()
    h = asc + desc
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((2, 0), text, fill=255, font=font)
    tx = np.linspace(0.0, 1.0, w, dtype=np.float32)[:, None]
    cl = np.array(c_left, np.float32)
    cr = np.array(c_right, np.float32)
    row = cl * (1.0 - tx) + cr * tx
    grad = np.repeat(row[None, :, :], h, axis=0)
    out = Image.fromarray(grad.astype("uint8"), "RGB").convert("RGBA")
    out.putalpha(mask)
    return out


def corner_glow(w: int, h: int, color, radius: int) -> "Image.Image":
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    max_r = max(w, h) * 0.95
    d = np.sqrt(xx ** 2 + (yy / 1.1) ** 2) / max_r
    a = np.clip(1.0 - d, 0.0, 1.0) ** 1.2 * 60.0
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    a = a * (np.asarray(mask, np.float32) / 255.0)
    arr = np.zeros((h, w, 4), np.float32)
    arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3] = color[0], color[1], color[2], a
    return Image.fromarray(arr.astype("uint8"), "RGBA")


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
