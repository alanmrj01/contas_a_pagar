from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from .excel_reader import TableData
from .normalizer import ValueParseError, find_column, to_date, to_float
from .text_utils import normalize_text


class ReconcileError(RuntimeError):
    pass


@dataclass
class ReconcileResult:
    previsto: list[dict[str, Any]]
    realizado: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    period_label: str
    period_year: int | None
    period_month: int | None
    base_rows: int


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _code(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return str(value).strip()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).strip()
    # Identificadores textuais permanecem textuais: "001" não pode virar "1".
    return str(value).strip()


def _source(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_file": _safe_str(row.get("__source_file__")),
        "source_sheet": _safe_str(row.get("__source_sheet__")),
        "source_row": int(row.get("__source_row__") or 0),
    }


def _required(table: TableData, label: str, specs: list[tuple[str, tuple[str, ...]]]) -> dict[str, str]:
    found: dict[str, str] = {}
    missing: list[str] = []
    for key, aliases in specs:
        col = find_column(table, *aliases)
        if not col:
            missing.append(aliases[0])
        else:
            found[key] = col
    if missing:
        raise ReconcileError(f"{label}: colunas obrigatórias ausentes: {', '.join(missing)}.")
    return found


def validate_base(base: TableData) -> None:
    cols = _required(base, "BASE DADOS", [
        ("code", ("Cód Fornecedor", "Codigo Fornecedor")),
        ("name", ("Fornecedor",)),
        ("flow", ("Fluxo JMM", "Fluxo")),
        ("category", ("Categoria",)),
    ])
    seen: dict[str, tuple[int, str, str]] = {}
    problems: list[str] = []
    for idx, row in enumerate(base.rows, start=1):
        src_row = int(row.get("__source_row__") or idx + base.header_row)
        code = _code(row.get(cols["code"]))
        name = _safe_str(row.get(cols["name"]))
        flow = _safe_str(row.get(cols["flow"]))
        category = _safe_str(row.get(cols["category"]))
        if not code or not name or not flow or not category:
            problems.append(f"linha {src_row}: código, fornecedor, Fluxo JMM e Categoria são obrigatórios")
            continue
        if code in seen:
            old_row, old_flow, old_cat = seen[code]
            problems.append(
                f"linha {src_row}: código {code} duplicado (já existe na linha {old_row}; "
                f"classificação anterior {old_flow}/{old_cat})"
            )
        else:
            seen[code] = (src_row, flow, category)
    if problems:
        sample = "; ".join(problems[:8])
        if len(problems) > 8:
            sample += f"; ... e mais {len(problems)-8} problema(s)"
        raise ReconcileError(f"BASE DADOS inválida: {sample}.")


def _build_base(base: TableData) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any] | None]]:
    validate_base(base)
    c_code = find_column(base, "Cód Fornecedor", "Codigo Fornecedor")
    c_name = find_column(base, "Fornecedor")
    c_flow = find_column(base, "Fluxo JMM", "Fluxo")
    c_cat = find_column(base, "Categoria")
    by_code: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any] | None] = {}
    for row in base.rows:
        entry = {
            "code": _code(row.get(c_code)),
            "name": _safe_str(row.get(c_name)),
            "norm": normalize_text(row.get(c_name)),
            "flow": _safe_str(row.get(c_flow)),
            "category": _safe_str(row.get(c_cat)),
            "base_row": int(row.get("__source_row__") or 0),
        }
        by_code[entry["code"]] = entry
        norm = entry["norm"]
        if norm:
            by_name[norm] = entry if norm not in by_name else None
    return by_code, by_name


def _classification_pair(row: dict[str, Any], flow_column: str | None, category_column: str | None) -> tuple[str, str] | None:
    if not flow_column or not category_column:
        return None
    flow = _safe_str(row.get(flow_column))
    category = _safe_str(row.get(category_column))
    if not flow or not category:
        return None
    if normalize_text(flow) == "NAO CLASSIFICADO" or normalize_text(category) == "NAO CLASSIFICADO":
        return None
    return flow, category


