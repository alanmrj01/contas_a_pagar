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
    assert 'category_chunks = [category_rows[index:index + 8]' in PDF_SOURCE
    assert 'todos os valores exatos aparecem em rótulos de alto contraste' in PDF_SOURCE
    assert 'value_bubble' in PDF_SOURCE
    assert 'def _category_month_rows(' in PDF_SOURCE
    assert 'monthly_comparison[index:index + 6]' in PDF_SOURCE


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


def test_supplier_lollipop_names_and_values_are_larger_without_text_scaling():
    assert '.supplierNameLab{font-size:13px!important;font-weight:750!important;text-rendering:geometricPrecision}' in TEMPLATE
    assert '.supplierValueLab{font-size:15px!important;font-weight:900!important;text-rendering:geometricPrecision}' in TEMPLATE
    assert 'class="lab supplierNameLab"' in TEMPLATE
    assert 'class="valueLab supplierValueLab"' in TEMPLATE
    assert "nameLines=splitSvgLabel(x.supplier,34,3)" in TEMPLATE
    assert 'x.supplier.slice(0,29)' not in TEMPLATE
    assert 'label_w = 270' in PDF_SOURCE
    assert 'value_w = 96' in PDF_SOURCE
    assert 'start_size=7.8, min_size=6.8' in PDF_SOURCE
    assert 'c.setFont("Helvetica-Bold", 8.2)' in PDF_SOURCE


def test_top_punctuality_kpi_is_removed_but_audit_data_can_remain_elsewhere():
    render = TEMPLATE.split('function render()', 1)[1].split("el('chartCategory')", 1)[0]
    kpi_line = render.split("el('kpis').innerHTML=", 1)[1].split(".map(x=>", 1)[0]
    assert "['Pontualidade'" not in kpi_line
    assert "['Fornecedores'" in kpi_line
    assert '@media screen and (min-width:1051px){.kpis{grid-template-columns:repeat(5,1fr)!important}}' in TEMPLATE


def test_report_content_uses_layout_scale_instead_of_native_browser_zoom():
    assert 'content="width=device-width,initial-scale=1.0"' in TEMPLATE
    assert '.style.zoom' not in TEMPLATE
    assert 'html{zoom:' not in TEMPLATE
    assert ':root{--report-screen-scale:.9}' in TEMPLATE


def test_category_chart_month_selection_obeys_zero_one_two_and_more_than_two_rules():
    assert 'function categoryComparisonMonth(items)' in TEMPLATE
    month_selector = TEMPLATE.split('function selectCategoryMonths', 1)[1].split('function categoryComparisonMonth', 1)[0]
    assert 'if(chosen.length===1)return chosen' in month_selector
    assert 'if(chosen.length>=2)return chosen.slice(-2)' in month_selector
    assert 'return months.slice(-2)' in month_selector
    assert 'previousMonthKey' not in month_selector
    assert "categoryMonthHint" in TEMPLATE
    assert "categoryMonthLegend" in TEMPLATE
    assert "periodText=labels.join(' x ')" in TEMPLATE
    assert "comparisonMonths.forEach" in TEMPLATE


def test_category_chart_is_horizontal_keeps_every_value_label_and_has_own_series_filter():
    assert 'id="categorySeriesFilter"' in TEMPLATE
    assert '>Previsto e Realizado</option>' in TEMPLATE
    assert '>Previsto</option>' in TEMPLATE
    assert '>Realizado</option>' in TEMPLATE
    assert 'function categoryBarsHorizontal' in TEMPLATE
    assert 'categoryBarValueBg' in TEMPLATE
    assert 'categoryBarValue' in TEMPLATE
    assert 'el(\'chartCategory\').innerHTML=categoryBarsHorizontal' in TEMPLATE
    assert 'categoryScreenVisibleIndices(values,slot)' not in TEMPLATE.split('function categoryBarsHorizontal', 1)[1].split('const MONTHS_PT', 1)[0]


