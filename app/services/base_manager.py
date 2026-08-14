from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import xlsxwriter

from .excel_reader import TableData, read_excel
from .reconciler import validate_base
from .sheet_detector import detect_base_table

APP_NAME = "ContasAPagar"
CUSTOM_BASE_NAME = "base_dados_ativa.xlsx"


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS, *parts)
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def app_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        path = root / APP_NAME
    else:
        path = Path.home() / ".contas_a_pagar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundled_base_path() -> Path:
    return resource_path("resources", "base_dados_padrao.xlsx")


def custom_base_path() -> Path:
    return app_data_dir() / CUSTOM_BASE_NAME


def active_base_path() -> Path:
    custom = custom_base_path()
    return custom if custom.exists() else bundled_base_path()


def load_active_base() -> TableData:
    path = active_base_path()
    wb = read_excel(path)
    table = detect_base_table(wb)
    validate_base(table)
    return table


def _write_base_xlsx(table: TableData, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(destination)
    ws = wb.add_worksheet("BASE DADOS")
    header = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#234865", "align": "center", "valign": "vcenter"})
    normal = wb.add_format({"valign": "top"})
    cols = ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"]
    # Resolve as colunas pelos nomes do arquivo recebido.
    from .normalizer import find_column
    mapping = [
        find_column(table, "Cód Fornecedor", "Codigo Fornecedor"),
        find_column(table, "Fornecedor"),
        find_column(table, "Fluxo JMM", "Fluxo"),
        find_column(table, "Categoria"),
    ]
    for c, title in enumerate(cols):
        ws.write(0, c, title, header)
    for r, row in enumerate(table.rows, start=1):
        for c, key in enumerate(mapping):
            ws.write(r, c, row.get(key) if key else "", normal)
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, len(table.rows), 3)
    ws.set_column(0, 0, 16)
    ws.set_column(1, 1, 42)
    ws.set_column(2, 2, 26)
    ws.set_column(3, 3, 30)
    wb.close()


def import_new_base(source: str | Path) -> tuple[Path, int]:
    wb = read_excel(source)
    table = detect_base_table(wb)
    validate_base(table)
    dest = custom_base_path()
    _write_base_xlsx(table, dest)
    # Reabre o arquivo persistido para garantir que o que será usado futuramente é válido.
    persisted = load_active_base()
    return dest, len(persisted.rows)


def export_active_base(destination: str | Path) -> Path:
    table = load_active_base()
    dest = Path(destination)
    _write_base_xlsx(table, dest)
    return dest


def base_info() -> dict[str, Any]:
    table = load_active_base()
    return {
        "path": str(active_base_path()),
        "rows": len(table.rows),
        "is_custom": custom_base_path().exists(),
        "sheet": table.sheet_name,
    }
