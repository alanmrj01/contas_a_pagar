from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

from .metrics import aggregate_suppliers, chart_data, least_squares_trend, summarize
from .reconciler import ReconcileResult

BLUE = HexColor("#234865")
BLUE2 = HexColor("#315F82")
ACCENT = HexColor("#65A9D5")
ACCENT2 = HexColor("#8ED1FF")
TEXT = HexColor("#173047")
MUTED = HexColor("#425D6F")
LIGHT = HexColor("#F2F6F9")
LINE = HexColor("#D6E1E8")
PASTEL = [
    HexColor("#7DB8DA"), HexColor("#E3A589"), HexColor("#89C9AF"),
    HexColor("#C7B2E0"), HexColor("#DDB866"), HexColor("#78BCC6"),
    HexColor("#B7D171"), HexColor("#D8A8C4"), HexColor("#9CB7F0"),
    HexColor("#F0C39C"),
]
MONTHS_PT = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}%".replace(".", ",")


def short_brl(v: float) -> str:
    value = float(v or 0)
    a = abs(value)
    sign = "-" if value < 0 else ""
    if a >= 1_000_000:
        return f"{sign}R$ {a / 1_000_000:.1f}M".replace(".", ",")
    if a >= 1_000:
        decimals = 0 if a >= 100_000 else 1
        return (f"{sign}R$ {a / 1_000:.{decimals}f} mil").replace(".", ",")
    return f"{sign}R$ {a:.0f}"


def _label_lines(text: str, width_chars: int = 13, max_lines: int = 2) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    idx = 0
    while idx < len(words) and len(lines) < max_lines:
        word = words[idx]
        test = f"{current} {word}".strip()
        if not current or len(test) <= width_chars:
            current = test
            idx += 1
        else:
            lines.append(current)
            current = ""
    if current and len(lines) < max_lines:
        lines.append(current)
    if idx < len(words) and lines:
        lines[-1] = lines[-1][: max(4, width_chars - 1)].rstrip() + "…"
    return lines or [""]


def _supplier_color(name: str):
    text = str(name or "")
    seed = 0
    for ch in text:
        seed = (seed * 31 + ord(ch)) & 0xFFFFFFFF
    return PASTEL[seed % len(PASTEL)]


def _mix_color(color, target, ratio: float):
    return Color(
        color.red * (1 - ratio) + target.red * ratio,
        color.green * (1 - ratio) + target.green * ratio,
        color.blue * (1 - ratio) + target.blue * ratio,
    )


def _category_series_colors(item: dict, category: str = ""):
    if item.get("mark") == "P":
        return HexColor("#AEB8C2"), HexColor("#687785")
    fill = _supplier_color(category)
    return fill, _mix_color(fill, HexColor("#17384D"), .42)


def _text(c: canvas.Canvas, x: float, y: float, text: str, size: float = 9, color=TEXT, bold=False):
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    c.drawString(x, y, str(text))


def _fit_text_size(text: object, max_width: float, start_size: float, min_size: float = 6.0, bold: bool = False) -> float:
    """Reduz a fonte somente quando necessário para impedir estouro horizontal no PDF."""
    value = str(text)
    font = "Helvetica-Bold" if bold else "Helvetica"
    size = float(start_size)
    while size > min_size and pdfmetrics.stringWidth(value, font, size) > max_width:
        size -= 0.25
    return max(min_size, size)


def _text_fit(c: canvas.Canvas, x: float, y: float, text: object, max_width: float, start_size: float = 9, min_size: float = 6, color=TEXT, bold: bool = False, align: str = "left"):
    value = str(text)
    size = _fit_text_size(value, max_width, start_size, min_size, bold)
    c.setFillColor(color)
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    if align == "right":
        c.drawRightString(x, y, value)
    elif align == "center":
        c.drawCentredString(x, y, value)
    else:
        c.drawString(x, y, value)


def _wrapped(c: canvas.Canvas, x: float, y: float, text: str, width_chars: int, size: float = 9, leading: float = 12, color=TEXT, bold=False) -> float:
    for line in wrap(str(text), width=max(8, width_chars)) or [""]:
        _text(c, x, y, line, size, color, bold)
        y -= leading
    return y


def _footer(c: canvas.Canvas, page: int, period: str):
    w, _ = A4
    c.setStrokeColor(LINE)
    c.line(36, 24, w - 36, 24)
    _text(c, 36, 12, f"CONTAS A PAGAR • PREVISTO x REALIZADO • {period}", 7.5, MUTED)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawRightString(w - 36, 12, f"Página {page}")


