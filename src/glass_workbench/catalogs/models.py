"""Shared catalog model aliases and strict source-cell helpers."""
from math import isfinite
import re
from openpyxl.utils.cell import column_index_from_string
from glass_workbench.contracts import Glass, Catalog


def cell(row, column):
    i = column_index_from_string(column)-1
    return row[i] if i < len(row) else None


def number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


def text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def coefficients(row, columns):
    values = tuple(number(cell(row,c)) for c in columns)
    return values if all(x is not None for x in values) else None


def family(name):
    base = re.sub(r"^(?:H|N|P|D|Q)-", "", name)
    match = re.match(r"[A-Za-z]+", base)
    return match.group(0).upper() if match else "Other"


def require_headers(rows, expected):
    for row_num, column, wanted in expected:
        actual = text(cell(rows[row_num-1],column))
        if actual != wanted:
            raise ValueError(f"Catalog schema mismatch at {column}{row_num}: expected {wanted!r}, got {actual!r}")
