from __future__ import annotations

from pathlib import Path
from typing import Optional

import pygame
from PIL import Image, ImageChops, ImageDraw

from drone.config import APP_CONFIG
from drone.hardware.joystick import (
    joystick_action_groups,
    joystick_axis_details,
    read_setup_action,
)
from drone.ui import fonts
from drone.ui.appearance import ASSETS_DIR, LOGO_GLOB, PROJECT_TITLE
from drone.ui.setup.effects import (
    CYAN_BRIGHT,
    CrossfadeBlitter,
    FOOTER_RULE,
    WHITE,
    YELLOW,
    draw_hover_button,
    fade_screen,
    flash_button_press,
    focus_window,
    grid_background,
    maximize_window,
)
from drone.ui.shapes import glow_box, paint_supersampled


PLATFORM_TITLE = "Cos'è WORK-GUARDIAN?"

PLATFORM_PARAGRAPHS = (
    "Work-Guardian è un progetto per la sicurezza nei cantieri edili, con particolare "
    "attenzione alle lavorazioni in quota. Integra un drone, un dispositivo indossabile per "
    "gli operatori e una stazione centrale, così da osservare sia l'ambiente di lavoro sia le "
    "condizioni dei lavoratori.",
    "Il flusso video acquisito dal drone aiuta a individuare protezioni mancanti e situazioni "
    "di pericolo. Il dispositivo indossabile rileva parametri fisiologici che possono "
    "segnalare una condizione anomala. La stazione centrale riunisce queste informazioni e "
    "comunica le criticità al supervisore e agli operatori interessati, offrendo un supporto "
    "per intervenire tempestivamente.",
)

NOTES = (
    (
        "SICUREZZA AUTOMATICA",
        "Quando la batteria è sotto al 30% il drone rientra e atterra automaticamente alla "
        "home. Quando la batteria è sotto al 20% il drone atterra nella posizione corrente.",
    ),
    (
        "DATI DEL VOLO",
        "I dati del volo vengono salvati solo quando la missione termina correttamente o "
        "quando viene premuto il tasto Options.",
    ),
)

COMMANDS_TITLE = "Comandi per il controllo del drone"

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

_FIT_ATTEMPTS = 10


def _scale(value: float) -> int:
    return int(round(value * _SUPERSAMPLE * _LAYOUT_SCALE))


def _unit() -> float:
    return _SUPERSAMPLE * _LAYOUT_SCALE


def _base_layout_scale(width: int, height: int) -> float:
    return min(
        1.25,
        max(0.55, min(width / _REFERENCE_WIDTH, height / _REFERENCE_HEIGHT)),
    )


_FRAME_OUTER = (4, 160, 172)
_FRAME_INNER = (4, 222, 230)

_CARD_BG = (3, 31, 55)
_CARD_EDGE = (4, 206, 216)
_UNDERLINE = (8, 244, 252)
_NOT_FOCUSED = (252, 190, 16)

_NOTE_BG = (3, 39, 69)
_NOTE_STYLES = (
    ("warn", YELLOW, (240, 210, 8)),
    ("info", CYAN_BRIGHT, (4, 196, 220)),
)
_WARN_INK = (10, 14, 18)

_PAD_FILL = (12, 14, 20)
_PAD_RIM = (112, 120, 136)
_PAD_INK = (236, 240, 246)

_GLYPH_COLORS = {
    "Croce": ("cross", (124, 178, 232)),
    "Cerchio": ("circle", (255, 102, 102)),
    "Quadrato": ("square", (244, 122, 220)),
    "Triangolo": ("triangle", (64, 226, 160)),
}

_LEFT_SHARE = 0.57

_TITLE_Y = 44
_TITLE_RULE_Y = 82

_BODY_TOP = 126
_BODY_STEP = 33
_PARAGRAPH_GAP = 14

_NOTE_INSET = 30
_NOTE_ICON_X = 50
_NOTE_RULE_X = 94
_NOTE_TEXT_X = 112
_NOTE_TITLE_Y = 30
_NOTE_TEXT_Y = 60
_NOTE_STEP = 28
_NOTE_BOTTOM = 30
_NOTE_GAP = 14