def test_category_chart_uses_exactly_four_fixed_solid_pastel_series_colors_and_print_space():
    assert '.categoryBar{fill:var(--category-fill);stroke:var(--category-stroke);fill-opacity:1' in TEMPLATE
    assert '.categoryBar--planned{stroke-width:3.2}' in TEMPLATE
    assert '.categoryBar--actual{stroke-width:1.4}' in TEMPLATE
    category_css = TEMPLATE.split('.categoryBar{', 1)[1].split('.categoryBar:hover', 1)[0]
    assert 'stroke-dasharray' not in category_css
    assert "planned:{fill:'#B9DCED',stroke:'#315F78'}" in TEMPLATE
    assert "actual:{fill:'#68AFC2',stroke:'#3E7088'}" in TEMPLATE
    assert "planned:{fill:'#F3CCBA',stroke:'#8D5B47'}" in TEMPLATE
    assert "actual:{fill:'#D98F73',stroke:'#8D4E3B'}" in TEMPLATE
    assert 'categorySeriesColors(color,info)' not in TEMPLATE
    assert "labels.flatMap(label=>legendMarks.map(mark=>`${label} ${mark}`))" in TEMPLATE
    assert 'monthIndex:index' in TEMPLATE
    assert 'categoryBar--${sideClass} categoryBar--${info.periodClass}' in TEMPLATE
    assert 'class="card cardWide categoryChartCard"' in TEMPLATE
    assert '.categoryChartCard #chartCategory svg{width:100%!important;height:auto!important;max-height:none!important' in TEMPLATE
    assert 'font_size = 7.6' in PDF_SOURCE
    assert '.categoryBarValue{font-size:11.5px!important}' in TEMPLATE
    assert 'def _category_series_colors(item: dict):' in PDF_SOURCE
    assert 'legend_items = rows[0]["series"]' in PDF_SOURCE


def test_monthly_comparison_numeric_labels_are_larger_and_not_scaled_horizontally():
    assert '.monthlyComparisonValue{fill:#102536;font-size:11.25px;font-weight:900;text-rendering:geometricPrecision}' in TEMPLATE
    monthly_fn = TEMPLATE.split('function monthlyComparisonChart(p,r)', 1)[1].split('function buildTimelineFilters', 1)[0]
    assert 'scaleX' not in monthly_fn
    assert 'text.length*6.8+18' in monthly_fn
    assert 'font_size = 7.2' in PDF_SOURCE
    assert 'label_w = min(82, max(54' in PDF_SOURCE


def test_supplier_period_context_and_waterfall_high_contrast_labels_are_present():
    assert 'id="supplierPeriodHint"' in TEMPLATE
    assert 'Acumulado de todos os meses do relatório' in TEMPLATE
    assert 'Conforme o(s) mês(es) filtrado(s)' in TEMPLATE
    assert 'function waterfallRefined' in TEMPLATE
    assert 'waterfallValueBg' in TEMPLATE
    assert 'waterfallValueText' in TEMPLATE


def test_monthly_comparison_replaces_waterfall_and_uses_filtered_rows_with_local_filters():
    render_fn = TEMPLATE.split('function render()', 1)[1].split('function reportMonths', 1)[0]
    assert "let p=D.previsto.filter(pass),r=D.realizado.filter(pass)" in render_fn
    assert "el('chartMonthlyComparison').innerHTML=monthlyComparisonChart(p,r)" in render_fn
    assert '<h2>Previsto x Realizado por mês</h2>' in TEMPLATE
    assert 'Contribuição para o desvio por Fluxo JMM' not in TEMPLATE
    assert 'id="timelineMonthFilter"' in TEMPLATE
    assert 'id="timelineSeriesFilter"' in TEMPLATE
    assert 'function monthlyComparisonChart(p,r)' in TEMPLATE
    assert "state.timelineMonths.length?available.filter" in TEMPLATE
    assert "if(state.timelineSeries!=='actual')" in TEMPLATE
    assert "if(state.timelineSeries!=='planned')" in TEMPLATE
    assert '<title>${esc(tooltip)}</title>' in TEMPLATE
    assert 'barMarkup+labelMarkup' in TEMPLATE


