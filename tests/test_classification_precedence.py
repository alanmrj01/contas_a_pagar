from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.services.excel_export import _write_updated_report_workbook
from app.services.excel_reader import TableData, read_excel
from app.services.metrics import chart_data, summarize
from app.services.reconciler import ReconcileResult, reconcile
from app.services.sheet_detector import detect_base_table, detect_input_tables


BASE_HEADERS = ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"]
PREVISTO_HEADERS = [
    "Título Previsto", "Cód Fornecedor", "Fornecedor", "Data prevista",
    "Valor previsto", "Fluxo JMM", "Categoria",
]
REALIZADO_HEADERS = [
    "Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original",
    "Ult. Pgto.", "Vencimento", "Fluxo JMM", "Categoria",
]


def _row(source_row: int = 2, **values):
    return {
        "__source_file__": "teste.xlsx",
        "__source_sheet__": "Dados",
        "__source_row__": source_row,
        **values,
    }


def _base(*rows):
    return TableData("BASE DADOS", BASE_HEADERS, list(rows))


def _previsto(*rows):
    return TableData("PREVISTO", PREVISTO_HEADERS, list(rows))


def _realizado(*rows):
    return TableData("REALIZADO", REALIZADO_HEADERS, list(rows))


def _reconcile(base_rows, previsto_rows=(), realizado_rows=()):
    return reconcile(_previsto(*previsto_rows), _realizado(*realizado_rows), _base(*base_rows))


def _p(code, name, flow="", category="", row=2, value=100.0):
    return _row(row, **{
        "Título Previsto": f"P-{row}", "Cód Fornecedor": code, "Fornecedor": name,
        "Data prevista": "01/05/2026", "Valor previsto": value,
        "Fluxo JMM": flow, "Categoria": category,
    })


def _r(code, name, flow="", category="", row=2, value=100.0):
    return _row(row, **{
        "Título": f"R-{row}", "Fornecedor": code, "Nome Fornecedor": name,
        "Vlr.Original": value, "Ult. Pgto.": "01/05/2026", "Vencimento": "01/05/2026",
        "Fluxo JMM": flow, "Categoria": category,
    })


def test_fixed_base_code_overrides_conflicting_spreadsheet_classification():
    result = _reconcile(
        [_row(**{"Cód Fornecedor": 10, "Fornecedor": "Fornecedor Base", "Fluxo JMM": "Fluxo Base", "Categoria": "Categoria Base"})],
        [_p(10, "Outro nome", "Fluxo Planilha", "Categoria Planilha")],
    )
    item = result.previsto[0]
    assert (item["flow"], item["category"], item["match"]) == (
        "Fluxo Base", "Categoria Base", "base_codigo",
    )


def test_unknown_code_uses_only_unique_exact_normalized_base_name():
    result = _reconcile(
        [_row(**{"Cód Fornecedor": 10, "Fornecedor": "ÁCME, LTDA.", "Fluxo JMM": "Fluxo Base", "Categoria": "Categoria Base"})],
        [_p(999, "acme ltda")],
    )
    assert result.previsto[0]["match"] == "base_nome"
    assert result.previsto[0]["supplier_key"] == "BASE:10"


def test_ambiguous_normalized_name_is_never_used_as_fallback():
    result = _reconcile(
        [
            _row(2, **{"Cód Fornecedor": 10, "Fornecedor": "Fornecedor ABC", "Fluxo JMM": "F1", "Categoria": "C1"}),
            _row(3, **{"Cód Fornecedor": 11, "Fornecedor": "FORNECEDOR-ABC", "Fluxo JMM": "F2", "Categoria": "C2"}),
        ],
        [_p(999, "fornecedor abc")],
    )
    assert result.previsto[0]["match"] == "nao_resolvida"
    assert result.previsto[0]["flow"] == "Não classificado"


def test_unique_history_from_same_code_classifies_missing_row():
    result = _reconcile(
        [_row(**{"Cód Fornecedor": 10, "Fornecedor": "Base", "Fluxo JMM": "FB", "Categoria": "CB"})],
        realizado_rows=[
            _r("EXT-7", "Externo", "Fluxo Direto", "Categoria Direta", row=2),
            _r("EXT-7", "Externo", row=3),
        ],
    )
    assert [item["match"] for item in result.realizado] == ["planilha_direta", "historico_codigo"]
    assert result.realizado[1]["flow"] == "Fluxo Direto"


def test_conflicting_history_does_not_classify_missing_row():
    result = _reconcile(
        [_row(**{"Cód Fornecedor": 10, "Fornecedor": "Base", "Fluxo JMM": "FB", "Categoria": "CB"})],
        realizado_rows=[
            _r("EXT-8", "Externo", "Fluxo A", "Categoria A", row=2),
            _r("EXT-8", "Externo", "Fluxo B", "Categoria B", row=3),
            _r("EXT-8", "Externo", row=4),
        ],
    )
    assert [item["match"] for item in result.realizado] == [
        "planilha_direta", "planilha_direta", "nao_resolvida",
    ]
    assert result.realizado[2]["category"] == "Não classificado"


def test_truly_unresolved_record_stays_explicit_and_warned():
    result = _reconcile(
        [_row(**{"Cód Fornecedor": "001", "Fornecedor": "Base", "Fluxo JMM": "FB", "Categoria": "CB"})],
        previsto_rows=[_p(1, "Nome sem correspondência")],
    )
    item = result.previsto[0]
    assert item["supplier_code"] == "1"
    assert item["match"] == "nao_resolvida"
    assert item["flow"] == item["category"] == "Não classificado"
    assert any(warning["title"] == "Classificação ausente no PREVISTO" for warning in result.warnings)


