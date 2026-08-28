from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
from typing import Any

import xlsxwriter

from .metrics import aggregate_suppliers
from .reconciler import ReconcileResult


HEADER_FMT = {"bold": True, "font_color": "#FFFFFF", "bg_color": "#234865", "border": 0, "align": "center", "valign": "vcenter"}
MONEY_FMT = {"num_format": 'R$ #,##0.00;[Red]-R$ #,##0.00'}
PCT_FMT = {"num_format": '0.00%;[Red]-0.00%'}
DATE_FMT = {"num_format": 'dd/mm/yyyy'}

PREVISTO_EXPORT_COLUMNS = [
    ("source_file", "Arquivo origem"), ("source_sheet", "Aba"), ("source_row", "Linha"),
    ("title", "Título previsto"), ("supplier_code", "Cód Fornecedor"), ("supplier_source", "Fornecedor original"),
    ("supplier", "Fornecedor classificado"), ("date", "Data prevista"), ("value", "Valor previsto"),
    ("flow", "Fluxo JMM"), ("category", "Categoria"), ("match", "Regra classificação"),
]

REALIZADO_EXPORT_COLUMNS = [
    ("source_file", "Arquivo origem"), ("source_sheet", "Aba"), ("source_row", "Linha"),
    ("title", "Título"), ("supplier_code", "Cód Fornecedor"), ("supplier_source", "Fornecedor original"),
    ("supplier", "Fornecedor classificado"), ("date", "Último pagamento"), ("due_date", "Vencimento"),
    ("value", "Vlr.Original"), ("flow", "Fluxo JMM"), ("category", "Categoria"),
    ("punctuality", "Pontualidade"), ("company", "Empresa"), ("branch", "Filial"),
    ("account", "Conta contábil"), ("financial_account", "Conta financeira"), ("cost_center", "Centro de custo"),
    ("match", "Regra classificação"),
]


def _required_number(value: Any, field: str) -> float:
    if value is None or (isinstance(value, str) and not value.strip()) or isinstance(value, bool):
        raise ValueError(f"{field}: valor monetário ausente ou inválido na exportação")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: valor monetário inválido na exportação") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field}: valor monetário não finito na exportação")
    return number


