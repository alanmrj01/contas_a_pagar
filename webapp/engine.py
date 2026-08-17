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

from .report_optimizer import optimize_report_file
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
        state = self.store.state(sid)
        if state.custom_base_table is not None:
            return BaseView(path=Path("BASE_DADOS_SESSAO.xlsx"), table=state.custom_base_table, is_custom=True)
        wb = read_excel(self.default_base)
        table = detect_base_table(wb)
        validate_base(table)
        return BaseView(path=self.default_base, table=table, is_custom=False)

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

        # Mantém a mesma serialização/segunda leitura de segurança da versão web
        # anterior, mas sem persistir a base personalizada em plaintext no disco.
        verify_dir = self.store.new_work_dir(sid, "base_verify")
        tmp = verify_dir / "base_dados_validada.xlsx"
        try:
            _write_base_xlsx(table, tmp)
            persisted_wb = read_excel(tmp)
            persisted_table = detect_base_table(persisted_wb)
            validate_base(persisted_table)
            self.store.state(sid).custom_base_table = persisted_table
        finally:
            shutil.rmtree(verify_dir, ignore_errors=True)
        self.store.invalidate_validation(sid, preserve_last_outputs=True)
        return self.base_info(sid)

    def export_base(self, sid: str) -> Path:
        table = self.active_base(sid).table
        work = self.store.new_work_dir(sid, "base_export")
        dest = work / "BASE_DADOS.xlsx"
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

        output_dir = self.store.new_report_staging(sid)
        try:
            report = generate_report(validated.result, output_dir, [p.name for p in validated.paths])
            pdf = output_dir / "Relatorio_Contas_a_Pagar.pdf"
            if not report.exists() or not pdf.exists():
                raise RuntimeError("A geração terminou sem produzir todos os arquivos esperados.")

            script_hashes = optimize_report_file(report)
            self.store.replace_report_artifacts(sid, output_dir, script_hashes)
        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

        return {"report_url": "/report/current", "pdf_url": "/report/Relatorio_Contas_a_Pagar.pdf"}
