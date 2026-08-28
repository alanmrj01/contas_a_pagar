from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .excel_export import export_report_workbooks
from .metrics import chart_data, summarize
from .pdf_report import generate_pdf
from .reconciler import ReconcileResult


def generate_report(result: ReconcileResult, output_dir: str | Path, source_names: list[str] | str) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    metrics = summarize(result.previsto, result.realizado)
    exports = export_report_workbooks(result, out)
    pdf_path = generate_pdf(result, out / "Relatorio_Contas_a_Pagar.pdf")
    if isinstance(source_names, str):
        source_names = [source_names]
    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "sourceNames": source_names,
        "sourceName": " • ".join(source_names),
        "period": result.period_label,
        "warnings": result.warnings,
        "summary": metrics,
        "charts": chart_data(result.previsto, result.realizado),
        "previsto": result.previsto,
        "realizado": result.realizado,
        "downloads": {**exports, "pdf": pdf_path.name},
        "calculationInfo": {
            "planned": "Soma do PREVISTO após validação. No layout padrão, o cálculo usa o campo exato 'Valor previsto'. No layout consolidado, usa o campo exato 'Previsto' somente nas linhas em que o campo exato 'Situação FC' é 'Previsto'. Nenhuma linha é deduplicada automaticamente.",
            "actual": "Soma do REALIZADO após validação. No layout padrão, o cálculo usa o campo exato 'Vlr.Original' (Valor Original). No layout consolidado, usa o valor absoluto do campo exato 'Realizado' somente nas linhas em que o campo exato 'Situação FC' é 'Realizado'. Nenhuma linha é deduplicada automaticamente.",
            "variance": "Cálculo do indicador: total Realizado menos total Previsto. O total Previsto vem do campo exato 'Valor previsto' no layout padrão ou 'Previsto' no consolidado; o total Realizado vem do campo exato 'Vlr.Original' (Valor Original) no layout padrão ou 'Realizado' no consolidado. Valor positivo significa realizado acima do previsto; negativo significa abaixo.",
            "variancePct": "Cálculo do indicador: (total Realizado - total Previsto) dividido pelo total Previsto, multiplicado por 100. Quando o total Previsto é zero, a variação percentual não é calculada.",
            "suppliers": "Quantidade de chaves canônicas de fornecedor. A chave determinística principal é o campo exato 'Cód Fornecedor' da BASE DADOS; o nome normalizado exato e inequívoco é usado somente como fallback controlado.",
            "punctuality": "Compara o campo exato 'Ult. Pgto.' (Último Pagamento) com o campo exato 'Vencimento'. Antecipado: pagamento anterior ao vencimento; Dentro do Prazo: pagamento na data do vencimento; Atrasado: pagamento posterior ao vencimento. Registros sem as duas datas válidas ficam fora da taxa.",
            "classification": "Classificação determinística: código exato da BASE DADOS; nome normalizado exato e inequívoco da base; classificação completa da própria linha; ou histórico inequívoco do mesmo código no arquivo. Conflitos permanecem como Não classificado.",
        },
    }
    template_path = Path(__file__).resolve().parent.parent / "report" / "report_template.html"
    html = template_path.read_text(encoding="utf-8")
    base_component_path = Path(__file__).resolve().parents[2] / "webapp" / "static" / "base_table_component.js"
    base_component = base_component_path.read_text(encoding="utf-8")
    action_feedback_path = Path(__file__).resolve().parents[2] / "webapp" / "static" / "action_feedback.js"
    action_feedback = action_feedback_path.read_text(encoding="utf-8")
    action_feedback_styles_path = Path(__file__).resolve().parents[2] / "webapp" / "static" / "action_feedback.css"
    action_feedback_styles = action_feedback_styles_path.read_text(encoding="utf-8")
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    html = html.replace("__REPORT_DATA__", data_json.replace("</", "<\\/"))
    html = html.replace("__ACTION_FEEDBACK_STYLES__", action_feedback_styles.replace("</", "<\\/"))
    html = html.replace("__ACTION_FEEDBACK_COMPONENT__", action_feedback.replace("</", "<\\/"))
    html = html.replace("__BASE_TABLE_COMPONENT__", base_component.replace("</", "<\\/"))
    output = out / "index.html"
    output.write_text(html, encoding="utf-8")
    return output
