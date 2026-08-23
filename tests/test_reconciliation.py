import sys
import types

# Permite testar a lógica pura mesmo em ambiente sem python-calamine.
if "python_calamine" not in sys.modules:
    module = types.ModuleType("python_calamine")
    module.CalamineWorkbook = type("Dummy", (), {})
    sys.modules["python_calamine"] = module

from app.services.excel_reader import TableData
from app.services.reconciler import reconcile


def row(**kwargs):
    base = {"__source_file__": "teste.xlsx", "__source_sheet__": "S", "__source_row__": 2}
    base.update(kwargs)
    return base


def test_ambiguous_similar_name_is_not_auto_classified():
    base = TableData("BASE DADOS", ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"], [
        row(**{"Cód Fornecedor": 21, "Fornecedor": "SECRETARIA DA RECEIT", "Fluxo JMM": "Otros Impuestos", "Categoria": "IMPOSTOS DIVERSOS"}),
        row(**{"Cód Fornecedor": 22, "Fornecedor": "SECRETARIA DA RECEIT", "Fluxo JMM": "Otros Impuestos", "Categoria": "IMPOSTOS IR E INSS"}),
    ])
    previsto = TableData("PREVISTO", ["Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto"], [
        row(**{"Cód Fornecedor": 22, "Fornecedor": "SECRETARIA DA RECEITA", "Data prevista": "01/05/2026", "Valor previsto": 100})
    ])
    realizado = TableData("REALIZADO", ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento"], [
        row(**{"Título": "X", "Fornecedor": 2, "Nome Fornecedor": "SECRETARIA DA RECEITA FEDERAL", "Vlr.Original": 90, "Ult. Pgto.": "01/05/2026", "Vencimento": "01/05/2026"})
    ])
    result = reconcile(previsto, realizado, base)
    assert result.previsto[0]["category"] == "IMPOSTOS IR E INSS"
    assert result.realizado[0]["category"] == "Não classificado"
    assert result.realizado[0]["match"] == "nao_resolvida"
    assert result.realizado[0]["punctuality"] == "Dentro do Prazo"
    assert result.warnings and result.warnings[0]["details"][0]["source_row"] == 2


def test_exact_unique_name_can_classify_when_code_missing():
    base = TableData("BASE DADOS", ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"], [
        row(**{"Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR TESTE LTDA", "Fluxo JMM": "Gastos", "Categoria": "RECORRENTE"})
    ])
    previsto = TableData("PREVISTO", ["Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto"], [
        row(**{"Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR TESTE LTDA", "Data prevista": "01/05/2026", "Valor previsto": 100})
    ])
    realizado = TableData("REALIZADO", ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento"], [
        row(**{"Título": "X", "Fornecedor": 999, "Nome Fornecedor": "FORNECEDOR TESTE LTDA", "Vlr.Original": 100, "Ult. Pgto.": "01/05/2026", "Vencimento": "01/05/2026"})
    ])
    result = reconcile(previsto, realizado, base)
    assert result.realizado[0]["category"] == "RECORRENTE"
    assert result.realizado[0]["match"] == "base_nome"


def test_realizado_emissao_is_preserved_as_iso_date_for_report_filter():
    base = TableData("BASE DADOS", ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"], [
        row(**{"Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR TESTE LTDA", "Fluxo JMM": "Gastos", "Categoria": "RECORRENTE"})
    ])
    previsto = TableData("PREVISTO", ["Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto"], [
        row(**{"Cód Fornecedor": 10, "Fornecedor": "FORNECEDOR TESTE LTDA", "Data prevista": "15/05/2026", "Valor previsto": 100})
    ])
    realizado = TableData(
        "REALIZADO",
        ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Emissão", "Ult. Pgto.", "Vencimento"],
        [row(**{
            "Título": "NF-1",
            "Fornecedor": 10,
            "Nome Fornecedor": "FORNECEDOR TESTE LTDA",
            "Vlr.Original": 100,
            "Emissão": "07/05/2026",
            "Ult. Pgto.": "15/05/2026",
            "Vencimento": "15/05/2026",
        })],
    )
    result = reconcile(previsto, realizado, base)
    assert result.realizado[0]["emission_date"] == "2026-05-07"
    assert result.realizado[0]["date"] == "2026-05-15"