_ROWS_TOP = 128
_ROW_STEP = 46
_ACTION_STEP = 28
_GLYPH_GAP = 10
_GROUP_GAP = 26

_BANNER_SOURCE_SIZE = (1983, 797)

_BANNER_PIECES = (
    ((0, 275, 650, 575), 0.64, ("width", 0.166), 0.32, 0.35, False),
    ((668, 228, 1192, 610), 0.83, ("width", 0.302), 0.09, 0.2, False),
    ((935, 395, 1250, 650), 0.56, ("width", 0.571), 0.41, 0.3, False),
    ((0, 275, 650, 575), 0.70, ("width", 0.632), 0.26, 0.35, True),
    ((668, 228, 1192, 610), 0.60, ("width", 0.754), 0.20, 0.3, False),
    ((0, 275, 650, 575), 0.59, ("width", 0.798), 0.38, 0.35, False),
    ((1805, 310, 1983, 665), 0.75, ("right", 0.45), 0.20, 0.2, False),
    ((1255, 105, 1850, 665), 0.88, ("width", 0.45), 0.05, 0.0, False),
    ((55, 100, 1145, 212), 0.25, ("height", 0.12), 0.09, 0.0, False),
    ((75, 585, 735, 722), 0.28, ("height", 0.12), 0.62, 0.0, False),
)

_BANNER_CACHE: dict[tuple[int, int], "Image.Image"] = {}


def _logo_file() -> Optional[Path]:
    try:
        for path in sorted(ASSETS_DIR.glob(LOGO_GLOB)):
            if path.is_file():
                return path
    except OSError:
        pass
    return None


def _multiply_paste(band, piece, x: float, y: float) -> None:
    x, y = int(round(x)), int(round(y))
    sx0, sy0 = max(0, -x), max(0, -y)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(band.width, x + piece.width), min(band.height, y + piece.height)
    if x1 <= x0 or y1 <= y0:
        return
    ritaglio = piece.crop((sx0, sy0, sx0 + (x1 - x0), sy0 + (y1 - y0)))
    band.paste(ImageChops.multiply(band.crop((x0, y0, x1, y1)), ritaglio), (x0, y0))


def _banner_image(width: int, height: int) -> Optional["Image.Image"]:
    width, height = max(1, int(width)), max(1, int(height))
    cached = _BANNER_CACHE.get((width, height))
    if cached is not None:
        return cached

    path = _logo_file()
    if path is None:
        return None
    try:
        sorgente = Image.open(path).convert("RGB")
    except OSError:
        return None

    fx = sorgente.width / _BANNER_SOURCE_SIZE[0]
    fy = sorgente.height / _BANNER_SOURCE_SIZE[1]
    fascia = Image.new("RGB", (width, height), (255, 255, 255))
    for box, alto, (ancora, valore), y, sbiadito, specchio in _BANNER_PIECES:
        pezzo = sorgente.crop((
            round(box[0] * fx), round(box[1] * fy), round(box[2] * fx), round(box[3] * fy),
        ))
        h = max(1, round(height * alto))
        pezzo = pezzo.resize((max(1, round(pezzo.width * h / pezzo.height)), h), Image.LANCZOS)
        if specchio:
            pezzo = pezzo.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if sbiadito:
            pezzo = Image.blend(pezzo, Image.new("RGB", pezzo.size, (255, 255, 255)), sbiadito)
        if ancora == "width":
            x = valore * width
        elif ancora == "right":
            x = width - valore * height
        else:
            x = valore * height
        _multiply_paste(fascia, pezzo, x, y * height)

    _BANNER_CACHE.clear()
    _BANNER_CACHE[(width, height)] = fascia
    return fascia


def _draw_banner(img, box, fonts_map) -> None:
    x0, y0, x1, y1 = box
    u = _unit()
    glow_box(img, box, radius=3 * u, edge=_FRAME_OUTER, width=2 * u, glow=8 * u, glow_alpha=150)
    inset = int(round(6 * u))
    banner = _banner_image(x1 - x0 - 2 * inset, y1 - y0 - 2 * inset)
    draw = ImageDraw.Draw(img)
    if banner is not None:
        img.paste(banner, (x0 + inset, y0 + inset))
    else:
        draw.rectangle((x0 + inset, y0 + inset, x1 - inset, y1 - inset), fill=_CARD_BG)
        draw.text(
            ((x0 + x1) / 2, (y0 + y1) / 2), PROJECT_TITLE,
            font=fonts_map["fallback_title"], fill=WHITE, anchor="mm",
        )
    bordo = 4 * u
    draw.rectangle(
        (x0 + bordo, y0 + bordo, x1 - bordo, y1 - bordo),
        outline=_FRAME_INNER, width=max(1, round(1.6 * u)),
    )


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