def _build_import_history(
    tables: list[tuple[TableData, str, str | None, str | None]],
) -> dict[str, tuple[str, str] | None]:
    candidates: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for table, code_column, flow_column, category_column in tables:
        for row in table.rows:
            code = _code(row.get(code_column))
            pair = _classification_pair(row, flow_column, category_column)
            if code and pair:
                candidates[code].add(pair)
    return {
        code: next(iter(pairs)) if len(pairs) == 1 else None
        for code, pairs in candidates.items()
    }


def _lookup_classification(
    code: str,
    name: str,
    by_code: dict[str, dict[str, Any]],
    by_name: dict[str, dict[str, Any] | None],
    direct: tuple[str, str] | None,
    history_by_code: dict[str, tuple[str, str] | None],
) -> tuple[dict[str, Any] | None, str]:
    # 1) Código exato da BASE DADOS é a chave determinística principal.
    if code and code in by_code:
        return by_code[code], "base_codigo"

    # 2) Nome normalizado exato só é aceito quando o índice da base é inequívoco.
    norm = normalize_text(name)
    exact_name = by_name.get(norm) if norm else None
    if exact_name is not None:
        return exact_name, "base_nome"

    # 3) A classificação completa já materializada na própria linha é preservada.
    if direct:
        return {"code": code, "name": name, "flow": direct[0], "category": direct[1]}, "planilha_direta"

    # 4) Histórico do mesmo código só vale quando existe um único par no arquivo.
    historical = history_by_code.get(code) if code else None
    if historical:
        return {"code": code, "name": name, "flow": historical[0], "category": historical[1]}, "historico_codigo"

    # 5) Nenhuma aproximação ou valor padrão é aplicado.
    return None, "nao_resolvida"


def _supplier_key(match: str, canonical_code: str, source_code: str, source_name: str) -> str:
    if match in {"base_codigo", "base_nome"}:
        return f"BASE:{canonical_code}"
    if match in {"planilha_direta", "historico_codigo"}:
        return f"ARQUIVO:{source_code}" if source_code else f"ARQUIVO_NOME:{normalize_text(source_name)}"
    return f"NAOCLASS:{source_code}:{normalize_text(source_name)}"


def _warning(title: str, summary: str, details: list[dict[str, Any]], level: str = "warning") -> dict[str, Any]:
    return {"level": level, "title": title, "summary": summary, "details": details}


