from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.excel_export import export_report_workbooks
from app.services.excel_reader import TableData, WorkbookData, read_excel
from app.services.normalizer import ValueParseError, to_float
from app.services.pdf_report import _category_month_rows
from app.services.reconciler import ReconcileResult, reconcile
from app.services.sheet_detector import _consolidated_value_columns, detect_base_table, detect_input_tables
from webapp.engine import WebEngine


BASE_HEADERS = ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"]
P_HEADERS = ["Título Previsto", "Cód Fornecedor", "Fornecedor", "Data prevista", "Valor previsto", "Fluxo JMM", "Categoria"]
R_HEADERS = ["Título", "Fornecedor", "Nome Fornecedor", "Vlr.Original", "Ult. Pgto.", "Vencimento", "Fluxo JMM", "Categoria"]


def _base(rows):
    return TableData("BASE DADOS", BASE_HEADERS, rows)


def _source(row_number, **values):
    return {
        "__source_file__": "entrada.xlsx",
        "__source_sheet__": "Dados",
        "__source_row__": row_number,
        **values,
    }


def _result(previsto, realizado):
    return ReconcileResult(
        previsto=previsto,
        realizado=realizado,
        warnings=[],
        period_label="JUN/26 A JUL/26",
        period_year=2026,
        period_month=7,
        base_rows=2,
    )


def _export_identity(row):
    return (str(row.get("Arquivo origem") or ""), str(row.get("Aba") or ""), int(row.get("Linha") or 0))


def test_missing_financial_value_is_never_silently_converted_to_zero():
    with pytest.raises(ValueParseError):
        to_float(None, field="Valor previsto")
    with pytest.raises(ValueParseError):
        to_float("  ", field="Vlr.Original")


def test_valor_valor2_uses_status_not_sign_and_exact_distinct_columns():
    consolidated = TableData(
        "Base de dados",
        ["Título", "Cód Fornecedor", "Fornecedor", "Data", "Valor", "Valor2", "Situação FC", "Fluxo JMM", "Categoria"],
        [
            _source(2, **{"Título": "P-1", "Cód Fornecedor": "P01", "Fornecedor": "Fornecedor P", "Data": "01/06/2026", "Valor": 125.5, "Valor2": -999, "Situação FC": "Previsto", "Fluxo JMM": "FP", "Categoria": "CP"}),
            _source(3, **{"Título": "R-1", "Cód Fornecedor": "R01", "Fornecedor": "Fornecedor R", "Data": "02/06/2026", "Valor": 777, "Valor2": -80.25, "Situação FC": "Realizado", "Fluxo JMM": "FR", "Categoria": "CR"}),
        ],
    )
    detection = detect_input_tables([WorkbookData(Path("entrada.xlsx"), [consolidated])])
    result = reconcile(
        detection.previsto,
        detection.realizado,
        _base([
            {"Cód Fornecedor": "P01", "Fornecedor": "Fornecedor P", "Fluxo JMM": "FP", "Categoria": "CP"},
            {"Cód Fornecedor": "R01", "Fornecedor": "Fornecedor R", "Fluxo JMM": "FR", "Categoria": "CR"},
        ]),
    )
    assert [row["value"] for row in result.previsto] == [125.5]
    assert [row["value"] for row in result.realizado] == [80.25]
    assert result.previsto[0]["kind"] == "previsto"
    assert result.realizado[0]["kind"] == "realizado"

    incomplete = TableData(
        "Inválida",
        ["Título", "Cód Fornecedor", "Fornecedor", "Data", "Valor2", "Situação FC"],
        [],
    )
    assert _consolidated_value_columns(incomplete) is None


@pytest.mark.parametrize("side", ["previsto", "realizado", "ambos"])
def test_excel_exports_are_strictly_partitioned_and_reconcile_counts_totals_and_origins(tmp_path, side):
    previsto = [{
        "kind": "previsto", "title": "P-1", "supplier_code": "10", "supplier_source": "Fornecedor A",
        "supplier": "Fornecedor A", "date": "2026-06-01", "value": 120.25, "flow": "F1", "category": "C1",
        "match": "base_codigo", "source_file": "entrada.xlsx", "source_sheet": "Previsto", "source_row": 2,
    }] if side in {"previsto", "ambos"} else []
    realizado = [{
        "kind": "realizado", "title": "R-1", "supplier_code": "10", "supplier_source": "Fornecedor A",
        "supplier": "Fornecedor A", "date": "2026-06-02", "due_date": "2026-06-03", "value": 95.75,
        "flow": "F1", "category": "C1", "punctuality": "Antecipado", "company": "", "branch": "",
        "account": "", "financial_account": "", "cost_center": "", "match": "base_codigo",
        "source_file": "entrada.xlsx", "source_sheet": "Realizado", "source_row": 2,
    }] if side in {"realizado", "ambos"} else []
    exports = export_report_workbooks(_result(previsto, realizado), tmp_path)
    p_rows = read_excel(tmp_path / exports["previsto"]).tables[0].rows
    r_rows = read_excel(tmp_path / exports["realizado"]).tables[0].rows

    assert len(p_rows) == len(previsto)
    assert len(r_rows) == len(realizado)
    assert sum(float(row.get("Valor previsto")) for row in p_rows) == sum(row["value"] for row in previsto)
    assert sum(float(row.get("Vlr.Original")) for row in r_rows) == sum(row["value"] for row in realizado)
    p_ids = {_export_identity(row) for row in p_rows}
    r_ids = {_export_identity(row) for row in r_rows}
    assert p_ids == {(row["source_file"], row["source_sheet"], row["source_row"]) for row in previsto}
    assert r_ids == {(row["source_file"], row["source_sheet"], row["source_row"]) for row in realizado}
    assert p_ids.intersection(r_ids) == set()


