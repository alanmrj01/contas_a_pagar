from __future__ import annotations

import html
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.base_manager import _write_base_xlsx
from app.services.excel_reader import TableData, WorkbookData, read_excel
from app.services.normalizer import find_column
from app.services.reconciler import ReconcileResult, normalize_supplier_code, reconcile, validate_base
from app.services.report_generator import generate_report
from app.services.sheet_detector import InputDetection, detect_base_table, detect_input_tables
from app.services.text_utils import normalize_text
from app.services.validation_service import ValidatedInput

from .report_optimizer import optimize_report_file
from .session_store import SessionStore
from .supabase_gateway import SupabaseGateway


@dataclass
class BaseView:
    path: Path
    table: TableData
    is_custom: bool


class WebEngine:
    """Adaptador web que reutiliza o motor determinístico original sem alterá-lo."""

    def __init__(self, project_root: Path, store: SessionStore, persistence: SupabaseGateway):
        self.project_root = project_root.resolve()
        self.store = store
        self.persistence = persistence
        self.default_base = self.project_root / "resources" / "base_dados_padrao.xlsx"

    @staticmethod
    def _base_items(table: TableData) -> list[dict[str, str]]:
        c_code = find_column(table, "Cód Fornecedor", "Codigo Fornecedor")
        c_name = find_column(table, "Fornecedor")
        c_flow = find_column(table, "Fluxo JMM", "Fluxo")
        c_cat = find_column(table, "Categoria")
        return [
            {
                "supplier_code": WebEngine._code_key(row.get(c_code)),
                "supplier": str(row.get(c_name) or "").strip(),
                "flow": str(row.get(c_flow) or "").strip(),
                "category": str(row.get(c_cat) or "").strip(),
            }
            for row in table.rows
        ]

    @staticmethod
    def _table_from_items(items: list[dict[str, Any]], *, source_name: str = "BASE_DADOS_EDITADA") -> TableData:
        headers = ["Cód Fornecedor", "Fornecedor", "Fluxo JMM", "Categoria"]
        rows = []
        for index, item in enumerate(items, start=2):
            rows.append({
                "Cód Fornecedor": str(item.get("supplier_code") or "").strip(),
                "Fornecedor": str(item.get("supplier") or "").strip(),
                "Fluxo JMM": str(item.get("flow") or "").strip(),
                "Categoria": str(item.get("category") or "").strip(),
                "__source_file__": source_name,
                "__source_path__": source_name,
                "__source_sheet__": "BASE DADOS",
                "__source_row__": index,
            })
        table = TableData(
            sheet_name="BASE DADOS",
            headers=headers,
            rows=rows,
            source_path=Path(source_name),
            header_row=1,
        )
        validate_base(table)
        return table

    def load_persistent_base(self, sid: str) -> dict[str, Any]:
        state = self.store.state(sid)
        if not state.authenticated_user_id:
            raise RuntimeError("Autenticação necessária para carregar a BASE DADOS.")
        loaded = self.persistence.load_base(state.authenticated_user_id)
        if loaded is None:
            state.custom_base_table = None
            state.custom_base_revision = ""
            return self.base_info(sid)
        items, revision = loaded
        table = self._table_from_items(items, source_name="BASE_DADOS_SUPABASE.enc")
        state.custom_base_table = table
        state.custom_base_revision = revision
        return self.base_info(sid)

    def _commit_base(self, sid: str, table: TableData) -> dict[str, Any]:
        validate_base(table)
        verify_dir = self.store.new_work_dir(sid, "base_verify")
        tmp = verify_dir / "base_dados_validada.xlsx"
        try:
            _write_base_xlsx(table, tmp)
            persisted_wb = read_excel(tmp)
            persisted_table = detect_base_table(persisted_wb)
            validate_base(persisted_table)
            state = self.store.state(sid)
            if not state.authenticated_user_id:
                raise RuntimeError("Autenticação necessária para salvar a BASE DADOS.")
            revision = self.persistence.save_base(
                state.authenticated_user_id,
                self._base_items(persisted_table),
            )
            state.custom_base_table = persisted_table
            state.custom_base_revision = revision
        finally:
            shutil.rmtree(verify_dir, ignore_errors=True)
        self.store.invalidate_validation(sid, preserve_last_outputs=True)
        return self.base_info(sid)

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
        state = self.store.state(sid)
        return {
            "rows": len(base.table.rows),
            "is_custom": base.is_custom,
            "origin": "persistida no Supabase" if base.is_custom else "padrão",
            "sheet": base.table.sheet_name,
            "revision": state.custom_base_revision if base.is_custom else "padrao",
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
                "supplier_code": self._code_key(row.get(c_code)),
                "supplier": str(row.get(c_name) or ""),
                "flow": str(row.get(c_flow) or ""),
                "category": str(row.get(c_cat) or ""),
            }
            for row in table.rows
        ]
        return {**self.base_info(sid), "items": rows}

    def base_options(self, sid: str) -> dict[str, list[str]]:
        items = self.base_rows(sid)["items"]
        return {
            "flows": sorted({item["flow"] for item in items if item["flow"]}, key=str.casefold),
            "categories": sorted({item["category"] for item in items if item["category"]}, key=str.casefold),
        }

    def import_base(
        self,
        sid: str,
        uploaded_path: Path,
        *,
        mode: str,
        duplicate_action: str = "ask",
        edited_duplicates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        wb = read_excel(uploaded_path)
        table = detect_base_table(wb)
        validate_base(table)
        imported_items = self._base_items(table)
        edits = {
            int(item.get("row_index")): item
            for item in (edited_duplicates or [])
            if str(item.get("row_index", "")).isdigit()
        }
        if edits:
            imported_items = [
                {
                    "supplier_code": str(edits[index].get("supplier_code") or "").strip(),
                    "supplier": str(edits[index].get("supplier") or "").strip(),
                    "flow": str(edits[index].get("flow") or "").strip(),
                    "category": str(edits[index].get("category") or "").strip(),
                }
                if index in edits else item
                for index, item in enumerate(imported_items)
            ]
            # A edição não pode introduzir campos vazios ou códigos duplicados.
            self._table_from_items(imported_items, source_name="BASE_DADOS_IMPORTADA_EDITADA")

        if mode == "replace":
            info = self._commit_base(sid, self._table_from_items(imported_items, source_name="BASE_DADOS_IMPORTADA"))
            return {"ok": True, "base": info, "added": len(imported_items), "ignored": 0}
        if mode != "append":
            raise RuntimeError("Escolha inválida para importação da BASE DADOS.")

        current_items = self._base_items(self.active_base(sid).table)
        by_code = {self._code_key(item["supplier_code"]): item for item in current_items}
        by_name = {normalize_text(item["supplier"]): item for item in current_items if normalize_text(item["supplier"])}
        conflicts: list[dict[str, Any]] = []
        additions: list[dict[str, str]] = []
        conflict_indexes: set[int] = set()
        for index, item in enumerate(imported_items):
            code = self._code_key(item["supplier_code"])
            name_key = normalize_text(item["supplier"])
            current = by_code.get(code) or by_name.get(name_key)
            if current is not None:
                reason = "Mesmo Cód Fornecedor" if code in by_code else "Mesmo Fornecedor"
                conflicts.append({
                    "row_index": index,
                    "reason": reason,
                    "current": dict(current),
                    "uploaded": dict(item),
                })
                conflict_indexes.add(index)
            else:
                additions.append(item)

        if conflicts and duplicate_action in {"ask", "edit"}:
            return {
                "ok": False,
                "requires_resolution": True,
                "conflicts": conflicts,
                "new_rows": len(additions),
            }
        if duplicate_action not in {"ask", "ignore", "edit"}:
            raise RuntimeError("Ação inválida para valores já existentes na BASE DADOS.")

        merged = [*current_items, *additions]
        if len(merged) == len(current_items):
            return {
                "ok": True,
                "base": self.base_info(sid),
                "added": 0,
                "ignored": len(conflict_indexes),
            }
        info = self._commit_base(sid, self._table_from_items(merged, source_name="BASE_DADOS_MESCLADA"))
        return {
            "ok": True,
            "base": info,
            "added": len(additions),
            "ignored": len(conflict_indexes),
        }

    def update_base(self, sid: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            raise RuntimeError("A BASE DADOS precisa conter ao menos um fornecedor.")
        return self._commit_base(sid, self._table_from_items(items))

    def apply_classifications(self, sid: str, assignments: list[dict[str, Any]]) -> dict[str, Any]:
        if not assignments:
            raise RuntimeError("Selecione ao menos uma linha para atualizar.")
        options = self.base_options(sid)
        allowed_flows = set(options["flows"])
        allowed_categories = set(options["categories"])
        grouped: dict[str, dict[str, str]] = {}
        for assignment in assignments:
            code = self._code_key(assignment.get("supplier_code"))
            candidate = {
                "supplier_code": code,
                "supplier": str(assignment.get("supplier") or "").strip(),
                "flow": str(assignment.get("flow") or "").strip(),
                "category": str(assignment.get("category") or "").strip(),
            }
            if not all(candidate.values()):
                raise RuntimeError("Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria são obrigatórios nas linhas selecionadas.")
            if candidate["flow"] not in allowed_flows or candidate["category"] not in allowed_categories:
                raise RuntimeError("Fluxo JMM ou Categoria não pertence às opções atuais da BASE DADOS.")
            previous = grouped.get(code)
            if previous and (previous["flow"].casefold(), previous["category"].casefold()) != (
                candidate["flow"].casefold(), candidate["category"].casefold()
            ):
                raise RuntimeError(f"O fornecedor de código {code} recebeu classificações conflitantes na mesma atualização.")
            grouped[code] = candidate

        items = self._base_items(self.active_base(sid).table)
        index_by_code = {self._code_key(item["supplier_code"]): index for index, item in enumerate(items)}
        for code, candidate in grouped.items():
            existing_index = index_by_code.get(code)
            if existing_index is None:
                index_by_code[code] = len(items)
                items.append(candidate)
            else:
                current = dict(items[existing_index])
                current["flow"] = candidate["flow"]
                current["category"] = candidate["category"]
                items[existing_index] = current
        return self._commit_base(sid, self._table_from_items(items, source_name="BASE_DADOS_CLASSIFICADA_NO_RELATORIO"))

    def export_base(self, sid: str) -> Path:
        table = self.active_base(sid).table
        work = self.store.new_work_dir(sid, "base_export")
        dest = work / "BASE_DADOS.xlsx"
        _write_base_xlsx(table, dest)
        return dest

    @staticmethod
    def _code_key(value: Any) -> str:
        """Normaliza código de fornecedor sem inferir ou aproximar seu conteúdo."""
        return normalize_supplier_code(value)

    @classmethod
    def _supplement_base_from_imported_workbooks(
        cls,
        base: TableData,
        workbooks: list[WorkbookData],
    ) -> tuple[TableData, dict[str, Any]]:
        """Complementa a BASE DADOS apenas para a validação/relatório corrente.

        Regras de segurança e integridade:
        - a BASE DADOS ativa continua tendo precedência;
        - somente códigos AUSENTES da base podem ser complementados;
        - a planilha de entrada precisa trazer, na mesma tabela, Cód Fornecedor,
          Fornecedor, Fluxo JMM e Categoria;
        - linhas incompletas nunca viram classificação automática;
        - se um mesmo código novo trouxer Fluxo JMM/Categoria conflitantes, ele
          não é adicionado e permanece sujeito ao tratamento normal de
          "Não classificado";
        - variações apenas no nome do mesmo código são toleradas quando Fluxo JMM
          e Categoria são idênticos; o nome mais frequente é usado, com desempate
          determinístico pelo texto mais completo.
        - nada é persistido na base padrão nem entre novas validações.
        """
        b_code = find_column(base, "Cód Fornecedor", "Codigo Fornecedor")
        b_name = find_column(base, "Fornecedor")
        b_flow = find_column(base, "Fluxo JMM", "Fluxo")
        b_cat = find_column(base, "Categoria")
        if not all((b_code, b_name, b_flow, b_cat)):
            # validate_base já produzirá a mensagem detalhada; não criar
            # comportamento paralelo quando a própria base estiver inválida.
            return base, {
                "added_suppliers": 0,
                "affected_records": 0,
                "conflicting_suppliers": 0,
                "conflicts": [],
                "conflicting_codes": [],
            }

        existing_codes = {
            cls._code_key(row.get(b_code))
            for row in base.rows
            if cls._code_key(row.get(b_code))
        }

        # code -> {"records": [...], "names": Counter, "classifications": {...}}
        candidates: dict[str, dict[str, Any]] = {}
        affected_records = Counter()

        for workbook in workbooks:
            for table in workbook.tables:
                c_code = find_column(table, "Cód Fornecedor", "Codigo Fornecedor")
                c_name = find_column(table, "Fornecedor")
                c_flow = find_column(table, "Fluxo JMM", "Fluxo")
                c_cat = find_column(table, "Categoria")
                if not all((c_code, c_name, c_flow, c_cat)):
                    continue

                for row in table.rows:
                    code = cls._code_key(row.get(c_code))
                    name = str(row.get(c_name) or "").strip()
                    flow = str(row.get(c_flow) or "").strip()
                    category = str(row.get(c_cat) or "").strip()

                    # O complemento só pode ser criado com a chave completa.
                    if not code or not name or not flow or not category:
                        continue
                    if code in existing_codes:
                        continue

                    bucket = candidates.setdefault(code, {
                        "names": Counter(),
                        "classifications": {},
                        "first_source": None,
                    })
                    bucket["names"][name] += 1
                    cls_key = (flow.casefold(), category.casefold())
                    bucket["classifications"].setdefault(cls_key, (flow, category))
                    affected_records[code] += 1
                    if bucket["first_source"] is None:
                        bucket["first_source"] = {
                            "__source_file__": row.get("__source_file__"),
                            "__source_path__": row.get("__source_path__"),
                            "__source_sheet__": row.get("__source_sheet__"),
                            "__source_row__": row.get("__source_row__"),
                        }

        new_rows: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for code in sorted(candidates, key=lambda item: (len(item), item)):
            bucket = candidates[code]
            classifications = list(bucket["classifications"].values())
            if len(classifications) != 1:
                conflicts.append({
                    "supplier_code": code,
                    "supplier": bucket["names"].most_common(1)[0][0] if bucket["names"] else "",
                    "classifications": [
                        {"flow": flow, "category": category}
                        for flow, category in classifications[:8]
                    ],
                    "records": int(affected_records[code]),
                })
                continue

            flow, category = classifications[0]
            # Preferência determinística: maior frequência; empate -> nome mais
            # completo; novo empate -> ordem alfabética normalizada.
            names = list(bucket["names"].items())
            names.sort(key=lambda item: (-item[1], -len(item[0]), normalize_text(item[0])))
            name = names[0][0]

            source = dict(bucket["first_source"] or {})
            new_rows.append({
                b_code: code,
                b_name: name,
                b_flow: flow,
                b_cat: category,
                **source,
            })

        if not new_rows:
            return base, {
                "added_suppliers": 0,
                "affected_records": 0,
                "conflicting_suppliers": len(conflicts),
                "conflicts": conflicts,
                "conflicting_codes": [item["supplier_code"] for item in conflicts],
            }

        augmented = TableData(
            sheet_name=f"{base.sheet_name} + complemento automático da planilha",
            headers=list(base.headers),
            rows=[*base.rows, *new_rows],
            source_path=base.source_path,
            header_row=base.header_row,
        )
        # Garante que a base produzida continua obedecendo ao mesmo contrato
        # determinístico do reconciliador antes de qualquer cálculo.
        validate_base(augmented)

        added_codes = {cls._code_key(row.get(b_code)) for row in new_rows}
        return augmented, {
            "added_suppliers": len(new_rows),
            "affected_records": sum(int(affected_records[c]) for c in added_codes),
            "conflicting_suppliers": len(conflicts),
            "conflicts": conflicts,
            "conflicting_codes": [item["supplier_code"] for item in conflicts],
        }

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

        # A base cadastrada continua sendo a referência principal. Para a
        # validação corrente, fornecedores realmente ausentes podem ser
        # complementados automaticamente com os quatro campos de classificação
        # existentes na própria planilha importada. Esse complemento é efêmero:
        # não altera o XLSX padrão, não persiste entre novas validações e não
        # contamina sessões de outros usuários.
        base = self.active_base(sid).table
        base_for_run, enrichment = self._supplement_base_from_imported_workbooks(base, workbooks)
        result: ReconcileResult = reconcile(
            detection.previsto,
            detection.realizado,
            base_for_run,
            blocked_import_classification_codes=set(enrichment["conflicting_codes"]),
        )

        # O detector legado tinha uma observação de que Fluxo JMM/Categoria do
        # consolidado eram ignorados. No Web atual, esses campos continuam sem
        # alterar registros já existentes da base, mas podem complementar apenas
        # códigos ausentes. Remove a mensagem antiga para não orientar o usuário
        # de forma incorreta.
        detection.notes = [
            note for note in detection.notes
            if "FLUXO JMM E CATEGORIA EVENTUALMENTE PRESENTES" not in str(note).upper()
        ]
        if enrichment["added_suppliers"]:
            detection.notes.append(
                "BASE DADOS complementada automaticamente nesta validação com "
                f"{enrichment['added_suppliers']} fornecedor(es) ausente(s) na base ativa, "
                f"usando {enrichment['affected_records']} registro(s) da própria planilha. "
                "Foram aceitos somente Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria completos e sem conflito."
            )

        if enrichment["conflicting_suppliers"]:
            result.warnings.insert(0, {
                "level": "warning",
                "title": "Classificação conflitante na planilha importada",
                "summary": (
                    f"{enrichment['conflicting_suppliers']} fornecedor(es) ausente(s) na BASE DADOS "
                    "apresentaram mais de uma combinação de Fluxo JMM/Categoria na própria planilha e, "
                    "por segurança, não foram complementados automaticamente."
                ),
                "details": enrichment["conflicts"],
            })

        if detection.notes:
            result.warnings.insert(0, {
                "level": "info",
                "title": "Formato de entrada reconhecido",
                "summary": "A automação adaptou o layout importado sem usar aproximações para classificar PREVISTO/REALIZADO.",
                "details": [{"mensagem": note} for note in detection.notes],
            })
        validated = ValidatedInput(unique, workbooks, detection, result)
        # Metadado somente da camada Web; não altera o contrato do motor legado.
        validated.base_enrichment = enrichment
        state = self.store.state(sid)
        state.validated = validated
        state.last_source_names = [p.name for p in unique]
        return validated

    @staticmethod
    def _base_health(result: ReconcileResult, enrichment: dict[str, Any] | None = None) -> dict[str, Any]:
        enrichment = enrichment or {}
        missing_details: list[dict[str, Any]] = []
        for warning in result.warnings:
            title = str(warning.get("title") or "")
            if title.startswith("Classificação ausente no "):
                missing_details.extend(list(warning.get("details") or []))
        unique: dict[str, str] = {}
        for item in missing_details:
            code = str(item.get("supplier_code") or "").strip()
            name = str(item.get("supplier") or "").strip() or "Fornecedor não identificado"
            key = f"code:{code}" if code else f"name:{name.casefold()}"
            unique.setdefault(key, name)
        suppliers = list(unique.values())
        added = int(enrichment.get("added_suppliers") or 0)
        affected = int(enrichment.get("affected_records") or 0)
        conflicts = int(enrichment.get("conflicting_suppliers") or 0)

        if missing_details:
            message = (
                f"Após complementar automaticamente a BASE DADOS com as classificações seguras encontradas "
                f"na própria planilha, ainda restaram {len(suppliers)} fornecedor(es) sem classificação "
                f"segura, envolvendo {len(missing_details)} registro(s). Confira se Cód Fornecedor, "
                "Fornecedor, Fluxo JMM e Categoria estão preenchidos de forma consistente no arquivo."
            )
        elif added:
            message = (
                f"A BASE DADOS foi complementada automaticamente nesta validação com {added} fornecedor(es) "
                f"que ainda não existiam na base ativa, aproveitando {affected} registro(s) com Cód Fornecedor, "
                "Fornecedor, Fluxo JMM e Categoria completos e consistentes."
            )
        else:
            message = "A BASE DADOS possui classificação segura para os fornecedores reconhecidos nesta validação."

        return {
            "status": "attention" if missing_details else "ok",
            "missing_records": len(missing_details),
            "missing_suppliers": len(suppliers),
            "suppliers": suppliers[:12],
            "auto_added_suppliers": added,
            "auto_added_records": affected,
            "conflicting_suppliers": conflicts,
            "message": message,
        }

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
            "base_health": self._base_health(r, getattr(validated, "base_enrichment", None)),
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
