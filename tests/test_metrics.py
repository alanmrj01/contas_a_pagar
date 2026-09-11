from app.services.metrics import aggregate_suppliers, category_waterfall, chart_data, least_squares_trend, summarize


def test_summary():
    p=[{"value":100,"supplier_key":"A"},{"value":200,"supplier_key":"B"}]
    r=[{"value":120,"supplier_key":"A","punctuality":"Dentro do Prazo"},{"value":240,"supplier_key":"B","punctuality":"Atrasado"}]
    s=summarize(p,r)
    assert s["planned"]==300
    assert s["actual"]==360
    assert s["variance"]==60
    assert round(s["variance_pct"],2)==20.0
    assert s["on_time_rate"]==50.0


def test_supplier_aggregation_does_not_pair_rows_one_to_one():
    p=[{"supplier_key":"BASE:1","supplier":"A","category":"C","flow":"F","value":200}]
    r=[
        {"supplier_key":"BASE:1","supplier":"A","category":"C","flow":"F","value":30},
        {"supplier_key":"BASE:1","supplier":"A","category":"C","flow":"F","value":45},
        {"supplier_key":"BASE:1","supplier":"A","category":"C","flow":"F","value":70},
        {"supplier_key":"BASE:1","supplier":"A","category":"C","flow":"F","value":55},
    ]
    rows=aggregate_suppliers(p,r)
    assert len(rows)==1
    assert rows[0]["planned"]==200
    assert rows[0]["actual"]==200
    assert rows[0]["variance"]==0


def test_chart_aggregations_reconcile_to_totals():
    p=[
        {"value":100,"supplier_key":"A","category":"C1","flow":"F1","date":"2026-05-01"},
        {"value":200,"supplier_key":"B","category":"C2","flow":"F2","date":"2026-05-02"},
    ]
    r=[
        {"value":130,"supplier_key":"A","category":"C1","flow":"F1","date":"2026-05-01","punctuality":"Dentro do Prazo"},
        {"value":250,"supplier_key":"B","category":"C2","flow":"F2","date":"2026-05-03","punctuality":"Atrasado"},
    ]
    s=summarize(p,r)
    charts=chart_data(p,r)
    assert sum(x["planned"] for x in charts["categories"]) == s["planned"]
    assert sum(x["actual"] for x in charts["categories"]) == s["actual"]
    assert sum(x["variance"] for x in charts["flows"]) == s["variance"]
    assert charts["timeline"][-1]["planned"] == s["planned"]
    assert charts["timeline"][-1]["actual"] == s["actual"]


def test_flow_contributions_preserve_positive_negative_and_close_values():
    p = [
        {"value": 100, "flow": "FLUXO A"},
        {"value": 20, "flow": "FLUXO A"},
        {"value": 200, "flow": "FLUXO B"},
        {"value": 50, "flow": "FLUXO C"},
        {"value": 100, "flow": "FLUXO E"},
        {"value": 100, "flow": "FLUXO F"},
    ]
    r = [
        {"value": 160, "flow": "FLUXO A"},
        {"value": 150, "flow": "FLUXO B"},
        {"value": 50, "flow": "FLUXO C"},
        {"value": 25, "flow": "FLUXO D"},
        {"value": 101, "flow": "FLUXO E"},
        {"value": 99, "flow": "FLUXO F"},
    ]

    summary = summarize(p, r)
    flows = {row["label"]: row for row in chart_data(p, r)["flows"]}

    assert flows["FLUXO A"]["variance"] == 40
    assert flows["FLUXO B"]["variance"] == -50
    assert flows["FLUXO C"]["variance"] == 0
    assert flows["FLUXO D"]["variance"] == 25
    assert flows["FLUXO E"]["variance"] == 1
    assert flows["FLUXO F"]["variance"] == -1
    assert sum(row["variance"] for row in flows.values()) == summary["variance"]


def test_realized_trend_is_linear_ordinary_least_squares_in_chronological_order():
    assert least_squares_trend([10, 20, 30, 40]) == [10, 20, 30, 40]
    assert least_squares_trend([10, 30, 20]) == [15, 20, 25]
    assert least_squares_trend([7]) == [7]


def test_category_waterfall_closes_exactly_at_reconciled_actual_total():
    p = [{"value": 100, "category": "A"}, {"value": 50, "category": "B"}]
    r = [{"value": 130, "category": "A"}, {"value": 20, "category": "B"}, {"value": 15, "category": "C"}]
    waterfall = category_waterfall(p, r)
    assert waterfall["planned"] == 150
    assert sum(step["contribution"] for step in waterfall["steps"]) == 15
    assert waterfall["planned"] + sum(step["contribution"] for step in waterfall["steps"]) == waterfall["actual"] == 165
    assert waterfall["variance"] == 15


def test_summary_does_not_report_zero_punctuality_when_dates_are_unavailable():
    s=summarize([{"value":100,"supplier_key":"A"}],[{"value":90,"supplier_key":"A","punctuality":"Sem data"}])
    assert s["punctuality_denominator"]==0
    assert s["on_time_rate"] is None