def _write_xlsx(
    path: Path,
    sheet_name: str,
    columns: list[tuple[str, str]],
    rows: list[dict[str, Any]],
    *,
    required_money_keys: set[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(path)
    ws = wb.add_worksheet(sheet_name[:31])
    header = wb.add_format(HEADER_FMT)
    money = wb.add_format(MONEY_FMT)
    percent = wb.add_format(PCT_FMT)
    date_fmt = wb.add_format(DATE_FMT)
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    normal = wb.add_format({"valign": "top"})
    ws.freeze_panes(1, 0)
    ws.autofilter(0, 0, max(0, len(rows)), max(0, len(columns)-1))
    for col_idx, (key, title) in enumerate(columns):
        ws.write(0, col_idx, title, header)
        width = min(42, max(12, len(title) + 3))
        if "Fornecedor" in title or "Arquivo" in title:
            width = 30
        ws.set_column(col_idx, col_idx, width)
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, (key, _) in enumerate(columns):
            value = row.get(key)
            if key in {"value", "planned", "actual", "variance", "unclassified_value"}:
                if value is None or (isinstance(value, str) and not value.strip()):
                    if key in (required_money_keys or set()):
                        _required_number(value, key)
                    ws.write_blank(r_idx, c_idx, None, normal)
                else:
                    ws.write_number(r_idx, c_idx, _required_number(value, key), money)
            elif key == "variance_pct":
                if value is None:
                    ws.write_blank(r_idx, c_idx, None, normal)
                else:
                    ws.write_number(r_idx, c_idx, float(value) / 100.0, percent)
            elif key in {"date", "due_date"} and value:
                try:
                    ws.write_datetime(r_idx, c_idx, datetime.fromisoformat(str(value)), date_fmt)
                except ValueError:
                    ws.write(r_idx, c_idx, str(value), normal)
            else:
                ws.write(r_idx, c_idx, "" if value is None else value, wrap if isinstance(value, str) and len(value) > 40 else normal)
    wb.close()


def _write_updated_report_workbook(path: Path, result: ReconcileResult) -> None:
    """Exporta um único arquivo reimportável sem alterar valores normalizados."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(path)
    header = wb.add_format(HEADER_FMT)
    money = wb.add_format(MONEY_FMT)
    date_fmt = wb.add_format(DATE_FMT)
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    normal = wb.add_format({"valign": "top"})

    sheets = [
        ("PREVISTO", [
            ("title", "Título Previsto"), ("supplier_code", "Cód Fornecedor"),
            ("supplier", "Fornecedor"), ("date", "Data prevista"), ("value", "Valor previsto"),
            ("month_text", "Mês"), ("flow", "Fluxo JMM"), ("category", "Categoria"),
            ("source_file", "Arquivo origem"), ("source_sheet", "Aba origem"), ("source_row", "Linha origem"),
        ], result.previsto),
        ("REALIZADO", [
            ("title", "Título"), ("supplier_code", "Fornecedor"), ("supplier", "Nome Fornecedor"),
            ("value", "Vlr.Original"), ("emission_date", "Emissão"), ("date", "Ult. Pgto."),
            ("due_date", "Vencimento"), ("company", "Empresa"), ("branch", "Filial"),
            ("status", "Sit."), ("account", "Desc. Conta Contábil"),
            ("financial_account", "Desc. Conta Financeira"), ("cost_center", "Desc. Centro de Custo"),
            ("flow", "Fluxo JMM"), ("category", "Categoria"),
            ("source_file", "Arquivo origem"), ("source_sheet", "Aba origem"), ("source_row", "Linha origem"),
        ], result.realizado),
    ]
    date_keys = {"date", "due_date", "emission_date"}
    for sheet_name, columns, rows in sheets:
        ws = wb.add_worksheet(sheet_name)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, max(0, len(rows)), len(columns) - 1)
        for col_idx, (_, title) in enumerate(columns):
            ws.write(0, col_idx, title, header)
            width = 30 if "Fornecedor" in title or "Arquivo" in title else min(42, max(12, len(title) + 3))
            ws.set_column(col_idx, col_idx, width)
        for row_idx, row in enumerate(rows, start=1):
            for col_idx, (key, _) in enumerate(columns):
                value = row.get(key)
                if key == "value":
                    ws.write_number(row_idx, col_idx, _required_number(value, key), money)
                elif key in date_keys and value:
                    try:
                        ws.write_datetime(row_idx, col_idx, datetime.fromisoformat(str(value)), date_fmt)
                    except ValueError:
                        ws.write(row_idx, col_idx, str(value), normal)
                else:
                    ws.write(row_idx, col_idx, "" if value is None else value, wrap if isinstance(value, str) and len(value) > 40 else normal)
    wb.close()


def export_filtered_report_workbook(result: ReconcileResult, output_dir: Path, kind: str) -> Path:
    """Materializa somente o conjunto já filtrado pelo backend da sessão."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if kind == "previsto":
        path = output_dir / "Previsto_filtrado.xlsx"
        _write_xlsx(path, "PREVISTO", PREVISTO_EXPORT_COLUMNS, result.previsto, required_money_keys={"value"})
        return path
    if kind == "realizado":
        path = output_dir / "Realizado_filtrado.xlsx"
        _write_xlsx(path, "REALIZADO", REALIZADO_EXPORT_COLUMNS, result.realizado, required_money_keys={"value"})
        return path
    if kind == "atualizado":
        path = output_dir / "Relatorio_atualizado_filtrado.xlsx"
        _write_updated_report_workbook(path, result)
        return path
    raise ValueError("Tipo de exportação inválido.")


def export_report_workbooks(result: ReconcileResult, output_dir: Path) -> dict[str, str]:
    exports = output_dir / "excel"
    exports.mkdir(parents=True, exist_ok=True)

    p_path = exports / "Previsto_normalizado.xlsx"
    _write_xlsx(p_path, "PREVISTO", PREVISTO_EXPORT_COLUMNS, result.previsto, required_money_keys={"value"})

    r_path = exports / "Realizado_normalizado.xlsx"
    _write_xlsx(r_path, "REALIZADO", REALIZADO_EXPORT_COLUMNS, result.realizado, required_money_keys={"value"})

    s_path = exports / "Analise_por_fornecedor.xlsx"
    _write_xlsx(s_path, "FORNECEDORES", [
        ("supplier_code", "Cód Fornecedor"), ("supplier", "Fornecedor"), ("category", "Categoria"), ("flow", "Fluxo JMM"),
        ("planned", "Previsto"), ("actual", "Realizado"), ("variance", "Desvio"), ("variance_pct", "Variação %"),
        ("planned_records", "Linhas previsto"), ("actual_records", "Títulos realizado"),
    ], aggregate_suppliers(result.previsto, result.realizado), required_money_keys={"planned", "actual", "variance"})

    alert_rows: list[dict[str, Any]] = []
    for warning in result.warnings:
        details = warning.get("details") or []
        if not details:
            alert_rows.append({"alert": warning.get("title"), "summary": warning.get("summary")})
        for detail in details:
            suggestions = detail.get("suggestions") or []
            sug_text = " | ".join(
                f"{s.get('code')} - {s.get('supplier')} ({round(float(s.get('score',0))*100,1)}%)"
                for s in suggestions
            )
            alert_rows.append({
                "alert": warning.get("title"), "summary": warning.get("summary"),
                "source_file": detail.get("source_file"), "source_sheet": detail.get("source_sheet"), "source_row": detail.get("source_row"),
                "title": detail.get("title"), "supplier_code": detail.get("supplier_code"), "supplier": detail.get("supplier"),
                "value": detail.get("value"), "suggestions": sug_text,
            })
    a_path = exports / "Alertas_validacao.xlsx"
    _write_xlsx(a_path, "ALERTAS", [
        ("alert", "Alerta"), ("summary", "Resumo"), ("source_file", "Arquivo"), ("source_sheet", "Aba"), ("source_row", "Linha"),
        ("title", "Título"), ("supplier_code", "Cód Fornecedor"), ("supplier", "Fornecedor"), ("value", "Valor"), ("suggestions", "Sugestões não aplicadas"),
    ], alert_rows)

    updated_path = exports / "Relatorio_atualizado_reimportavel.xlsx"
    _write_updated_report_workbook(updated_path, result)

    return {
        "previsto": str(p_path.relative_to(output_dir)).replace("\\", "/"),
        "realizado": str(r_path.relative_to(output_dir)).replace("\\", "/"),
        "fornecedores": str(s_path.relative_to(output_dir)).replace("\\", "/"),
        "alertas": str(a_path.relative_to(output_dir)).replace("\\", "/"),
        "atualizado": str(updated_path.relative_to(output_dir)).replace("\\", "/"),
    }
