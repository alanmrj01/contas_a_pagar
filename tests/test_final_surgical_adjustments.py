from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
import xlsxwriter

from app.services.excel_export import export_filtered_report_workbook
from app.services.excel_reader import TableData, UncalculatedFormula, read_excel
from app.services.metrics import category_waterfall
from app.services.normalizer import ValueParseError, to_date, to_float
from app.services.reconciler import reconcile
from app.services.sheet_detector import InputDetection
from webapp.engine import WebEngine


def source(row: int, **values):
    return {
        **values,
        "__source_file__": "cirurgico.xlsx",
        "__source_path__": "cirurgico.xlsx",
        "__source_sheet__": "PREVISTO",
        "__source_row__": row,
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1234.56, 1234.56),
        ("1234.56", 1234.56),
        ("1.234,56", 1234.56),
        ("R$ 1.234,56", 1234.56),
        ("US$ 1,234.56", 1234.56),
        ("1,234,567", 1234567.0),
        ("R$\u00a01.234,56", 1234.56),
        ("(1.234,56)", -1234.56),
    ],
)
def test_deterministic_money_formats(raw, expected):
    assert to_float(raw, field="Valor previsto") == expected


@pytest.mark.parametrize("raw", [None, "", "1,234", "1.234", "12,34,56", "=A1+B1", True])
def test_missing_ambiguous_or_uncalculated_money_never_becomes_zero(raw):
    with pytest.raises(ValueParseError):
        to_float(raw, field="Valor previsto")


def test_excel_native_serial_and_supported_text_dates_are_deterministic():
    assert to_date(45292) == date(2024, 1, 1)
    assert to_date(datetime(2026, 7, 15, 13, 45)) == date(2026, 7, 15)
    assert to_date(date(2026, 7, 15)) == date(2026, 7, 15)
    assert to_date("15/07/2026") == date(2026, 7, 15)
    assert to_date("2026-07-15") == date(2026, 7, 15)
    assert to_date("31/02/2026") is None
    assert to_date(123) is None


def test_excel_formula_uses_cached_value_and_exposes_formula_without_cache(tmp_path):
    cached_path = tmp_path / "formula_cache.xlsx"
    workbook = xlsxwriter.Workbook(cached_path)
    sheet = workbook.add_worksheet("PREVISTO")
    sheet.write(0, 0, "Valor previsto")
    sheet.write_formula(1, 0, "=1200+34.56", None, 1234.56)
    workbook.close()
    cached = read_excel(cached_path).tables[0].rows[0]["Valor previsto"]
    assert cached == 1234.56
    assert to_float(cached, field="Valor previsto") == 1234.56

    uncached_path = tmp_path / "formula_sem_cache.xlsx"
    workbook = xlsxwriter.Workbook(uncached_path)
    sheet = workbook.add_worksheet("PREVISTO")
    sheet.write(0, 0, "Valor previsto")
    sheet.write_formula(1, 0, "=1200+34.56", None, "")
    workbook.close()
    uncached = read_excel(uncached_path).tables[0].rows[0]["Valor previsto"]
    assert isinstance(uncached, UncalculatedFormula)
    assert str(uncached) == "=1200+34.56"
    with pytest.raises(ValueParseError):
        to_float(uncached, field="Valor previsto")


