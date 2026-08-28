from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = (ROOT / "webapp" / "static" / "action_feedback.js").read_text(encoding="utf-8")
STYLES = (ROOT / "webapp" / "static" / "action_feedback.css").read_text(encoding="utf-8")
INDEX = (ROOT / "webapp" / "templates" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
REPORT = (ROOT / "app" / "report" / "report_template.html").read_text(encoding="utf-8")
GENERATOR = (ROOT / "app" / "services" / "report_generator.py").read_text(encoding="utf-8")


def test_same_feedback_component_is_used_on_home_and_embedded_report():
    assert '<script src="/static/action_feedback.js" defer></script>' in INDEX
    assert '<link rel="stylesheet" href="/static/action_feedback.css" />' in INDEX
    assert INDEX.index("action_feedback.js") < INDEX.index("app.js")
    assert "__ACTION_FEEDBACK_STYLES__" in REPORT
    assert "__ACTION_FEEDBACK_COMPONENT__" in REPORT
    assert 'html.replace("__ACTION_FEEDBACK_STYLES__"' in GENERATOR
    assert 'html.replace("__ACTION_FEEDBACK_COMPONENT__"' in GENERATOR
    assert "window.ActionFeedback.create()" in APP_JS
    assert "window.ActionFeedback.create()" in REPORT


def test_feedback_is_nonblocking_accessible_and_safe_for_print():
    assert "aria-live', 'polite'" in COMPONENT
    assert "safeType === 'error' ? 'alert' : 'status'" in COMPONENT
    assert "pointer-events:none" in STYLES
    assert "@media print{.actionFeedbackRegion{display:none!important}}" in STYLES
    assert "prefers-reduced-motion:reduce" in STYLES
    assert "textContent = text" in COMPONENT
    assert "innerHTML" not in COMPONENT
    assert "createElement('style')" not in COMPONENT


def test_one_action_key_moves_from_started_to_final_state_without_stacking():
    assert "const active = new Map()" in COMPONENT
    assert "let item = active.get(safeKey)" in COMPONENT
    assert "started: (message, key = '') => notify(message, 'progress', key, 0)" in COMPONENT
    assert "success: (message, key = '') => notify(message, 'success', key)" in COMPONENT
    assert "error: (message, key = '') => notify(message, 'error', key)" in COMPONENT
    assert "noChange: (message, key = '') => notify(message, 'neutral', key)" in COMPONENT


def test_main_base_flows_report_started_success_error_and_no_change():
    assert "actionFeedback.started('Salvando as alterações da Base de Dados...', 'base-save')" in APP_JS
    assert "actionFeedback.success(`Alterações salvas." in APP_JS
    assert "actionFeedback.error('Não foi possível salvar as alterações" in APP_JS
    assert "actionFeedback.started('Protegendo e importando a nova Base de Dados...', 'base-import')" in APP_JS
    assert "Arquivo importado com sucesso." in APP_JS
    assert "Nenhum novo registro precisava ser adicionado." in APP_JS
    assert "Download da Base de Dados solicitado ao navegador." in APP_JS


def test_report_reuses_loading_and_carries_completion_across_refresh():
    assert "function beginReportUpdate(" in REPORT
    assert "actionFeedback.next(message,'success');location.replace(url)" in REPORT
    assert "Classificações atualizadas com sucesso." in REPORT
    assert "Alterações salvas. O relatório foi atualizado." in REPORT
    assert "Arquivo complementar importado com sucesso." in REPORT
    assert "Base de Dados importada com sucesso." in REPORT
    assert "sessionStorage.setItem(NEXT_MESSAGE_KEY" in COMPONENT
    assert "sessionStorage.removeItem(NEXT_MESSAGE_KEY)" in COMPONENT


def test_report_errors_and_exports_use_nonblocking_feedback():
    assert "function reportError(error){actionFeedback.error(" in REPORT
    assert "alert(" not in REPORT
    assert "data-filtered-export" in REPORT
    assert "actionFeedback.started('Preparando a planilha com os filtros atuais...'" in REPORT
    assert "Planilha filtrada preparada com ${rows} registro(s)." in REPORT
    assert "Os filtros atuais não retornaram registros." in REPORT
    assert "Download solicitado ao navegador." in REPORT
    assert "Preparando o PDF com os filtros atuais..." in REPORT
