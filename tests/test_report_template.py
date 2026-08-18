from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / 'app' / 'report' / 'report_template.html').read_text(encoding='utf-8')
PDF_SOURCE = (ROOT / 'app' / 'services' / 'pdf_report.py').read_text(encoding='utf-8')


def test_multiselect_filters_and_clear_button_exist():
    for token in ('mfCategory', 'mfFlow', 'mfSupplier', 'clearFilters'):
        assert token in TEMPLATE
    assert 'type="checkbox"' in TEMPLATE


def test_comma_separated_search_is_supported():
    assert "state.search.split(',')" in TEMPLATE
    assert 'fornecedor A, fornecedor B' in TEMPLATE


def test_month_filter_is_local_to_monthly_component():
    assert 'monthFilterOptions' in TEMPLATE
    assert 'state.months' in TEMPLATE
    pass_fn = TEMPLATE.split('function pass(x)', 1)[1].split('function group', 1)[0]
    assert 'state.months' not in pass_fn


def test_kpi_values_have_dynamic_fit_and_global_tooltip():
    assert 'fitReportValues' in TEMPLATE
    assert 'globalInfoTip' in TEMPLATE
    assert 'z-index:100000' in TEMPLATE


def test_monthly_area_fits_up_to_three_blocks_and_has_stronger_hover():
    assert ".slice(0,3)" in TEMPLATE
    assert 'fitMonthlyViewport' in TEMPLATE
    assert 'box-shadow:0 25px 50px' in TEMPLATE


def test_warnings_are_named_avisos_and_identify_columns():
    assert '<h2>Avisos</h2>' in TEMPLATE
    assert 'Coluna(s) com informação ausente, inválida ou não classificada' in TEMPLATE
    assert "fields=['Fluxo JMM','Categoria']" in TEMPLATE


def test_filtered_pdf_uses_current_dom_and_print_has_no_scroll_areas():
    assert 'Salvar PDF com filtros atuais' in TEMPLATE
    assert "window.print()" in TEMPLATE
    assert 'Filtros aplicados neste PDF' in TEMPLATE
    assert '.monthlyChart,.tableWrap,.warningDetails{max-height:none!important;height:auto!important;overflow:visible!important' in TEMPLATE
    assert '@page{size:A4 portrait' in TEMPLATE


def test_lists_are_complete_in_html_and_static_pdf_is_paginated():
    assert "el('titleRows').innerHTML=r.map" in TEMPLATE
    assert 'r.slice(0,700)' not in TEMPLATE
    assert 'def _paginated_table(' in PDF_SOURCE
    assert 'Títulos realizados - lista completa' in PDF_SOURCE
    assert 'Comparativo mensal completo' in PDF_SOURCE


def test_avisos_are_excluded_from_both_pdf_paths():
    assert '.warningsSection,.warnings{display:none!important}' in TEMPLATE
    assert '_text(c, 36, y, "Avisos"' not in PDF_SOURCE


def test_search_has_context_help_with_exact_searchable_fields():
    assert 'Como usar a pesquisa' in TEMPLATE
    assert 'Pesquisa nos campos Fornecedor, nome do fornecedor como veio no arquivo de origem e Título' in TEMPLATE
    assert 'separe os termos por vírgula' in TEMPLATE


def test_monthly_viewport_is_bounded_when_unfiltered():
    assert 'const maxViewport=1040' in TEMPLATE
    assert 'Math.min(total,maxViewport)' in TEMPLATE


def test_print_contrast_and_overflow_guards_exist():
    assert '.axisLab,.xLab,.smallLab,.valueLab,.timelineValueP,.timelineValueR,.pairMark{fill:#173047!important}' in TEMPLATE
    assert '.monthOverview>span{grid-template-columns:minmax(0,1fr)!important' in TEMPLATE
    assert 'node.style.transform=`scaleX(${ratio})`' in TEMPLATE
    assert '_fit_text_size' in PDF_SOURCE
    assert '_text_fit(c, x + 10, y + h - 39, value' in PDF_SOURCE


def test_empresa_filter_was_removed_without_affecting_other_filters():
    assert 'id="mfCompany"' not in TEMPLATE
    assert "state.company" not in TEMPLATE
    assert 'Empresa: ${state.company' not in TEMPLATE
    for token in ('mfCategory', 'mfFlow', 'mfSupplier', 'fSearch', 'clearFilters'):
        assert token in TEMPLATE


def test_payment_month_filter_supports_month_and_exact_date():
    assert 'id="mfEmission"' in TEMPLATE
    assert 'Pagamento/Mês' in TEMPLATE
    assert 'Emissão/Competência' not in TEMPLATE
    assert 'name="emissionMode" value="month"' in TEMPLATE
    assert 'name="emissionMode" value="date"' in TEMPLATE
    assert "function competenceDateForItem(x){return x.date||''}" in TEMPLATE
    assert "state.emissionMode==='date'" in TEMPLATE
    assert 'REALIZADO: Pagamento • PREVISTO: Data prevista' in TEMPLATE
    assert 'buildEmissionFilter()' in TEMPLATE


