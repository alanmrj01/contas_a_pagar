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
LOGIN_HTML = (ROOT / "webapp" / "templates" / "login.html").read_text(encoding="utf-8")
LOGIN_JS = (ROOT / "webapp" / "static" / "login.js").read_text(encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_core_financial_files_match_desktop_2_0_2_manifest():
    manifest = json.loads((ROOT / "docs" / "CORE_PARITY_SHA256.json").read_text(encoding="utf-8"))
    approved = manifest.get("approved_web_overrides", {})
    for rel, expected in manifest["files"].items():
        if rel in approved:
            assert approved[rel]["desktop_2_0_2_sha256"] == expected, rel
            assert sha(ROOT / rel) == approved[rel]["current_sha256"], rel
        else:
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


def test_validation_result_is_organized_for_non_technical_users_without_changing_its_data():
    render_validation = JS.split("function renderValidation(summary)", 1)[1].split("async function validateFiles", 1)[0]

    for heading in (
        "O que foi encontrado",
        "O que está correto",
        "O que precisa de atenção",
        "O que isso significa",
        "O que o usuário deve fazer",
    ):
        assert heading in render_validation

    for source_field in (
        "summary.previsto",
        "summary.previsto_tables",
        "summary.realizado",
        "summary.realizado_tables",
        "summary.base",
        "summary.period",
        "summary.notes",
        "summary.warnings",
        "summary.base_health",
    ):
        assert source_field in render_validation

    assert "baseHealth?.status === 'attention'" in render_validation
    assert "baseHealth?.status === 'ok'" in render_validation
    assert "map(esc)" in render_validation
    assert "esc(warning.title)" in render_validation
    assert "esc(warning.summary)" in render_validation
    assert ".analysis-summary" in CSS
    assert ".analysis-facts" in CSS
    assert ".analysis-attention-list" in CSS
    assert ".analysis-action-list" in CSS


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


def test_report_template_changes_are_explicitly_registered_as_approved_override():
    manifest = json.loads((ROOT / "docs" / "CORE_PARITY_SHA256.json").read_text(encoding="utf-8"))
    rel = "app/report/report_template.html"
    override = manifest["approved_web_overrides"][rel]
    assert override["desktop_2_0_2_sha256"] == manifest["files"][rel]
    assert sha(ROOT / rel) == override["current_sha256"]
    assert MARKER not in (ROOT / rel).read_text(encoding="utf-8")


def test_unreadable_file_fallback_clears_browser_selection_without_reload():
    assert "function isFileReadAccessError" in JS
    assert "function clearFilesAfterReadFailure" in JS
    assert "state.files = []" in JS
    assert "input.value = ''" in JS
    assert "Faça uma cópia do arquivo" in JS
    fallback = JS.split("function clearFilesAfterReadFailure", 1)[1].split("function ", 1)[0]
    assert "window.location.reload" not in fallback


def test_error_dialog_is_guided_in_three_steps_and_keeps_technical_details_collapsed():
    assert "error-steps" in JS
    assert "guide.steps.map" in JS
    assert "Detalhes técnicos" in JS
    assert "clearFilesAfterReadFailure" in JS


def test_login_precedes_the_application_and_credentials_are_not_hardcoded():
    assert "Acesso seguro" in LOGIN_HTML
    assert '<label for="email">E-mail</label>' in LOGIN_HTML
    assert 'id="email" name="email" type="email"' in LOGIN_HTML
    assert 'autocomplete="email"' in LOGIN_HTML
    assert 'autocomplete="current-password"' in LOGIN_HTML
    assert 'id="togglePassword"' in LOGIN_HTML
    assert 'type="button" aria-label="Mostrar senha"' in LOGIN_HTML
    assert "passwordInput.type = visible ? 'password' : 'text'" in LOGIN_JS
    assert "'Ocultar senha'" in LOGIN_JS
    assert "/api/auth/login" in LOGIN_JS
    project_text = "\n".join([
        (ROOT / "main.py").read_text(encoding="utf-8"),
        LOGIN_HTML,
        LOGIN_JS,
    ])
    assert "positivo123" not in project_text


def test_fixed_username_domain_is_absent_and_secret_key_stays_server_side():
    runtime_files = [
        ROOT / "main.py",
        ROOT / "webapp" / "supabase_gateway.py",
        ROOT / "webapp" / "static" / "login.js",
        ROOT / "webapp" / "templates" / "login.html",
        ROOT / ".env.example",
        ROOT / "render.yaml",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    removed_setting = "SUPABASE_USERNAME" + "_DOMAIN"
    assert removed_setting not in combined
    assert "@contasapagar.local" not in combined
    assert "body:JSON.stringify(body)" in LOGIN_JS
    assert "await authPost('/api/auth/login', {" in LOGIN_JS
    assert "email:emailInput.value.trim().toLowerCase()" in LOGIN_JS
    frontend = "\n".join([LOGIN_HTML, LOGIN_JS, JS])
    assert "SUPABASE_SECRET_KEY" not in frontend
    assert "secret_key" not in frontend


def test_logout_exists_on_application_and_report_and_rotates_server_session():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    report = (ROOT / "app" / "report" / "report_template.html").read_text(encoding="utf-8")
    assert 'id="logoutBtn"' in HTML
    assert "'/api/auth/logout'" in JS
    assert '@app.post("/api/auth/logout")' in main
    assert "store.destroy_session(sid)" in main
    assert "request.state.session_destroyed = True" in main
    assert 'id="reportLogoutBtn"' in report
    assert "'/api/auth/logout'" in report


def test_expired_csrf_is_renewed_once_without_mislabeling_it_as_file_origin_failure():
    assert "CSRF_REFRESH_REQUIRED" in JS
    assert "return api(url, options, true)" in JS
    assert "response.status === 401" in JS
