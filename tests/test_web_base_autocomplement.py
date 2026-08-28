from pathlib import Path

from app.services.excel_reader import TableData, WorkbookData
from app.services.reconciler import validate_base
from webapp.engine import WebEngine


def _base(rows):
    return TableData(
        sheet_name="BASE DADOS",
        headers=["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"],
        rows=rows,
        source_path=Path("base.xlsx"),
        header_row=1,
    )


def _input(rows):
    table = TableData(
        sheet_name="Dados importados",
        headers=["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"],
        rows=rows,
        source_path=Path("entrada.xlsx"),
        header_row=1,
    )
    return [WorkbookData(path=Path("entrada.xlsx"), tables=[table])]


def test_complementa_apenas_fornecedor_ausente_sem_sobrescrever_base():
    base = _base([
        {"Cód Fornecedor": 10, "Fornecedor": "Fornecedor Base", "Fluxo JMM": "Fluxo A", "Categoria": "Categoria A"},
    ])
    imported = _input([
        {"Cód Fornecedor": 10, "Fornecedor": "Nome diferente", "Fluxo JMM": "Outro fluxo", "Categoria": "Outra categoria"},
        {"Cód Fornecedor": 20, "Fornecedor": "Fornecedor Novo", "Fluxo JMM": "Fluxo B", "Categoria": "Categoria B"},
        {"Cód Fornecedor": 20, "Fornecedor": "Fornecedor Novo", "Fluxo JMM": "Fluxo B", "Categoria": "Categoria B"},
    ])

    augmented, info = WebEngine._supplement_base_from_imported_workbooks(base, imported)

    validate_base(augmented)
    assert len(base.rows) == 1
    assert base.rows[0]["Fluxo JMM"] == "Fluxo A"
    assert len(augmented.rows) == 2
    assert augmented.rows[0]["Fornecedor"] == "Fornecedor Base"
    assert augmented.rows[0]["Fluxo JMM"] == "Fluxo A"
    assert augmented.rows[1]["Cód Fornecedor"] == "20"
    assert augmented.rows[1]["Fornecedor"] == "Fornecedor Novo"
    assert augmented.rows[1]["Fluxo JMM"] == "Fluxo B"
    assert augmented.rows[1]["Categoria"] == "Categoria B"
    assert info["added_suppliers"] == 1
    assert info["affected_records"] == 2
    assert info["conflicting_suppliers"] == 0


def test_variacao_de_nome_e_aceita_quando_classificacao_e_identica():
    base = _base([])
    imported = _input([
        {"Cód Fornecedor": 30, "Fornecedor": "EMPRESA ABC", "Fluxo JMM": "Fluxo C", "Categoria": "Categoria C"},
        {"Cód Fornecedor": 30, "Fornecedor": "EMPRESA ABC LTDA", "Fluxo JMM": "Fluxo C", "Categoria": "Categoria C"},
        {"Cód Fornecedor": 30, "Fornecedor": "EMPRESA ABC LTDA", "Fluxo JMM": "Fluxo C", "Categoria": "Categoria C"},
    ])

    augmented, info = WebEngine._supplement_base_from_imported_workbooks(base, imported)

    validate_base(augmented)
    assert len(augmented.rows) == 1
    assert augmented.rows[0]["Fornecedor"] == "EMPRESA ABC LTDA"
    assert info["added_suppliers"] == 1
    assert info["affected_records"] == 3


def test_conflito_de_fluxo_ou_categoria_nao_e_classificado_automaticamente():
    base = _base([])
    imported = _input([
        {"Cód Fornecedor": 40, "Fornecedor": "Fornecedor Conflitante", "Fluxo JMM": "Fluxo X", "Categoria": "Categoria X"},
        {"Cód Fornecedor": 40, "Fornecedor": "Fornecedor Conflitante", "Fluxo JMM": "Fluxo Y", "Categoria": "Categoria X"},
    ])

    augmented, info = WebEngine._supplement_base_from_imported_workbooks(base, imported)

    assert augmented is base
    assert len(augmented.rows) == 0
    assert info["added_suppliers"] == 0
    assert info["conflicting_suppliers"] == 1


def test_frontend_nao_recomenda_mais_atualizacao_manual_da_base():
    js = (Path(__file__).parents[1] / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
    assert "Atualização da Base de Dados recomendada" not in js
    assert "Algumas classificações continuam incompletas." in js
    assert "complementado(s) com dados completos da planilha" in js
