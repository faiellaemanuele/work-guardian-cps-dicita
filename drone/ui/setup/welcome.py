from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame
from PIL import Image, ImageDraw

from drone.config import APP_CONFIG
from drone.hardware.joystick import (
    joystick_action_groups,
    joystick_axis_details,
    read_setup_action,
)
from drone.ui import fonts
from drone.ui.appearance import ASSETS_DIR, LOGO_GLOB, PROJECT_TITLE
from drone.ui.setup.effects import (
    CrossfadeBlitter,
    fade_screen,
    flash_button_press,
    focus_window,
    maximize_window,
)


SUBTITLE = "Sorveglianza del cantiere con drone"

PLATFORM_TITLE = "La piattaforma"

PLATFORM_PARAGRAPHS = (
    "Work Guardian sorveglia un cantiere dall'alto. Un drone Tello EDU percorre da solo "
    "una rotta di waypoint e si ferma nei punti di supervisione, dove guarda il cantiere "
    "con la vista artificiale e scrive nel log ciò che non va.",
    "Si localizza dai marker AprilTag posati sul cantiere, quindi sa dove si trova senza "
    "GPS, anche al chiuso. Il pilota sei sempre tu: il controller riprende il comando in "
    "qualunque momento.",
    "Nella schermata successiva scegli lo scenario. Da lì vengono la rotta, i controlli "
    "che il drone esegue durante le soste e i modelli di riconoscimento, che si caricano "
    "da soli.",
)

NOTES = (
    (
        "SICUREZZA AUTOMATICA",
        "Sotto il 30% di batteria rientra alla home, sotto il 20% atterra dov'è.",
    ),
    (
        "DATI DEL VOLO",
        "Si salvano solo a missione completata: un atterraggio manuale non lascia file.",
    ),
)

COMMANDS_TITLE = "Comandi del controller"
AXES_TITLE = "STICK"

START_TEXT = "Inizia"
EXIT_TEXT = "Esci"


def start_label() -> str:
    return f"{START_TEXT} ({APP_CONFIG.joystick.label_setup_confirm})"


def exit_label() -> str:
    return f"{EXIT_TEXT} ({APP_CONFIG.joystick.label_setup_cancel})"


NOT_FOCUSED_NOTE = "La finestra non è attiva, clicca per usarla"


_SUPERSAMPLE = 2

_REFERENCE_WIDTH = 1920
_REFERENCE_HEIGHT = 1080

_LAYOUT_SCALE = 1.0


def _scale(value: float) -> int:
    return int(round(value * _SUPERSAMPLE * _LAYOUT_SCALE))


def _base_layout_scale(width: int, height: int) -> float:
    return min(
        1.25,
        max(0.55, min(width / _REFERENCE_WIDTH, height / _REFERENCE_HEIGHT)),
    )


_BG = (255, 255, 255)
_BG_WASH = (242, 244, 249)
_CARD_BG = (13, 15, 20)
_CARD_BORDER = (0, 0, 0)
_TEXT = (238, 240, 245)
_MUTED = (138, 146, 162)
_SOFT = (198, 204, 216)
_AMBER = (232, 165, 32)
_INK = (18, 21, 28)
_INK_SOFT = (92, 100, 116)

_NOTE_BG = (30, 25, 14)
_NOTE_BORDER = (104, 80, 32)

_GLYPH_BG = (26, 30, 39)
_GLYPH_BORDER = (66, 72, 88)
_SHOULDER = (206, 212, 224)

_GLYPH_COLORS = {
    "Croce": ("cross", (124, 178, 232)),
    "Cerchio": ("circle", (232, 106, 118)),
    "Quadrato": ("square", (226, 128, 206)),
    "Triangolo": ("triangle", (108, 214, 158)),
}

_BANNER_WIDTH = 540

_BANNER_CACHE: dict[int, "Image.Image"] = {}


def _logo_file() -> Optional[Path]:
    try:
        for path in sorted(ASSETS_DIR.glob(LOGO_GLOB)):
            if path.is_file():
                return path
    except OSError:
        pass
    return None


def _logo_image(width: int) -> Optional["Image.Image"]:
    cached = _BANNER_CACHE.get(width)
    if cached is not None:
        return cached

    path = _logo_file()
    if path is None:
        return None

    try:
        banner = Image.open(path).convert("RGB")
    except OSError:
        return None

    altezza = max(1, int(round(width * banner.height / banner.width)))
    banner = banner.resize((width, altezza), Image.LANCZOS)

    _BANNER_CACHE.clear()
    _BANNER_CACHE[width] = banner
    return banner


