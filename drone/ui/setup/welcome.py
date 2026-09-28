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
    CARD_EDGE_ON,
    CARD_FILL,
    CHIP_EDGE,
    CHIP_FILL,
    CYAN_BRIGHT,
    CYAN_TEXT,
    CrossfadeBlitter,
    ICON_CYAN,
    WHITE,
    draw_alert,
    draw_pad_arrow,
    draw_pad_button,
    draw_pad_key,
    draw_setup_footer,
    fade_screen,
    flash_button_press,
    focus_window,
    footer_rule_y,
    grid_background,
    maximize_window,
)
from drone.ui.shapes import draw_centered_label, glow_box, paint_supersampled


PLATFORM_TITLE = "Presentazione del progetto"

PLATFORM_TEXT = (
    "Work-Guardian è un Cyber-Physical-Human System progettato per supportare la sicurezza "
    "nei cantieri edili, con particolare attenzione alle attività svolte in quota. Il progetto "
    "integra in un’unica architettura un drone per la sorveglianza dell’area di lavoro, un "
    "wearable device per il monitoraggio degli operatori e una central control station "
    "incaricata di coordinare l’intero sistema. Il drone acquisisce immagini del cantiere, che "
    "vengono analizzate mediante tecniche di Computer Vision per verificare la presenza dei "
    "dispositivi di protezione individuale e collettiva e rilevare eventuali situazioni di "
    "pericolo. Parallelamente, il wearable device esegue il real-time monitoring di alcuni "
    "parametri fisiologici dell’operatore, come la frequenza cardiaca e la saturazione "
    "dell’ossigeno, permettendo di riconoscere possibili condizioni di affaticamento o "
    "malessere. La central control station raccoglie e integra i dati provenienti dai diversi "
    "sottosistemi, genera gli alert e fornisce al supervisore una visione complessiva dello "
    "stato del cantiere. Work-Guardian combina così il monitoraggio dell’ambiente e degli "
    "operatori, favorendo l’individuazione tempestiva delle criticità e supportando la "
    "gestione delle situazioni di emergenza."
)

NOTES = (
    (
        "BATTERIA BASSA",
        "Sotto il 30% il drone in volo autonomo rientra alla home; sotto il 20% esegue un "
        "atterraggio d’emergenza.",
    ),
    (
        "SALVATAGGIO DEI DATI",
        "Il volo si registra a missione conclusa o dopo un atterraggio automatico, non con "
        "quello manuale.",
    ),
)

COMMANDS_TITLE = "Comandi del controller"

NEXT_TEXT = "Avanti"
EXIT_TEXT = "Esci"


def start_label() -> str:
    return f"{NEXT_TEXT} ({APP_CONFIG.joystick.label_setup_confirm})"


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


_NOTE_ICONS = ("battery", "save")

_GLYPH_SHAPES = {
    "Croce": "cross",
    "Cerchio": "circle",
    "Quadrato": "square",
    "Triangolo": "triangle",
}

_LEFT_SHARE = 0.57

_TITLE_Y = 44
_TITLE_RULE_Y = 82

_BODY_TOP = 126
_BODY_STEP = 33

_NOTE_INSET = 22
_NOTE_ICON = 40
_NOTE_ICON_X = 40
_NOTE_RULE_X = 74
_NOTE_TEXT_X = 90
_NOTE_TITLE_Y = 24
_NOTE_TEXT_Y = 48
_NOTE_STEP = 22
_NOTE_BOTTOM = 22
_NOTE_GAP = 10

_CARD_PAD_X = 32

