from __future__ import annotations

import hashlib
import json
from pathlib import Path

from webapp.engine import WebEngine
from webapp.session_store import SessionStore

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "webapp" / "templates" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "webapp" / "static" / "styles.css").read_text(encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_core_financial_files_match_desktop_2_0_2_manifest():
    manifest = json.loads((ROOT / "docs" / "CORE_PARITY_SHA256.json").read_text(encoding="utf-8"))
    for rel, expected in manifest["files"].items():
        assert sha(ROOT / rel) == expected, rel


def test_web_home_preserves_three_step_story_and_base_access():
    assert "CONTAS A PAGAR" in HTML
    assert "Previsto x Realizado" in HTML
    assert "Arraste seu arquivo financeiro aqui" in HTML
    assert "Validar arquivo" in HTML
    assert "Gerar relatório" in HTML
    assert "Base de Dados" in HTML
    assert "Abrir último relatório" in HTML
    assert "Abrir PDF" in HTML


def test_web_steps_remain_sequential_and_actions_turn_green_only_when_ready():
    assert "const validateReady = hasFiles && !state.busy" in JS
    assert "const generateReady = state.validated && !state.busy" in JS
    assert "classList.toggle('ready', validateReady)" in JS
    assert "classList.toggle('ready', generateReady)" in JS
    assert ".btn.ready,.action-btn.ready" in CSS


def test_generate_navigates_same_browser_tab_to_original_report():
    assert "window.location.assign(state.reportUrl)" in JS
    assert "generate_report(validated.result" in (ROOT / "webapp" / "engine.py").read_text(encoding="utf-8")


def test_upload_extensions_match_desktop():
    assert ".xlsx,.xls,.xlsm,.xlsb" in HTML
    assert "SUPPORTED_EXTENSIONS" in (ROOT / "main.py").read_text(encoding="utf-8")


def test_end_to_end_sample_uses_same_engine_and_generates_exact_report_template(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_DATA_DIR", str(tmp_path / "data"))
    store = SessionStore(ROOT)
    engine = WebEngine(ROOT, store)
    sid = "a" * 32
    sample = ROOT / "samples" / "PLANILHAS PAGAR E PREVISTO.xlsx"
    validated = engine.validate(sid, [sample])
    assert validated.result.previsto
    assert validated.result.realizado
    assert validated.result.base_rows > 0
    outputs = engine.generate(sid)
    report = store.report_dir(sid) / "index.html"
    pdf = store.report_dir(sid) / "Relatorio_Contas_a_Pagar.pdf"
    assert report.is_file() and report.stat().st_size > 20_000
    assert pdf.is_file() and pdf.stat().st_size > 1_000
    assert outputs["report_url"].endswith("/index.html")
    generated = report.read_text(encoding="utf-8")
    template = (ROOT / "app" / "report" / "report_template.html").read_text(encoding="utf-8")
    assert "__REPORT_DATA__" not in generated
    # Estrutura/CSS/JS do relatório é o mesmo template desktop, somente com payload injetado.
    before, after = template.split("__REPORT_DATA__", 1)
    assert generated.startswith(before)
    assert generated.endswith(after)