def _banner_height(width: int) -> int:
    banner = _logo_image(width)
    return banner.height if banner is not None else _scale(96)


def _draw_logo(img, cx: int, top: int, width: int) -> int:
    banner = _logo_image(width)
    if banner is not None:
        img.paste(banner, (cx - width // 2, top))
        return top + banner.height
    font = fonts.sans_bold(_scale(46))
    altezza = _scale(96)
    ImageDraw.Draw(img).text(
        (cx, top + altezza // 2), PROJECT_TITLE, font=font, fill=_INK, anchor="mm",
    )
    return top + altezza


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


def _background(width: int, height: int) -> "Image.Image":
    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)
    fascia = _scale(260)
    for i in range(fascia):
        f = i / fascia
        colore = tuple(int(_BG_WASH[c] * (1.0 - f) + _BG[c] * f) for c in range(3))
        draw.line((0, i, width, i), fill=colore)
    return img.convert("RGBA")


def _draw_card(img, draw, box, title, font_title) -> None:
    x0, y0, x1, y1 = box
    ombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ombra).rounded_rectangle(
        (x0 + _scale(3), y0 + _scale(7), x1 + _scale(3), y1 + _scale(7)),
        radius=_scale(16), fill=(15, 20, 35, 30),
    )
    img.alpha_composite(ombra)
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=_scale(16),
        fill=_CARD_BG, outline=_CARD_BORDER, width=_scale(1),
    )
    draw.text((x0 + _scale(30), y0 + _scale(26)), title, font=font_title, fill=_TEXT, anchor="lt")
    draw.line(
        (x0 + _scale(30), y0 + _scale(68), x1 - _scale(30), y0 + _scale(68)),
        fill=(48, 53, 66), width=_scale(1),
    )


def _draw_glyph(draw, kind, color, cx: int, cy: int, r: int) -> None:
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=_GLYPH_BG, outline=_GLYPH_BORDER, width=_scale(1),
    )
    k = r * 0.46
    if kind == "cross":
        draw.line((cx - k, cy - k, cx + k, cy + k), fill=color, width=_scale(3))
        draw.line((cx - k, cy + k, cx + k, cy - k), fill=color, width=_scale(3))
    elif kind == "circle":
        draw.ellipse((cx - k, cy - k, cx + k, cy + k), outline=color, width=_scale(3))
    elif kind == "square":
        draw.rectangle((cx - k, cy - k, cx + k, cy + k), outline=color, width=_scale(3))
    else:
        draw.polygon(
            [
                (cx, cy - k * 1.18),
                (cx + k * 1.08, cy + k * 0.82),
                (cx - k * 1.08, cy + k * 0.82),
            ],
            outline=color, width=_scale(3),
        )