def _draw_card(img, box, title, fonts_map) -> None:
    u = _unit()
    glow_box(img, box, radius=14 * u, edge=_CARD_EDGE, width=2 * u, fill=_CARD_BG,
             glow=7 * u, glow_alpha=120)
    draw = ImageDraw.Draw(img)
    x0, y0, x1, _y1 = box
    draw.text((x0 + _scale(32), y0 + _scale(_TITLE_Y)), title, font=fonts_map["card"],
              fill=WHITE, anchor="lm")
    draw.line(
        (x0 + _scale(29), y0 + _scale(_TITLE_RULE_Y), x1 - _scale(29), y0 + _scale(_TITLE_RULE_Y)),
        fill=_UNDERLINE, width=max(1, round(3 * u)),
    )


def _paint_icon(img, cx, cy, reach, paint) -> None:
    paint_supersampled(img, (cx - reach, cy - reach, cx + reach, cy + reach), (cx, cy), paint)


def _draw_glyph(img, kind, color, cx, cy, r) -> None:
    u = _unit()

    def paint(d, ax, ay, s):
        rr = r * s
        d.ellipse((ax - rr, ay - rr, ax + rr, ay + rr), fill=_PAD_FILL, outline=_PAD_RIM,
                  width=max(1, round(2 * u * s)))
        w = max(1, round(3.4 * u * s))
        k = rr * 0.42
        if kind == "cross":
            d.line((ax - k, ay - k, ax + k, ay + k), fill=color, width=w)
            d.line((ax - k, ay + k, ax + k, ay - k), fill=color, width=w)
        elif kind == "circle":
            d.ellipse((ax - k, ay - k, ax + k, ay + k), outline=color, width=w)
        elif kind == "square":
            q = k * 0.9
            d.rectangle((ax - q, ay - q, ax + q, ay + q), outline=color, width=w)
        else:
            d.polygon(
                [
                    (ax, ay - k * 1.1),
                    (ax + k * 1.12, ay + k * 0.82),
                    (ax - k * 1.12, ay + k * 0.82),
                ],
                outline=color, width=w,
            )

    _paint_icon(img, cx, cy, r + _scale(3), paint)


def _draw_stick(img, letter: str, cx, cy, r, font) -> None:
    u = _unit()
    _paint_icon(
        img, cx, cy, r + _scale(3),
        lambda d, ax, ay, s: d.ellipse(
            (ax - r * s, ay - r * s, ax + r * s, ay + r * s),
            fill=_PAD_FILL, outline=_PAD_RIM, width=max(1, round(2 * u * s)),
        ),
    )
    ImageDraw.Draw(img).text((cx, cy), letter, font=font, fill=_PAD_INK, anchor="mm")


def _draw_key(img, x, cy, w, h, label: str, font) -> None:
    u = _unit()
    _paint_icon(
        img, x + w / 2, cy, w / 2 + _scale(3),
        lambda d, ax, ay, s: d.rounded_rectangle(
            (ax - w / 2 * s, ay - h / 2 * s, ax + w / 2 * s, ay + h / 2 * s), radius=_scale(9) * s,
            fill=_PAD_FILL, outline=_PAD_RIM, width=max(1, round(2 * u * s)),
        ),
    )
    ImageDraw.Draw(img).text((x + w / 2, cy), label, font=font, fill=_PAD_INK, anchor="mm")


