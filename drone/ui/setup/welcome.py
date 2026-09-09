from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame
from PIL import Image, ImageDraw

from drone.hardware.joystick import (
    is_joystick_connected,
    joystick_actions,
    joystick_axis_actions,
)
from drone.ui import fonts
from drone.ui.appearance import ASSETS_DIR, LOGO_GLOB, PROJECT_TITLE
from drone.ui.setup.effects import (
    bg_gradient,
    CrossfadeBlitter,
    fade_screen,
    flash_button_press,
    focus_window,
    maximize_window,
)


SUBTITLE = "Sorveglianza del cantiere con drone"

PLATFORM_TITLE = "La piattaforma"

PLATFORM_PARAGRAPHS = (
    "Work Guardian sorveglia un cantiere dall'alto. Un drone Tello EDU percorre "
    "da solo una rotta di waypoint, si ferma nei punti di supervisione e da lì "
    "guarda il cantiere con la vista artificiale.",
    "Si localizza dai marker AprilTag posati sul cantiere, quindi sa dove si "
    "trova senza GPS, anche al chiuso. Il pilota sei sempre tu: il controller "
    "riprende il comando in qualunque momento.",
    "Nella schermata successiva scegli lo scenario di verifica. Da lì vengono la "
    "rotta, i controlli che il drone eseguirà durante le soste e i modelli di "
    "riconoscimento, che si caricano da soli.",
)

NOTES = (
    (
        "SICUREZZA AUTOMATICA",
        "Sotto il 30% di batteria il drone rientra da solo alla home; "
        "sotto il 20% atterra dov'è.",
    ),
    (
        "DATI DEL VOLO",
        "Si salvano solo quando la missione è completata. In caso di atterraggio manuale, "
        "la sessione si chiude senza file.",
    ),
)

COMMANDS_TITLE = "Comandi del controller"
AXES_TITLE = "STICK"
START_LABEL = "Inizia (Invio)"
EXIT_LABEL = "Esci (Esc)"

JOYSTICK_ON = "Controller collegato"
JOYSTICK_OFF = "Controller assente"

NOT_FOCUSED_NOTE = "La finestra non è attiva, clicca per usarla"


_SUPERSAMPLE = 2


def _scale(value: float) -> int:
    return int(round(value * _SUPERSAMPLE))


_CARD_BG = (24, 27, 35)
_CARD_BORDER = (58, 63, 78)
_TEXT = (231, 234, 241)
_MUTED = (150, 157, 172)
_SOFT = (196, 202, 214)
_GREEN = (61, 200, 132)
_AMBER = (224, 154, 16)

_NOTE_BG = (34, 28, 18)
_NOTE_BORDER = (96, 74, 30)

_LOGO_CACHE: dict[int, "Image.Image"] = {}


def _logo_file() -> Optional[Path]:
    try:
        for path in sorted(ASSETS_DIR.glob(LOGO_GLOB)):
            if path.is_file():
                return path
    except OSError:
        pass
    return None


def _logo_image(diameter: int) -> Optional["Image.Image"]:
    cached = _LOGO_CACHE.get(diameter)
    if cached is not None:
        return cached
    path = _logo_file()
    if path is None:
        return None
    try:
        logo = Image.open(path).convert("RGB")
    except OSError:
        return None
    lato = min(logo.size)
    left = (logo.width - lato) // 2
    top = (logo.height - lato) // 2
    logo = logo.crop((left, top, left + lato, top + lato))
    logo = logo.resize((diameter, diameter), Image.LANCZOS).convert("RGBA")
    maschera = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(maschera).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    logo.putalpha(maschera.resize((diameter, diameter), Image.LANCZOS))
    _LOGO_CACHE.clear()
    _LOGO_CACHE[diameter] = logo
    return logo


def _draw_logo(img, cx: int, cy: int, radius: int) -> None:
    logo = _logo_image(radius * 2)
    if logo is not None:
        img.alpha_composite(logo, (cx - radius, cy - radius))
        return
    font = fonts.sans_bold(_scale(46))
    ImageDraw.Draw(img).text((cx, cy), PROJECT_TITLE, font=font, fill=_TEXT, anchor="mm")


def _wrap(text: str, font, max_width: int) -> list[str]:
    righe: list[str] = []
    riga = ""
    for parola in text.split():
        prova = f"{riga} {parola}".strip()
        if font.getlength(prova) <= max_width or not riga:
            riga = prova
        else:
            righe.append(riga)
            riga = parola
    if riga:
        righe.append(riga)
    return righe


def _draw_card(draw, box, title, font_title) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=_scale(14),
        fill=(*_CARD_BG, 235), outline=_CARD_BORDER, width=_scale(1),
    )
    draw.text((x0 + _scale(26), y0 + _scale(26)), title, font=font_title, fill=_TEXT, anchor="lt")
    draw.line(
        (x0 + _scale(26), y0 + _scale(62), x1 - _scale(26), y0 + _scale(62)),
        fill=(46, 50, 62), width=_scale(1),
    )


