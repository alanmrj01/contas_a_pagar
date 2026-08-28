from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = (ROOT / "webapp" / "static" / "base_table_component.js").read_text(encoding="utf-8")
INDEX = (ROOT / "webapp" / "templates" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
REPORT = (ROOT / "app" / "report" / "report_template.html").read_text(encoding="utf-8")
GENERATOR = (ROOT / "app" / "services" / "report_generator.py").read_text(encoding="utf-8")


def test_both_base_interfaces_use_the_same_table_component():
    assert '<script src="/static/base_table_component.js" defer></script>' in INDEX
    assert "__BASE_TABLE_COMPONENT__" in REPORT
    assert 'html.replace("__BASE_TABLE_COMPONENT__"' in GENERATOR
    assert "window.BaseTableComponent.create" in APP_JS
    assert "window.BaseTableComponent.create" in REPORT


def test_both_base_interfaces_expose_add_remove_filters_and_paging():
    for source, prefix in ((INDEX, "base"), (REPORT, "reportBase")):
        assert "Adicionar linha" in source
        assert "Remover selecionadas" in source
        assert 'data-base-column-filter="supplier_code"' in source
        assert 'data-base-column-filter="supplier"' in source
        assert 'data-base-column-filter="flow"' in source
        assert 'data-base-column-filter="category"' in source
        assert f'id="{prefix}SelectPage"' in source


def test_shared_component_filters_without_mutation_and_limits_dom_rows():
    assert "function matchesFilters(item, filters)" in COMPONENT
    assert "items.filter(item => matchesNormalizedFilters(item, current))" in COMPONENT
    assert "pageSize: 200" in APP_JS
    assert "pageSize:200" in REPORT
    assert "index + 4000" in COMPONENT
    assert "setTimeout(step, 0)" in COMPONENT


def test_shared_component_requires_confirmation_and_keeps_save_validation():
    assert "window.confirm" in COMPONENT
    assert "A remoção será efetivada somente ao salvar" in COMPONENT
    assert "getItems" in COMPONENT
    assert "Preencha Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria" in COMPONENT
    assert "method:'PUT'" in APP_JS
    assert "method:'PUT'" in REPORT


def test_shared_component_selects_the_whole_row_without_interfering_with_edit_fields():
    assert 'class="base-selectable-row${selectedClass}"' in COMPONENT
    assert 'tabindex="0" aria-selected=' in COMPONENT
    assert "body.addEventListener('click'" in COMPONENT
    assert "!isInteractiveTarget(event.target)" in COMPONENT
    assert "event.key === 'Enter' || event.key === ' '" in COMPONENT
    assert "input,select,textarea,button,a,label" in COMPONENT
    assert '.base-selectable-row.is-selected td' in (ROOT / 'webapp' / 'static' / 'styles.css').read_text(encoding='utf-8')
    assert '.reportModal .base-selectable-row.is-selected td' in REPORT