_ROWS_TOP = _BODY_TOP
_ROW_STEP = 48
_ROW_STEP_MAX = 64
_ACTION_STEP = 28
_SYMBOL_R = 21
_KEY_H = 38
_KEY_PAD = 30
_ARROW_GAP = 8
_ACTION_GAP = 30

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
    glow_box(img, box, radius=3 * u, edge=CARD_EDGE_ON, width=2 * u, glow=8 * u, glow_alpha=150)
    inset = int(round(6 * u))
    banner = _banner_image(x1 - x0 - 2 * inset, y1 - y0 - 2 * inset)
    draw = ImageDraw.Draw(img)
    if banner is not None:
        img.paste(banner, (x0 + inset, y0 + inset))
    else:
        draw.rectangle((x0 + inset, y0 + inset, x1 - inset, y1 - inset), fill=CARD_FILL)
        draw.text(
            ((x0 + x1) / 2, (y0 + y1) / 2), PROJECT_TITLE,
            font=fonts_map["fallback_title"], fill=WHITE, anchor="mm",
        )
    bordo = 4 * u
    draw.rectangle(
        (x0 + bordo, y0 + bordo, x1 - bordo, y1 - bordo),
        outline=CYAN_BRIGHT, width=max(1, round(1.6 * u)),
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
    glow_box(img, box, radius=14 * u, edge=CARD_EDGE_ON, width=2 * u, fill=CARD_FILL,
             glow=7 * u, glow_alpha=120)
    draw = ImageDraw.Draw(img)
    x0, y0, x1, _y1 = box
    draw.text((x0 + _scale(_CARD_PAD_X), y0 + _scale(_TITLE_Y)), title, font=fonts_map["card"],
              fill=WHITE, anchor="lm")
    draw.line(
        (x0 + _scale(29), y0 + _scale(_TITLE_RULE_Y), x1 - _scale(29), y0 + _scale(_TITLE_RULE_Y)),
        fill=CYAN_BRIGHT, width=max(1, round(3 * u)),
    )


def _paint_icon(img, cx, cy, reach, paint) -> None:
    paint_supersampled(img, (cx - reach, cy - reach, cx + reach, cy + reach), (cx, cy), paint)


def _draw_glyph(img, kind, cx, cy, r) -> None:
    u = _unit()
    _paint_icon(
        img, cx, cy, r + _scale(3),
        lambda d, ax, ay, s: draw_pad_button(d, kind, ax, ay, r * s, u * s),
    )


def _draw_stick(img, letter: str, verso: str, cx, cy, r, font) -> None:
    u = _unit()
    _paint_icon(
        img, cx, cy, r + _scale(3),
        lambda d, ax, ay, s: draw_pad_button(d, None, ax, ay, r * s, u * s),
    )
    draw_centered_label(ImageDraw.Draw(img), cx, cy, letter, font, WHITE)
    freccia_x = cx + 2 * r + _scale(_ARROW_GAP)
    _paint_icon(
        img, freccia_x, cy, r + _scale(3),
        lambda d, ax, ay, s: draw_pad_arrow(d, verso, ax, ay, r * s, u * s),
    )


def _draw_key(img, label: str, cx, cy, size, font) -> None:
    u = _unit()
    w, h = size
    _paint_icon(
        img, cx, cy, w / 2 + _scale(3),
        lambda d, ax, ay, s: draw_pad_key(d, ax, ay, w * s, h * s, u * s),
    )
    draw_centered_label(ImageDraw.Draw(img), cx, cy, label, font, WHITE)


def _draw_battery_icon(img, cx, cy, size, color) -> None:
    def paint(d, ax, ay, s):
        lato = size * s
        tratto = max(1, round(lato * 0.075))
        w = lato * 0.76
        h = lato * 0.46
        polo_w = lato * 0.09
        polo_h = h * 0.44
        x0 = ax - (w + polo_w) / 2
        y0 = ay - h / 2
        d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=lato * 0.08, outline=color,
                            width=tratto)
        d.rounded_rectangle((x0 + w, ay - polo_h / 2, x0 + w + polo_w, ay + polo_h / 2),
                            radius=polo_w * 0.35, fill=color)
        margine = tratto + lato * 0.05
        carica = (w - 2 * margine) * 0.24
        d.rounded_rectangle((x0 + margine, y0 + margine, x0 + margine + carica, y0 + h - margine),
                            radius=lato * 0.02, fill=color)

    _paint_icon(img, cx, cy, size * 0.6, paint)


def _draw_save_icon(img, cx, cy, size, color) -> None:
    def paint(d, ax, ay, s):
        lato = size * s
        tratto = max(1, round(lato * 0.075))
        m = lato * 0.38
        taglio = m * 0.42
        x0, y0, x1, y1 = ax - m, ay - m, ax + m, ay + m
        d.polygon([(x0, y0), (x1 - taglio, y0), (x1, y0 + taglio), (x1, y1), (x0, y1)],
                  outline=color, width=tratto)
        d.rectangle((ax - m * 0.52, y0, ax + m * 0.34, y0 + m * 0.64), fill=color)
        d.rectangle((ax + m * 0.04, y0 + m * 0.16, ax + m * 0.2, y0 + m * 0.48), fill=CHIP_FILL)
        d.rectangle((x0 + m * 0.32, ay + m * 0.14, x1 - m * 0.32, y1), outline=color,
                    width=tratto)

    _paint_icon(img, cx, cy, size * 0.6, paint)


def _note_icons() -> list:
    return [_NOTE_ICONS[i % len(_NOTE_ICONS)] for i in range(len(NOTES))]