def test_report_allows_complementary_files_base_editing_and_inline_classification():
    assert 'id="reportBaseBtn"' in TEMPLATE
    assert 'Adicionar dados complementares' in TEMPLATE
    assert 'Editar a Base de Dados' in TEMPLATE
    assert "'/api/report/refresh'" in TEMPLATE
    assert "'/api/base/classifications'" in TEMPLATE
    assert 'data-bulk-flow' in TEMPLATE
    assert 'data-bulk-category' in TEMPLATE
    assert 'Atualizar relatório' in TEMPLATE


def test_warning_classification_rows_have_accessible_selection_and_manual_apply_feedback():
    assert 'class="classificationRow${usable?' in TEMPLATE
    assert 'data-class-row="${warningIndex}"' in TEMPLATE
    assert 'tabindex="0" role="checkbox" aria-checked="false"' in TEMPLATE
    assert 'aria-label="Selecionar linha de ${esc(supplierLabel)}"' in TEMPLATE
    assert "event.target.closest('input,select,button,a,label,textarea')" in TEMPLATE
    assert "event.key==='Enter'||event.key===' '" in TEMPLATE
    assert 'function syncClassificationRow' in TEMPLATE
    assert "row.classList.toggle('isSelected',check.checked)" in TEMPLATE
    assert 'data-class-status="${warningIndex}" role="status" aria-live="polite"' in TEMPLATE
    assert 'Valores aplicados à tabela. Atualize o relatório.' in TEMPLATE

    apply_values = TEMPLATE.split("else if(fill)", 1)[1].split("else if(submit)", 1)[0]
    assert 'location.replace' not in apply_values
    assert 'reportApi(' not in apply_values


def test_report_recalculation_has_nonblocking_loading_and_concurrency_guard():
    assert 'id="reportUpdateLoading"' in TEMPLATE
    assert 'role="status" aria-live="polite" aria-atomic="true"' in TEMPLATE
    assert '<strong>Atualizando relatório</strong>' in TEMPLATE
    assert 'Processando os dados e recalculando os resultados...' in TEMPLATE
    assert '.reportUpdateLoading{' in TEMPLATE
    assert 'pointer-events:none' in TEMPLATE.split('.reportUpdateLoading{', 1)[1].split('}', 1)[0]
    assert 'let REPORT_UPDATE_IN_PROGRESS=false' in TEMPLATE
    assert 'if(REPORT_UPDATE_IN_PROGRESS)return false' in TEMPLATE
    assert "document.querySelectorAll('[data-report-update-action]')" in TEMPLATE
    assert "content.setAttribute('aria-busy','true')" in TEMPLATE
    assert "content.removeAttribute('aria-busy')" in TEMPLATE
    assert 'function failReportUpdate(error)' in TEMPLATE
    assert 'Não foi possível atualizar o relatório.' in TEMPLATE
    assert 'setInterval(' not in TEMPLATE

    for function_name in (
        'submitClassificationUpdate',
        'saveReportBase',
        'addComplementaryFiles',
        'startReportBaseImport',
    ):
        function_body = TEMPLATE.split(f'async function {function_name}', 1)[1].split('\n', 1)[0]
        assert 'beginReportUpdate(' in function_body
        assert 'failReportUpdate(error)' in function_body

    assert 'data-submit-class="${warningIndex}" data-report-update-action' in TEMPLATE
    assert 'id="reportBaseSave" data-report-update-action' in TEMPLATE