def _draw_warn_icon(draw, cx, cy, size, color) -> None:
    h = size * 0.9
    draw.polygon(
        [(cx, cy - h / 2), (cx + h * 0.58, cy + h / 2), (cx - h * 0.58, cy + h / 2)],
        fill=color,
    )
    draw.line((cx, cy - h * 0.12, cx, cy + h * 0.2), fill=_WARN_INK,
              width=max(1, round(size * 0.08)))
    e = size * 0.05
    draw.ellipse((cx - e, cy + h * 0.3 - e, cx + e, cy + h * 0.3 + e), fill=_WARN_INK)


def _draw_info_icon(draw, cx, cy, size, color, font) -> None:
    r = size * 0.46
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color,
                 width=max(1, round(size * 0.075)))
    draw.text((cx, cy + size * 0.02), "i", font=font, fill=color, anchor="mm")


def _note_styles() -> list:
    return [_NOTE_STYLES[i % len(_NOTE_STYLES)] for i in range(len(NOTES))]


def _platform_layout(box, fonts_map):
    x0, y0, x1, y1 = box
    testo_x = x0 + _scale(32)
    max_w = x1 - x0 - _scale(64)
    righe = []
    y = y0 + _scale(_BODY_TOP)
    ultima = y
    for indice, paragrafo in enumerate(PLATFORM_PARAGRAPHS):
        if indice:
            y += _scale(_PARAGRAPH_GAP)
        for riga in _wrap(paragrafo, fonts_map["body"], max_w):
            righe.append((testo_x, y, riga))
            ultima = y
            y += _scale(_BODY_STEP)

    nx0, nx1 = x0 + _scale(_NOTE_INSET), x1 - _scale(_NOTE_INSET)
    nota_x = nx0 + _scale(_NOTE_TEXT_X)
    fondo = y1 - _scale(_NOTE_INSET)
    note = []
    for (titolo, testo), stile in reversed(list(zip(NOTES, _note_styles()))):
        corpo = _wrap(testo, fonts_map["note_text"], nx1 - _scale(22) - nota_x)
        alto = _scale(_NOTE_TEXT_Y) + _scale(_NOTE_STEP) * (len(corpo) - 1) + _scale(_NOTE_BOTTOM)
        note.append(((nx0, fondo - alto, nx1, fondo), titolo, corpo, stile))
        fondo -= alto + _scale(_NOTE_GAP)
    note.reverse()

    cima_note = note[0][0][1] if note else y1
    return righe, note, ultima + _scale(_BODY_STEP / 2) + _scale(16) <= cima_note


def _draw_platform_card(img, box, fonts_map) -> None:
    _draw_card(img, box, PLATFORM_TITLE, fonts_map)
    righe, note, _ci_sta = _platform_layout(box, fonts_map)
    draw = ImageDraw.Draw(img)
    for x, y, riga in righe:
        draw.text((x, y), riga, font=fonts_map["body"], fill=WHITE, anchor="lm")

    u = _unit()
    for (bx0, by0, bx1, by1), titolo, corpo, (forma, colore, bordo) in note:
        glow_box(img, (bx0, by0, bx1, by1), radius=10 * u, edge=bordo, width=2 * u,
                 fill=_NOTE_BG, glow=5 * u, glow_alpha=90)
        draw = ImageDraw.Draw(img)
        cy = (by0 + by1) / 2
        icona_x = bx0 + _scale(_NOTE_ICON_X)
        if forma == "warn":
            _draw_warn_icon(draw, icona_x, cy, _scale(46), colore)
        else:
            _draw_info_icon(draw, icona_x, cy, _scale(46), colore, fonts_map["info"])
        linea_x = bx0 + _scale(_NOTE_RULE_X)
        mezza = (by1 - by0) / 2 - _scale(18)
        draw.line((linea_x, cy - mezza, linea_x, cy + mezza), fill=colore,
                  width=max(1, round(2.4 * u)))
        testo_x = bx0 + _scale(_NOTE_TEXT_X)
        draw.text((testo_x, by0 + _scale(_NOTE_TITLE_Y)), titolo, font=fonts_map["note_label"],
                  fill=colore, anchor="lm")
        for n, riga in enumerate(corpo):
            draw.text((testo_x, by0 + _scale(_NOTE_TEXT_Y) + _scale(_NOTE_STEP) * n), riga,
                      font=fonts_map["note_text"], fill=WHITE, anchor="lm")


