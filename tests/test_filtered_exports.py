from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from app.services.excel_export import export_filtered_report_workbook
from app.services.excel_reader import read_excel
from app.services.reconciler import ReconcileResult
from app.services.sheet_detector import detect_input_tables
from webapp.engine import WebEngine


def _row(kind: str, index: int, supplier: str, category: str, flow: str, date: str, value: float, title: str):
    return {
        "kind": kind,
        "source_file": f"{kind}.xlsx",
        "source_sheet": kind.upper(),
        "source_row": (100 if kind == "previsto" else 200) + index,
        "title": title,
        "supplier_code": f"C{index}",
        "supplier_source": supplier,
        "supplier": supplier,
        "supplier_key": f"code:C{index}",
        "date": date,
        "due_date": date if kind == "realizado" else None,
        "value": value,
        "flow": flow,
        "category": category,
        "match": "base_codigo",
        "punctuality": "Dentro do Prazo" if kind == "realizado" else "",
    }


@pytest.fixture
def result() -> ReconcileResult:
    previsto = [
        _row("previsto", 1, "Fornecedor Compartilhado", "Categoria A", "Fluxo 1", "2026-01-05", 10, "Alpha"),
        _row("previsto", 2, "Fornecedor Outro", "Categoria A", "Fluxo 2", "2026-02-10", 20, "Beta"),
        _row("previsto", 3, "Fornecedor Compartilhado", "Categoria B", "Fluxo 1", "2026-02-15", 30, "Gamma"),
        _row("previsto", 4, "Fornecedor Terceiro", "Categoria B", "Fluxo 2", "2026-03-20", 40, "Delta"),
    ]
    realizado = [
        _row("realizado", 1, "Fornecedor Compartilhado", "Categoria A", "Fluxo 1", "2026-01-05", 11, "Alpha"),
        _row("realizado", 2, "Fornecedor Outro", "Categoria A", "Fluxo 2", "2026-02-10", 22, "Beta"),
        _row("realizado", 3, "Fornecedor Compartilhado", "Categoria B", "Fluxo 1", "2026-02-15", 33, "Gamma"),
        _row("realizado", 4, "Fornecedor Terceiro", "Categoria B", "Fluxo 2", "2026-03-20", 44, "Delta"),
    ]
    return ReconcileResult(previsto, realizado, [], "JAN/26 a MAR/26", 2026, 3, 4)


SCENARIOS = [
    ("sem filtro", {}, 4, 100, 4, 110),
    ("categoria", {"category": ["Categoria A"]}, 2, 30, 2, 33),
    ("fluxo", {"flow": ["Fluxo 1"]}, 2, 40, 2, 44),
    ("fornecedor nos dois lados", {"supplier": ["Fornecedor Compartilhado"]}, 2, 40, 2, 44),
    ("mês", {"emission": ["2026-02"], "emission_mode": "month"}, 2, 50, 2, 55),
    ("data exata", {"emission": ["2026-02-15"], "emission_mode": "date"}, 1, 30, 1, 33),
    ("pesquisa", {"search": "gamma"}, 1, 30, 1, 33),
    ("combinados", {"category": ["Categoria B"], "flow": ["Fluxo 2"], "emission": ["2026-03"], "search": "terceiro"}, 1, 40, 1, 44),
    ("zero registros", {"search": "inexistente"}, 0, 0, 0, 0),
]


@pytest.mark.parametrize("_name,filters,p_count,p_total,r_count,r_total", SCENARIOS)
def test_backend_reapplies_every_global_filter(_name, filters, p_count, p_total, r_count, r_total, result):
    filtered = WebEngine.filter_report_result(result, filters)
    assert len(filtered.previsto) == p_count
    assert sum(row["value"] for row in filtered.previsto) == p_total
    assert len(filtered.realizado) == r_count
    assert sum(row["value"] for row in filtered.realizado) == r_total


@pytest.mark.parametrize("_name,filters,p_count,p_total,r_count,r_total", SCENARIOS)
def test_filtered_xlsx_contents_reconcile_and_never_mix(_name, filters, p_count, p_total, r_count, r_total, result, tmp_path):
    filtered = WebEngine.filter_report_result(result, filters)
    previsto_path = export_filtered_report_workbook(filtered, tmp_path / "previsto", "previsto")
    realizado_path = export_filtered_report_workbook(filtered, tmp_path / "realizado", "realizado")
    atualizado_path = export_filtered_report_workbook(filtered, tmp_path / "atualizado", "atualizado")

    previsto = read_excel(previsto_path).tables[0]
    realizado = read_excel(realizado_path).tables[0]
    assert len(previsto.rows) == p_count
    assert sum(float(row["Valor previsto"]) for row in previsto.rows) == p_total
    assert len(realizado.rows) == r_count
    assert sum(float(row["Vlr.Original"]) for row in realizado.rows) == r_total
    assert {row["Linha"] for row in previsto.rows}.isdisjoint({row["Linha"] for row in realizado.rows})

    detection = detect_input_tables([read_excel(atualizado_path)])
    assert len(detection.previsto.rows) == p_count
    assert len(detection.realizado.rows) == r_count
    assert sum(float(row["Valor previsto"]) for row in detection.previsto.rows) == p_total
    assert sum(float(row["Vlr.Original"]) for row in detection.realizado.rows) == r_total
    for table in (detection.previsto, detection.realizado):
        assert all(str(row.get("Fluxo JMM") or "").strip() for row in table.rows)
        assert all(str(row.get("Categoria") or "").strip() for row in table.rows)
    with ZipFile(atualizado_path) as archive:
        worksheet_xml = b"".join(archive.read(name) for name in archive.namelist() if name.startswith("xl/worksheets/") and name.endswith(".xml"))
    assert b"<f" not in worksheet_xml


def test_filter_payload_cannot_replace_financial_rows(result):
    filtered = WebEngine.filter_report_result(result, {"previsto": [{"value": 999999}], "realizado": [], "search": "Alpha"})
    assert [row["value"] for row in filtered.previsto] == [10]
    assert [row["value"] for row in filtered.realizado] == [11]
