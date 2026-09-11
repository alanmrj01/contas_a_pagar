from __future__ import annotations

from datetime import date, datetime, timedelta
import math
import re
from typing import Any

from .excel_reader import TableData
from .text_utils import normalize_text

EXCEL_EPOCH = datetime(1899, 12, 30)
_SAFE_SPACES_RE = re.compile(r"[\s\u00a0\u202f\u2007]+")
_CURRENCY_RE = re.compile(r"^(?:R\$|BRL|US\$|USD|EUR|€|\$)\s*", re.IGNORECASE)
_PLAIN_NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
_GROUPED_COMMA_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3}){2,}$")
_GROUPED_DOT_RE = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3}){2,}$")
_BR_NUMBER_RE = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})*,\d{1,2}$|^[+-]?\d+,\d{1,2}$")
_INTL_NUMBER_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})*\.\d{1,2}$|^[+-]?\d+\.\d{1,2}$")


class ValueParseError(ValueError):
    pass


def to_float(value: Any, *, field: str = "valor") -> float:
    if value in (None, ""):
        raise ValueParseError(f"{field}: valor ausente")
    if isinstance(value, bool):
        raise ValueParseError(f"{field}: valor booleano não é monetário")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueParseError(f"{field}: valor não finito não é válido")
        return number
    text = _SAFE_SPACES_RE.sub("", str(value).strip())
    text = _CURRENCY_RE.sub("", text)
    if not text:
        raise ValueParseError(f"{field}: valor ausente")
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = "-" + text[1:-1]

    if not _PLAIN_NUMBER_RE.fullmatch(text) and not (
        _GROUPED_COMMA_RE.fullmatch(text)
        or _GROUPED_DOT_RE.fullmatch(text)
        or _BR_NUMBER_RE.fullmatch(text)
        or _INTL_NUMBER_RE.fullmatch(text)
    ):
        raise ValueParseError(f"{field}: '{value}' não possui formato numérico reconhecido com segurança")

    if _GROUPED_COMMA_RE.fullmatch(text):
        text = text.replace(",", "")
    elif _GROUPED_DOT_RE.fullmatch(text):
        text = text.replace(".", "")
    elif _BR_NUMBER_RE.fullmatch(text):
        text = text.replace(".", "").replace(",", ".")
    elif _INTL_NUMBER_RE.fullmatch(text):
        text = text.replace(",", "")
    elif "," in text:
        decimals = len(text.rsplit(",", 1)[1])
        if decimals == 3:
            raise ValueParseError(f"{field}: '{value}' é ambíguo; informe o separador decimal explicitamente")
        text = text.replace(",", ".")
    elif "." in text and len(text.rsplit(".", 1)[1]) == 3:
        raise ValueParseError(f"{field}: '{value}' é ambíguo; informe o separador decimal explicitamente")
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
    text = _SAFE_SPACES_RE.sub(" ", str(value).strip())
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
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