def _only_glyphs(righe) -> bool:
    return all(lato is None and nome in _GLYPH_COLORS for nome, _azione, lato in righe)


def _commands_layout(box, fonts_map):
    x0, y0, x1, y1 = box
    colonna = x0 + _scale(34)
    raggio = _scale(21)
    gruppi = joystick_action_groups()
    assi = joystick_axis_details()

    tasti = [tasto for _sezione, righe in gruppi for tasto, _azione in righe]
    chiavi = [tasto for tasto in tasti if tasto not in _GLYPH_COLORS]
    pastiglia_w = max(
        [int(fonts_map["key"].getlength(tasto)) + _scale(28) for tasto in chiavi]
        + [2 * raggio]
    )
    pastiglia_h = _scale(36)
    nome_x = colonna + 2 * raggio + _scale(14)
    fine_nomi = max(
        [colonna + pastiglia_w]
        + [nome_x + fonts_map["name"].getlength(f"+ {verso}") for _lato, verso, _azione in assi]
    )
    azione_x = int(fine_nomi) + _scale(36)
    azione_w = x1 - _scale(30) - azione_x

    sezioni = [[(t, a, None) for t, a in righe] for _sezione, righe in gruppi[:-1]]
    sezioni.append([(f"+ {verso}", azione, lato) for lato, verso, azione in assi])
    sezioni += [[(t, a, None) for t, a in righe] for _sezione, righe in gruppi[-1:]]

    elementi = []
    y = y0 + _scale(_ROWS_TOP)
    ultima = y
    precedente = None
    for righe in sezioni:
        if precedente is not None:
            stretto = _only_glyphs(precedente) and _only_glyphs(righe)
            y += _scale(_GLYPH_GAP if stretto else _GROUP_GAP)
        for nome, azione, lato in righe:
            linee = _wrap(azione, fonts_map["action"], azione_w)
            extra = _scale(_ACTION_STEP) * (len(linee) - 1)
            cy = y + extra / 2
            elementi.append((cy, nome, linee, lato))
            ultima = cy + extra / 2
            y += _scale(_ROW_STEP) + extra
        precedente = righe

    colonne = {
        "colonna": colonna,
        "raggio": raggio,
        "pastiglia": (pastiglia_w, pastiglia_h),
        "nome_x": nome_x,
        "azione_x": azione_x,
    }
    return elementi, colonne, ultima + raggio + _scale(18) <= y1


def _draw_commands_card(img, box, fonts_map) -> None:
    _draw_card(img, box, COMMANDS_TITLE, fonts_map)
    elementi, c, _ci_sta = _commands_layout(box, fonts_map)
    colonna, raggio = c["colonna"], c["raggio"]
    glifo_x = colonna + raggio
    for cy, nome, linee, lato in elementi:
        if lato is not None:
            _draw_stick(img, lato, glifo_x, cy, raggio, fonts_map["stick"])
            ImageDraw.Draw(img).text((c["nome_x"], cy), nome, font=fonts_map["name"],
                                     fill=WHITE, anchor="lm")
        elif nome in _GLYPH_COLORS:
            forma, colore = _GLYPH_COLORS[nome]
            _draw_glyph(img, forma, colore, glifo_x, cy, raggio)
        else:
            _draw_key(img, colonna, cy, c["pastiglia"][0], c["pastiglia"][1], nome,
                      fonts_map["key"])
        draw = ImageDraw.Draw(img)
        ay = cy - _scale(_ACTION_STEP) * (len(linee) - 1) / 2
        for linea in linee:
            draw.text((c["azione_x"], ay), linea, font=fonts_map["action"],
                      fill=WHITE, anchor="lm")
            ay += _scale(_ACTION_STEP)


def _fonts_map():
    S = _scale
    return {
        "card": fonts.sans_bold(S(34)),
        "body": fonts.sans(S(23)),
        "key": fonts.sans_bold(S(18)),
        "name": fonts.sans_bold(S(23)),
        "action": fonts.sans(S(23)),
        "stick": fonts.sans_bold(S(19)),
        "note_label": fonts.sans_bold(S(21)),
        "note_text": fonts.sans(S(21)),
        "info": fonts.sans_bold(S(29)),
        "chip": fonts.sans_bold(S(25)),
        "button": fonts.sans_bold(S(25)),
        "fallback_title": fonts.sans_bold(S(46)),
    }