def _draw_key(draw, x: int, cy: int, label: str, font) -> int:
    h = _scale(34)
    w = max(int(font.getlength(label)) + _scale(20), h)
    draw.rounded_rectangle(
        (x, cy - h // 2, x + w, cy + h // 2), radius=_scale(8),
        fill=(40, 45, 57), outline=(78, 85, 103), width=_scale(1),
    )
    draw.line(
        (x + _scale(5), cy + h // 2 - _scale(2), x + w - _scale(5), cy + h // 2 - _scale(2)),
        fill=(78, 85, 103), width=_scale(2),
    )
    draw.text((x + w // 2, cy), label, font=font, fill=_TEXT, anchor="mm")
    return w


def _draw_notes(draw, x0: int, x1: int, bottom: int, font_label, font_text) -> int:
    y1 = bottom - _scale(26)
    for title, text in reversed(NOTES):
        righe = _wrap(text, font_text, x1 - x0 - _scale(36))
        h = _scale(46) + _scale(26) * len(righe)
        y0 = y1 - h
        draw.rounded_rectangle(
            (x0, y0, x1, y1), radius=_scale(10),
            fill=_NOTE_BG, outline=_NOTE_BORDER, width=_scale(1),
        )
        draw.text((x0 + _scale(18), y0 + _scale(24)), title,
                  font=font_label, fill=_AMBER, anchor="lm")
        y = y0 + _scale(52)
        for riga in righe:
            draw.text((x0 + _scale(18), y), riga, font=font_text, fill=_SOFT, anchor="lm")
            y += _scale(26)
        y1 = y0 - _scale(14)
    return y1


def _draw_platform_card(draw, box, fonts_map) -> None:
    x0, y0, x1, y1 = box
    _draw_card(draw, box, PLATFORM_TITLE, fonts_map["card"])
    limite = _draw_notes(
        draw, x0 + _scale(26), x1 - _scale(26), y1,
        fonts_map["note_label"], fonts_map["note_text"],
    )
    y = y0 + _scale(96)
    max_w = x1 - x0 - _scale(68)
    for paragrafo in PLATFORM_PARAGRAPHS:
        righe = _wrap(paragrafo, fonts_map["body"], max_w)
        if y + _scale(31) * len(righe) > limite:
            break
        for riga in righe:
            draw.text((x0 + _scale(34), y), riga, font=fonts_map["body"], fill=_SOFT, anchor="lm")
            y += _scale(31)
        y += _scale(20)


def _draw_commands_card(draw, box, fonts_map) -> None:
    x0, y0, x1, _y1 = box
    _draw_card(draw, box, COMMANDS_TITLE, fonts_map["card"])

    azioni = joystick_actions()
    assi = joystick_axis_actions()
    colonna = x0 + _scale(26)
    larghezza_etichette = max(
        max(int(fonts_map["key"].getlength(tasto)) + _scale(20) for tasto, _ in azioni),
        max(int(fonts_map["action"].getlength(asse)) for asse, _ in assi),
    )
    colonna_azione = colonna + larghezza_etichette + _scale(28)

    y = y0 + _scale(84)
    for tasto, azione in azioni:
        _draw_key(draw, colonna, y, tasto, fonts_map["key"])
        draw.text((colonna_azione, y), azione, font=fonts_map["action"],
                  fill=_SOFT, anchor="lm")
        y += _scale(40)

    y += _scale(4)
    draw.line((colonna, y, x1 - _scale(26), y), fill=(46, 50, 62), width=_scale(1))
    y += _scale(22)
    draw.text((colonna, y), AXES_TITLE, font=fonts_map["section"], fill=_MUTED, anchor="lm")
    y += _scale(26)
    for asse, azione in assi:
        draw.text((colonna, y), asse, font=fonts_map["action"], fill=_TEXT, anchor="lm")
        draw.text((colonna_azione, y), azione, font=fonts_map["action"],
                  fill=_SOFT, anchor="lm")
        y += _scale(29)


def _draw_joystick_chip(draw, x: int, cy: int, connected: bool, font) -> None:
    testo = JOYSTICK_ON if connected else JOYSTICK_OFF
    colore = _GREEN if connected else _AMBER
    w = int(font.getlength(testo)) + _scale(58)
    draw.rounded_rectangle(
        (x, cy - _scale(19), x + w, cy + _scale(19)), radius=_scale(19),
        fill=(*_CARD_BG, 235), outline=_CARD_BORDER, width=_scale(1),
    )
    r = _scale(6)
    draw.ellipse((x + _scale(20) - r, cy - r, x + _scale(20) + r, cy + r), fill=colore)
    draw.text((x + _scale(38), cy), testo, font=font, fill=_SOFT, anchor="lm")


def _draw_buttons(draw, start_rect, exit_rect, start_hover, exit_hover, font) -> None:
    ss = _SUPERSAMPLE
    draw.rounded_rectangle(
        [exit_rect.x * ss, exit_rect.y * ss, exit_rect.right * ss, exit_rect.bottom * ss],
        radius=_scale(10),
        fill=(30, 34, 42) if exit_hover else (22, 25, 32),
        outline=(70, 76, 90), width=_scale(1),
    )
    draw.text(
        ((exit_rect.x + exit_rect.width / 2) * ss, (exit_rect.y + exit_rect.height / 2) * ss),
        EXIT_LABEL, font=font, fill=(205, 209, 218), anchor="mm",
    )
    draw.rounded_rectangle(
        [start_rect.x * ss, start_rect.y * ss, start_rect.right * ss, start_rect.bottom * ss],
        radius=_scale(10),
        fill=(80, 210, 130) if start_hover else (61, 200, 132),
        outline=(61, 200, 132), width=_scale(1),
    )
    draw.text(
        ((start_rect.x + start_rect.width / 2) * ss, (start_rect.y + start_rect.height / 2) * ss),
        START_LABEL, font=font, fill=(8, 19, 12), anchor="mm",
    )


def _render_welcome_screen(width, height, *, connected, focused, start_rect, exit_rect,
                           start_hover, exit_hover):
    S = _scale
    W, H = width * _SUPERSAMPLE, height * _SUPERSAMPLE
    img = bg_gradient(W, H).convert("RGBA")
    draw = ImageDraw.Draw(img)

    fonts_map = {
        "card": fonts.sans_bold(S(25)),
        "body": fonts.sans(S(21)),
        "key": fonts.sans_bold(S(18)),
        "action": fonts.sans(S(19)),
        "section": fonts.sans_bold(S(17)),
        "note_label": fonts.sans_bold(S(17)),
        "note_text": fonts.sans(S(19)),
        "chip": fonts.sans_bold(S(19)),
        "button": fonts.sans_bold(S(23)),
        "subtitle": fonts.sans(S(23)),
    }

    margine = S(max(48, int(width * 0.045)))
    raggio = S(120)
    logo_cy = S(24) + raggio
    _draw_logo(img, W // 2, logo_cy, raggio)
    sotto_logo = logo_cy + raggio + S(22)
    draw.text((W // 2, sotto_logo), SUBTITLE, font=fonts_map["subtitle"],
              fill=_SOFT, anchor="mm")

    top = sotto_logo + S(52)
    bottom = H - S(96)
    gap = S(26)
    larghezza = (W - 2 * margine - gap) // 2

    _draw_platform_card(draw, (margine, top, margine + larghezza, bottom), fonts_map)
    _draw_commands_card(
        draw, (margine + larghezza + gap, top, W - margine, bottom), fonts_map,
    )

    draw.line((margine, H - S(74), W - margine, H - S(74)), fill=(38, 42, 52), width=S(1))
    _draw_joystick_chip(draw, margine, H - S(40), connected, fonts_map["chip"])
    if not focused:
        draw.text(
            (W // 2, H - S(40)), NOT_FOCUSED_NOTE, font=fonts_map["chip"],
            fill=(212, 156, 66), anchor="mm",
        )
    _draw_buttons(draw, start_rect, exit_rect, start_hover, exit_hover, fonts_map["button"])

    final = img.convert("RGB").resize((width, height), Image.LANCZOS)
    return pygame.image.frombytes(final.tobytes(), final.size, "RGB").convert()


def show_welcome_screen(screen) -> bool:
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
        connected = is_joystick_connected()

        start_rect = pygame.Rect(width - 282, height - 82, 250, 54)
        exit_rect = pygame.Rect(width - 552, height - 82, 250, 54)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                continue
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    return True
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if start_rect.collidepoint(event.pos):
                    flash_button_press(screen, cached_surf, start_rect)
                    return True
                if exit_rect.collidepoint(event.pos):
                    flash_button_press(screen, cached_surf, exit_rect)
                    return False

        mouse_pos = pygame.mouse.get_pos()
        start_hover = start_rect.collidepoint(mouse_pos)
        exit_hover = exit_rect.collidepoint(mouse_pos)
        sig = (width, height, connected, bool(focused), start_hover, exit_hover)
        if sig != cache_sig:
            cached_surf = _render_welcome_screen(
                width, height, connected=connected, focused=focused,
                start_rect=start_rect, exit_rect=exit_rect,
                start_hover=start_hover, exit_hover=exit_hover,
            )
            cache_sig = sig

        if not faded_in:
            fade_screen(screen, cached_surf, fade_in=True)
            faded_in = True

        crossfade.draw(screen, cached_surf)
        pygame.display.flip()
        clock.tick(30)