def _new_page(c: canvas.Canvas, title: str, period: str, page: int):
    w, h = A4
    c.setFillColor(white)
    c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(0, h - 72, w, 72, fill=1, stroke=0)
    _text(c, 36, h - 32, "CONTAS A PAGAR", 9, ACCENT2, True)
    _text(c, 36, h - 54, title, 19, white, True)
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(ACCENT2)
    c.drawRightString(w - 36, h - 46, period)
    _footer(c, page, period)
    return w, h


def _kpi(c: canvas.Canvas, x, y, w, h, label, value, note):
    c.setFillColor(LIGHT)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=0)
    _text(c, x + 10, y + h - 17, label.upper(), 7.5, MUTED, True)
    _text_fit(c, x + 10, y + h - 39, value, max_width=w - 20, start_size=13, min_size=8.2, color=BLUE, bold=True)
    _text_fit(c, x + 10, y + 9, note, max_width=w - 20, start_size=6.8, min_size=5.5, color=MUTED)


def _draw_value_bubble(c: canvas.Canvas, cx: float, by: float, label: str, x_min: float, x_max: float, leader_from: tuple[float, float] | None = None):
    font_size = 7.2
    label_w = min(82, max(54, pdfmetrics.stringWidth(label, "Helvetica-Bold", font_size) + 9))
    bx = max(x_min, min(x_max - label_w, cx - label_w / 2))
    if leader_from is not None:
        target_y = by if by > leader_from[1] else by + 14
        c.setStrokeColor(HexColor("#69818F"))
        c.setLineWidth(.55)
        c.line(leader_from[0], leader_from[1], cx, target_y)
    c.setFillColor(white)
    c.setStrokeColor(HexColor("#69818F"))
    c.setLineWidth(.45)
    c.roundRect(bx, by, label_w, 14, 3, fill=1, stroke=1)
    c.setFillColor(TEXT)
    c.setFont("Helvetica-Bold", font_size)
    c.drawCentredString(bx + label_w / 2, by + 4.1, label)
    return bx, by, label_w, 14


def _category_month_rows(previsto, realizado):
    months = sorted({
        str(item.get("date"))[:7]
        for item in [*previsto, *realizado]
        if len(str(item.get("date") or "")) >= 7
    })[-2:]
    if not months:
        return [], []
    totals: dict[str, dict[tuple[str, str], float]] = {}
    for side, items in (("P", previsto), ("R", realizado)):
        for item in items:
            month = str(item.get("date") or "")[:7]
            if month not in months:
                continue
            category = str(item.get("category") or "Não classificado")
            category_totals = totals.setdefault(category, {})
            category_totals[(month, side)] = category_totals.get((month, side), 0.0) + float(item["value"])
    labels = [f"{MONTHS_PT[int(month[5:7]) - 1]}/{month[2:4]}" for month in months]
    rows = []
    for category, values in totals.items():
        series = []
        for index, month in enumerate(months):
            for mark, kind in (("P", "Previsto"), ("R", "Realizado")):
                series.append({
                    "label": f"{labels[index]} {mark}",
                    "kind": kind,
                    "mark": mark,
                    "month_index": index,
                    "previous": len(months) > 1 and index == 0,
                    "value": float(values.get((month, mark), 0.0)),
                })
        rows.append({"label": category, "series": series})
    rows.sort(key=lambda row: max(abs(item["value"]) for item in row["series"]), reverse=True)
    return rows, labels