def _geometry(width, height, exit_rect, start_rect):
    SS = _SUPERSAMPLE
    k = _base_layout_scale(width, height)
    W = width * SS
    sinistra_x = exit_rect.x * SS
    destra_x = start_rect.right * SS
    linea = (exit_rect.y - int(round(28 * k))) * SS
    banner_top = _scale(30)
    banner_bottom = banner_top + _scale(212)
    gap = _scale(20)
    disponibile = destra_x - sinistra_x - gap
    sinistra = int(disponibile * _LEFT_SHARE)
    return {
        "W": W,
        "banner": (sinistra_x, banner_top, destra_x, banner_bottom),
        "top": banner_bottom + _scale(22),
        "bottom": linea - int(round(24 * k)) * SS,
        "rule": linea,
        "x0": sinistra_x,
        "x1": destra_x,
        "gap": gap,
        "sinistra": sinistra,
    }


def _card_boxes(geometria):
    x0, top, bottom = geometria["x0"], geometria["top"], geometria["bottom"]
    sinistra = (x0, top, x0 + geometria["sinistra"], bottom)
    destra = (x0 + geometria["sinistra"] + geometria["gap"], top, geometria["x1"], bottom)
    return sinistra, destra


def _layout_fits(geometria, fonts_map) -> bool:
    if geometria["bottom"] - geometria["top"] <= 0:
        return False
    sinistra, destra = _card_boxes(geometria)
    return (
        _platform_layout(sinistra, fonts_map)[2]
        and _commands_layout(destra, fonts_map)[2]
    )


def _fit_layout(width: int, height: int, exit_rect, start_rect):
    global _LAYOUT_SCALE

    base = _base_layout_scale(width, height)
    fonts_map = None
    geometria = None
    for tentativo in range(_FIT_ATTEMPTS):
        _LAYOUT_SCALE = base * (0.94 ** tentativo)
        fonts_map = _fonts_map()
        geometria = _geometry(width, height, exit_rect, start_rect)
        if _layout_fits(geometria, fonts_map):
            break
    return fonts_map, geometria


def button_rects(width: int, height: int):
    k = _base_layout_scale(width, height)
    larghezza = int(round(250 * k))
    altezza = int(round(60 * k))
    margine = int(round(48 * k))
    y = height - altezza - int(round(28 * k))
    start_rect = pygame.Rect(width - margine - larghezza, y, larghezza, altezza)
    exit_rect = pygame.Rect(margine, y, larghezza, altezza)
    return start_rect, exit_rect


def _rect_box(rect):
    SS = _SUPERSAMPLE
    return (rect.x * SS, rect.y * SS, rect.right * SS, rect.bottom * SS)


def _render_welcome_screen(width, height, *, focused, start_rect, exit_rect,
                           start_hover, exit_hover):
    SS = _SUPERSAMPLE
    W, H = width * SS, height * SS

    fonts_map, geometria = _fit_layout(width, height, exit_rect, start_rect)
    u = _unit()

    img = grid_background(W, H, _scale(64), _scale(6))
    _draw_banner(img, geometria["banner"], fonts_map)

    sinistra, destra = _card_boxes(geometria)
    _draw_platform_card(img, sinistra, fonts_map)
    _draw_commands_card(img, destra, fonts_map)

    draw = ImageDraw.Draw(img)
    draw.line((geometria["x0"], geometria["rule"], geometria["x1"], geometria["rule"]),
              fill=FOOTER_RULE, width=max(1, round(1.3 * u)))
    if not focused:
        draw.text(
            (W // 2, int((exit_rect.y + exit_rect.height / 2) * SS)),
            NOT_FOCUSED_NOTE, font=fonts_map["chip"], fill=_NOT_FOCUSED, anchor="mm",
        )
    draw_hover_button(img, _rect_box(exit_rect), exit_label(), fonts_map["button"],
                      unit=u, hover=exit_hover)
    draw_hover_button(img, _rect_box(start_rect), start_label(), fonts_map["button"],
                      unit=u, hover=start_hover)

    final = img.resize((width, height), Image.LANCZOS)
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
