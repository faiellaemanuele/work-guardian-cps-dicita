from __future__ import annotations

from typing import Any, Callable, Optional

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from drone.data.flight_excel_style import (
    BASE_FONT,
    CELL_BORDER,
    CENTER,
    HEADER_BORDER,
    HEADER_FILL,
    HEADER_FONT,
    LABEL_FONT,
    LEFT,
    RIGHT,
    SUBTITLE_FONT,
    TITLE_FONT,
    WRAP_LEFT,
    ZEBRA_FILL,
    autofit_columns,
    section_title,
    table_header,
)

# I fogli dei report di volo e di quelli biometrici sono costruiti con gli
# stessi mattoni: una tabella di campioni, una tabella di statistiche, l'elenco
# dei parametri e la legenda delle colonne. Qui stanno quei mattoni, senza
# sapere nulla di cosa ci si scrive dentro.

# Una colonna di un foglio dati: intestazione, come ricavare il valore dal
# campione, formato numerico (None quando la colonna è testo).
Column = tuple[str, Callable[[Any], Any], Optional[str]]

# Una statistica, come la restituisce column_stats: nome, minimo, massimo,
# media, deviazione standard (None quando non è calcolabile).
Stat = tuple[str, float, float, float, Optional[float]]


def write_data_sheet(
    ws: Worksheet,
    entries,
    columns: list[Column],
    *,
    highlights: Optional[dict[str, tuple[str, PatternFill, Font]]] = None,
) -> None:
    headers = [header for header, _getter, _fmt in columns]

    for col_index, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_index, value=header)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
        cell.border = HEADER_BORDER

    for row_index, entry in enumerate(entries, start=2):
        zebra = ZEBRA_FILL if (row_index % 2 == 0) else None
        for col_index, (_header, getter, fmt) in enumerate(columns, start=1):
            cell = ws.cell(row=row_index, column=col_index, value=getter(entry))
            cell.font = BASE_FONT
            if fmt is not None:
                cell.number_format = fmt
                cell.alignment = RIGHT
            else:
                cell.alignment = LEFT
            if zebra is not None:
                cell.fill = zebra

        for header, (trigger_word, fill, font) in (highlights or {}).items():
            hi_cell = ws.cell(row=row_index, column=headers.index(header) + 1)
            if str(hi_cell.value) == trigger_word:
                hi_cell.fill = fill
                hi_cell.font = font
                hi_cell.alignment = CENTER

    autofit_columns(ws)

    ws.freeze_panes = "A2"
    last_col = get_column_letter(len(columns))
    last_row = len(entries) + 1
    ws.auto_filter.ref = f"A1:{last_col}{last_row}"


def write_stats_table(
    ws: Worksheet,
    row: int,
    stats: list[Stat],
    *,
    labels: dict[str, str],
    number_format: Callable[[str], str],
) -> int:
    row = table_header(ws, row, ["Grandezza", "Minimo", "Massimo", "Media", "Dev. std"])
    for name, mn, mx, mean, std in stats:
        fmt = number_format(name)
        label_cell = ws.cell(row=row, column=1, value=labels.get(name, name))
        label_cell.font = BASE_FONT
        label_cell.alignment = LEFT
        label_cell.border = CELL_BORDER
        for col_index, val in ((2, mn), (3, mx), (4, mean), (5, std)):
            if val is None:
                c = ws.cell(row=row, column=col_index, value="—")
                c.alignment = CENTER
            else:
                c = ws.cell(row=row, column=col_index, value=val)
                c.number_format = fmt
                c.alignment = RIGHT
            c.font = BASE_FONT
            c.border = CELL_BORDER
        row += 1
    return row


def write_parameters_sheet(
    ws: Worksheet,
    parameters: list[tuple[str, list[tuple[str, str]]]],
    *,
    subtitle: str,
    note: Optional[str] = None,
) -> None:
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:B1")
    title = ws.cell(row=1, column=1, value="Parametri della sessione")
    title.font = TITLE_FONT
    ws.merge_cells("A2:B2")
    subtitle_cell = ws.cell(row=2, column=1, value=subtitle)
    subtitle_cell.font = SUBTITLE_FONT
    row = 4

    for group_title, items in parameters:
        row = section_title(ws, row, group_title, span=2)
        for label, value in items:
            label_cell = ws.cell(row=row, column=1, value=label)
            label_cell.font = LABEL_FONT
            label_cell.alignment = LEFT
            label_cell.border = CELL_BORDER
            value_cell = ws.cell(row=row, column=2, value=value)
            value_cell.font = BASE_FONT
            value_cell.alignment = LEFT
            value_cell.border = CELL_BORDER
            row += 1
        row += 1

    if note:
        note_cell = ws.cell(row=row, column=1, value=note)
        note_cell.font = SUBTITLE_FONT
        note_cell.alignment = WRAP_LEFT
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)

    autofit_columns(ws)


def write_legend_sheet(
    ws: Worksheet,
    blocks: list[tuple[str, list[tuple[str, str]]]],
    *,
    name_width: int = 32,
    meaning_width: int = 78,
) -> None:
    ws.column_dimensions["A"].width = name_width
    ws.column_dimensions["B"].width = meaning_width
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:B1")
    title = ws.cell(row=1, column=1, value="Legenda delle colonne")
    title.font = TITLE_FONT
    row = 3

    for section_name, pairs in blocks:
        row = section_title(ws, row, section_name, span=2)
        row = table_header(ws, row, ["Colonna", "Significato"])
        for name, meaning in pairs:
            name_cell = ws.cell(row=row, column=1, value=name)
            name_cell.font = LABEL_FONT
            name_cell.alignment = WRAP_LEFT
            name_cell.border = CELL_BORDER
            mean_cell = ws.cell(row=row, column=2, value=meaning)
            mean_cell.font = BASE_FONT
            mean_cell.alignment = WRAP_LEFT
            mean_cell.border = CELL_BORDER
            row += 1
        row += 1
