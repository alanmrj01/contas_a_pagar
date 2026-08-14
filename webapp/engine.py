from __future__ import annotations

import html
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.base_manager import _write_base_xlsx
from app.services.excel_reader import TableData, WorkbookData, read_excel
from app.services.normalizer import find_column
from app.services.reconciler import ReconcileResult, reconcile, validate_base
from app.services.report_generator import generate_report
from app.services.sheet_detector import InputDetection, detect_base_table, detect_input_tables
from app.services.validation_service import ValidatedInput

from .session_store import SessionStore


@dataclass
class BaseView:
    path: Path
    table: TableData
    is_custom: bool


class WebEngine:
    """Adaptador web que reutiliza o motor determinístico original sem alterá-lo."""

    def __init__(self, project_root: Path, store: SessionStore):
        self.project_root = project_root.resolve()
        self.store = store
        self.default_base = self.project_root / "resources" / "base_dados_padrao.xlsx"

    def active_base(self, sid: str) -> BaseView:
        custom = self.store.custom_base_path(sid)
        path = custom if custom.exists() else self.default_base
        wb = read_excel(path)
        table = detect_base_table(wb)
        validate_base(table)
        return BaseView(path=path, table=table, is_custom=custom.exists())

    def base_info(self, sid: str) -> dict[str, Any]:
        base = self.active_base(sid)
        return {
            "rows": len(base.table.rows),
            "is_custom": base.is_custom,
            "origin": "personalizada" if base.is_custom else "padrão",
            "sheet": base.table.sheet_name,
        }

    def base_rows(self, sid: str) -> dict[str, Any]:
        base = self.active_base(sid)
        table = base.table
        c_code = find_column(table, "Cód Fornecedor", "Codigo Fornecedor")
        c_name = find_column(table, "Fornecedor")
        c_flow = find_column(table, "Fluxo JMM", "Fluxo")
        c_cat = find_column(table, "Categoria")
        rows = [
            {
                "supplier_code": str(row.get(c_code) or ""),
                "supplier": str(row.get(c_name) or ""),
                "flow": str(row.get(c_flow) or ""),
                "category": str(row.get(c_cat) or ""),
            }
            for row in table.rows
        ]
        return {**self.base_info(sid), "items": rows}

    def import_base(self, sid: str, uploaded_path: Path) -> dict[str, Any]:
        wb = read_excel(uploaded_path)
        table = detect_base_table(wb)
        validate_base(table)
        dest = self.store.custom_base_path(sid)
        tmp = dest.with_suffix(".tmp.xlsx")
        try:
            _write_base_xlsx(table, tmp)
            # Reabre antes de substituir, exatamente para não destruir uma base
            # anterior válida se o arquivo persistido não puder ser relido.
            persisted_wb = read_excel(tmp)
            persisted_table = detect_base_table(persisted_wb)
            validate_base(persisted_table)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
        self.store.invalidate_validation(sid, preserve_last_outputs=True)
        return self.base_info(sid)

    def export_base(self, sid: str) -> Path:
        table = self.active_base(sid).table
        dest = self.store.export_base_path(sid)
        _write_base_xlsx(table, dest)
        return dest

    def validate(self, sid: str, paths: list[Path]) -> ValidatedInput:
        # Mesma sequência determinística de validation_service.validate_inputs;
        # a única diferença é a resolução da BASE DADOS por sessão web.
        unique: list[Path] = []
        seen: set[str] = set()
        for raw in paths:
            path = Path(raw).resolve()
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                unique.append(path)
        if not unique:
            raise RuntimeError("Adicione ao menos um arquivo com PREVISTO e/ou REALIZADO.")

        workbooks: list[WorkbookData] = [read_excel(path) for path in unique]
        detection: InputDetection = detect_input_tables(workbooks)
        base = self.active_base(sid).table
        result: ReconcileResult = reconcile(detection.previsto, detection.realizado, base)
        if detection.notes:
            result.warnings.insert(0, {
                "level": "info",
                "title": "Formato de entrada reconhecido",
                "summary": "A automação adaptou o layout importado sem usar aproximações para classificar PREVISTO/REALIZADO.",
                "details": [{"mensagem": note} for note in detection.notes],
            })
        validated = ValidatedInput(unique, workbooks, detection, result)
        state = self.store.state(sid)
        state.validated = validated
        state.last_source_names = [p.name for p in unique]
        return validated

    def validation_summary(self, validated: ValidatedInput) -> dict[str, Any]:
        d = validated.detection
        r = validated.result
        notes = [str(x) for x in getattr(d, "notes", []) if str(x).strip()]
        if d.ignored_tables:
            ignored = ", ".join(
                f"{t.source_path.name if t.source_path else ''} / {t.sheet_name}"
                for t in d.ignored_tables[:6]
            )
            notes.append(f"Abas identificadas, mas não usadas como PREVISTO/REALIZADO: {ignored}")
        return {
            "previsto": len(r.previsto),
            "previsto_tables": len(d.previsto_tables),
            "realizado": len(r.realizado),
            "realizado_tables": len(d.realizado_tables),
            "base": r.base_rows,
            "period": str(r.period_label),
            "notes": notes,
            "warnings": [
                {
                    "level": str(w.get("level") or "warning"),
                    "title": str(w.get("title") or ""),
                    "summary": str(w.get("summary") or ""),
                }
                for w in r.warnings
            ],
        }

    def generate(self, sid: str) -> dict[str, str]:
        state = self.store.state(sid)
        validated = state.validated
        if validated is None:
            raise RuntimeError("Valide os arquivos antes de gerar o relatório.")

        output_dir = self.store.report_dir(sid)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        report = generate_report(validated.result, output_dir, [p.name for p in validated.paths])
        pdf = output_dir / "Relatorio_Contas_a_Pagar.pdf"
        if not report.exists() or not pdf.exists():
            raise RuntimeError("A geração terminou sem produzir todos os arquivos esperados.")

        report_url = f"/generated/{sid}/current/index.html"
        pdf_url = f"/generated/{sid}/current/Relatorio_Contas_a_Pagar.pdf"
        state.last_report_url = report_url
        state.last_pdf_url = pdf_url
        return {"report_url": report_url, "pdf_url": pdf_url}
