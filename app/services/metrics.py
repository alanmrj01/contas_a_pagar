from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable


def _sum(items: Iterable[dict[str, Any]]) -> float:
    return sum(float(x.get("value", 0.0) or 0.0) for x in items)


def summarize(previsto: list[dict[str, Any]], realizado: list[dict[str, Any]]) -> dict[str, Any]:
    planned = _sum(previsto)
    actual = _sum(realizado)
    variance = actual - planned
    variance_pct = (variance / planned * 100.0) if planned else 0.0
    suppliers = {x.get("supplier_key") for x in previsto + realizado if x.get("supplier_key")}
    punctual = Counter(x.get("punctuality", "Sem data") for x in realizado)
    with_date = sum(v for k, v in punctual.items() if k != "Sem data")
    ontime = punctual.get("Dentro do Prazo", 0) + punctual.get("Antecipado", 0)
    unclassified = [x for x in realizado if x.get("category") == "Não classificado" or x.get("flow") == "Não classificado"]
    return {
        "planned": planned,
        "actual": actual,
        "variance": variance,
        "variance_pct": variance_pct,
        "titles": len(realizado),
        "suppliers": len(suppliers),
        "punctuality": dict(punctual),
        "on_time_rate": (ontime / with_date * 100.0) if with_date else None,
        "punctuality_denominator": with_date,
        "unclassified_records": len(unclassified),
        "unclassified_value": _sum(unclassified),
    }


def group_values(items: list[dict[str, Any]], key: str) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for item in items:
        label = str(item.get(key) or "Não classificado")
        out[label] += float(item.get("value") or 0.0)
    return dict(out)


def aggregate_suppliers(previsto: list[dict[str, Any]], realizado: list[dict[str, Any]]) -> list[dict[str, Any]]:
    acc: dict[str, dict[str, Any]] = {}

    def add(item: dict[str, Any], side: str) -> None:
        key = str(item.get("supplier_key") or item.get("supplier") or "SEM_FORNECEDOR")
        row = acc.setdefault(key, {
            "supplier_key": key,
            "supplier": item.get("supplier") or "Sem fornecedor",
            "supplier_code": item.get("supplier_code") or "",
            "category": item.get("category") or "Não classificado",
            "flow": item.get("flow") or "Não classificado",
            "planned": 0.0,
            "actual": 0.0,
            "planned_records": 0,
            "actual_records": 0,
        })
        row[side] += float(item.get("value") or 0.0)
        row["planned_records" if side == "planned" else "actual_records"] += 1
        if row["category"] == "Não classificado" and item.get("category"):
            row["category"] = item["category"]
        if row["flow"] == "Não classificado" and item.get("flow"):
            row["flow"] = item["flow"]
        if not row["supplier_code"] and item.get("supplier_code"):
            row["supplier_code"] = item["supplier_code"]

    for item in previsto:
        add(item, "planned")
    for item in realizado:
        add(item, "actual")

    result: list[dict[str, Any]] = []
    for row in acc.values():
        row["variance"] = row["actual"] - row["planned"]
        row["variance_pct"] = (row["variance"] / row["planned"] * 100.0) if row["planned"] else None
        result.append(row)
    result.sort(key=lambda x: abs(float(x["variance"])), reverse=True)
    return result


def accumulated_by_date(previsto: list[dict[str, Any]], realizado: list[dict[str, Any]]) -> list[dict[str, Any]]:
    p = group_values([x for x in previsto if x.get("date")], "date")
    r = group_values([x for x in realizado if x.get("date")], "date")
    dates = sorted(set(p) | set(r))
    cp = cr = 0.0
    out: list[dict[str, Any]] = []
    for d in dates:
        cp += p.get(d, 0.0)
        cr += r.get(d, 0.0)
        out.append({"date": d, "planned": cp, "actual": cr})
    return out



