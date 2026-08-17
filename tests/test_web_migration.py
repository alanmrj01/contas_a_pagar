from __future__ import annotations

import hashlib
import json
from pathlib import Path

from webapp.report_optimizer import MARKER
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


def test_generate_navigates_same_browser_tab_and_visual_assets_are_unchanged():
    assert "window.location.assign(state.reportUrl)" in JS
    assert "stageEncryptedFile" in JS
    assert "AES-GCM" in JS
    assert "RSA-OAEP" in JS
    # A otimização do relatório é aplicada somente após o motor desktop gerar o HTML.
    engine = (ROOT / "webapp" / "engine.py").read_text(encoding="utf-8")
    assert "generate_report(validated.result" in engine
    assert "optimize_report_file(report)" in engine


def test_upload_extensions_and_200mb_security_limit_are_kept():
    assert ".xlsx,.xls,.xlsm,.xlsb" in HTML
    assert "SUPPORTED_EXTENSIONS" in (ROOT / "main.py").read_text(encoding="utf-8")
    store = SessionStore(ROOT)
    assert store.max_upload_bytes == 200 * 1024 * 1024
    assert store.session_ttl_seconds == 2 * 60 * 60


def test_session_id_is_not_exposed_in_report_urls_and_generated_mount_is_gone():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    engine = (ROOT / "webapp" / "engine.py").read_text(encoding="utf-8")
    assert '"/report/current"' in engine
    assert '"/report/Relatorio_Contas_a_Pagar.pdf"' in engine
    assert 'app.mount("/generated"' not in main
    assert "samesite=\"strict\"" in main
    assert "httponly=True" in main


def test_report_template_itself_remains_desktop_baseline():
    manifest = json.loads((ROOT / "docs" / "CORE_PARITY_SHA256.json").read_text(encoding="utf-8"))
    rel = "app/report/report_template.html"
    assert sha(ROOT / rel) == manifest["files"][rel]
    assert MARKER not in (ROOT / rel).read_text(encoding="utf-8")