def _platform_layout(box, fonts_map):
    x0, y0, x1, y1 = box
    testo_x = x0 + _scale(_CARD_PAD_X)
    max_w = x1 - x0 - 2 * _scale(_CARD_PAD_X)
    righe = []
    y = y0 + _scale(_BODY_TOP)
    ultima = y
    for riga in _wrap(PLATFORM_TEXT, fonts_map["body"], max_w):
        righe.append((testo_x, y, riga))
        ultima = y
        y += _scale(_BODY_STEP)

    nx0, nx1 = x0 + _scale(_NOTE_INSET), x1 - _scale(_NOTE_INSET)
    nota_x = nx0 + _scale(_NOTE_TEXT_X)
    fondo = y1 - _scale(_NOTE_INSET)
    note = []
    for (titolo, testo), icona in reversed(list(zip(NOTES, _note_icons()))):
        corpo = _wrap(testo, fonts_map["note_text"], nx1 - _scale(22) - nota_x)
        alto = _scale(_NOTE_TEXT_Y) + _scale(_NOTE_STEP) * (len(corpo) - 1) + _scale(_NOTE_BOTTOM)
        note.append(((nx0, fondo - alto, nx1, fondo), titolo, corpo, icona))
        fondo -= alto + _scale(_NOTE_GAP)
    note.reverse()

    cima_note = note[0][0][1] if note else y1
    return righe, note, ultima + _scale(_BODY_STEP / 2) + _scale(16) <= cima_note


def _draw_platform_card(img, box, fonts_map) -> None:
    _draw_card(img, box, PLATFORM_TITLE, fonts_map)
    righe, note, _ci_sta = _platform_layout(box, fonts_map)
    draw = ImageDraw.Draw(img)
    for x, y, riga in righe:
        draw.text((x, y), riga, font=fonts_map["body"], fill=CYAN_TEXT, anchor="lm")

    u = _unit()
    for (bx0, by0, bx1, by1), titolo, corpo, icona in note:
        glow_box(img, (bx0, by0, bx1, by1), radius=10 * u, edge=CHIP_EDGE, width=2 * u,
                 fill=CHIP_FILL)
        draw = ImageDraw.Draw(img)
        cy = (by0 + by1) / 2
        icona_x = bx0 + _scale(_NOTE_ICON_X)
        if icona == "battery":
            _draw_battery_icon(img, icona_x, cy, _scale(_NOTE_ICON), ICON_CYAN)
        else:
            _draw_save_icon(img, icona_x, cy, _scale(_NOTE_ICON), ICON_CYAN)
        linea_x = bx0 + _scale(_NOTE_RULE_X)
        mezza = (by1 - by0) / 2 - _scale(18)
        draw.line((linea_x, cy - mezza, linea_x, cy + mezza), fill=ICON_CYAN,
                  width=max(1, round(2.4 * u)))
        testo_x = bx0 + _scale(_NOTE_TEXT_X)
        draw.text((testo_x, by0 + _scale(_NOTE_TITLE_Y)), titolo, font=fonts_map["note_label"],
                  fill=CYAN_BRIGHT, anchor="lm")
        for n, riga in enumerate(corpo):
            draw.text((testo_x, by0 + _scale(_NOTE_TEXT_Y) + _scale(_NOTE_STEP) * n), riga,
                      font=fonts_map["note_text"], fill=CYAN_TEXT, anchor="lm")


def _commands_layout(box, fonts_map):
    x0, y0, x1, y1 = box
    colonna = x0 + _scale(_CARD_PAD_X)
    raggio = _scale(_SYMBOL_R)
    gruppi = joystick_action_groups()
    assi = joystick_axis_details()

    tasti = [tasto for _sezione, righe in gruppi for tasto, _azione in righe]
    chiavi = [tasto for tasto in tasti if tasto not in _GLYPH_SHAPES]
    tasto_w = max(
        [int(fonts_map["key"].getlength(tasto)) + _scale(_KEY_PAD) for tasto in chiavi]
        + [2 * raggio]
    )
    simbolo_w = max(tasto_w, 4 * raggio + _scale(_ARROW_GAP))
    azione_x = colonna + simbolo_w + _scale(_ACTION_GAP)
    azione_w = x1 - _scale(_CARD_PAD_X) - azione_x

    voci = [(t, a, None) for _sezione, gruppo in gruppi[:-1] for t, a in gruppo]
    voci += [(verso, azione, lato) for lato, verso, azione in assi]
    voci += [(t, a, None) for _sezione, gruppo in gruppi[-1:] for t, a in gruppo]
    testi = [_wrap(azione, fonts_map["action"], azione_w) for _nome, azione, _lato in voci]
    extra = [_scale(_ACTION_STEP) * (len(linee) - 1) for linee in testi]

    cima = y0 + _scale(_ROWS_TOP)
    fondo = y1 - _scale(_NOTE_INSET) - raggio
    passo = _scale(_ROW_STEP)
    if len(voci) > 1:
        riempie = (fondo - cima - sum(extra)) / (len(voci) - 1)
        passo = max(passo, min(_scale(_ROW_STEP_MAX), riempie))

    elementi = []
    y = cima
    ultima = y
    for (nome, _azione, lato), linee, alto in zip(voci, testi, extra):
        cy = y + alto / 2
        elementi.append((cy, nome, linee, lato))
        ultima = cy + alto / 2
        y += passo + alto

    colonne = {
        "colonna": colonna,
        "raggio": raggio,
        "tasto": (tasto_w, _scale(_KEY_H)),
        "simbolo_w": simbolo_w,
        "azione_x": azione_x,
    }
    return elementi, colonne, ultima + raggio + _scale(18) <= y1