def test_light_and_dark_screen_themes_and_toggle_are_present_without_changing_print_theme():
    assert 'id="tema-aprovado-emissao-1-1-9"' in TEMPLATE
    assert 'id="theme-toggle-1-2-0"' in TEMPLATE
    assert 'linear-gradient(135deg,#08769f 0%,#168eb8 35%,#6794a0 68%,#9ba8aa 100%)' in TEMPLATE
    assert 'linear-gradient(135deg,#042f5d 0%,#08518c 48%,#0b5b94 78%,#0a477f 100%)' in TEMPLATE
    assert 'id="themeLightBtn"' in TEMPLATE
    assert 'id="themeDarkBtn"' in TEMPLATE
    assert "const THEME_KEY='contasapagar-report-theme'" in TEMPLATE
    assert '@page{size:A4 portrait' in TEMPLATE


def test_only_requested_excel_buttons_remain_in_report_toolbar():
    assert "['previsto','Excel • Previsto']" in TEMPLATE
    assert "['realizado','Excel • Realizado']" in TEMPLATE
    assert "['fornecedores','Excel • Fornecedores']" not in TEMPLATE
    assert "['alertas','Excel • Alertas']" not in TEMPLATE


def test_filter_options_are_faceted_by_other_active_filters():
    assert 'function passExcept(x,excludedFacet=' in TEMPLATE
    assert "function possibleFacetValues(facet)" in TEMPLATE
    assert "ALL_ITEMS.filter(x=>passExcept(x,facet))" in TEMPLATE
    assert 'function pruneUnavailableSelections()' in TEMPLATE
    assert 'function refreshFilterOptions()' in TEMPLATE
    assert "paintStandardFilter('category')" in TEMPLATE
    assert "paintStandardFilter('flow')" in TEMPLATE
    assert "paintStandardFilter('supplier')" in TEMPLATE
    assert 'paintEmissionFilter()' in TEMPLATE


def test_filters_still_apply_automatically_and_have_force_apply_button():
    assert 'id="applyFilters"' in TEMPLATE
    assert '>Aplicar Filtros</button>' in TEMPLATE
    assert 'function applyFiltersNow(){refreshFilterOptions();render()}' in TEMPLATE
    assert "state[key]=[...box.querySelectorAll('input:checked')].map(x=>x.value);applyFiltersNow()" in TEMPLATE
    assert "el('fSearch').addEventListener('input',e=>{state.search=e.target.value.trim();applyFiltersNow()})" in TEMPLATE
    assert "el('applyFilters').addEventListener('click'" in TEMPLATE
    assert 'syncStateFromFilterControls()' in TEMPLATE


def test_month_filter_options_follow_current_global_filters():
    assert 'function refreshMonthFilterOptions()' in TEMPLATE
    assert 'const eligible=ALL_ITEMS.filter(pass)' in TEMPLATE
    assert 'state.months=state.months.filter(m=>allowed.has(m))' in TEMPLATE


def test_theme_switch_uses_sun_and_moon_icons_instead_of_text_labels():
    assert 'id="themeLightBtn"' in TEMPLATE and '>☀</button>' in TEMPLATE
    assert 'id="themeDarkBtn"' in TEMPLATE and '>☾</button>' in TEMPLATE
    assert '>White</button>' not in TEMPLATE
    assert '>Dark</button>' not in TEMPLATE
    assert 'aria-label="Usar tema claro"' in TEMPLATE
    assert 'aria-label="Usar tema escuro"' in TEMPLATE


def test_light_warning_subtitle_has_dedicated_contrast_and_larger_font():
    assert 'body[data-theme="light"] .warningsHeader span,body:not([data-theme]) .warningsHeader span{color:#102536!important;font-size:13px!important;font-weight:700!important}' in TEMPLATE


def test_supplier_lollipop_values_are_slightly_larger_only_on_value_labels():
    assert '.supplierValueLab{font-size:11.8px!important;font-weight:850!important}' in TEMPLATE
    assert 'class="valueLab supplierValueLab"' in TEMPLATE


def test_top_punctuality_kpi_is_removed_but_audit_data_can_remain_elsewhere():
    render = TEMPLATE.split('function render()', 1)[1].split("el('chartCategory')", 1)[0]
    kpi_line = render.split("el('kpis').innerHTML=", 1)[1].split(".map(x=>", 1)[0]
    assert "['Pontualidade'" not in kpi_line
    assert "['Fornecedores'" in kpi_line
    assert '@media screen and (min-width:1051px){.kpis{grid-template-columns:repeat(5,1fr)!important}}' in TEMPLATE


def test_report_content_starts_at_explicit_100_percent_zoom():
    assert 'content="width=device-width,initial-scale=1.0"' in TEMPLATE
    assert "document.documentElement.style.zoom='1';document.body.style.zoom='1';" in TEMPLATE
    assert 'html{zoom:1!important}' in TEMPLATE


def test_category_chart_compares_named_current_and_previous_months():
    assert 'function categoryComparisonMonth(items)' in TEMPLATE
    assert 'previousMonth=previousMonthKey(currentMonth)' in TEMPLATE
    assert "categoryMonthHint" in TEMPLATE
    assert "categoryMonthLegend" in TEMPLATE
    assert "previousLabel=monthLabel(previousMonth+'-01',true)" in TEMPLATE
    assert "currentLabel=monthLabel(currentMonth+'-01',true)" in TEMPLATE
    assert "currentP={},currentR={},previousP={},previousR={}" in TEMPLATE


def test_monthly_cards_require_a_filter_and_never_use_generic_latest_month_tag():
    assert 'Aplique pelo menos um filtro para visualizar os cards mensais.' in TEMPLATE
    assert "periodLabel:monthLabel(latest+'-01',multiYear)" in TEMPLATE
    assert "periodLabel:'MÊS MAIS RECENTE'" not in TEMPLATE