def _category_chart(c, x, y, w, h, rows):
    if not rows:
        _text(c, x, y + h / 2, "Sem dados", 10, MUTED)
        return
    values = [float(item["value"]) for row in rows for item in row["series"]]
    domain_min = min([0.0, *values])
    domain_max = max([0.0, *values])
    span = domain_max - domain_min or 1.0
    left = x + 172
    right = x + w - 96
    bottom = y + 43
    top = y + h - 16
    plot_w = right - left
    row_h = (top - bottom) / max(1, len(rows))

    def xx(value: float) -> float:
        return left + (value - domain_min) / span * plot_w

    zero_x = xx(0.0)

    def value_bubble(endpoint: float, cy: float, label: str, positive: bool) -> None:
        font_size = 7.6
        bubble_w = min(98, max(60, pdfmetrics.stringWidth(label, "Helvetica-Bold", font_size) + 13))
        desired = endpoint + 4 if positive else endpoint - bubble_w - 4
        bx = max(left + 2, min(x + w - bubble_w - 2, desired))
        c.setFillColor(white)
        c.setStrokeColor(HexColor("#69818F"))
        c.setLineWidth(.55)
        c.roundRect(bx, cy - 6.75, bubble_w, 13.5, 3.5, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(TEXT)
        c.drawCentredString(bx + bubble_w / 2, cy - 2.65, label)

    for i in range(6):
        value = domain_min + span * i / 5
        x_tick = xx(value)
        c.setStrokeColor(LINE)
        c.setLineWidth(.7)
        c.line(x_tick, bottom, x_tick, top)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(MUTED)
        c.drawCentredString(x_tick, top + 8, short_brl(value))

    for i, row in enumerate(rows):
        color = PASTEL[i % len(PASTEL)]
        row_top = top - i * row_h
        series = row["series"]
        inner_gap = max(9.5, min(14.0, (row_h - 16) / max(1, len(series))))
        first_y = row_top - 17
        _text_fit(c, x + 1, row_top - 7, row["label"], max_width=left - x - 8, start_size=8.2, min_size=6.2, color=TEXT, bold=True)
        for series_index, item in enumerate(series):
            value = float(item["value"])
            cy = first_y - series_index * inner_gap
            endpoint = xx(value)
            bar_x = min(zero_x, endpoint)
            bar_w = max(1.0, abs(endpoint - zero_x))
            planned = item["mark"] == "P"
            fill_color, stroke_color = _category_series_colors(item, row["label"])
            c.setFillColor(fill_color)
            c.setStrokeColor(stroke_color)
            c.setLineWidth(2.0 if planned else .85)
            c.roundRect(bar_x, cy - 4.2, bar_w, 8.4, 2.6, fill=1, stroke=1)
            c.setFont("Helvetica-Bold", 7.1)
            c.setFillColor(TEXT)
            c.drawRightString(left - 7, cy - 2.5, item["label"])
            value_bubble(endpoint, cy, brl(value), value >= 0)
        c.setStrokeColor(color)
        c.setLineWidth(.35)
        c.line(x + 1, row_top - row_h + 2, x + w - 1, row_top - row_h + 2)

    legend = ("P - Previsto", "R - Realizado")
    slot = min(110, w / len(legend))
    start_x = x + (w - slot * len(legend)) / 2
    for index, label in enumerate(legend):
        _text_fit(c, start_x + index * slot, y + 25, label, max_width=slot - 8, start_size=6.1, min_size=5.2, color=MUTED, bold=True)


def _monthly_comparison_rows(previsto, realizado):
    totals: dict[str, dict[str, float]] = {}
    for side, items in (("planned", previsto), ("actual", realizado)):
        for item in items:
            month = str(item.get("date") or "")[:7]
            if len(month) != 7:
                continue
            bucket = totals.setdefault(month, {"planned": 0.0, "actual": 0.0})
            bucket[side] += float(item["value"])
    return [
        {"month": month, **totals[month]}
        for month in sorted(totals)
    ]


def _monthly_comparison_chart(c, x, y, w, h, rows):
    if not rows:
        _text(c, x, y + h / 2, "Sem dados mensais", 10, MUTED)
        return
    trend = least_squares_trend([float(row["actual"]) for row in rows])
    values = [float(row[key]) for row in rows for key in ("planned", "actual")] + trend
    domain_min = min(0.0, *values)
    domain_max = max(0.0, *values)
    span = domain_max - domain_min or 1.0
    left, right = x + 46, x + w - 8
    bottom, top = y + 46, y + h - 48
    plot_w, plot_h = right - left, top - bottom

    def yy(value: float) -> float:
        return bottom + (value - domain_min) / span * plot_h

    zero_y = yy(0.0)
    for index in range(5):
        value = domain_min + span * index / 4
        tick_y = yy(value)
        c.setStrokeColor(LINE)
        c.setLineWidth(.6)
        c.line(left, tick_y, right, tick_y)
        _text(c, x, tick_y - 2, short_brl(value), 5.5, MUTED)

    slot = plot_w / len(rows)
    bar_w = min(18.0, max(5.0, slot * .25))
    points = [
        (left + slot * (index + .5), yy(value))
        for index, value in enumerate(trend)
    ]
    bars = []
    for index, row in enumerate(rows):
        center = left + slot * (index + .5)
        group_bars = []
        for series_index, (key, fill, stroke) in enumerate((
            ("planned", HexColor("#AEB8C2"), HexColor("#687785")),
            ("actual", HexColor("#E6A58F"), HexColor("#8D4E3B")),
        )):
            value = float(row[key])
            value_y = yy(value)
            bar_x = center + (-bar_w - 2 if series_index == 0 else 2)
            bar_y = min(zero_y, value_y)
            bar_h = max(1.0, abs(zero_y - value_y))
            c.setFillColor(fill)
            c.setStrokeColor(stroke)
            c.setLineWidth(1.2 if series_index == 0 else .7)
            c.roundRect(bar_x, bar_y, bar_w, bar_h, 2, fill=1, stroke=1)
            group_bars.append({
                "center": center,
                "bar_center": bar_x + bar_w / 2,
                "bar_x": bar_x,
                "bar_y": bar_y,
                "bar_h": bar_h,
                "value": value,
                "label": brl(value),
            })
        positive_top = max([item["bar_y"] + item["bar_h"] for item in group_bars if item["value"] >= 0] or [zero_y])
        negative_bottom = min([item["bar_y"] for item in group_bars if item["value"] < 0] or [zero_y])
        for item in group_bars:
            item["preferred"] = positive_top + 8 if item["value"] >= 0 else negative_bottom - 22
            bars.append(item)
        month = str(row["month"])
        label = f"{MONTHS_PT[int(month[5:7]) - 1]}/{month[2:4]}"
        _text(c, center - 11, y + 27, label, 6.2, MUTED, True)

    def overlaps(first, second, margin=0.0):
        return (
            first[0] < second[0] + second[2] + margin
            and first[0] + first[2] + margin > second[0]
            and first[1] < second[1] + second[3] + margin
            and first[1] + first[3] + margin > second[1]
        )

    def trend_hits(rect, margin=6.0):
        rect_left = rect[0] - margin
        rect_right = rect[0] + rect[2] + margin
        rect_bottom = rect[1] - margin
        rect_top = rect[1] + rect[3] + margin
        if any(rect_left <= point_x <= rect_right and rect_bottom <= point_y <= rect_top for point_x, point_y in points):
            return True
        for first, last in zip(points, points[1:]):
            segment_left = max(rect_left, min(first[0], last[0]))
            segment_right = min(rect_right, max(first[0], last[0]))
            if segment_left > segment_right:
                continue
            if first[0] == last[0]:
                if rect_left <= first[0] <= rect_right and max(min(first[1], last[1]), rect_bottom) <= min(max(first[1], last[1]), rect_top):
                    return True
                continue
            first_y = first[1] + (last[1] - first[1]) * (segment_left - first[0]) / (last[0] - first[0])
            last_y = first[1] + (last[1] - first[1]) * (segment_right - first[0]) / (last[0] - first[0])
            if max(min(first_y, last_y), rect_bottom) <= min(max(first_y, last_y), rect_top):
                return True
        return False

    bar_rects = [(item["bar_x"], item["bar_y"], bar_w, item["bar_h"]) for item in bars]
    placed = []
    min_label_y, max_label_y = y + 32, y + h - 14
    for item in bars:
        label_w = min(82, max(54, pdfmetrics.stringWidth(item["label"], "Helvetica-Bold", 7.2) + 9))
        direction = 1 if item["value"] >= 0 else -1
        candidates = [item["preferred"]]
        candidates.extend(item["preferred"] + direction * step * 18 for step in range(1, 13))
        candidates.extend(item["preferred"] - direction * step * 18 for step in range(1, 13))
        candidates.extend(min_label_y + step * 17 for step in range(max(1, int((max_label_y - min_label_y) / 17) + 1)))
        chosen = None
        for candidate in candidates:
            if candidate < min_label_y or candidate > max_label_y:
                continue
            rect = (item["center"] - label_w / 2, candidate, label_w, 14)
            if any(overlaps(rect, other, 3) for other in placed):
                continue
            if any(overlaps(rect, bar, 3) for bar in bar_rects):
                continue
            if trend_hits(rect):
                continue
            chosen = rect
            break
        if chosen is None:
            chosen = (item["center"] - label_w / 2, max(min_label_y, min(max_label_y, item["preferred"])), label_w, 14)
        placed.append(chosen)
        bar_edge = item["bar_y"] + item["bar_h"] if item["value"] >= 0 else item["bar_y"]
        _draw_value_bubble(
            c,
            item["center"],
            chosen[1],
            item["label"],
            x,
            x + w,
            leader_from=(item["bar_center"], bar_edge),
        )

    c.setStrokeColor(HexColor("#2F88B8"))
    c.setLineWidth(1.8)
    for index in range(1, len(points)):
        c.line(points[index - 1][0], points[index - 1][1], points[index][0], points[index][1])
    for point_x, point_y in points:
        c.setFillColor(white)
        c.circle(point_x, point_y, 2.2, fill=1, stroke=1)

    c.setFillColor(HexColor("#AEB8C2"))
    c.setStrokeColor(HexColor("#687785"))
    c.roundRect(x + 95, y + 5, 12, 8, 2, fill=1, stroke=1)
    _text(c, x + 111, y + 6, "Previsto", 6.2, MUTED, True)
    c.setFillColor(HexColor("#E6A58F"))
    c.setStrokeColor(HexColor("#8D4E3B"))
    c.roundRect(x + 181, y + 5, 12, 8, 2, fill=1, stroke=1)
    _text(c, x + 197, y + 6, "Realizado", 6.2, MUTED, True)
    c.setStrokeColor(HexColor("#2F88B8"))
    c.setLineWidth(1.8)
    c.line(x + 273, y + 9, x + 291, y + 9)
    _text(c, x + 297, y + 6, "Tendência do Realizado", 6.2, MUTED, True)


def _monthly_local_kpis(c, x, y, w, h, rows):
    planned = sum(float(row["planned"]) for row in rows)
    actual = sum(float(row["actual"]) for row in rows)
    variance = actual - planned
    variation = variance / planned * 100 if planned else None
    cards = (
        ("Previsto total", brl(planned)),
        ("Realizado total", brl(actual)),
        ("Desvio total", brl(variance)),
        ("Variação total", pct(variation)),
    )
    gap = 7
    card_h = (h - gap * 3) / 4
    for index, (label, value) in enumerate(cards):
        card_y = y + h - (index + 1) * card_h - index * gap
        _kpi(c, x, card_y, w, card_h, label, value, "")


def _graph_period_subtitle(labels: list[str]) -> str:
    if not labels:
        return "Mês do gráfico: sem mês válido"
    prefix = "Mês do gráfico: " if len(labels) == 1 else "Meses do gráfico: "
    return prefix + " • ".join(labels)


def _period_chip(c, x, y, text):
    _text_fit(c, x, y, str(text), max_width=A4[0] - x - 36, start_size=7.1, min_size=5.8, color=MUTED, bold=True)


def _waterfall(c, x, y, w, h, rows, start):
    rows = list(rows)
    if len(rows) > 8:
        others = rows[8:]
        rows = rows[:8] + [{"label": "Outras categorias", "variance": sum(float(r["variance"]) for r in others)}]
    if not rows:
        _text(c, x, y + h / 2, "Sem dados", 10, MUTED)
        return

    cumulative = [float(start)]
    cur = float(start)
    for row in rows:
        cur += float(row["variance"])
        cumulative.append(cur)
    actual = cur
    domain_min = min([0.0] + cumulative)
    domain_max = max([0.0] + cumulative)
    span = domain_max - domain_min or 1.0

    left = x + 48
    right = x + w - 5
    bottom = y + 56
    top = y + h - 7
    pw = right - left
    ph = top - bottom
    slot = pw / (len(rows) + 2)
    bw = min(38, slot * .58)

    def yy(value: float) -> float:
        return bottom + ph * (value - domain_min) / span

    for i in range(5):
        value = domain_min + span * i / 4
        y_tick = yy(value)
        c.setStrokeColor(LINE)
        c.setLineWidth(.7)
        c.line(left, y_tick, right, y_tick)
        c.setFont("Helvetica", 5.8)
        c.setFillColor(MUTED)
        c.drawRightString(left - 5, y_tick - 2, short_brl(value))

    zero_y = yy(0)
    start_x = left + slot * .2
    start_y = yy(start)
    c.setFillColor(HexColor("#AEB8C2"))
    c.setStrokeColor(HexColor("#687785"))
    c.roundRect(start_x, min(zero_y, start_y), bw, max(3, abs(start_y - zero_y)), 2.5, fill=1, stroke=0)
    start_edge = max(zero_y, start_y)
    _draw_value_bubble(c, start_x + bw / 2, min(top - 14, start_edge + 5), brl(float(start)), x + 1, x + w - 1, leader_from=(start_x + bw / 2, start_edge))
    _text(c, start_x, y + 13, "Previsto", 5.8, MUTED, True)

    prev = float(start)
    for i, row in enumerate(rows, start=1):
        value = float(row["variance"])
        nxt = prev + value
        x0 = left + i * slot + slot * .2
        y1, y2 = yy(prev), yy(nxt)
        c.setStrokeColor(HexColor("#91A7B7"))
        c.setDash(2, 2)
        c.line(x0 - slot + bw, y1, x0, y1)
        c.setDash()
        bar_color = HexColor("#78B7DB") if value >= 0 else HexColor("#DF8588")
        c.setFillColor(bar_color)
        c.roundRect(x0, min(y1, y2), bw, max(3, abs(y2 - y1)), 2.5, fill=1, stroke=0)
        bar_edge = max(y1, y2) if value >= 0 else min(y1, y2)
        value_y = (bar_edge + 5 + (18 if i % 2 else 0)) if value >= 0 else (bar_edge - 19 - (18 if i % 2 else 0))
        value_y = max(bottom + 1, min(top - 14, value_y))
        _draw_value_bubble(c, x0 + bw / 2, value_y, brl(value), x + 1, x + w - 1, leader_from=(x0 + bw / 2, bar_edge))
        for j, label in enumerate(_label_lines(row["label"], 10, 2)):
            c.setFont("Helvetica-Bold", 5.1)
            c.setFillColor(MUTED)
            c.drawCentredString(x0 + bw / 2, y + 20 - j * 6.5, label)
        prev = nxt

    final_x = left + (len(rows) + 1) * slot + slot * .2
    final_y = yy(actual)
    c.setFillColor(HexColor("#DF8588") if actual - float(start) < 0 else HexColor("#78B7DB"))
    c.roundRect(final_x, min(zero_y, final_y), bw, max(3, abs(final_y - zero_y)), 2.5, fill=1, stroke=0)
    final_edge = max(zero_y, final_y)
    final_value_y = min(top - 14, final_edge + 5 + (18 if len(rows) % 2 else 0))
    _draw_value_bubble(c, final_x + bw / 2, final_value_y, brl(float(actual)), x + 1, x + w - 1, leader_from=(final_x + bw / 2, final_edge))
    c.setFont("Helvetica-Bold", 5.8)
    c.setFillColor(MUTED)
    c.drawCentredString(final_x + bw / 2, y + 13, "Realizado")

    legend = (
        ("Previsto", HexColor("#AEB8C2")),
        ("Contribuição positiva", HexColor("#78B7DB")),
        ("Contribuição negativa", HexColor("#DF8588")),
        ("Realizado", HexColor("#78B7DB" if actual - float(start) >= 0 else "#DF8588")),
    )
    legend_slot = w / len(legend)
    for index, (label, color) in enumerate(legend):
        lx = x + index * legend_slot
        c.setFillColor(color)
        c.roundRect(lx, y + 1, 10, 7, 1.5, fill=1, stroke=0)
        _text_fit(c, lx + 13, y + 1.5, label, max_width=legend_slot - 15, start_size=5.4, min_size=4.6, color=MUTED, bold=True)



def _cell_lines(value: object, width: float, font_size: float) -> list[str]:
    text = str(value if value not in (None, '') else '—')
    available = max(8.0, width)
    lines: list[str] = []
    current = ''

    def fits(candidate: str) -> bool:
        return pdfmetrics.stringWidth(candidate, 'Helvetica', font_size) <= available

    def split_long_word(word: str) -> tuple[list[str], str]:
        chunks: list[str] = []
        remaining = word
        while remaining and not fits(remaining):
            cut = 1
            while cut < len(remaining) and fits(remaining[:cut + 1]):
                cut += 1
            chunks.append(remaining[:cut])
            remaining = remaining[cut:]
        return chunks, remaining

    for paragraph_index, paragraph in enumerate(text.splitlines() or ['']):
        if paragraph_index and current:
            lines.append(current)
            current = ''
        for word in paragraph.split() or ['']:
            candidate = f'{current} {word}'.strip()
            if fits(candidate):
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ''
            chunks, current = split_long_word(word)
            lines.extend(chunks)
    if current or not lines:
        lines.append(current or '—')
    return lines


def _paginated_table(
    c: canvas.Canvas,
    title: str,
    period: str,
    page: int,
    headers: list[str],
    widths: list[float],
    rows: list[list[object]],
    *,
    font_size: float = 5.8,
    leading: float = 6.8,
) -> int:
    """Desenha uma tabela completa em A4 vertical, repetindo cabeçalho e sem cortar linhas."""
    if abs(sum(widths) - (A4[0] - 72)) > 2:
        raise ValueError('As larguras da tabela devem ocupar a largura útil A4.')

    def begin(current_page: int):
        w, h = _new_page(c, title, period, current_page)
        y = h - 102
        c.setFillColor(BLUE)
        c.rect(36, y - 17, sum(widths), 19, fill=1, stroke=0)
        xx = 36
        for head, ww in zip(headers, widths):
            _text(c, xx + 3, y - 11, head, 5.7, white, True)
            xx += ww
        return y - 20

    page += 1
    y = begin(page)
    for raw_row in rows:
        cell_lines = [_cell_lines(value, width - 6, font_size) for value, width in zip(raw_row, widths)]
        row_h = max(12.0, max(len(lines) for lines in cell_lines) * leading + 4.2)
        if y - row_h < 35:
            c.showPage()
            page += 1
            y = begin(page)
        c.setStrokeColor(LINE)
        c.line(36, y - row_h + 1.5, 36 + sum(widths), y - row_h + 1.5)
        xx = 36
        for lines, ww in zip(cell_lines, widths):
            ty = y - font_size - 1
            for line in lines:
                _text(c, xx + 3, ty, line, font_size, TEXT)
                ty -= leading
            xx += ww
        y -= row_h
    c.showPage()
    return page


def _iso_date(value: object) -> str:
    raw = str(value or '')
    if len(raw) >= 10 and raw[4:5] == '-' and raw[7:8] == '-':
        return f'{raw[8:10]}/{raw[5:7]}/{raw[:4]}'
    return '—'


def generate_pdf(result: ReconcileResult, destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    metrics = summarize(result.previsto, result.realizado)
    charts = chart_data(result.previsto, result.realizado)
    suppliers = aggregate_suppliers(result.previsto, result.realizado)

    page = 1
    w, h = _new_page(c, "Relatório Executivo - Previsto x Realizado", result.period_label, page)
    y = h - 160
    gap = 8
    kw = (w - 72 - gap * 2) / 3
    kh = 66
    kpis = [
        ("Previsto", brl(metrics["planned"]), "Soma de Valor previsto"),
        ("Realizado", brl(metrics["actual"]), "Soma do Realizado"),
        ("Desvio", brl(metrics["variance"]), "Realizado menos Previsto"),
        ("Variação", pct(metrics["variance_pct"]), "Desvio dividido pelo Previsto"),
        ("Títulos", str(metrics["titles"]), "Registros realizados"),
        ("Pontualidade", pct(metrics["on_time_rate"]), "Antecipado + dentro do prazo"),
    ]
    for i, k in enumerate(kpis):
        row = i // 3
        col = i % 3
        _kpi(c, 36 + col * (kw + gap), y - row * (kh + gap), kw, kh, *k)
    y -= 2 * (kh + gap) + 30
    _text(c, 36, y, "Leitura executiva", 12, BLUE, True)
    y -= 18
    direction = "acima" if metrics["variance"] >= 0 else "abaixo"
    if metrics["punctuality_denominator"]:
        punctuality_text = f"A pontualidade considera {metrics['punctuality_denominator']} títulos com datas válidas e resultou em {pct(metrics['on_time_rate'])}."
    else:
        punctuality_text = "A pontualidade não foi calculada porque não há Último Pagamento e Vencimento válidos simultaneamente."
    summary = (
        f"O realizado ficou {abs(metrics['variance_pct']):.2f}% {direction} do previsto, com desvio de {brl(abs(metrics['variance']))}. "
        + punctuality_text
    )
    y = _wrapped(c, 36, y, summary, 94, 9, 13, TEXT) - 8
    # Avisos pertencem à auditoria interativa/Excel e, por decisão de apresentação,
    # não são renderizados no PDF executivo.
    c.showPage()

    category_rows, category_months = _category_month_rows(result.previsto, result.realizado)
    category_chunks = [category_rows[index:index + 8] for index in range(0, len(category_rows), 8)] or [[]]
    for chunk_index, chunk in enumerate(category_chunks):
        page += 1
        w, h = _new_page(c, "Gráficos financeiros", result.period_label, page)
        suffix = f" ({chunk_index + 1}/{len(category_chunks)})" if len(category_chunks) > 1 else ""
        _text(c, 36, h - 98, f"1. Previsto x Realizado por categoria{suffix}", 11.5, BLUE, True)
        _period_chip(c, 36, h - 114, _graph_period_subtitle(category_months))
        _category_chart(c, 18, 48, w - 36, h - 170, chunk)
        c.showPage()

    monthly_comparison = _monthly_comparison_rows(result.previsto, result.realizado)
    monthly_chunks = [monthly_comparison[index:index + 6] for index in range(0, len(monthly_comparison), 6)] or [[]]
    for chunk_index, chunk in enumerate(monthly_chunks, start=1):
        page += 1
        w, h = _new_page(c, "Previsto x Realizado por mês", result.period_label, page)
        suffix = f" ({chunk_index}/{len(monthly_chunks)})" if len(monthly_chunks) > 1 else ""
        _text(c, 36, h - 98, f"2. Previsto x Realizado por mês{suffix}", 11.5, BLUE, True)
        shown_months = [
            f"{MONTHS_PT[int(str(row['month'])[5:7]) - 1]}/{str(row['month'])[2:4]}"
            for row in chunk
        ]
        _period_chip(c, 36, h - 114, _graph_period_subtitle(shown_months))
        chart_x, chart_y, chart_h = 30, 92, h - 225
        kpi_w, gap = 132, 12
        chart_w = w - 60 - kpi_w - gap
        _monthly_comparison_chart(c, chart_x, chart_y, chart_w, chart_h, chunk)
        _monthly_local_kpis(c, chart_x + chart_w + gap, chart_y, kpi_w, chart_h, chunk)
        c.showPage()

    waterfall_data = charts["category_waterfall"]
    waterfall_rows = [
        {"label": row["label"], "variance": float(row["contribution"])}
        for row in waterfall_data["steps"]
    ]
    page += 1
    w, h = _new_page(c, "Previsto x Realizado por categoria - Cascata", result.period_label, page)
    _text(c, 36, h - 98, "3. Previsto x Realizado por categoria - Cascata", 11.5, BLUE, True)
    waterfall_months = [
        f"{MONTHS_PT[int(str(row['month'])[5:7]) - 1]}/{str(row['month'])[2:4]}"
        for row in monthly_comparison
    ]
    _period_chip(c, 36, h - 114, _graph_period_subtitle(waterfall_months))
    _waterfall(c, 24, 68, w - 48, h - 205, waterfall_rows, float(waterfall_data["planned"]))
    c.showPage()

    supplier_rows = [[
        row.get("supplier") or "Sem fornecedor",
        row.get("category") or "Não classificado",
        row.get("subcategory") or "",
        row.get("flow") or "Não classificado",
        brl(float(row.get("planned") or 0)),
        brl(float(row.get("actual") or 0)),
        brl(float(row.get("variance") or 0)),
        pct(row.get("variance_pct")),
    ] for row in suppliers]
    page = _paginated_table(
        c, "Detalhamento completo por fornecedor", result.period_label, page,
        ["Fornecedor", "Categoria", "Subcategoria", "Fluxo JMM", "Previsto", "Realizado", "Desvio", "Variação"],
        [108, 58, 58, 55, 62, 62, 62, 58],
        supplier_rows, font_size=5.45, leading=6.3,
    )

    title_rows = [[
        f"{row.get('source_file') or '—'} • {row.get('source_sheet') or '—'}",
        row.get("source_row") or "—",
        row.get("title") or "—",
        row.get("supplier") or "Sem fornecedor",
        row.get("category") or "Não classificado",
        row.get("subcategory") or "",
        _iso_date(row.get("date")),
        _iso_date(row.get("due_date")),
        row.get("punctuality") or "—",
        brl(float(row.get("value") or 0)),
    ] for row in result.realizado]
    page = _paginated_table(
        c, "Títulos realizados - lista completa", result.period_label, page,
        ["Origem", "Linha", "Título", "Fornecedor", "Categoria", "Subcategoria", "Pagamento", "Vencimento", "Pontualidade", "Valor"],
        [63, 24, 77, 72, 48, 48, 42, 42, 48, 59],
        title_rows, font_size=5.0, leading=5.9,
    )

    c.save()
    return path
