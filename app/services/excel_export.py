from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import xlsxwriter

from .metrics import aggregate_suppliers
from .reconciler import ReconcileResult


HEADER_FMT = {"bold": True, "font_color": "#FFFFFF", "bg_color": "#234865", "border": 0, "align": "center", "valign": "vcenter"}
MONEY_FMT = {"num_format": 'R$ #,##0.00;[Red]-R$ #,##0.00'}
PCT_FMT = {"num_format": '0.00%;[Red]-0.00%'}
DATE_FMT = {"num_format": 'dd/mm/yyyy'}


def _write_xlsx(path: Path, sheet_name: str, columns: list[tuple[str, str]], rows: list[dict[str, Any]]) -> None:
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
                ws.write_number(r_idx, c_idx, float(value or 0.0), money)
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


def export_report_workbooks(result: ReconcileResult, output_dir: Path) -> dict[str, str]:
    exports = output_dir / "excel"
    exports.mkdir(parents=True, exist_ok=True)

    p_path = exports / "Previsto_normalizado.xlsx"
    _write_xlsx(p_path, "PREVISTO", [
        ("source_file", "Arquivo origem"), ("source_sheet", "Aba"), ("source_row", "Linha"),
        ("title", "Título previsto"), ("supplier_code", "Cód Fornecedor"), ("supplier_source", "Fornecedor original"),
        ("supplier", "Fornecedor classificado"), ("date", "Data prevista"), ("value", "Valor previsto"),
        ("flow", "Fluxo JMM"), ("category", "Categoria"), ("match", "Regra classificação"),
    ], result.previsto)

    r_path = exports / "Realizado_normalizado.xlsx"
    _write_xlsx(r_path, "REALIZADO", [
        ("source_file", "Arquivo origem"), ("source_sheet", "Aba"), ("source_row", "Linha"),
        ("title", "Título"), ("supplier_code", "Cód Fornecedor"), ("supplier_source", "Fornecedor original"),
        ("supplier", "Fornecedor classificado"), ("date", "Último pagamento"), ("due_date", "Vencimento"),
        ("value", "Vlr.Original"), ("flow", "Fluxo JMM"), ("category", "Categoria"),
        ("punctuality", "Pontualidade"), ("company", "Empresa"), ("branch", "Filial"),
        ("account", "Conta contábil"), ("financial_account", "Conta financeira"), ("cost_center", "Centro de custo"),
        ("match", "Regra classificação"),
    ], result.realizado)

    s_path = exports / "Analise_por_fornecedor.xlsx"
    _write_xlsx(s_path, "FORNECEDORES", [
        ("supplier_code", "Cód Fornecedor"), ("supplier", "Fornecedor"), ("category", "Categoria"), ("flow", "Fluxo JMM"),
        ("planned", "Previsto"), ("actual", "Realizado"), ("variance", "Desvio"), ("variance_pct", "Variação %"),
        ("planned_records", "Linhas previsto"), ("actual_records", "Títulos realizado"),
    ], aggregate_suppliers(result.previsto, result.realizado))

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

    return {
        "previsto": str(p_path.relative_to(output_dir)).replace("\\", "/"),
        "realizado": str(r_path.relative_to(output_dir)).replace("\\", "/"),
        "fornecedores": str(s_path.relative_to(output_dir)).replace("\\", "/"),
        "alertas": str(a_path.relative_to(output_dir)).replace("\\", "/"),
    }