def _draw_commands_card(img, box, fonts_map) -> None:
    _draw_card(img, box, COMMANDS_TITLE, fonts_map)
    elementi, c, _ci_sta = _commands_layout(box, fonts_map)
    colonna, raggio = c["colonna"], c["raggio"]
    cerchio_x = colonna + raggio
    for cy, nome, linee, lato in elementi:
        if lato is not None:
            _draw_stick(img, lato, nome, cerchio_x, cy, raggio, fonts_map["stick"])
        elif nome in _GLYPH_SHAPES:
            _draw_glyph(img, _GLYPH_SHAPES[nome], cerchio_x, cy, raggio)
        else:
            _draw_key(img, nome, colonna + c["tasto"][0] / 2, cy, c["tasto"], fonts_map["key"])
        draw = ImageDraw.Draw(img)
        ay = cy - _scale(_ACTION_STEP) * (len(linee) - 1) / 2
        for linea in linee:
            draw.text((c["azione_x"], ay), linea, font=fonts_map["action"],
                      fill=CYAN_TEXT, anchor="lm")
            ay += _scale(_ACTION_STEP)


def _fonts_map():
    S = _scale
    return {
        "card": fonts.sans_bold(S(34)),
        "body": fonts.sans(S(23)),
        "key": fonts.sans_bold(S(18)),
        "action": fonts.sans(S(23)),
        "stick": fonts.sans_bold(S(19)),
        "note_label": fonts.sans_bold(S(19)),
        "note_text": fonts.sans(S(19)),
        "fallback_title": fonts.sans_bold(S(46)),
    }


def _geometry(width, height, exit_rect, start_rect):
    SS = _SUPERSAMPLE
    k = _base_layout_scale(width, height)
    W = width * SS
    sinistra_x = exit_rect.x * SS
    destra_x = start_rect.right * SS
    linea = footer_rule_y(exit_rect.y, supersample=SS, unit=SS * k)
    banner_top = _scale(30)
    banner_bottom = banner_top + _scale(190)
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


def _render_welcome_screen(width, height, *, focused, start_rect, exit_rect,
                           start_hover, exit_hover):
    SS = _SUPERSAMPLE
    W, H = width * SS, height * SS

    fonts_map, geometria = _fit_layout(width, height, exit_rect, start_rect)
    piede = SS * _base_layout_scale(width, height)

    img = grid_background(W, H, int(round(64 * piede)), int(round(6 * piede)))
    _draw_banner(img, geometria["banner"], fonts_map)

    sinistra, destra = _card_boxes(geometria)
    _draw_platform_card(img, sinistra, fonts_map)
    _draw_commands_card(img, destra, fonts_map)

    if not focused:
        draw_alert(
            ImageDraw.Draw(img), W // 2, int(round(exit_rect.centery * SS)), NOT_FOCUSED_NOTE,
            fonts.sans_bold(int(round(28 * piede))), unit=piede,
        )
    draw_setup_footer(
        img,
        [(exit_rect, exit_label(), exit_hover), (start_rect, start_label(), start_hover)],
        (), supersample=SS, unit=piede,
    )

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
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if start_rect.collidepoint(event.pos):
                    comando = "confirm"
                elif exit_rect.collidepoint(event.pos):
                    comando = "cancel"
            if comando in ("confirm", "select", "cancel"):
                avanti = comando != "cancel"
                flash_button_press(screen, _render_welcome_screen(
                    width, height, focused=focused,
                    start_rect=start_rect, exit_rect=exit_rect,
                    start_hover=avanti, exit_hover=not avanti,
                ))
                return avanti

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