def _draw_key(draw, x: int, cy: int, label: str, font, width: int) -> None:
    h = _scale(36)
    draw.rounded_rectangle(
        (x, cy - h // 2, x + width, cy + h // 2), radius=_scale(9),
        fill=_GLYPH_BG, outline=(80, 87, 105), width=_scale(1),
    )
    draw.line(
        (x + _scale(6), cy + h // 2 - _scale(3), x + width - _scale(6), cy + h // 2 - _scale(3)),
        fill=(80, 87, 105), width=_scale(2),
    )
    draw.text((x + width // 2, cy), label, font=font, fill=_SHOULDER, anchor="mm")


def _draw_stick(draw, verso: str, cx: int, cy: int, r: int) -> None:
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=_GLYPH_BG, outline=(74, 81, 98), width=_scale(1),
    )
    draw.ellipse(
        (cx - r * 0.38, cy - r * 0.38, cx + r * 0.38, cy + r * 0.38), fill=(104, 112, 130),
    )
    a = r * 0.80
    punta = (182, 190, 206)
    if verso == "orizzontale":
        draw.line((cx - a, cy, cx + a, cy), fill=punta, width=_scale(2))
        for sx in (-1, 1):
            draw.polygon(
                [
                    (cx + sx * a, cy),
                    (cx + sx * (a - _scale(7)), cy - _scale(5)),
                    (cx + sx * (a - _scale(7)), cy + _scale(5)),
                ],
                fill=punta,
            )
    else:
        draw.line((cx, cy - a, cx, cy + a), fill=punta, width=_scale(2))
        for sy in (-1, 1):
            draw.polygon(
                [
                    (cx, cy + sy * a),
                    (cx - _scale(5), cy + sy * (a - _scale(7))),
                    (cx + _scale(5), cy + sy * (a - _scale(7))),
                ],
                fill=punta,
            )


def _draw_notes(draw, x0: int, x1: int, bottom: int, font_label, font_text) -> int:
    y1 = bottom - _scale(26)
    for title, text in reversed(NOTES):
        y0 = y1 - _scale(70)
        draw.rounded_rectangle(
            (x0, y0, x1, y1), radius=_scale(12),
            fill=_NOTE_BG, outline=_NOTE_BORDER, width=_scale(1),
        )
        draw.text((x0 + _scale(20), y0 + _scale(25)), title,
                  font=font_label, fill=_AMBER, anchor="lm")
        draw.text((x0 + _scale(20), y0 + _scale(53)), text,
                  font=font_text, fill=_SOFT, anchor="lm")
        y1 = y0 - _scale(14)
    return y1


def _notes_block_height() -> int:
    return _scale(26) + len(NOTES) * _scale(70) + (len(NOTES) - 1) * _scale(14)


def _platform_height(larghezza: int, fonts_map) -> int:
    max_w = larghezza - _scale(74)
    paragrafi = [_wrap(testo, fonts_map["body"], max_w) for testo in PLATFORM_PARAGRAPHS]
    occupato = sum(_scale(34) * len(righe) for righe in paragrafi)
    return (
        _scale(108) + occupato + len(paragrafi) * _scale(18) + _notes_block_height()
    )


def _draw_platform_card(img, draw, box, fonts_map) -> None:
    x0, y0, x1, y1 = box
    _draw_card(img, draw, box, PLATFORM_TITLE, fonts_map["card"])

    limite = _draw_notes(
        draw, x0 + _scale(30), x1 - _scale(30), y1,
        fonts_map["note_label"], fonts_map["note_text"],
    )

    max_w = x1 - x0 - _scale(74)
    paragrafi = [_wrap(testo, fonts_map["body"], max_w) for testo in PLATFORM_PARAGRAPHS]
    altezza_riga = _scale(34)
    occupato = sum(altezza_riga * len(righe) for righe in paragrafi)
    y = y0 + _scale(108)
    stacco = max(_scale(18), (limite - y - occupato) // max(1, len(paragrafi)))

    for righe in paragrafi:
        for riga in righe:
            draw.text((x0 + _scale(37), y), riga, font=fonts_map["body"], fill=_SOFT, anchor="lm")
            y += altezza_riga
        y += stacco


def _command_columns(x0: int, fonts_map, gruppi, assi):
    raggio = _scale(20)
    larghezza_tasto = max(
        [
            int(fonts_map["key"].getlength(tasto)) + _scale(24)
            for _sezione, righe in gruppi
            for tasto, _azione in righe
            if tasto not in _GLYPH_COLORS
        ]
        or [raggio * 2]
    )
    colonna_nome = x0 + max(raggio * 2, larghezza_tasto) + _scale(22)
    larghezza_nome = max(
        [
            int(fonts_map["name"].getlength(tasto))
            for _sezione, righe in gruppi
            for tasto, _azione in righe
            if tasto in _GLYPH_COLORS
        ]
        + [int(fonts_map["name"].getlength(verso)) for _lato, verso, _azione in assi]
    )
    return raggio, larghezza_tasto, colonna_nome, colonna_nome + larghezza_nome + _scale(24)


def _commands_height(larghezza: int, fonts_map) -> int:
    gruppi = joystick_action_groups()
    assi = joystick_axis_details()
    _raggio, _tasto_w, _colonna_nome, colonna_azione = _command_columns(
        _scale(30), fonts_map, gruppi, assi,
    )
    azione_max_w = larghezza - _scale(30) - colonna_azione

    altezza = _scale(86)
    for _sezione, righe in gruppi:
        altezza += _scale(26)
        for _tasto, azione in righe:
            testo = _wrap(azione, fonts_map["action"], azione_max_w)
            altezza += _scale(38) + _scale(26) * (len(testo) - 1)
        altezza += _scale(6)
    altezza += _scale(2) + _scale(22) + _scale(28)
    altezza += _scale(38) * len(assi)
    return altezza + _scale(20)


def _draw_commands_card(img, draw, box, fonts_map) -> None:
    x0, y0, x1, _y1 = box
    _draw_card(img, draw, box, COMMANDS_TITLE, fonts_map["card"])

    gruppi = joystick_action_groups()
    assi = joystick_axis_details()
    colonna = x0 + _scale(30)
    raggio, larghezza_tasto, colonna_nome, colonna_azione = _command_columns(
        colonna, fonts_map, gruppi, assi,
    )
    azione_max_w = x1 - _scale(30) - colonna_azione
    altezza_azione = _scale(26)

    y = y0 + _scale(86)
    for sezione, righe in gruppi:
        draw.text((colonna, y), sezione, font=fonts_map["section"], fill=_MUTED, anchor="lm")
        y += _scale(26)
        for tasto, azione in righe:
            testo = _wrap(azione, fonts_map["action"], azione_max_w)
            extra = altezza_azione * (len(testo) - 1)
            y += extra // 2
            forma = _GLYPH_COLORS.get(tasto)
            if forma is None:
                _draw_key(draw, colonna, y, tasto, fonts_map["key"], larghezza_tasto)
            else:
                _draw_glyph(draw, forma[0], forma[1], colonna + raggio, y, raggio)
                draw.text((colonna_nome, y), tasto, font=fonts_map["name"],
                          fill=_TEXT, anchor="lm")
            ay = y - extra // 2
            for riga in testo:
                draw.text((colonna_azione, ay), riga, font=fonts_map["action"],
                          fill=_SOFT, anchor="lm")
                ay += altezza_azione
            y += _scale(38) + extra - extra // 2
        y += _scale(6)

    y += _scale(2)
    draw.line((colonna, y, x1 - _scale(30), y), fill=(48, 53, 66), width=_scale(1))
    y += _scale(22)
    draw.text((colonna, y), AXES_TITLE, font=fonts_map["section"], fill=_MUTED, anchor="lm")
    y += _scale(28)
    for lato, verso, azione in assi:
        _draw_stick(draw, verso, colonna + raggio, y, raggio)
        draw.text((colonna_nome - _scale(16), y), lato, font=fonts_map["tiny"],
                  fill=_MUTED, anchor="rm")
        draw.text((colonna_nome, y), verso, font=fonts_map["name"], fill=_TEXT, anchor="lm")
        draw.text((colonna_azione, y), azione, font=fonts_map["action"], fill=_SOFT, anchor="lm")
        y += _scale(38)


def _draw_buttons(draw, start_rect, exit_rect, start_hover, exit_hover, font) -> None:
    SS = _SUPERSAMPLE
    draw.rounded_rectangle(
        [exit_rect.x * SS, exit_rect.y * SS, exit_rect.right * SS, exit_rect.bottom * SS],
        radius=_scale(10),
        fill=(240, 242, 246) if exit_hover else (255, 255, 255),
        outline=(24, 28, 36), width=_scale(2),
    )
    draw.text(
        ((exit_rect.x + exit_rect.width / 2) * SS, (exit_rect.y + exit_rect.height / 2) * SS),
        exit_label(), font=font, fill=_INK, anchor="mm",
    )
    draw.rounded_rectangle(
        [start_rect.x * SS, start_rect.y * SS, start_rect.right * SS, start_rect.bottom * SS],
        radius=_scale(10),
        fill=(34, 39, 50) if start_hover else _CARD_BG,
    )
    draw.text(
        ((start_rect.x + start_rect.width / 2) * SS, (start_rect.y + start_rect.height / 2) * SS),
        start_label(), font=font, fill=(255, 255, 255), anchor="mm",
    )


def _fonts_map():
    S = _scale
    return {
        "card": fonts.sans_bold(S(26)),
        "body": fonts.sans(S(20)),
        "key": fonts.sans_bold(S(18)),
        "name": fonts.sans_bold(S(19)),
        "action": fonts.sans(S(19)),
        "section": fonts.sans_bold(S(16)),
        "tiny": fonts.sans_bold(S(15)),
        "note_label": fonts.sans_bold(S(16)),
        "note_text": fonts.sans(S(18)),
        "chip": fonts.sans_bold(S(19)),
        "button": fonts.sans_bold(S(23)),
        "subtitle": fonts.sans(S(24)),
    }


def _geometry(width, height, fonts_map, buttons_top):
    W, H = width * _SUPERSAMPLE, height * _SUPERSAMPLE
    larghezza_banner = min(_scale(_BANNER_WIDTH), int(W * 0.34))
    alto_banner = _scale(22)
    fondo_banner = alto_banner + _banner_height(larghezza_banner)
    sotto_banner = fondo_banner + _scale(14)

    top = sotto_banner + sum(fonts_map["subtitle"].getmetrics()) + _scale(26)
    bottom = buttons_top * _SUPERSAMPLE - _scale(26)
    margine = _scale(48) + int((W - 2 * _scale(48)) * 0.008)
    gap = _scale(26)
    disponibile = W - 2 * margine - gap
    larghezza = int(disponibile * 0.56)

    return {
        "banner_width": larghezza_banner,
        "banner_top": alto_banner,
        "subtitle_y": sotto_banner,
        "top": top,
        "bottom": bottom,
        "margine": margine,
        "gap": gap,
        "sinistra": larghezza,
        "destra": disponibile - larghezza,
    }


def _layout_fits(geometria, fonts_map) -> bool:
    altezza = geometria["bottom"] - geometria["top"]
    if altezza <= 0:
        return False
    return (
        _platform_height(geometria["sinistra"], fonts_map) <= altezza
        and _commands_height(geometria["destra"], fonts_map) <= altezza
    )


def _fit_layout(width: int, height: int, buttons_top: int):
    global _LAYOUT_SCALE

    base = _base_layout_scale(width, height)
    fonts_map = None
    geometria = None
    for tentativo in range(6):
        _LAYOUT_SCALE = base * (0.94 ** tentativo)
        fonts_map = _fonts_map()
        geometria = _geometry(width, height, fonts_map, buttons_top)
        if _layout_fits(geometria, fonts_map):
            break
    return fonts_map, geometria


def button_rects(width: int, height: int):
    k = _base_layout_scale(width, height)
    larghezza = int(round(250 * k))
    altezza = int(round(54 * k))
    margine = int(round(32 * k))
    stacco = int(round(20 * k))
    y = height - altezza - int(round(22 * k))
    start_rect = pygame.Rect(width - margine - larghezza, y, larghezza, altezza)
    exit_rect = pygame.Rect(start_rect.x - stacco - larghezza, y, larghezza, altezza)
    return start_rect, exit_rect


def _render_welcome_screen(width, height, *, focused, start_rect, exit_rect,
                           start_hover, exit_hover):
    S = _scale
    W, H = width * _SUPERSAMPLE, height * _SUPERSAMPLE

    fonts_map, geometria = _fit_layout(width, height, exit_rect.y)

    img = _background(W, H)
    fondo_banner = _draw_logo(
        img, W // 2, geometria["banner_top"], geometria["banner_width"],
    )
    draw = ImageDraw.Draw(img)

    draw.text((W // 2, geometria["subtitle_y"]), SUBTITLE, font=fonts_map["subtitle"],
              fill=_INK_SOFT, anchor="mt")

    margine = geometria["margine"]
    top = geometria["top"]
    bottom = geometria["bottom"]
    larghezza = geometria["sinistra"]

    _draw_platform_card(img, draw, (margine, top, margine + larghezza, bottom), fonts_map)
    _draw_commands_card(
        img, draw,
        (margine + larghezza + geometria["gap"], top, W - margine, bottom), fonts_map,
    )

    linea = int((exit_rect.y - 12) * _SUPERSAMPLE)
    draw.line((margine, linea, W - margine, linea), fill=(223, 227, 235), width=S(1))
    if not focused:
        draw.text(
            (margine, int((exit_rect.y + exit_rect.height / 2) * _SUPERSAMPLE)),
            NOT_FOCUSED_NOTE, font=fonts_map["chip"], fill=(176, 122, 22), anchor="lm",
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

        start_rect, exit_rect = button_rects(width, height)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                continue
            comando = read_setup_action(event)
            if comando in ("confirm", "select"):
                return True
            if comando == "cancel":
                return False
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
        sig = (width, height, bool(focused), start_hover, exit_hover)
        if sig != cache_sig:
            cached_surf = _render_welcome_screen(
                width, height, focused=focused,
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
