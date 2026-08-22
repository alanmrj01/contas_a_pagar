from __future__ import annotations

import math
from pathlib import Path
from textwrap import wrap

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics

from .metrics import aggregate_suppliers, chart_data, summarize
from .reconciler import ReconcileResult

BLUE = HexColor("#234865")
BLUE2 = HexColor("#315F82")
ACCENT = HexColor("#65A9D5")
ACCENT2 = HexColor("#8ED1FF")
TEXT = HexColor("#173047")
MUTED = HexColor("#425D6F")
GOOD = HexColor("#3A9E76")
BAD = HexColor("#D85F65")
WARN = HexColor("#D49B39")
LIGHT = HexColor("#F2F6F9")
LINE = HexColor("#D6E1E8")
PASTEL = [
    HexColor("#8EC5E8"), HexColor("#F1B6A8"), HexColor("#A8D8C5"),
    HexColor("#D4C0E8"), HexColor("#EBCB88"), HexColor("#8FCCD1"),
    HexColor("#C7D89B"), HexColor("#E4B8CF"),
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


def _category_chart(c, x, y, w, h, rows):
    if not rows:
        _text(c, x, y + h / 2, "Sem dados", 10, MUTED)
        return
    values = [float(row[key]) for row in rows for key in ("planned", "actual")]
    domain_min = min([0.0, *values])
    domain_max = max([0.0, *values])
    span = domain_max - domain_min or 1.0
    left = x + 145
    right = x + w - 92
    bottom = y + 12
    top = y + h - 30
    plot_w = right - left
    row_h = (top - bottom) / max(1, len(rows))

    def xx(value: float) -> float:
        return left + (value - domain_min) / span * plot_w

    zero_x = xx(0.0)

    def value_bubble(endpoint: float, cy: float, label: str, positive: bool) -> None:
        font_size = 5.8
        bubble_w = min(88, max(52, pdfmetrics.stringWidth(label, "Helvetica-Bold", font_size) + 10))
        desired = endpoint + 4 if positive else endpoint - bubble_w - 4
        bx = max(x + 1, min(x + w - bubble_w - 1, desired))
        c.setFillColor(white)
        c.setStrokeColor(HexColor("#69818F"))
        c.setLineWidth(.55)
        c.roundRect(bx, cy - 5.5, bubble_w, 11, 3, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(TEXT)
        c.drawCentredString(bx + bubble_w / 2, cy - 2, label)

    c.setFillColor(HexColor("#E7F3FA"))
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.2)
    c.roundRect(x + w - 178, y + h - 15, 12, 8, 2, fill=1, stroke=1)
    _text(c, x + w - 161, y + h - 14, "Previsto (claro)", 6.2, MUTED, True)
    c.setFillColor(ACCENT)
    c.setStrokeColor(ACCENT)
    c.roundRect(x + w - 80, y + h - 15, 12, 8, 2, fill=1, stroke=1)
    _text(c, x + w - 63, y + h - 14, "Realizado", 6.2, MUTED, True)

    for i in range(6):
        value = domain_min + span * i / 5
        x_tick = xx(value)
        c.setStrokeColor(LINE)
        c.setLineWidth(.7)
        c.line(x_tick, bottom, x_tick, top)
        c.setFont("Helvetica", 5.8)
        c.setFillColor(MUTED)
        c.drawCentredString(x_tick, top + 8, short_brl(value))

    for i, row in enumerate(rows):
        color = PASTEL[i % len(PASTEL)]
        row_top = top - i * row_h
        middle = row_top - row_h / 2
        _text_fit(c, x + 1, middle - 2, row["label"], max_width=125, start_size=6.4, min_size=4.8, color=MUTED, bold=True)
        for series_index, (key, mark, filled) in enumerate((("planned", "P", False), ("actual", "R", True))):
            value = float(row[key])
            cy = middle + (5.8 if series_index == 0 else -5.8)
            endpoint = xx(value)
            bar_x = min(zero_x, endpoint)
            bar_w = max(1.0, abs(endpoint - zero_x))
            c.setFillColor(color if filled else HexColor("#F7FAFC"))
            c.setStrokeColor(color)
            c.setLineWidth(1.1 if filled else 1.4)
            c.roundRect(bar_x, cy - 3.7, bar_w, 7.4, 2.4, fill=1, stroke=1)
            c.setFont("Helvetica-Bold", 5.6)
            c.setFillColor(MUTED)
            c.drawRightString(left - 5, cy - 2, mark)
            value_bubble(endpoint, cy, brl(value), value >= 0)
        c.setStrokeColor(color)
        c.setLineWidth(.35)
        c.line(x + 1, row_top - row_h + 1, x + w - 1, row_top - row_h + 1)


def _line_chart(c, x, y, w, h, rows):
    if not rows:
        _text(c, x, y + h / 2, "Sem dados temporais suficientes", 10, MUTED)
        return

    monthly: dict[str, dict] = {}
    for row in rows:
        key = str(row["date"])[:7]
        monthly[key] = row
    rows = [monthly[key] for key in sorted(monthly)]

    maxv = max(max(float(r["planned"]), float(r["actual"])) for r in rows) or 1
    left, bottom = x + 49, y + 38
    pw, ph = w - 62, h - 72

    for i in range(5):
        yy = bottom + ph * i / 4
        value = maxv * i / 4
        c.setStrokeColor(LINE)
        c.setLineWidth(.7)
        c.line(left, yy, left + pw, yy)
        c.setFont("Helvetica", 5.8)
        c.setFillColor(MUTED)
        c.drawRightString(left - 5, yy - 2, short_brl(value))

    def px(index: int) -> float:
        return left + (pw / 2 if len(rows) == 1 else pw * index / (len(rows) - 1))

    def py(value: float) -> float:
        return bottom + ph * value / maxv

    for key, color in (("planned", ACCENT), ("actual", HexColor("#F1B6A8"))):
        points = [(px(i), py(float(row[key]))) for i, row in enumerate(rows)]
        c.setStrokeColor(color)
        c.setLineWidth(2.2)
        for a0, b0 in zip(points, points[1:]):
            c.line(a0[0], a0[1], b0[0], b0[1])

    years = {str(row["date"])[:4] for row in rows}
    include_year = len(years) > 1
    for i, row in enumerate(rows):
        raw = str(row["date"])
        year, month = raw[:7].split("-")
        label = MONTHS_PT[int(month) - 1] + (f"/{year[-2:]}" if include_year else "")
        xx = px(i)
        yp, ya = py(float(row["planned"])), py(float(row["actual"]))
        c.setFillColor(ACCENT)
        c.circle(xx, yp, 3.1, fill=1, stroke=0)
        c.setFillColor(HexColor("#F1B6A8"))
        c.circle(xx, ya, 3.1, fill=1, stroke=0)
        c.setFont("Helvetica-Bold", 4.7)
        c.setFillColor(ACCENT)
        p_y = min(y + h - 8, yp + 6)
        a_y = min(y + h - 8, ya + 6)
        if abs(p_y - a_y) < 7:
            a_y = max(bottom + 3, ya - 8)
        c.drawCentredString(xx, p_y, brl(float(row["planned"])))
        c.setFillColor(HexColor("#C76E5C"))
        c.drawCentredString(xx, a_y, brl(float(row["actual"])))
        c.setStrokeColor(MUTED)
        c.line(xx, bottom - 2, xx, bottom - 5)
        c.setFont("Helvetica-Bold", 6.2)
        c.setFillColor(MUTED)
        c.drawCentredString(xx, y + 10, label)

    c.setFillColor(ACCENT)
    c.circle(x + w - 142, y + h - 9, 2.6, fill=1, stroke=0)
    _text(c, x + w - 134, y + h - 12, "Previsto acumulado", 6.2, MUTED)
    c.setFillColor(HexColor("#F1B6A8"))
    c.circle(x + w - 66, y + h - 9, 2.6, fill=1, stroke=0)
    _text(c, x + w - 58, y + h - 12, "Realizado", 6.2, MUTED)


def _lollipop(c, x, y, w, h, rows):
    rows = rows[:8]
    if not rows:
        _text(c, x, y + h / 2, "Sem dados", 10, MUTED)
        return
    maxv = max(abs(r["variance"]) for r in rows) or 1
    label_w = 150
    plot_w = w - label_w - 55
    rh = h / len(rows)
    zero = x + label_w + plot_w / 2
    c.setStrokeColor(LINE)
    c.setLineWidth(.8)
    c.line(zero, y, zero, y + h)
    for i, row in enumerate(rows):
        yy = y + h - (i + .5) * rh
        _text(c, x, yy - 3, str(row["supplier"])[:24], 6.6, MUTED)
        dx = (plot_w / 2 - 10) * row["variance"] / maxv
        # Solicitação visual: positivo em verde; negativo em coral/vermelho.
        color = GOOD if row["variance"] >= 0 else BAD
        c.setStrokeColor(color)
        c.setLineWidth(3.2)
        c.line(zero, yy, zero + dx, yy)
        c.setFillColor(color)
        c.circle(zero + dx, yy, 4.2, fill=1, stroke=0)
        label = brl(float(row["variance"]))
        c.setFont("Helvetica-Bold", 5.6)
        c.setFillColor(color)
        c.drawRightString(x + w, yy - 2, label)


def _waterfall(c, x, y, w, h, rows, start):
    rows = list(rows)
    if len(rows) > 5:
        others = rows[5:]
        rows = rows[:5] + [{"label": "Outros fluxos", "variance": sum(float(r["variance"]) for r in others)}]
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
    bottom = y + 43
    top = y + h - 7
    pw = right - left
    ph = top - bottom
    slot = pw / (len(rows) + 2)
    bw = min(38, slot * .58)

    def yy(value: float) -> float:
        return bottom + ph * (value - domain_min) / span

    def value_bubble(cx: float, preferred_y: float, label: str, stagger: bool = False) -> None:
        font_size = 5.7
        bubble_w = min(78, max(49, pdfmetrics.stringWidth(label, "Helvetica-Bold", font_size) + 9))
        bx = max(x + 1, min(x + w - bubble_w - 1, cx - bubble_w / 2))
        by = max(bottom + 1, min(top - 12, preferred_y + (8 if stagger else 0)))
        c.setFillColor(white)
        c.setStrokeColor(HexColor("#69818F"))
        c.setLineWidth(.55)
        c.roundRect(bx, by, bubble_w, 11, 3, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(TEXT)
        c.drawCentredString(bx + bubble_w / 2, by + 3.1, label)

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
    c.setFillColor(ACCENT)
    c.roundRect(start_x, min(zero_y, start_y), bw, max(3, abs(start_y - zero_y)), 2.5, fill=1, stroke=0)
    value_bubble(start_x + bw / 2, max(zero_y, start_y) + 4, brl(float(start)))
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
        bar_color = BAD if value >= 0 else GOOD
        c.setFillColor(bar_color)
        c.roundRect(x0, min(y1, y2), bw, max(3, abs(y2 - y1)), 2.5, fill=1, stroke=0)
        value_y = (max(y1, y2) + 4 + (8 if i % 2 else 0)) if value >= 0 else (min(y1, y2) - 14 - (8 if i % 2 else 0))
        value_bubble(x0 + bw / 2, value_y, brl(value))
        for j, label in enumerate(_label_lines(row["label"], 10, 2)):
            c.setFont("Helvetica-Bold", 5.1)
            c.setFillColor(MUTED)
            c.drawCentredString(x0 + bw / 2, y + 20 - j * 6.5, label)
        prev = nxt

    final_x = left + (len(rows) + 1) * slot + slot * .2
    final_y = yy(actual)
    c.setFillColor(HexColor("#9CD8FF"))
    c.roundRect(final_x, min(zero_y, final_y), bw, max(3, abs(final_y - zero_y)), 2.5, fill=1, stroke=0)
    value_bubble(final_x + bw / 2, max(zero_y, final_y) + 4, brl(float(actual)), stagger=bool(len(rows) % 2))
    c.setFont("Helvetica-Bold", 5.8)
    c.setFillColor(MUTED)
    c.drawCentredString(final_x + bw / 2, y + 13, "Realizado")



def _monthly_supplier_category_chart(c, x, y, w, h, rows):
    """Resumo A4: mês + fornecedor + Fluxo JMM + Categoria + comparação mensal."""
    if not rows:
        _text(c, x, y + h / 2, "Sem dados mensais com data válida", 9, MUTED)
        return

    rows = sorted(rows, key=lambda r: max(abs(float(r["planned"])), abs(float(r["actual"]))), reverse=True)[:10]
    maxv = max(max(abs(float(r["planned"])), abs(float(r["actual"]))) for r in rows) or 1.0
    cols = 2
    gap_x, gap_y = 10, 9
    card_w = (w - gap_x) / cols
    rows_count = math.ceil(len(rows) / cols)
    card_h = min(105, (h - gap_y * max(0, rows_count - 1)) / max(1, rows_count))
    years = {str(r["month"])[:4] for r in rows}
    include_year = len(years) > 1

    for i, row in enumerate(rows):
        col = i % cols
        rr = i // cols
        cx = x + col * (card_w + gap_x)
        cy = y + h - (rr + 1) * card_h - rr * gap_y
        supplier_color = _supplier_color(str(row["supplier"]))

        c.setFillColor(HexColor("#F8FAFC"))
        c.setStrokeColor(LINE)
        c.setLineWidth(.8)
        c.roundRect(cx, cy, card_w, card_h, 7, fill=1, stroke=1)
        c.setFillColor(supplier_color)
        c.roundRect(cx, cy, 3.2, card_h, 1.5, fill=1, stroke=0)

        month = str(row["month"])
        year, month_num = month.split("-")
        month_label = MONTHS_PT[int(month_num) - 1] + (f"/{year[-2:]}" if include_year else "")
        _text(c, cx + 10, cy + card_h - 15, str(row["supplier"])[:31], 6.8, supplier_color, True)
        c.setFont("Helvetica-Bold", 5.6)
        c.setFillColor(MUTED)
        c.drawRightString(cx + card_w - 9, cy + card_h - 15, month_label)
        _text(c, cx + 10, cy + card_h - 28, f"Fluxo JMM: {str(row.get('flow') or 'Não classificado')[:28]}", 5.4, MUTED, True)
        _text(c, cx + 10, cy + card_h - 39, f"Categoria: {str(row.get('category') or 'Não classificado')[:29]}", 5.4, MUTED)

        metrics = (
            ("Previsto", float(row["planned"]), ACCENT),
            ("Realizado", float(row["actual"]), HexColor("#F1B6A8")),
        )
        for j, (name, value, color) in enumerate(metrics):
            yy = cy + card_h - 56 - j * 17
            _text(c, cx + 10, yy, name, 5.5, MUTED, True)
            _text_fit(c, cx + card_w - 10, yy, brl(value), max_width=card_w * .58, start_size=5.9, min_size=4.7, color=TEXT, bold=True, align="right")
            track_y = yy - 7
            track_w = card_w - 20
            c.setFillColor(HexColor("#E9EFF3"))
            c.roundRect(cx + 10, track_y, track_w, 4.5, 2.2, fill=1, stroke=0)
            fill_w = track_w * abs(value) / maxv if value else 0
            c.setFillColor(color)
            c.roundRect(cx + 10, track_y, max(1.1 if value else 0, fill_w), 4.5, 2.2, fill=1, stroke=0)

        if row.get("has_previous"):
            dp = float(row.get("planned_mom_delta") or 0)
            dr = float(row.get("actual_mom_delta") or 0)
            prev = str(row.get("previous_month") or "")
            py, pm = prev.split("-") if "-" in prev else ("", "")
            prev_label = MONTHS_PT[int(pm) - 1] + (f"/{py[-2:]}" if include_year and py else "") if pm else "mês anterior"
            _text_fit(c, cx + 10, cy + 8, f"vs {prev_label}: P {brl(dp)} | R {brl(dr)}", max_width=card_w - 20, start_size=5.3, min_size=4.2, color=MUTED, bold=True)
        else:
            _text_fit(c, cx + 10, cy + 8, "Comparação mensal: sem registro equivalente no mês anterior", max_width=card_w - 20, start_size=5.0, min_size=4.0, color=MUTED)

def _donut(c, x, y, size, counts):
    # Compatibilidade com relatórios gerados por versões anteriores.
    counts = dict(counts)
    if "No vencimento" in counts and "Dentro do Prazo" not in counts:
        counts["Dentro do Prazo"] = counts.pop("No vencimento")
    total = sum(counts.values()) or 1
    colors = {"Antecipado": ACCENT, "Dentro do Prazo": GOOD, "Atrasado": BAD, "Sem data": WARN}
    start_angle = 90
    order = ["Antecipado", "Dentro do Prazo", "Atrasado", "Sem data"]
    for name in order:
        n = counts.get(name, 0)
        if not n:
            continue
        extent = 360 * n / total
        c.setFillColor(colors[name])
        c.setStrokeColor(white)
        c.wedge(x, y, x + size, y + size, start_angle, extent, fill=1, stroke=1)
        start_angle += extent
    inner = size * .54
    c.setFillColor(white)
    c.circle(x + size / 2, y + size / 2, inner / 2, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(BLUE)
    c.drawCentredString(x + size / 2, y + size / 2 + 1, str(total))
    _text(c, x + size / 2 - 16, y + size / 2 - 12, "títulos", 6.2, MUTED)
    legend_x = x + size + 18
    legend_y = y + size - 12
    for name in order:
        n = counts.get(name, 0)
        if n:
            c.setFillColor(colors[name])
            c.circle(legend_x, legend_y + 2, 3, fill=1, stroke=0)
            percentage = n / total * 100
            _text(c, legend_x + 9, legend_y, f"{name}: {n} ({percentage:.1f}%)".replace(".", ","), 7.3, MUTED)
            legend_y -= 16




def _cell_lines(value: object, width: float, font_size: float) -> list[str]:
    text = str(value if value not in (None, '') else '—')
    approx_chars = max(4, int(width / max(2.8, font_size * 0.54)))
    return wrap(text, width=approx_chars, break_long_words=True, break_on_hyphens=True) or ['—']


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

    category_rows = list(charts["categories"])
    category_chunks = [category_rows[index:index + 8] for index in range(0, len(category_rows), 8)] or [[]]
    for chunk_index, chunk in enumerate(category_chunks):
        page += 1
        w, h = _new_page(c, "Gráficos financeiros", result.period_label, page)
        suffix = f" ({chunk_index + 1}/{len(category_chunks)})" if len(category_chunks) > 1 else ""
        _text(c, 36, h - 98, f"1. Previsto x Realizado por categoria{suffix}", 10, BLUE, True)
        _text(c, 36, h - 112, "Barras horizontais; todos os valores exatos aparecem em rótulos de alto contraste.", 6.8, MUTED)
        _category_chart(c, 36, h - 625, w - 72, 480, chunk)
        c.showPage()

    page += 1
    w, h = _new_page(c, "Comparativo mensal por fornecedor", result.period_label, page)
    _text(c, 36, h - 98, "2. Previsto x Realizado por fornecedor, Fluxo JMM e Categoria", 10, BLUE, True)
    _text(c, 36, h - 112, "Resumo visual das maiores relações. O detalhamento mensal completo, sem barras de rolagem, segue nas páginas seguintes.", 6.3, MUTED)
    _monthly_supplier_category_chart(c, 36, h - 720, w - 72, 565, charts["monthly_supplier_category"])
    c.showPage()

    monthly_rows = []
    for row in charts["monthly_supplier_category"]:
        if row.get("has_previous"):
            previous = f"Previsto {brl(float(row.get('planned_mom_delta') or 0))}; Realizado {brl(float(row.get('actual_mom_delta') or 0))}"
        else:
            previous = "Sem a mesma relação no mês anterior"
        monthly_rows.append([
            str(row.get("month") or "—"),
            row.get("supplier") or "Sem fornecedor",
            row.get("flow") or "Não classificado",
            row.get("category") or "Não classificado",
            brl(float(row.get("planned") or 0)),
            brl(float(row.get("actual") or 0)),
            previous,
        ])
    page = _paginated_table(
        c, "Comparativo mensal completo", result.period_label, page,
        ["Mês", "Fornecedor", "Fluxo JMM", "Categoria", "Previsto", "Realizado", "Comparação com mês anterior"],
        [42, 105, 62, 67, 67, 67, 113],
        monthly_rows, font_size=5.35, leading=6.2,
    )

    page += 1
    w, h = _new_page(c, "Desvios financeiros", result.period_label, page)
    _text(c, 36, h - 98, "3. Maiores desvios por fornecedor", 10, BLUE, True)
    _lollipop(c, 36, h - 365, w - 72, 240, suppliers)
    _text(c, 36, h - 405, "4. Contribuição para o desvio por Fluxo JMM", 10, BLUE, True)
    _waterfall(c, 36, h - 720, w - 72, 275, charts["flows"], metrics["planned"])
    c.showPage()

    supplier_rows = [[
        row.get("supplier") or "Sem fornecedor",
        row.get("category") or "Não classificado",
        row.get("flow") or "Não classificado",
        brl(float(row.get("planned") or 0)),
        brl(float(row.get("actual") or 0)),
        brl(float(row.get("variance") or 0)),
        pct(row.get("variance_pct")),
    ] for row in suppliers]
    page = _paginated_table(
        c, "Detalhamento completo por fornecedor", result.period_label, page,
        ["Fornecedor", "Categoria", "Fluxo JMM", "Previsto", "Realizado", "Desvio", "Variação"],
        [130, 70, 65, 66, 66, 66, 60],
        supplier_rows, font_size=5.45, leading=6.3,
    )

    title_rows = [[
        f"{row.get('source_file') or '—'} • {row.get('source_sheet') or '—'}",
        row.get("source_row") or "—",
        row.get("title") or "—",
        row.get("supplier") or "Sem fornecedor",
        row.get("category") or "Não classificado",
        _iso_date(row.get("date")),
        _iso_date(row.get("due_date")),
        row.get("punctuality") or "—",
        brl(float(row.get("value") or 0)),
    ] for row in result.realizado]
    page = _paginated_table(
        c, "Títulos realizados - lista completa", result.period_label, page,
        ["Origem", "Linha", "Título", "Fornecedor", "Categoria", "Pagamento", "Vencimento", "Pontualidade", "Valor"],
        [64, 28, 88, 80, 52, 50, 50, 55, 56],
        title_rows, font_size=5.0, leading=5.9,
    )

    c.save()
    return path