def reconcile(previsto_table: TableData, realizado_table: TableData, base_table: TableData) -> ReconcileResult:
    by_code, by_name = _build_base(base_table)
    warnings: list[dict[str, Any]] = []

    pc = _required(previsto_table, "PREVISTO", [
        ("code", ("Cód Fornecedor", "Codigo Fornecedor")),
        ("name", ("Fornecedor",)),
        ("date", ("Data prevista",)),
        ("value", ("Valor previsto",)),
    ])
    rc = _required(realizado_table, "REALIZADO", [
        ("title", ("Título", "Titulo")),
        ("code", ("Fornecedor", "Cód Fornecedor")),
        ("name", ("Nome Fornecedor", "Fornecedor Nome")),
        ("value", ("Vlr.Original", "Valor Original", "Total")),
        ("paid", ("Ult. Pgto.", "Ult Pgto", "Data Pagamento")),
        ("due", ("Vencimento",)),
    ])
    p_month = find_column(previsto_table, "Mês", "Mes")
    p_title = find_column(previsto_table, "Título Previsto", "Titulo Previsto")
    p_flow = find_column(previsto_table, "Fluxo JMM", "Fluxo")
    p_category = find_column(previsto_table, "Categoria")
    r_flow = find_column(realizado_table, "Fluxo JMM", "Fluxo")
    r_category = find_column(realizado_table, "Categoria")
    history_by_code = _build_import_history([
        (previsto_table, pc["code"], p_flow, p_category),
        (realizado_table, rc["code"], r_flow, r_category),
    ])

    previsto: list[dict[str, Any]] = []
    p_unclassified: list[dict[str, Any]] = []
    p_name_matches: list[dict[str, Any]] = []
    p_bad_dates: list[dict[str, Any]] = []
    for row in previsto_table.rows:
        src = _source(row)
        code = _code(row.get(pc["code"]))
        source_name = _safe_str(row.get(pc["name"])) or "Sem fornecedor"
        try:
            value = to_float(row.get(pc["value"]), field="Valor previsto")
        except ValueParseError as exc:
            raise ReconcileError(
                f"PREVISTO: valor inválido em {src['source_file']} > {src['source_sheet']} > "
                f"linha {src['source_row']}: {exc}."
            ) from exc
        raw_date = row.get(pc["date"])
        parsed_date = to_date(raw_date)
        if raw_date not in (None, "") and parsed_date is None:
            p_bad_dates.append({**src, "supplier_code": code, "supplier": source_name, "value": value, "raw_date": _safe_str(raw_date)})

        direct = _classification_pair(row, p_flow, p_category)
        entry, match = _lookup_classification(code, source_name, by_code, by_name, direct, history_by_code)
        if entry:
            canonical_code = entry["code"]
            supplier = entry["name"]
            flow = entry["flow"]
            category = entry["category"]
            if match == "base_nome":
                p_name_matches.append({**src, "supplier_code": code, "supplier": source_name, "matched_code": canonical_code, "matched_supplier": supplier})
        else:
            canonical_code = ""
            supplier = source_name
            flow = "Não classificado"
            category = "Não classificado"
            p_unclassified.append({**src, "supplier_code": code, "supplier": source_name, "value": value, "suggestions": []})

        previsto.append({
            "kind": "previsto",
            "title": _safe_str(row.get(p_title)) if p_title else "",
            "supplier_code": code,
            "supplier_source": source_name,
            "supplier": supplier,
            "supplier_key": _supplier_key(match, canonical_code, code, source_name),
            "date": parsed_date.isoformat() if parsed_date else None,
            "value": value,
            "flow": flow,
            "category": category,
            "match": match,
            "month_text": _safe_str(row.get(p_month)) if p_month else "",
            **src,
        })

    r_company = find_column(realizado_table, "Empresa")
    r_emission = find_column(realizado_table, "Emissão", "Emissao")
    r_branch = find_column(realizado_table, "Filial")
    r_status = find_column(realizado_table, "Sit.", "Sit")
    r_account = find_column(realizado_table, "Desc. Conta Contábil", "Desc Conta Contábil")
    r_financial = find_column(realizado_table, "Desc. Conta Financeira", "Desc Conta Financeira")
    r_cost = find_column(realizado_table, "Desc. Centro de Custo", "Desc Centro de Custo")

    realizado: list[dict[str, Any]] = []
    r_unclassified: list[dict[str, Any]] = []
    r_name_matches: list[dict[str, Any]] = []
    r_bad_dates: list[dict[str, Any]] = []
    for row in realizado_table.rows:
        src = _source(row)
        code = _code(row.get(rc["code"]))
        source_name = _safe_str(row.get(rc["name"])) or "Sem fornecedor"
        title = _safe_str(row.get(rc["title"]))
        try:
            value = to_float(row.get(rc["value"]), field="Vlr.Original")
        except ValueParseError as exc:
            raise ReconcileError(
                f"REALIZADO: valor inválido em {src['source_file']} > {src['source_sheet']} > "
                f"linha {src['source_row']}: {exc}."
            ) from exc

        raw_paid = row.get(rc["paid"])
        raw_due = row.get(rc["due"])
        raw_emission = row.get(r_emission) if r_emission else None
        paid = to_date(raw_paid)
        due = to_date(raw_due)
        emission = to_date(raw_emission)
        if (
            (raw_paid not in (None, "") and paid is None)
            or (raw_due not in (None, "") and due is None)
            or (raw_emission not in (None, "") and emission is None)
        ):
            r_bad_dates.append({
                **src, "title": title, "supplier_code": code, "supplier": source_name, "value": value,
                "raw_paid": _safe_str(raw_paid), "raw_due": _safe_str(raw_due),
                "raw_emission": _safe_str(raw_emission),
            })
        punctuality = "Sem data"
        if paid and due:
            punctuality = "Antecipado" if paid < due else "Dentro do Prazo" if paid == due else "Atrasado"

        direct = _classification_pair(row, r_flow, r_category)
        entry, match = _lookup_classification(code, source_name, by_code, by_name, direct, history_by_code)
        if entry:
            canonical_code = entry["code"]
            supplier = entry["name"]
            flow = entry["flow"]
            category = entry["category"]
            if match == "base_nome":
                r_name_matches.append({
                    **src, "title": title, "supplier_code": code, "supplier": source_name,
                    "matched_code": canonical_code, "matched_supplier": supplier, "value": value,
                })
        else:
            canonical_code = ""
            supplier = source_name
            flow = "Não classificado"
            category = "Não classificado"
            r_unclassified.append({
                **src, "title": title, "supplier_code": code, "supplier": source_name,
                "value": value, "suggestions": [],
            })

        realizado.append({
            "kind": "realizado",
            "title": title,
            "supplier_code": code,
            "supplier_source": source_name,
            "supplier": supplier,
            "supplier_key": _supplier_key(match, canonical_code, code, source_name),
            "date": paid.isoformat() if paid else None,
            "emission_date": emission.isoformat() if emission else None,
            "due_date": due.isoformat() if due else None,
            "value": value,
            "flow": flow,
            "category": category,
            "match": match,
            "punctuality": punctuality,
            "company": _safe_str(row.get(r_company)) if r_company else "",
            "branch": _safe_str(row.get(r_branch)) if r_branch else "",
            "status": _safe_str(row.get(r_status)) if r_status else "",
            "account": _safe_str(row.get(r_account)) if r_account else "",
            "financial_account": _safe_str(row.get(r_financial)) if r_financial else "",
            "cost_center": _safe_str(row.get(r_cost)) if r_cost else "",
            **src,
        })

    def _brl(value: float) -> str:
        raw = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{'-' if value < 0 else ''}R$ {raw}"

    def grouped_unclassified(details: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
        if not details:
            return None
        distinct = {(d.get("supplier_code", ""), d.get("supplier", "")) for d in details}
        total = sum(float(d.get("value") or 0) for d in details)
        supplier_word = "fornecedor" if len(distinct) == 1 else "fornecedores"
        return _warning(
            f"Classificação ausente no {label}",
            f"{len(details)} registro(s), {len(distinct)} {supplier_word}, total de {_brl(total)}. "
            "Esses registros permanecem como 'Não classificado' e NÃO são atribuídos por similaridade.",
            details,
        )

    for warning in (grouped_unclassified(p_unclassified, "PREVISTO"), grouped_unclassified(r_unclassified, "REALIZADO")):
        if warning:
            warnings.append(warning)
    if p_name_matches:
        warnings.append(_warning(
            "Classificação por nome exato no PREVISTO",
            f"{len(p_name_matches)} registro(s) não tinham código correspondente, mas possuíam nome normalizado exato e inequívoco na BASE DADOS.",
            p_name_matches,
            "info",
        ))
    if r_name_matches:
        warnings.append(_warning(
            "Classificação por nome exato no REALIZADO",
            f"{len(r_name_matches)} registro(s) não tinham código correspondente, mas possuíam nome normalizado exato e inequívoco na BASE DADOS.",
            r_name_matches,
            "info",
        ))
    if p_bad_dates:
        warnings.append(_warning(
            "Datas inválidas no PREVISTO",
            f"{len(p_bad_dates)} registro(s) possuem Data prevista não reconhecida e ficam fora do gráfico temporal.",
            p_bad_dates,
        ))
    if r_bad_dates:
        warnings.append(_warning(
            "Datas inválidas no REALIZADO",
            f"{len(r_bad_dates)} registro(s) possuem emissão/pagamento/vencimento não reconhecido e ficam fora dos filtros ou cálculos que dependem dessas datas quando necessário.",
            r_bad_dates,
        ))

    dates: list[date] = []
    for item in previsto + realizado:
        if item.get("date"):
            try:
                dates.append(date.fromisoformat(item["date"]))
            except Exception:
                pass
    months = ["JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO", "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
    if dates:
        first, last = min(dates), max(dates)
        if first.year == last.year and first.month == last.month:
            year, month = first.year, first.month
            period_label = f"{months[month-1]} {year}"
        else:
            year = month = None
            period_label = f"{first.strftime('%d/%m/%Y')} A {last.strftime('%d/%m/%Y')}"
    else:
        year = month = None
        period_label = "PERÍODO NÃO IDENTIFICADO"

    return ReconcileResult(
        previsto=previsto,
        realizado=realizado,
        warnings=warnings,
        period_label=period_label,
        period_year=year,
        period_month=month,
        base_rows=len(base_table.rows),
    )