def test_report_initial_screen_scale_is_layout_based_responsive_and_print_safe():
    assert 'id="reportViewport" class="reportViewport"' in TEMPLATE
    assert ':root{--report-screen-scale:.9}' in TEMPLATE
    assert '@media screen and (min-width:721px)' in TEMPLATE
    assert 'transform:scale(var(--report-screen-scale))' in TEMPLATE
    assert 'width:calc(100% / var(--report-screen-scale))' in TEMPLATE
    assert 'overflow-x:clip' in TEMPLATE
    assert '@media screen and (max-width:720px)' in TEMPLATE
    assert '.reportViewport>.wrap{width:auto;transform:none}' in TEMPLATE
    assert '.reportViewport{display:block!important;width:auto!important;height:auto!important;overflow:visible!important}' in TEMPLATE
    assert '.reportViewport>.wrap{width:auto!important;max-width:none!important;transform:none!important}' in TEMPLATE
    assert 'function scheduleReportScreenScale()' in TEMPLATE
    assert "new ResizeObserver(scheduleReportScreenScale)" in TEMPLATE
    assert "content.getBoundingClientRect().height" in TEMPLATE
    assert "matchMedia('print').matches" in TEMPLATE
    assert "blocks.reduce((sum,b)=>sum+b.offsetHeight,0)" in TEMPLATE
    assert ".style.zoom" not in TEMPLATE


def test_filter_bar_is_sticky_on_desktop_and_reduced_width_but_not_print():
    assert 'id="report-sticky-filters"' in TEMPLATE
    sticky_css = TEMPLATE.split('<style id="report-sticky-filters">', 1)[1].split('</style>', 1)[0]
    assert '@media screen{' in sticky_css
    assert '.reportFilterStickyHost{position:relative;z-index:6000}' in sticky_css
    assert '.filters.isViewportPinned{position:fixed;top:0' in sticky_css
    assert '@media screen and (max-width:720px)' in sticky_css
    assert '.reportFilterStickyHost{position:sticky;top:0}' in sticky_css
    assert '@media print{' in sticky_css
    assert '.reportFilterStickyHost,.reportFilterStickyHost>.filters{position:static!important}' in sticky_css
    assert 'id="reportFilterStickyHost" class="reportFilterStickyHost"' in TEMPLATE
    assert "let needsScaledFallback=matchMedia('(min-width:721px)').matches&&!matchMedia('print').matches" in TEMPLATE
    assert "window.addEventListener('scroll',scheduleReportFiltersPin,{passive:true})" in TEMPLATE
    assert 'requestAnimationFrame' in TEMPLATE.split('function scheduleReportFiltersPin()', 1)[1].split('\n', 1)[0]
    assert "window.addEventListener('beforeprint',releaseReportFiltersPin)" in TEMPLATE


def test_top_filters_support_hover_click_keyboard_escape_and_touch_fallback():
    assert "matchMedia('(hover: hover) and (pointer: fine)')" in TEMPLATE
    assert 'REPORT_FILTER_CLOSE_DELAY=200' in TEMPLATE
    interactions = TEMPLATE.split('function initReportFilterInteractions()', 1)[1].split("buildMultiFilter('mfCategory'", 1)[0]
    assert "document.querySelectorAll('.filters details.multiFilter')" in TEMPLATE
    assert "filter.addEventListener('pointerenter'" in interactions
    assert "filter.addEventListener('pointerleave'" in interactions
    assert "event.pointerType!=='mouse'" in interactions
    assert 'setTimeout(()=>{filter.open=false' in interactions
    assert 'closeOtherReportFilters(filter)' in interactions
    assert "filter.addEventListener('toggle'" in interactions
    assert "summary.addEventListener('click'" in interactions
    assert 'event.detail>0&&filter.open&&reportFiltersOpenedByHover.has(filter)' in interactions
    assert 'event.preventDefault();reportFiltersOpenedByHover.delete(filter)' in interactions
    assert "event.key!=='Escape'" in interactions
    assert "focused.querySelector('summary').focus()" in interactions
    assert 'event.preventDefault()' in interactions
    assert 'initReportFilterInteractions();' in TEMPLATE
    assert '.checked=' not in interactions
    assert 'applyFiltersNow' not in interactions