def monthly_supplier_category(previsto: list[dict[str, Any]], realizado: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consolida mês + fornecedor + Fluxo JMM + Categoria com comparação mensal.

    Regras determinísticas:
    - somente registros com data válida entram nesta visualização;
    - Fluxo JMM e Categoria vêm da classificação já reconciliada com a BASE DADOS;
    - a comparação é feita contra o mês-calendário imediatamente anterior para a
      MESMA combinação fornecedor + fluxo + categoria;
    - ausência da combinação no mês anterior é marcada como ``has_previous=False``
      e nunca convertida silenciosamente em zero.
    """
    acc: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def add(item: dict[str, Any], side: str) -> None:
        raw_date = str(item.get("date") or "")
        if len(raw_date) < 7:
            return
        month = raw_date[:7]
        supplier_key = str(item.get("supplier_key") or item.get("supplier") or "SEM_FORNECEDOR")
        supplier = str(item.get("supplier") or "Sem fornecedor")
        flow = str(item.get("flow") or "Não classificado")
        category = str(item.get("category") or "Não classificado")
        key = (month, supplier_key, flow, category)
        row = acc.setdefault(key, {
            "month": month,
            "supplier_key": supplier_key,
            "supplier": supplier,
            "flow": flow,
            "category": category,
            "planned": 0.0,
            "actual": 0.0,
        })
        row[side] += float(item.get("value") or 0.0)

    for item in previsto:
        add(item, "planned")
    for item in realizado:
        add(item, "actual")

    def previous_month(month: str) -> str:
        year, mon = map(int, month.split("-"))
        if mon == 1:
            return f"{year-1:04d}-12"
        return f"{year:04d}-{mon-1:02d}"

    rows = list(acc.values())
    index = {(r["month"], r["supplier_key"], r["flow"], r["category"]): r for r in rows}
    for row in rows:
        prev = index.get((previous_month(row["month"]), row["supplier_key"], row["flow"], row["category"]))
        row["has_previous"] = prev is not None
        row["previous_month"] = previous_month(row["month"])
        row["previous_planned"] = float(prev["planned"]) if prev else None
        row["previous_actual"] = float(prev["actual"]) if prev else None
        row["planned_mom_delta"] = float(row["planned"]) - float(prev["planned"]) if prev else None
        row["actual_mom_delta"] = float(row["actual"]) - float(prev["actual"]) if prev else None
        row["planned_mom_pct"] = (row["planned_mom_delta"] / abs(float(prev["planned"])) * 100.0) if prev and float(prev["planned"]) != 0 else None
        row["actual_mom_pct"] = (row["actual_mom_delta"] / abs(float(prev["actual"])) * 100.0) if prev and float(prev["actual"]) != 0 else None

    rows.sort(key=lambda x: (x["month"], -max(abs(float(x["planned"])), abs(float(x["actual"]))), x["supplier"], x["flow"], x["category"]))
    return rows

def chart_data(previsto: list[dict[str, Any]], realizado: list[dict[str, Any]]) -> dict[str, Any]:
    cat_p, cat_r = group_values(previsto, "category"), group_values(realizado, "category")
    categories = [
        {"label": k, "planned": cat_p.get(k, 0.0), "actual": cat_r.get(k, 0.0)}
        for k in set(cat_p) | set(cat_r)
    ]
    categories.sort(key=lambda x: max(abs(x["planned"]), abs(x["actual"])), reverse=True)

    flow_p, flow_r = group_values(previsto, "flow"), group_values(realizado, "flow")
    flows = [
        {"label": k, "planned": flow_p.get(k, 0.0), "actual": flow_r.get(k, 0.0), "variance": flow_r.get(k, 0.0) - flow_p.get(k, 0.0)}
        for k in set(flow_p) | set(flow_r)
    ]
    flows.sort(key=lambda x: abs(x["variance"]), reverse=True)

    punctuality = Counter(x.get("punctuality") or "Sem data" for x in realizado)
    return {
        "categories": categories,
        "timeline": accumulated_by_date(previsto, realizado),
        "suppliers": aggregate_suppliers(previsto, realizado),
        "flows": flows,
        "monthly_supplier_category": monthly_supplier_category(previsto, realizado),
        "punctuality": dict(punctuality),
    }
