from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base_manager import load_active_base
from .excel_reader import WorkbookData, read_excel
from .reconciler import ReconcileResult, reconcile
from .sheet_detector import InputDetection, detect_input_tables


@dataclass
class ValidatedInput:
    paths: list[Path]
    workbooks: list[WorkbookData]
    detection: InputDetection
    result: ReconcileResult


def validate_inputs(paths: list[str | Path]) -> ValidatedInput:
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

    workbooks = [read_excel(path) for path in unique]
    detection = detect_input_tables(workbooks)
    base = load_active_base()
    result = reconcile(detection.previsto, detection.realizado, base)
    if detection.notes:
        result.warnings.insert(0, {
            "level": "info",
            "title": "Formato de entrada reconhecido",
            "summary": "A automação adaptou o layout importado sem usar aproximações para classificar PREVISTO/REALIZADO.",
            "details": [{"mensagem": note} for note in detection.notes],
        })
    return ValidatedInput(unique, workbooks, detection, result)
