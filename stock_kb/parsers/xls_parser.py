from __future__ import annotations

from pathlib import Path
from typing import Any

import xlrd


def read_xls_matrix(path: str | Path) -> list[list[Any]]:
    wb = xlrd.open_workbook(str(path), ignore_workbook_corruption=True)
    sheet = wb.sheet_by_index(0)
    rows: list[list[Any]] = []
    for r in range(sheet.nrows):
        rows.append([sheet.cell_value(r, c) for c in range(sheet.ncols)])
    return rows