def test_real_excel_exports_reconcile_counts_totals_and_have_no_source_intersection(tmp_path):
    root = Path(__file__).resolve().parents[1]
    locations = (root.parent, Path.home() / "Downloads")
    pair = next((
        (directory / "BASE_DADOS.xlsx", directory / "Report prev e real - 05.06.07.xlsx")
        for directory in locations
        if (directory / "BASE_DADOS.xlsx").is_file()
        and (directory / "Report prev e real - 05.06.07.xlsx").is_file()
    ), None)
    if pair is None:
        pytest.skip("Arquivos reais de regressão não disponíveis neste ambiente.")
    base_path, report_path = pair
    base = detect_base_table(read_excel(base_path))
    detection = detect_input_tables([read_excel(report_path)])
    result = reconcile(detection.previsto, detection.realizado, base)
    exports = export_report_workbooks(result, tmp_path)
    p_rows = read_excel(tmp_path / exports["previsto"]).tables[0].rows
    r_rows = read_excel(tmp_path / exports["realizado"]).tables[0].rows

    assert (len(p_rows), len(r_rows)) == (290, 2087)
    assert round(sum(float(row["Valor previsto"]) for row in p_rows), 2) == 19316472.20
    assert round(sum(float(row["Vlr.Original"]) for row in r_rows), 2) == 24650245.76
    assert {_export_identity(row) for row in p_rows}.isdisjoint({_export_identity(row) for row in r_rows})


def test_web_supplier_code_normalization_does_not_merge_text_identifiers():
    assert WebEngine._code_key("001") == "001"
    assert WebEngine._code_key("1") == "1"
    assert WebEngine._code_key(1.0) == "1"
    assert WebEngine._code_key("001") != WebEngine._code_key("1")


def test_pdf_category_rows_keep_one_or_two_real_months_and_all_four_series():
    previsto = [
        {"date": "2026-05-01", "category": "C1", "value": 10},
        {"date": "2026-06-01", "category": "C1", "value": 20},
        {"date": "2026-07-01", "category": "C1", "value": 30},
    ]
    realizado = [
        {"date": "2026-06-02", "category": "C1", "value": 12},
        {"date": "2026-07-02", "category": "C1", "value": 18},
    ]
    rows, months = _category_month_rows(previsto, realizado)
    assert months == ["JUN/26", "JUL/26"]
    assert [item["label"] for item in rows[0]["series"]] == ["JUN/26 P", "JUN/26 R", "JUL/26 P", "JUL/26 R"]
    assert [item["value"] for item in rows[0]["series"]] == [20.0, 12.0, 30.0, 18.0]


def test_conflicting_temporary_complement_is_unclassified_end_to_end():
    base = _base([])
    previsto = TableData(
        "PREVISTO",
        P_HEADERS,
        [
            _source(2, **{"Título Previsto": "P1", "Cód Fornecedor": "X1", "Fornecedor": "Novo", "Data prevista": "01/06/2026", "Valor previsto": 10, "Fluxo JMM": "F1", "Categoria": "C1"}),
            _source(3, **{"Título Previsto": "P2", "Cód Fornecedor": "X1", "Fornecedor": "Novo", "Data prevista": "02/06/2026", "Valor previsto": 20, "Fluxo JMM": "F2", "Categoria": "C2"}),
        ],
    )
    imported = [WorkbookData(Path("entrada.xlsx"), [previsto])]
    effective, info = WebEngine._supplement_base_from_imported_workbooks(base, imported)
    result = reconcile(
        previsto,
        TableData("REALIZADO", R_HEADERS, []),
        effective,
        blocked_import_classification_codes=set(info["conflicting_codes"]),
    )
    assert info["conflicting_suppliers"] == 1
    assert [row["match"] for row in result.previsto] == ["nao_resolvida", "nao_resolvida"]
    assert all(row["flow"] == row["category"] == "Não classificado" for row in result.previsto)


class _MemoryPersistence:
    def __init__(self):
        self.saved = None

    def save_base(self, user_id, items):
        self.saved = ([dict(item) for item in items], "rev-1")
        return "rev-1"

    def load_base(self, user_id):
        return self.saved


class _MemoryStore:
    def __init__(self, root):
        self.root = root
        self.session = SimpleNamespace(
            authenticated_user_id="user-1", custom_base_table=None, custom_base_revision="", validated="anterior",
        )

    def state(self, sid):
        return self.session

    def new_work_dir(self, sid, name):
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def invalidate_validation(self, sid, preserve_last_outputs=True):
        self.session.validated = None


def test_base_edit_add_read_export_reload_and_invalid_update_preserves_previous_state(tmp_path):
    store = _MemoryStore(tmp_path)
    persistence = _MemoryPersistence()
    engine = WebEngine(Path(__file__).resolve().parents[1], store, persistence)
    items = [
        {"supplier_code": "001", "supplier": "Fornecedor Um", "flow": "Fluxo A", "category": "Categoria A"},
        {"supplier_code": "2", "supplier": "Fornecedor Dois", "flow": "Fluxo B", "category": "Categoria B"},
    ]
    info = engine.update_base("sid", items)
    assert info["rows"] == 2
    assert engine.base_rows("sid")["items"] == items
    exported = engine.export_base("sid")
    exported_table = read_excel(exported)
    assert WebEngine._base_items(exported_table.tables[0]) == items

    store.session.custom_base_table = None
    engine.load_persistent_base("sid")
    assert engine.base_rows("sid")["items"] == items

    with pytest.raises(Exception):
        engine.update_base("sid", [items[0], {**items[1], "supplier_code": "001"}])
    assert engine.base_rows("sid")["items"] == items
