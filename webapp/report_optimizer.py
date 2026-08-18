from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

MARKER = "<!-- WEB-PERFORMANCE-PATCH-2.0.2 -->"


def _script_hashes(html: str) -> list[str]:
    hashes: list[str] = []
    for script in re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, flags=re.IGNORECASE | re.DOTALL):
        digest = hashlib.sha256(script.encode("utf-8")).digest()
        hashes.append("sha256-" + base64.b64encode(digest).decode("ascii"))
    return hashes


def optimize_report_file(path: Path) -> list[str]:
    """Otimizações somente de execução no navegador; sem mudar dados, layout ou regras."""

    path = Path(path)
    html = path.read_text(encoding="utf-8")
    original = html

    # Intl.NumberFormat era recriado milhares de vezes em relatórios grandes.
    old = (
        "const D=window.REPORT_DATA;const el=id=>document.getElementById(id);"
        "const brl=v=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(Number(v)||0);"
        "const pct=v=>v===null||v===undefined?'—':new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v)||0)+'%';"
    )
    new = (
        "const D=window.REPORT_DATA;const el=id=>document.getElementById(id);"
        "const BRL_FMT=new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}),"
        "PCT_FMT=new Intl.NumberFormat('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}),"
        "DATE_FMT=new Intl.DateTimeFormat('pt-BR');"
        "const brl=v=>BRL_FMT.format(Number(v)||0);"
        "const pct=v=>v===null||v===undefined?'—':PCT_FMT.format(Number(v)||0)+'%';"
        "const dateBR=v=>v?DATE_FMT.format(new Date(v+'T00:00:00')):'—';"
    )
    if old not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (formatadores).")
    html = html.replace(old, new, 1)

    old_dates = "${x.date?new Date(x.date+'T00:00:00').toLocaleDateString('pt-BR'):'—'}</td><td>${x.due_date?new Date(x.due_date+'T00:00:00').toLocaleDateString('pt-BR'):'—'}"
    new_dates = "${dateBR(x.date)}</td><td>${dateBR(x.due_date)}"
    if old_dates not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (datas).")
    html = html.replace(old_dates, new_dates, 1)

    # Evita recriar termos e a string pesquisável para cada linha, em cada facet/render.
    old_search_core = (
        "const ALL_ITEMS=[...(D.previsto||[]),...(D.realizado||[])];"
    )
    new_search_core = (
        "const ALL_ITEMS=[...(D.previsto||[]),...(D.realizado||[])];"
        "ALL_ITEMS.forEach(x=>{x.__webSearch=`${x.supplier||''} ${x.supplier_source||''} ${x.title||''}`.toLowerCase()});"
    )
    if old_search_core not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (índice de pesquisa).")
    html = html.replace(old_search_core, new_search_core, 1)

    terms_pattern = re.compile(
        r"function searchTerms\(\)\{return state\.search\.split\(','\)\.map\(v=>v\.trim\(\)\.toLowerCase\(\)\)\.filter\(Boolean\)\}\s*"
        r"function passesSearch\(x\)\{let terms=searchTerms\(\);if\(!terms\.length\)return true;let hay=`\$\{x\.supplier\|\|''\} \$\{x\.supplier_source\|\|''\} \$\{x\.title\|\|''\}`\.toLowerCase\(\);return terms\.some\(q=>hay\.includes\(q\)\)\}"
    )
    new_terms = "let SEARCH_CACHE_VALUE=null,SEARCH_CACHE_TERMS=[];function searchTerms(){if(SEARCH_CACHE_VALUE!==state.search){SEARCH_CACHE_VALUE=state.search;SEARCH_CACHE_TERMS=state.search.split(',').map(v=>v.trim().toLowerCase()).filter(Boolean)}return SEARCH_CACHE_TERMS}function passesSearch(x){let terms=searchTerms();if(!terms.length)return true;return terms.some(q=>x.__webSearch.includes(q))}"
    html, count = terms_pattern.subn(new_terms, html, count=1)
    if count != 1:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (cache de pesquisa).")

    pass_pattern = re.compile(
        r"function pass\(x\)\{if\(!matchesSelected\(x\.category,state\.category\)\)return false;if\(!matchesSelected\(x\.flow,state\.flow\)\)return false;if\(!matchesSelected\(x\.supplier,state\.supplier\)\)return false;if\(state\.emission\.length&&!state\.emission\.includes\(emissionKeyForItem\(x\)\)\)return false;let terms=state\.search\.split\(','\)\.map\(v=>v\.trim\(\)\.toLowerCase\(\)\)\.filter\(Boolean\);if\(terms\.length\)\{let hay=`\$\{x\.supplier\|\|''\} \$\{x\.supplier_source\|\|''\} \$\{x\.title\|\|''\}`\.toLowerCase\(\);if\(!terms\.some\(q=>hay\.includes\(q\)\)\)return false\}return true\}"
    )
    new_pass = "function pass(x){if(!matchesSelected(x.category,state.category))return false;if(!matchesSelected(x.flow,state.flow))return false;if(!matchesSelected(x.supplier,state.supplier))return false;if(state.emission.length&&!state.emission.includes(emissionKeyForItem(x)))return false;let terms=searchTerms();if(terms.length&&!terms.some(q=>x.__webSearch.includes(q)))return false;return true}"
    html, count = pass_pattern.subn(new_pass, html, count=1)
    if count != 1:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (filtro de pesquisa).")

    # Seleções são consultadas milhares de vezes durante filtros grandes. Um WeakMap
    # mantém Sets somente enquanto o array atual de seleção existir.
    old_matches = "function matchesSelected(value,selected){return !selected.length||selected.includes(value||'')}"
    new_matches = "const FILTER_SET_CACHE=new WeakMap();function matchesSelected(value,selected){if(!selected.length)return true;let set=FILTER_SET_CACHE.get(selected);if(!set){set=new Set(selected);FILTER_SET_CACHE.set(selected,set)}return set.has(value||'')}"
    if old_matches not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (seleções).")
    html = html.replace(old_matches, new_matches, 1)

    # O filtro em cascata consultava as mesmas combinações várias vezes na mesma
    # atualização. O cache é invalidado a cada ciclo e recalculado somente quando
    # alguma seleção é podada.
    old_possible = (
        "function possibleFacetValues(facet){\n"
        "  const items=ALL_ITEMS.filter(x=>passExcept(x,facet));\n"
        "  if(facet==='emission')return [...new Set(items.map(x=>{let raw=String(competenceDateForItem(x)||'');return raw?raw.slice(0,state.emissionMode==='date'?10:7):''}).filter(Boolean))].sort();\n"
        "  const cfg=FACET_CONFIG[facet];return uniq(items,cfg.field);\n"
        "}"
    )
    new_possible = (
        "const FACET_VALUE_CACHE=new Map();"
        "function facetStateKey(facet){return [facet,state.category.join('\\u001f'),state.flow.join('\\u001f'),state.supplier.join('\\u001f'),state.emissionMode,state.emission.join('\\u001f'),state.search].join('\\u001e')}"
        "function possibleFacetValues(facet){const cacheKey=facetStateKey(facet);if(FACET_VALUE_CACHE.has(cacheKey))return FACET_VALUE_CACHE.get(cacheKey);"
        "const items=ALL_ITEMS.filter(x=>passExcept(x,facet));let values;"
        "if(facet==='emission')values=[...new Set(items.map(x=>{let raw=String(competenceDateForItem(x)||'');return raw?raw.slice(0,state.emissionMode==='date'?10:7):''}).filter(Boolean))].sort();"
        "else{const cfg=FACET_CONFIG[facet];values=uniq(items,cfg.field)}FACET_VALUE_CACHE.set(cacheKey,values);return values}"
    )
    if old_possible not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (facets).")
    html = html.replace(old_possible, new_possible, 1)

    old_refresh = "function refreshFilterOptions(){pruneUnavailableSelections();paintStandardFilter('category');paintStandardFilter('flow');paintStandardFilter('supplier');paintEmissionFilter();refreshMonthFilterOptions()}\nfunction applyFiltersNow(){refreshFilterOptions();render()}"
    new_refresh = "function refreshFilterOptions(){FACET_VALUE_CACHE.clear();const changed=pruneUnavailableSelections();if(changed)FACET_VALUE_CACHE.clear();paintStandardFilter('category');paintStandardFilter('flow');paintStandardFilter('supplier');paintEmissionFilter();refreshMonthFilterOptions()}let filterApplyFrame=0;function applyFiltersNow(){if(filterApplyFrame)cancelAnimationFrame(filterApplyFrame);filterApplyFrame=requestAnimationFrame(()=>{filterApplyFrame=0;refreshFilterOptions();render()})}"
    if old_refresh not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (ciclo de filtros).")
    html = html.replace(old_refresh, new_refresh, 1)

    # Mantém a pesquisa dinâmica, mas evita reconstruir todo o dashboard a cada tecla.
    old_search = "el('fSearch').addEventListener('input',e=>{state.search=e.target.value.trim();applyFiltersNow()});"
    new_search = (
        "let searchRenderTimer=0;"
        "el('fSearch').addEventListener('input',e=>{state.search=e.target.value.trim();"
        "clearTimeout(searchRenderTimer);searchRenderTimer=setTimeout(applyFiltersNow,180)});"
    )
    if old_search not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (pesquisa).")
    html = html.replace(old_search, new_search, 1)

    # Evita dezenas de recalculos de layout durante resize contínuo.
    old_resize = "window.addEventListener('resize',()=>{hideInfoTip();fitReportValues();fitMonthlyViewport()});"
    new_resize = (
        "let resizeFrame=0;window.addEventListener('resize',()=>{hideInfoTip();"
        "if(resizeFrame)return;resizeFrame=requestAnimationFrame(()=>{resizeFrame=0;fitReportValues();fitMonthlyViewport()})});"
    )
    if old_resize not in html:
        raise RuntimeError("Patch de desempenho incompatível com o template atual (resize).")
    html = html.replace(old_resize, new_resize, 1)

    html = html.replace("</head>", MARKER + "\n</head>", 1)
    if html == original:
        raise RuntimeError("Nenhuma otimização de relatório foi aplicada.")
    path.write_text(html, encoding="utf-8")
    return _script_hashes(html)
