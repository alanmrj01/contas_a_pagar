from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any

from .excel_reader import TableData
from .text_utils import normalize_text

EXCEL_EPOCH = datetime(1899, 12, 30)


class ValueParseError(ValueError):
    pass


def to_float(value: Any, *, field: str = "valor") -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, bool):
        raise ValueParseError(f"{field}: valor booleano não é monetário")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueParseError(f"{field}: valor não finito não é válido")
        return number
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
        if not math.isfinite(number):
            raise ValueError
        return number
    except ValueError as exc:
        raise ValueParseError(f"{field}: '{value}' não pôde ser convertido em número") from exc


def to_date(value: Any) -> date | None:
    if value in (None, "", "00/00/0000"):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 20000 < float(value) < 80000:
        return (EXCEL_EPOCH + timedelta(days=float(value))).date()
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def find_column(table: TableData, *aliases: str) -> str | None:
    normalized = {normalize_text(h): h for h in table.headers}
    for alias in aliases:
        target = normalize_text(alias)
        if target in normalized:
            return normalized[target]
    for alias in aliases:
        target = normalize_text(alias)
        for norm, raw in normalized.items():
            if target and target in norm:
                return raw
    return None
