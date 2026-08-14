(() => {
  'use strict';

  const el = (id) => document.getElementById(id);
  const supported = new Set(['.xlsx','.xls','.xlsm','.xlsb']);
  const state = {
    files: [],
    selected: new Set(),
    validated: false,
    busy: false,
    reportUrl: '',
    pdfUrl: '',
    spinnerTimer: null,
    spinnerIndex: 0,
    pendingBaseFile: null,
  };
  const spinnerFrames = ['◜','◝','◞','◟'];

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function fileKey(file, index) {
    return `${index}|${file.name}|${file.size}|${file.lastModified}`;
  }

  function showMessage(title, message) {
    el('messageTitle').textContent = title;
    el('messageText').textContent = message;
    el('messageDialog').showModal();
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {credentials:'same-origin', ...options});
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      throw new Error((payload && payload.detail) || `Falha HTTP ${response.status}`);
    }
    return payload;
  }

  function setAnalysis(badge, message) {
    el('analysisBadge').textContent = badge.toUpperCase();
    el('analysisIntro').textContent = message;
  }

  function setSpinner(on) {
    if (on) {
      el('spinner').classList.add('visible');
      state.spinnerIndex = 0;
      el('spinner').textContent = spinnerFrames[0];
      clearInterval(state.spinnerTimer);
      state.spinnerTimer = setInterval(() => {
        state.spinnerIndex = (state.spinnerIndex + 1) % spinnerFrames.length;
        el('spinner').textContent = spinnerFrames[state.spinnerIndex];
      }, 110);
    } else {
      clearInterval(state.spinnerTimer);
      state.spinnerTimer = null;
      el('spinner').classList.remove('visible');
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    setSpinner(busy);
    syncSteps();
  }

  function invalidateValidation(reason = '') {
    state.validated = false;
    if (reason) {
      setAnalysis('AGUARDANDO', reason);
      el('analysisDetails').innerHTML = '<div class="analysis-placeholder">O resumo organizado da validação aparecerá aqui.</div>';
    }
    syncSteps();
  }

  function syncSteps() {
    const hasFiles = state.files.length > 0;
    const validateReady = hasFiles && !state.busy;
    const generateReady = state.validated && !state.busy;

    el('step1').classList.toggle('disabled-card', state.busy);
    el('step2').classList.toggle('disabled-card', !hasFiles);
    el('step3').classList.toggle('disabled-card', !state.validated);

    el('pickBtn').disabled = state.busy;
    el('dropArea').disabled = state.busy;
    el('removeBtn').disabled = state.busy || state.selected.size === 0;
    el('clearBtn').disabled = state.busy || !hasFiles;
    el('baseBtn').disabled = state.busy;

    el('validateBtn').disabled = !validateReady;
    el('validateBtn').classList.toggle('ready', validateReady);
    el('generateBtn').disabled = !generateReady;
    el('generateBtn').classList.toggle('ready', generateReady);
    el('openReportBtn').disabled = !(state.validated && state.reportUrl && !state.busy);
    el('openPdfBtn').disabled = !(state.validated && state.pdfUrl && !state.busy);
  }

  function renderFiles() {
    if (!state.files.length) {
      el('fileList').innerHTML = '<div class="file-empty">Nenhum arquivo adicionado.</div>';
      state.selected.clear();
      syncSteps();
      return;
    }
    el('fileList').innerHTML = state.files.map((file, index) => {
      const key = fileKey(file,index);
      return `<div class="file-item${state.selected.has(key) ? ' selected' : ''}" data-index="${index}" title="${esc(file.name)}">${esc(file.name)}</div>`;
    }).join('');
    syncSteps();
  }

  function addFiles(fileList) {
    let added = 0;
    const existing = new Set(state.files.map(f => `${f.name.toLowerCase()}|${f.size}|${f.lastModified}`));
    for (const file of Array.from(fileList || [])) {
      const ext = file.name.includes('.') ? `.${file.name.split('.').pop().toLowerCase()}` : '';
      if (!supported.has(ext)) continue;
      const unique = `${file.name.toLowerCase()}|${file.size}|${file.lastModified}`;
      if (!existing.has(unique)) {
        state.files.push(file);
        existing.add(unique);
        added += 1;
      }
    }
    renderFiles();
    invalidateValidation('Arquivos alterados. Execute a validação antes de gerar o relatório.');
    if (added) {
      el('filesDialogText').textContent = `${added} arquivo(s) adicionado(s). Deseja importar mais arquivos ou iniciar a validação?`;
      el('filesDialog').showModal();
    }
  }

  function renderValidation(summary) {
    let html = '<div><p><b class="blue">O que foi reconhecido</b></p><table>';
    html += `<tr><td><b>PREVISTO</b></td><td>${summary.previsto} registros em ${summary.previsto_tables} tabela(s)</td></tr>`;
    html += `<tr><td><b>REALIZADO</b></td><td>${summary.realizado} registros em ${summary.realizado_tables} tabela(s)</td></tr>`;
    html += `<tr><td><b>BASE DADOS</b></td><td>${summary.base} registros</td></tr>`;
    html += `<tr><td><b>Período</b></td><td>${esc(summary.period)}</td></tr></table>`;
    if (summary.notes && summary.notes.length) {
      html += '<p><b class="light-blue">Observações da leitura</b></p><ul>';
      html += summary.notes.map(note => `<li>${esc(note)}</li>`).join('');
      html += '</ul>';
    }
    if (summary.warnings && summary.warnings.length) {
      html += '<p><b class="warning">Pontos de atenção</b></p><ul>';
      html += summary.warnings.map(w => `<li><b>${esc(w.title)}</b>: ${esc(w.summary)}</li>`).join('');
      html += '</ul>';
    } else {
      html += '<p class="good"><b>Nenhum aviso de consistência foi identificado nesta validação.</b></p>';
    }
    html += '</div>';
    el('analysisDetails').innerHTML = html;
  }

  async function validateFiles() {
    if (!state.files.length || state.busy) return;
    state.validated = false;
    setBusy(true);
    setAnalysis('ANALISANDO', 'Lendo os arquivos e conferindo estrutura, valores, datas e classificação. Nenhuma informação é alterada durante esta etapa.');
    el('analysisDetails').innerHTML = '';
    const form = new FormData();
    state.files.forEach(file => form.append('files', file, file.name));
    try {
      setAnalysis('ANALISANDO', 'Identificando o formato financeiro e separando PREVISTO/REALIZADO com segurança...');
      const result = await api('/api/validate', {method:'POST', body:form});
      renderValidation(result.summary);
      state.validated = true;
      setAnalysis('VALIDADO', 'Validação concluída. Revise o resumo abaixo; se estiver de acordo, o botão Gerar relatório já está liberado.');
    } catch (error) {
      state.validated = false;
      setAnalysis('ATENÇÃO', 'A automação interrompeu a etapa para evitar gerar um relatório com dados possivelmente incorretos.');
      el('analysisDetails').innerHTML = `<div><p><b class="danger">O que aconteceu</b></p><p>${esc(error.message)}</p><p style="color:#b9cad7">Revise a mensagem acima e corrija somente o ponto indicado. Os arquivos originais e a BASE DADOS foram preservados.</p></div>`;
      const title = error.message.includes('Não consegui identificar com segurança') ? 'Não foi possível identificar os dados' : 'Não foi possível concluir';
      showMessage(title, error.message);
    } finally {
      setBusy(false);
    }
  }

  async function generateReport() {
    if (!state.validated || state.busy) return;
    setBusy(true);
    setAnalysis('GERANDO', 'Criando Excel de auditoria, PDF A4 e relatório interativo com os dados já validados.');
    try {
      const result = await api('/api/generate', {method:'POST'});
      state.reportUrl = result.report_url;
      state.pdfUrl = result.pdf_url;
      setAnalysis('PRONTO', 'Relatório concluído. O relatório interativo será aberto agora.');
      el('analysisDetails').innerHTML = '<div><p><b class="good">Arquivos gerados com sucesso</b></p><p>O relatório interativo, o PDF A4 e as planilhas Excel de auditoria foram gerados com os dados validados.</p></div>';
      setBusy(false);
      window.location.assign(state.reportUrl);
    } catch (error) {
      setAnalysis('ATENÇÃO', 'A automação interrompeu a etapa para evitar gerar um relatório com dados possivelmente incorretos.');
      el('analysisDetails').innerHTML = `<div><p><b class="danger">O que aconteceu</b></p><p>${esc(error.message)}</p><p style="color:#b9cad7">Os arquivos originais e a BASE DADOS foram preservados.</p></div>`;
      showMessage('Não foi possível concluir', error.message);
      setBusy(false);
    }
  }

  async function loadState() {
    try {
      const result = await api('/api/state');
      el('baseInfo').textContent = `BASE DADOS ativa: ${result.base.rows} registros • ${result.base.origin}`;
      state.validated = !!result.validated;
      state.reportUrl = result.report_url || '';
      state.pdfUrl = result.pdf_url || '';
      // Uma nova navegação não possui os File objetos originais do navegador.
      // Por segurança, revalidação exige nova seleção caso a página tenha sido recarregada.
      if (!state.files.length) state.validated = false;
      syncSteps();
    } catch (error) {
      el('baseInfo').textContent = `ERRO NA BASE DADOS: ${error.message}`;
    }
  }

  async function openBaseDialog() {
    if (state.busy) return;
    el('baseDialogInfo').textContent = 'Carregando BASE DADOS...';
    el('baseTableBody').innerHTML = '<tr><td colspan="4">Carregando...</td></tr>';
    el('baseDialog').showModal();
    try {
      const data = await api('/api/base');
      el('baseDialogInfo').textContent = `BASE DADOS ativa: ${data.rows} registros • ${data.origin}`;
      el('baseTableBody').innerHTML = data.items.map(row => `<tr><td>${esc(row.supplier_code)}</td><td>${esc(row.supplier)}</td><td>${esc(row.flow)}</td><td>${esc(row.category)}</td></tr>`).join('');
    } catch (error) {
      el('baseTableBody').innerHTML = `<tr><td colspan="4" class="danger">${esc(error.message)}</td></tr>`;
    }
  }

  async function importBase(file) {
    const form = new FormData();
    form.append('file', file, file.name);
    try {
      const result = await api('/api/base/import', {method:'POST', body:form});
      el('baseInfo').textContent = `BASE DADOS ativa: ${result.base.rows} registros • ${result.base.origin}`;
      invalidateValidation('BASE DADOS alterada. Valide novamente os arquivos antes de gerar o relatório.');
      await openBaseDialogRefresh();
      showMessage('Base atualizada', `Nova BASE DADOS validada e salva com ${result.base.rows} registros.`);
    } catch (error) {
      showMessage('Base recusada', error.message);
    }
  }

  async function openBaseDialogRefresh() {
    try {
      const data = await api('/api/base');
      el('baseDialogInfo').textContent = `BASE DADOS ativa: ${data.rows} registros • ${data.origin}`;
      el('baseTableBody').innerHTML = data.items.map(row => `<tr><td>${esc(row.supplier_code)}</td><td>${esc(row.supplier)}</td><td>${esc(row.flow)}</td><td>${esc(row.category)}</td></tr>`).join('');
    } catch (_) {}
  }

  el('pickBtn').addEventListener('click', () => el('fileInput').click());
  el('dropArea').addEventListener('click', () => el('fileInput').click());
  el('fileInput').addEventListener('change', event => { addFiles(event.target.files); event.target.value = ''; });
  el('dropArea').addEventListener('dragover', event => { event.preventDefault(); if (!state.busy) el('dropArea').classList.add('dragover'); });
  el('dropArea').addEventListener('dragleave', () => el('dropArea').classList.remove('dragover'));
  el('dropArea').addEventListener('drop', event => { event.preventDefault(); el('dropArea').classList.remove('dragover'); if (!state.busy) addFiles(event.dataTransfer.files); });

  el('fileList').addEventListener('click', event => {
    const item = event.target.closest('.file-item');
    if (!item || state.busy) return;
    const index = Number(item.dataset.index);
    const key = fileKey(state.files[index], index);
    state.selected.has(key) ? state.selected.delete(key) : state.selected.add(key);
    renderFiles();
  });

  el('removeBtn').addEventListener('click', () => {
    const oldFiles = state.files;
    state.files = oldFiles.filter((file,index) => !state.selected.has(fileKey(file,index)));
    state.selected.clear();
    renderFiles();
    invalidateValidation('Arquivos alterados. Valide novamente.');
  });
  el('clearBtn').addEventListener('click', () => {
    state.files = [];
    state.selected.clear();
    renderFiles();
    invalidateValidation('Lista de arquivos limpa.');
  });

  el('validateBtn').addEventListener('click', validateFiles);
  el('generateBtn').addEventListener('click', generateReport);
  el('openReportBtn').addEventListener('click', () => { if (state.reportUrl) window.location.assign(state.reportUrl); });
  el('openPdfBtn').addEventListener('click', () => { if (state.pdfUrl) window.open(state.pdfUrl, '_blank', 'noopener'); });

  el('dialogMore').addEventListener('click', () => { el('filesDialog').close(); el('fileInput').click(); });
  el('dialogValidate').addEventListener('click', () => { el('filesDialog').close(); validateFiles(); });

  el('baseBtn').addEventListener('click', openBaseDialog);
  el('baseClose').addEventListener('click', () => el('baseDialog').close());
  el('importBaseBtn').addEventListener('click', () => el('baseFileInput').click());
  el('baseFileInput').addEventListener('change', event => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    state.pendingBaseFile = file;
    el('confirmBaseDialog').showModal();
  });
  el('confirmBaseYes').addEventListener('click', () => {
    el('confirmBaseDialog').close();
    const file = state.pendingBaseFile;
    state.pendingBaseFile = null;
    if (file) importBase(file);
  });
  el('confirmBaseDialog').addEventListener('close', () => { if (el('confirmBaseDialog').returnValue === 'no') state.pendingBaseFile = null; });

  renderFiles();
  loadState();
})();
