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
            "subcategory": item.get("subcategory") or "",
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
        if not row["subcategory"] and item.get("subcategory"):
            row["subcategory"] = item["subcategory"]
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


def least_squares_trend(values: list[float]) -> list[float]:
    """Tendência linear OLS sobre posições cronológicas 0..n-1."""

    if not values:
        return []
    if len(values) == 1:
        return [float(values[0])]
    numeric = [float(value) for value in values]
    x_mean = (len(numeric) - 1) / 2.0
    y_mean = sum(numeric) / len(numeric)
    denominator = sum((index - x_mean) ** 2 for index in range(len(numeric)))
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(numeric)) / denominator
    intercept = y_mean - slope * x_mean
    return [intercept + slope * index for index in range(len(numeric))]


def category_waterfall(previsto: list[dict[str, Any]], realizado: list[dict[str, Any]]) -> dict[str, Any]:
    """Fecha Previsto + somatório(Realizado - Previsto por categoria) = Realizado."""

    planned_by_category = group_values(previsto, "category")
    actual_by_category = group_values(realizado, "category")
    labels = set(planned_by_category) | set(actual_by_category)
    steps = [
        {
            "label": label,
            "planned": planned_by_category.get(label, 0.0),
            "actual": actual_by_category.get(label, 0.0),
            "contribution": actual_by_category.get(label, 0.0) - planned_by_category.get(label, 0.0),
        }
        for label in labels
    ]
    steps.sort(key=lambda row: (-max(abs(row["planned"]), abs(row["actual"])), row["label"].casefold()))
    planned = _sum(previsto)
    actual = _sum(realizado)
    return {
        "planned": planned,
        "steps": steps,
        "actual": actual,
        "variance": actual - planned,
    }



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
        "category_waterfall": category_waterfall(previsto, realizado),
        "punctuality": dict(punctuality),
    }