def test_manual_value_and_date_corrections_are_cell_scoped_and_preserve_provenance():
    previsto = TableData(
        "PREVISTO",
        ["Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto"],
        [
            source(2, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Data prevista": "15/07/2026", "Valor previsto": "1,234"}),
            source(3, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Data prevista": "31/02/2026", "Valor previsto": 10}),
        ],
    )
    realizado = TableData(
        "REALIZADO",
        ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento"],
        [],
    )
    base = TableData(
        "BASE DADOS",
        ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"],
        [source(10, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Fluxo JMM": "Fluxo", "Categoria": "Categoria"})],
    )
    detection = InputDetection([previsto], [realizado], [])
    before = reconcile(detection.previsto, detection.realizado, base)
    assert sum(row["value"] for row in before.previsto) == 10
    assert any(warning["title"] == "Valores inválidos no PREVISTO" for warning in before.warnings)
    assert any(warning["title"] == "Datas inválidas no PREVISTO" for warning in before.warnings)

    corrections = [
        {"source_file": "cirurgico.xlsx", "source_sheet": "PREVISTO", "source_row": 2, "field": "Valor previsto", "value": "R$ 1.234,56"},
        {"source_file": "cirurgico.xlsx", "source_sheet": "PREVISTO", "source_row": 3, "field": "Data prevista", "value": "16/07/2026"},
    ]
    normalized = WebEngine._apply_manual_corrections(detection, corrections)
    assert normalized[0]["parsed_value"] == 1234.56
    assert normalized[1]["parsed_value"] == "2026-07-16"
    after = reconcile(detection.previsto, detection.realizado, base)
    assert sum(row["value"] for row in after.previsto) == 1244.56
    assert [row["date"] for row in after.previsto] == ["2026-07-15", "2026-07-16"]
    assert {(row["source_file"], row["source_sheet"], row["source_row"]) for row in after.previsto} == {
        ("cirurgico.xlsx", "PREVISTO", 2),
        ("cirurgico.xlsx", "PREVISTO", 3),
    }
    assert not any(warning["title"].startswith(("Valores inválidos", "Datas inválidas")) for warning in after.warnings)


def test_manual_correction_rejects_ambiguous_value_before_mutating_source():
    row = source(2, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Data prevista": "15/07/2026", "Valor previsto": "1,234"})
    detection = InputDetection(
        [TableData("PREVISTO", ["Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto"], [row])],
        [TableData("REALIZADO", ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento"], [])],
        [],
    )
    with pytest.raises(RuntimeError, match="ambíguo"):
        WebEngine._apply_manual_corrections(detection, [{
            "source_file": "cirurgico.xlsx",
            "source_sheet": "PREVISTO",
            "source_row": 2,
            "field": "Valor previsto",
            "value": "1,234",
        }])
    assert row["Valor previsto"] == "1,234"


def test_optional_subcategory_reconciles_filters_and_exports_without_breaking_old_base(tmp_path):
    previsto = TableData(
        "PREVISTO",
        ["Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto"],
        [source(2, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Data prevista": "15/07/2026", "Valor previsto": 100})],
    )
    realizado = TableData(
        "REALIZADO",
        ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento"],
        [{
            **source(3),
            "__source_sheet__": "REALIZADO",
            "Título": "R-1",
            "Fornecedor": "1",
            "Nome Fornecedor": "Fornecedor A",
            "Vlr.Original": 80,
            "Ult. Pgto.": "15/07/2026",
            "Vencimento": "15/07/2026",
        }],
    )
    base_with_subcategory = TableData(
        "BASE DADOS",
        ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria", "Subcategoria"],
        [source(10, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Fluxo JMM": "Fluxo", "Categoria": "Compras Extras SPOT", "Subcategoria": "TI"})],
    )
    result = reconcile(previsto, realizado, base_with_subcategory)
    assert {row["subcategory"] for row in [*result.previsto, *result.realizado]} == {"TI"}
    filtered = WebEngine.filter_report_result(result, {"subcategory": ["TI"]})
    assert len(filtered.previsto) == len(filtered.realizado) == 1
    waterfall = category_waterfall(filtered.previsto, filtered.realizado)
    assert waterfall["planned"] + sum(step["contribution"] for step in waterfall["steps"]) == waterfall["actual"] == 80
    assert WebEngine.filter_report_result(result, {"subcategory": ["Manutenção"]}).previsto == []
    exported = export_filtered_report_workbook(filtered, tmp_path, "previsto")
    exported_table = read_excel(exported).tables[0]
    assert "Subcategoria" in exported_table.headers
    assert exported_table.rows[0]["Subcategoria"] == "TI"

    old_base = TableData(
        "BASE DADOS",
        ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"],
        [source(10, **{"Cód Fornecedor": "1", "Fornecedor": "Fornecedor A", "Fluxo JMM": "Fluxo", "Categoria": "Compras Extras SPOT"})],
    )
    legacy_result = reconcile(previsto, realizado, old_base)
    assert {row["subcategory"] for row in [*legacy_result.previsto, *legacy_result.realizado]} == {""}
