from __future__ import annotations

import csv
from pathlib import Path


def read_numeric_csv(path: Path) -> list[list[float]]:
    rows: list[list[float]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            while row and row[-1].strip() == "":
                row.pop()
            numeric_row: list[float] = []
            for cell in row:
                value = cell.strip()
                if value == "":
                    numeric_row.append(0.0)
                    continue
                try:
                    numeric_row.append(float(value))
                except ValueError:
                    numeric_row.append(0.0)
            if numeric_row:
                rows.append(numeric_row)
    return rows


def shape(matrix: list[list[float]]) -> tuple[int, int]:
    return len(matrix), max((len(row) for row in matrix), default=0)
