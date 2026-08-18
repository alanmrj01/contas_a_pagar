import sys
import types

# Permite testar a lógica pura mesmo em ambiente sem python-calamine.
if "python_calamine" not in sys.modules:
    module = types.ModuleType("python_calamine")
    module.CalamineWorkbook = type("Dummy", (), {})
    sys.modules["python_calamine"] = module

import pytest

from app.services.excel_reader import TableData, WorkbookData
from app.services.reconciler import reconcile
from app.services.sheet_detector import SheetDetectionError, detect_input_tables, table_role


def src(row, **values):
    return {
        "__source_file__": "cliente.xlsx",
        "__source_sheet__": "Base de dados",
        "__source_row__": row,
        **values,
    }


def test_consolidated_client_layout_is_split_deterministically():
    headers = ["Título", "Tipo", "Cód Fornecedor", "Fornecedor", "Data", "Previsto", "Realizado", "Situação FC", "Mês ", "Fluxo JMM", "Categoria "]
    table = TableData("Base de dados", headers, [
        src(2, **{"Título": "PREV CONTRATO", "Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR A", "Data": 46145, "Previsto": 100, "Realizado": 100, "Situação FC": "Previsto", "Mês ": "MAIO", "Fluxo JMM": "NAO USAR", "Categoria ": "NAO USAR"}),
        src(3, **{"Título": "NF-1", "Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR A", "Data": 46146, "Previsto": 90, "Realizado": -90, "Situação FC": "Realizado ", "Mês ": "MAIO", "Fluxo JMM": "ERRADO", "Categoria ": "ERRADO"}),
    ])
    wb = WorkbookData(path=None, tables=[table])  # type: ignore[arg-type]
    assert table_role(table) == "consolidado"
    detection = detect_input_tables([wb])
    assert len(detection.previsto.rows) == 1
    assert len(detection.realizado.rows) == 1
    assert detection.previsto.rows[0]["Valor previsto"] == 100
    assert detection.realizado.rows[0]["Vlr.Original"] == 90
    assert detection.realizado.rows[0]["Fornecedor"] == 10
    assert detection.realizado.rows[0]["Nome Fornecedor"] == "FORNECEDOR A"
    assert detection.realizado.rows[0]["Emissão"] == 46146
    assert detection.realizado.rows[0]["Vencimento"] is None
    assert detection.notes

    base = TableData("BASE DADOS", ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"], [
        src(2, **{"Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR A", "Fluxo JMM": "FLUXO CERTO", "Categoria": "CATEGORIA CERTA"})
    ])
    result = reconcile(detection.previsto, detection.realizado, base)
    assert result.previsto[0]["value"] == 100
    assert result.realizado[0]["value"] == 90
    assert result.realizado[0]["flow"] == "FLUXO CERTO"
    assert result.realizado[0]["category"] == "CATEGORIA CERTA"
    assert result.realizado[0]["emission_date"] == result.realizado[0]["date"]
    assert result.realizado[0]["punctuality"] == "Sem data"



def test_consolidated_valor_valor2_layout_is_split_deterministically():
    headers = ["Título", "Tipo", "Cód Fornecedor", "Fornecedor", "Data", "Valor", "Valor2", "Situação FC", "Mês ", "Fluxo JMM", "Categoria "]
    table = TableData("Base de dados", headers, [
        src(2, **{"Título": "PREV CONTRATO", "Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR A", "Data": 46145, "Valor": 14369.68, "Valor2": 14369.68, "Situação FC": "Previsto", "Mês ": "MAIO"}),
        src(3, **{"Título": "NF-1", "Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR A", "Data": 46146, "Valor": 162.18, "Valor2": -162.18, "Situação FC": "Realizado ", "Mês ": "MAIO"}),
    ])
    wb = WorkbookData(path=None, tables=[table])  # type: ignore[arg-type]

    assert table_role(table) == "consolidado"
    detection = detect_input_tables([wb])
    assert len(detection.previsto.rows) == 1
    assert len(detection.realizado.rows) == 1
    assert detection.previsto.rows[0]["Valor previsto"] == 14369.68
    assert detection.realizado.rows[0]["Vlr.Original"] == 162.18
    assert detection.realizado.rows[0]["Fornecedor"] == 10
    assert detection.realizado.rows[0]["Nome Fornecedor"] == "FORNECEDOR A"
    assert any("Valor alimenta PREVISTO" in note for note in detection.notes)

def test_unsupported_layout_has_friendly_specific_error():
    table = TableData("Dados", ["Fornecedor qualquer", "Valor qualquer"], [src(2, **{"Fornecedor qualquer": "A", "Valor qualquer": 10})])
    wb = WorkbookData(path=type("P", (), {"name": "invalido.xlsx"})(), tables=[table])  # lightweight path-like for message
    with pytest.raises(SheetDetectionError) as exc:
        detect_input_tables([wb])
    message = str(exc.value)
    assert "Não consegui identificar com segurança" in message
    assert "Relatórios separados" in message
    assert "Relatório consolidado" in message
    assert "Colunas encontradas" in message
    assert "Fornecedor qualquer" in message


def test_standard_separate_layout_remains_supported_without_regression():
    previsto = TableData("PREVISTO", ["Título Previsto", "Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto", "Mês"], [
        src(2, **{"Título Previsto": "PREV CONTRATO", "Cód Fornecedor": 4034, "Fornecedor": "3M DO BRASIL LTDA", "Data prevista": 46163, "Valor previsto": 100.0, "Mês": "MAIO"})
    ])
    realizado = TableData("REALIZADO", ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento"], [
        src(2, **{"Título": "743528/01", "Fornecedor": 4034, "Nome Fornecedor": "3M DO BRASIL LTDA", "Vlr.Original": 90.0, "Ult. Pgto.": 46163, "Vencimento": 46163})
    ])
    wb = WorkbookData(path=type("P", (), {"name": "padrao.xlsx"})(), tables=[previsto, realizado])
    detection = detect_input_tables([wb])
    assert len(detection.previsto.rows) == 1
    assert len(detection.realizado.rows) == 1
    assert detection.previsto.rows[0]["Valor previsto"] == 100.0
    assert detection.realizado.rows[0]["Vlr.Original"] == 90.0
    assert detection.notes == []
