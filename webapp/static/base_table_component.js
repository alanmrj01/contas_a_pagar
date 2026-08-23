(() => {
  'use strict';

  const FIELDS = ['supplier_code', 'supplier', 'flow', 'category'];
  const emptyRow = () => ({supplier_code:'', supplier:'', flow:'', category:''});
  const normalized = value => String(value ?? '').trim().toLocaleLowerCase('pt-BR');
  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  let searchCache = new WeakMap();

  function normalizedFilters(filters) {
    return Object.fromEntries(FIELDS.map(field => [field, normalized(filters[field])]));
  }

  function indexedValues(item) {
    let values = searchCache.get(item);
    if (!values) {
      values = Object.fromEntries(FIELDS.map(field => [field, normalized(item[field])]));
      searchCache.set(item, values);
    }
    return values;
  }

  function matchesNormalizedFilters(item, filters) {
    const values = indexedValues(item);
    return FIELDS.every(field => !filters[field] || values[field].includes(filters[field]));
  }

  function matchesFilters(item, filters) {
    return matchesNormalizedFilters(item, normalizedFilters(filters));
  }

  function filterItems(items, filters) {
    const current = normalizedFilters(filters);
    return items.filter(item => matchesNormalizedFilters(item, current));
  }

  function addEmptyRow(items) {
    return [...items, emptyRow()];
  }

  function removeRowsByIndex(items, indexes) {
    const removed = new Set(indexes);
    return items.filter((_item, index) => !removed.has(index));
  }

  function create(config) {
    const body = config.body;
    const filterInputs = [...config.filterInputs];
    const pageSize = Math.max(50, Number(config.pageSize) || 200);
    const inputClass = config.inputClass || 'base-cell-input';
    const checkboxClass = config.checkboxClass || 'base-row-check';
    const columns = Number(config.columns) || 5;
    let items = [];
    let snapshot = null;
    let editing = false;
    let selected = new Set();
    let visibleIndexes = null;
    let page = 0;
    let filtering = false;
    let filterTimer = 0;
    let filterRun = 0;

    function filters() {
      const result = {};
      filterInputs.forEach(input => { result[input.dataset.baseColumnFilter] = input.value.trim(); });
      return result;
    }

    function activeFilters() {
      return Object.values(filters()).some(Boolean);
    }

    function visibleCount() {
      return visibleIndexes === null ? items.length : visibleIndexes.length;
    }

    function visibleIndexAt(position) {
      return visibleIndexes === null ? position : visibleIndexes[position];
    }

    function pageIndexes() {
      const total = visibleCount();
      const pages = Math.max(1, Math.ceil(total / pageSize));
      page = Math.min(page, pages - 1);
      const start = page * pageSize;
      const end = Math.min(total, start + pageSize);
      const result = [];
      for (let position = start; position < end; position += 1) result.push(visibleIndexAt(position));
      return result;
    }

    function updateControls(currentPageIndexes = pageIndexes()) {
      const total = visibleCount();
      const pages = Math.max(1, Math.ceil(total / pageSize));
      const selectedCount = selected.size;
      const prefix = filtering ? `Filtrando ${items.length.toLocaleString('pt-BR')} registros...` : `${total.toLocaleString('pt-BR')} de ${items.length.toLocaleString('pt-BR')} registro(s)`;
      config.status.textContent = `${prefix} • página ${page + 1} de ${pages}${selectedCount ? ` • ${selectedCount} selecionada(s)` : ''}`;
      config.previous.disabled = filtering || page <= 0;
      config.next.disabled = filtering || page >= pages - 1;
      config.remove.disabled = selectedCount === 0;
      const pageItems = currentPageIndexes.map(index => items[index]);
      config.selectPage.checked = pageItems.length > 0 && pageItems.every(item => selected.has(item));
      config.selectPage.indeterminate = !config.selectPage.checked && pageItems.some(item => selected.has(item));
      if (typeof config.onEditingChange === 'function') config.onEditingChange(editing);
    }

    function render() {
      const indexes = pageIndexes();
      if (!indexes.length) {
        body.innerHTML = `<tr><td colspan="${columns}" class="base-empty-row">Nenhum registro encontrado com os filtros informados.</td></tr>`;
        updateControls(indexes);
        return;
      }
      body.innerHTML = indexes.map(index => {
        const item = items[index];
        const checked = selected.has(item) ? ' checked' : '';
        const cells = FIELDS.map(field => editing
          ? `<td><input class="${inputClass}" data-base-index="${index}" data-base-field="${field}" value="${escapeHtml(item[field])}" autocomplete="off"></td>`
          : `<td>${escapeHtml(item[field])}</td>`).join('');
        return `<tr><td class="base-select-cell"><input class="${checkboxClass}" type="checkbox" data-base-select="${index}" aria-label="Selecionar linha ${index + 1}"${checked}></td>${cells}</tr>`;
      }).join('');
      updateControls(indexes);
    }

    function applyFilters(delay = 160) {
      clearTimeout(filterTimer);
      const token = ++filterRun;
      filtering = true;
      updateControls();
      filterTimer = setTimeout(() => {
        const current = normalizedFilters(filters());
        if (!Object.values(current).some(Boolean)) {
          visibleIndexes = null;
          filtering = false;
          page = 0;
          render();
          return;
        }
        const matches = [];
        let index = 0;
        const step = () => {
          if (token !== filterRun) return;
          const end = Math.min(items.length, index + 4000);
          for (; index < end; index += 1) if (matchesNormalizedFilters(items[index], current)) matches.push(index);
          if (index < items.length) {
            setTimeout(step, 0);
          } else {
            visibleIndexes = matches;
            filtering = false;
            page = 0;
            render();
          }
        };
        step();
      }, delay);
    }

    function startEditing() {
      if (editing) return;
      snapshot = items.map(item => ({...item}));
      editing = true;
      render();
    }

    function cancelEditing() {
      if (snapshot) items = snapshot.map(item => ({...item}));
      snapshot = null;
      editing = false;
      selected.clear();
      applyFilters(0);
    }

    function clearFilters() {
      filterInputs.forEach(input => { input.value = ''; });
      filterRun += 1;
      visibleIndexes = null;
      filtering = false;
      page = 0;
    }

    function addRow() {
      startEditing();
      clearFilters();
      items.push(emptyRow());
      page = Math.max(0, Math.ceil(items.length / pageSize) - 1);
      render();
      setTimeout(() => body.querySelector(`[data-base-index="${items.length - 1}"][data-base-field="supplier_code"]`)?.focus(), 0);
    }

    function removeSelected() {
      if (!selected.size) return;
      if (selected.size >= items.length) {
        config.showError('A Base de Dados precisa manter ao menos uma linha.');
        return;
      }
      const count = selected.size;
      if (!window.confirm(`Remover ${count} linha(s) selecionada(s)? A remoção será efetivada somente ao salvar as alterações.`)) return;
      startEditing();
      items = items.filter(item => !selected.has(item));
      selected.clear();
      page = 0;
      applyFilters(0);
    }

    function getItems() {
      const result = items.map(item => Object.fromEntries(FIELDS.map(field => [field, String(item[field] ?? '').trim()])));
      const invalidIndex = result.findIndex(item => FIELDS.some(field => !item[field]));
      if (invalidIndex >= 0) throw new Error(`Preencha Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria na linha ${invalidIndex + 1}.`);
      return result;
    }

    body.addEventListener('input', event => {
      const input = event.target.closest('[data-base-index][data-base-field]');
      if (!input) return;
      const index = Number(input.dataset.baseIndex);
      if (!Number.isInteger(index) || !items[index]) return;
      items[index][input.dataset.baseField] = input.value;
      searchCache.delete(items[index]);
      if (activeFilters()) applyFilters(320);
    });
    body.addEventListener('change', event => {
      const checkbox = event.target.closest('[data-base-select]');
      if (!checkbox) return;
      const item = items[Number(checkbox.dataset.baseSelect)];
      if (!item) return;
      checkbox.checked ? selected.add(item) : selected.delete(item);
      updateControls();
    });
    filterInputs.forEach(input => input.addEventListener('input', () => applyFilters()));
    config.selectPage.addEventListener('change', () => {
      pageIndexes().forEach(index => config.selectPage.checked ? selected.add(items[index]) : selected.delete(items[index]));
      render();
    });
    config.previous.addEventListener('click', () => { if (page > 0) { page -= 1; render(); } });
    config.next.addEventListener('click', () => { if ((page + 1) * pageSize < visibleCount()) { page += 1; render(); } });
    config.add.addEventListener('click', addRow);
    config.remove.addEventListener('click', removeSelected);

    return {
      load(rows) {
        filterRun += 1;
        searchCache = new WeakMap();
        items = (rows || []).map(row => Object.fromEntries(FIELDS.map(field => [field, String(row[field] ?? '')])));
        snapshot = null;
        editing = false;
        selected.clear();
        page = 0;
        applyFilters(0);
      },
      startEditing,
      cancelEditing,
      getItems,
      isEditing: () => editing,
      render,
    };
  }

  window.BaseTableComponent = {
    create,
    __test: {matchesFilters, filterItems, addEmptyRow, removeRowsByIndex},
  };
})();