def _business_signature(result: ReconcileResult):
    fields = (
        "kind", "title", "supplier_code", "supplier", "supplier_key", "date",
        "emission_date", "due_date", "value", "flow", "category",
    )
    return [tuple(item.get(field) for field in fields) for item in result.previsto + result.realizado]


def _synthetic_roundtrip_result():
    base_rows = [_row(**{"Cód Fornecedor": 10, "Fornecedor": "Fornecedor Base", "Fluxo JMM": "Fluxo Base", "Categoria": "Categoria Base"})]
    return _reconcile(
        base_rows,
        previsto_rows=[
            _p(10, "Fornecedor Base", "Ignorado", "Ignorada", row=2, value=150),
            _p("EXT-9", "Fornecedor Externo", "Fluxo Externo", "Categoria Externa", row=3, value=50),
        ],
        realizado_rows=[
            _r(10, "Fornecedor Base", row=4, value=170),
            _r("EXT-9", "Fornecedor Externo", row=5, value=60),
        ],
    ), _base(*base_rows)


def test_updated_workbook_roundtrip_materializes_classifications_without_formulas(tmp_path):
    first, base = _synthetic_roundtrip_result()
    exported = tmp_path / "Relatorio_atualizado_reimportavel.xlsx"
    _write_updated_report_workbook(exported, first)

    with ZipFile(exported) as archive:
        worksheet_xml = b"".join(
            archive.read(name) for name in archive.namelist() if name.startswith("xl/worksheets/sheet")
        )
        assert b"<f" not in worksheet_xml
        assert not any(name.startswith("xl/externalLinks/") for name in archive.namelist())

    detection = detect_input_tables([read_excel(exported)])
    second = reconcile(detection.previsto, detection.realizado, base)
    assert _business_signature(second) == _business_signature(first)
    assert summarize(second.previsto, second.realizado) == summarize(first.previsto, first.realizado)
    assert chart_data(second.previsto, second.realizado)["flows"] == chart_data(first.previsto, first.realizado)["flows"]
    assert all(item["flow"] != "Não classificado" for item in second.previsto + second.realizado)


def _regression_paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[1]
    candidates = []
    configured = os.environ.get("CONTAS_PAGAR_REGRESSION_DIR")
    if configured:
        candidates.append(Path(configured))
    candidates.extend([root.parent, Path.home() / "Downloads"])
    for directory in candidates:
        base = directory / "BASE_DADOS.xlsx"
        report = directory / "Report prev e real - 05.06.07.xlsx"
        if base.is_file() and report.is_file():
            return base, report
    pytest.skip("Arquivos reais de regressão não disponíveis neste ambiente.")


def _real_result():
    base_path, report_path = _regression_paths()
    base = detect_base_table(read_excel(base_path))
    detection = detect_input_tables([read_excel(report_path)])
    return reconcile(detection.previsto, detection.realizado, base), base


def _assert_expected_real_indicators(result: ReconcileResult):
    summary = summarize(result.previsto, result.realizado)
    assert len(result.previsto) + len(result.realizado) == 2377
    assert (len(result.previsto), len(result.realizado)) == (290, 2087)
    assert round(summary["planned"], 2) == 19316472.20
    assert round(summary["actual"], 2) == 24650245.76
    assert round(summary["variance"], 2) == 5333773.56
    assert round(summary["variance_pct"], 2) == 27.61
    assert summary["suppliers"] == 265
    assert all(
        item["flow"] != "Não classificado" and item["category"] != "Não classificado"
        for item in result.previsto + result.realizado
    )
    flows = {row["label"]: round(row["variance"], 2) for row in chart_data(result.previsto, result.realizado)["flows"]}
    assert flows == {
        "Gastos Generales": 4346351.14,
        "Materia prima/peças": 984508.86,
        "Institución bancaria": -830000.00,
        "Nominas": 692526.48,
        "Otros Impuestos": 140387.08,
    }
    assert round(sum(flows.values()), 2) == 5333773.56


def test_real_regression_kpis_waterfall_and_classification_origins():
    result, _ = _real_result()
    _assert_expected_real_indicators(result)
    assert Counter(item["match"] for item in result.previsto) == Counter({
        "base_codigo": 287, "base_nome": 2, "planilha_direta": 1,
    })
    assert Counter(item["match"] for item in result.realizado) == Counter({
        "base_codigo": 1981, "base_nome": 8, "planilha_direta": 67, "historico_codigo": 31,
    })


def test_real_updated_workbook_roundtrip_remains_identical(tmp_path):
    first, base = _real_result()
    exported = tmp_path / "Relatorio_atualizado_reimportavel.xlsx"
    _write_updated_report_workbook(exported, first)
    detection = detect_input_tables([read_excel(exported)])
    second = reconcile(detection.previsto, detection.realizado, base)

    _assert_expected_real_indicators(second)
    assert _business_signature(second) == _business_signature(first)
    assert summarize(second.previsto, second.realizado) == summarize(first.previsto, first.realizado)
    assert chart_data(second.previsto, second.realizado)["flows"] == chart_data(first.previsto, first.realizado)["flows"]