def test_excel_downloads_send_only_filter_state_to_authenticated_backend_export():
    assert "['atualizado','Planilha atualizada do relatório']" in TEMPLATE
    assert 'data-filtered-export="${kind}"' in TEMPLATE
    assert "reportApi('/api/report/export'" in TEMPLATE
    assert 'filters:currentGlobalFilterPayload()' in TEMPLATE
    assert "category:[...state.category]" in TEMPLATE
    assert "flow:[...state.flow]" in TEMPLATE
    assert "supplier:[...state.supplier]" in TEMPLATE
    assert "emission:[...state.emission]" in TEMPLATE
    assert 'previsto:D.previsto' not in TEMPLATE
    assert 'realizado:D.realizado' not in TEMPLATE
    excel_source = (ROOT / 'app' / 'services' / 'excel_export.py').read_text(encoding='utf-8')
    assert 'Relatorio_atualizado_filtrado.xlsx' in excel_source
    assert '_write_updated_report_workbook' in excel_source


def test_monthly_cards_require_a_filter_and_never_use_generic_latest_month_tag():
    assert 'Aplique pelo menos um filtro para visualizar os cards mensais.' in TEMPLATE
    assert "periodLabel:monthLabel(latest+'-01',multiYear)" in TEMPLATE
    assert "periodLabel:'MÊS MAIS RECENTE'" not in TEMPLATE


def test_every_graph_has_dynamic_global_and_local_filter_subtitle():
    for element_id in (
        'categoryFilterSummary',
        'monthlyCardsFilterSummary',
        'supplierFilterSummary',
        'timelineFilterSummary',
    ):
        assert f'id="{element_id}"' in TEMPLATE
    assert 'function globalFilterParts()' in TEMPLATE
    assert 'function updateChartFilterSummaries(p,r)' in TEMPLATE
    assert "el('categoryFilterSummary').textContent=filterSummaryWith" in TEMPLATE
    assert "el('monthlyCardsFilterSummary').textContent=filterSummaryWith" in TEMPLATE
    assert "el('supplierFilterSummary').textContent=filterSummaryWith()" in TEMPLATE
    assert "el('timelineFilterSummary').textContent=filterSummaryWith" in TEMPLATE
    assert 'updateChartFilterSummaries(p,r)' in TEMPLATE


def test_monthly_cards_have_isolated_series_filter():
    assert 'id="monthlyCardSeriesFilter"' in TEMPLATE
    assert "state.monthlyCardSeries!=='actual'" in TEMPLATE
    assert "state.monthlyCardSeries!=='planned'" in TEMPLATE
    assert "state.monthlyCardSeries==='planned'" in TEMPLATE
    assert "state.monthlyCardSeries==='actual'" in TEMPLATE
    pass_fn = TEMPLATE.split('function pass(x)', 1)[1].split('function group', 1)[0]
    assert 'monthlyCardSeries' not in pass_fn
    assert "renderMonthlyCardsLocal()" in TEMPLATE


def test_local_chart_filters_do_not_trigger_full_report_render():
    category_handler = TEMPLATE.split("el('categorySeriesFilter').addEventListener", 1)[1].split('\n', 1)[0]
    timeline_handlers = TEMPLATE.split('function buildTimelineFilters()', 1)[1].split('\n', 1)[0]
    monthly_handlers = TEMPLATE.split('function buildMonthFilter()', 1)[1].split('\n', 1)[0]
    assert 'renderCategoryLocal()' in category_handler and 'render()' not in category_handler
    assert 'renderTimelineLocal()' in timeline_handlers and 'render()' not in timeline_handlers
    assert 'renderMonthlyCardsLocal()' in monthly_handlers and 'render()' not in monthly_handlers
    assert 'function currentFilteredRows()' in TEMPLATE
