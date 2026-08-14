from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from python_calamine import CalamineWorkbook

from .text_utils import clean_header, normalize_text

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".xlsb"}


@dataclass
class TableData:
    sheet_name: str
    headers: list[str]
    rows: list[dict[str, Any]]
    source_path: Path | None = None
    header_row: int = 1


@dataclass
class WorkbookData:
    path: Path
    tables: list[TableData]


class ExcelReadError(RuntimeError):
    pass


def _detect_header_row(matrix: list[list[Any]], max_scan: int = 25) -> int:
    best_idx = 0
    best_score = -1
    keywords = {
        "FORNECEDOR", "VALOR", "DATA", "TITULO", "VENCIMENTO", "CATEGORIA",
        "FLUXO", "COD FORNECEDOR", "VLR ORIGINAL", "NOME FORNECEDOR",
    }
    for idx, row in enumerate(matrix[:max_scan]):
        cleaned = [normalize_text(v) for v in row]
        nonempty = sum(bool(v) for v in cleaned)
        keyword_hits = sum(any(k in v for k in keywords) for v in cleaned if v)
        score = nonempty + keyword_hits * 4
        if score > best_score:
            best_idx, best_score = idx, score
    return best_idx


def read_excel(path: str | Path) -> WorkbookData:
    file_path = Path(path)
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ExcelReadError(f"Formato não suportado: {file_path.suffix}")
    if not file_path.exists():
        raise ExcelReadError("Arquivo não encontrado.")

    try:
        workbook = CalamineWorkbook.from_path(str(file_path))
    except Exception as exc:
        raise ExcelReadError(f"Não foi possível abrir a planilha '{file_path.name}': {exc}") from exc

    tables: list[TableData] = []
    for sheet_name in workbook.sheet_names:
        sheet = workbook.get_sheet_by_name(sheet_name)
        matrix = sheet.to_python()
        if not matrix:
            continue
        header_idx = _detect_header_row(matrix)
        raw_headers = matrix[header_idx]
        headers: list[str] = []
        seen: dict[str, int] = {}
        for col_idx, value in enumerate(raw_headers):
            header = clean_header(value) or f"COLUNA_{col_idx + 1}"
            count = seen.get(header, 0) + 1
            seen[header] = count
            headers.append(header if count == 1 else f"{header}_{count}")

        rows: list[dict[str, Any]] = []
        for source_row, raw in enumerate(matrix[header_idx + 1 :], start=header_idx + 2):
            if not any(v not in (None, "") for v in raw):
                continue
            padded = list(raw) + [None] * max(0, len(headers) - len(raw))
            item = {headers[i]: padded[i] for i in range(len(headers))}
            item["__source_file__"] = file_path.name
            item["__source_path__"] = str(file_path)
            item["__source_sheet__"] = sheet_name
            item["__source_row__"] = source_row
            rows.append(item)
        tables.append(TableData(
            sheet_name=sheet_name,
            headers=headers,
            rows=rows,
            source_path=file_path,
            header_row=header_idx + 1,
        ))

    if not tables:
        raise ExcelReadError(f"Nenhuma tabela com dados foi encontrada em '{file_path.name}'.")
    return WorkbookData(path=file_path, tables=tables)


def combine_tables(tables: Iterable[TableData], name: str) -> TableData:
    tables = list(tables)
    if not tables:
        raise ExcelReadError(f"Nenhuma tabela foi informada para combinar como {name}.")
    headers: list[str] = []
    seen: set[str] = set()
    for table in tables:
        for header in table.headers:
            if header not in seen:
                seen.add(header)
                headers.append(header)
    rows: list[dict[str, Any]] = []
    for table in tables:
        rows.extend(table.rows)
    return TableData(sheet_name=name, headers=headers, rows=rows)
