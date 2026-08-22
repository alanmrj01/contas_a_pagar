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
    pendingBaseUploadId: '',
    pendingBaseConflicts: [],
    baseItems: [],
    baseEditing: false,
    security: null,
    serverPublicKey: null,
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
    el('messageText').innerHTML = `<p>${esc(message)}</p>`;
    el('messageDialog').showModal();
  }

  function isFileReadAccessError(error) {
    const message = String((error && error.message) || error || '').toLowerCase();
    return [
      'requested file could not be read',
      'could not be read',
      'notreadableerror',
      'permission problem',
      'permission denied',
      'não foi possível ler o arquivo',
      'nao foi possivel ler o arquivo',
      'não foi possível abrir a planilha',
      'nao foi possivel abrir a planilha',
    ].some(part => message.includes(part));
  }

  function clearFilesAfterReadFailure() {
    state.files = [];
    state.selected.clear();
    state.validated = false;
    const input = el('fileInput');
    if (input) input.value = '';
    renderFiles();
    invalidateValidation('O arquivo anterior foi removido automaticamente. Adicione uma cópia local e valide novamente.');
  }

  function errorGuide(error, context = 'validate') {
    const message = String((error && error.message) || error || 'Ocorreu um erro inesperado.');

    if (isFileReadAccessError(error)) {
      return {
        title: 'Não foi possível ler o arquivo',
        summary: 'O navegador perdeu ou não recebeu permissão suficiente para ler a planilha selecionada. Isso pode acontecer quando o arquivo está aberto no Excel, está em pasta de rede, OneDrive/SharePoint ou veio de uma origem com acesso controlado.',
        steps: [
          'Feche a planilha no Excel ou em qualquer outro programa que possa estar usando o arquivo.',
          'Faça uma cópia do arquivo para uma pasta local simples, como Downloads ou Área de Trabalho.',
          'Clique em Adicionar arquivo, selecione essa cópia e execute Validar arquivo novamente.',
        ],
        footer: 'A lista de arquivos foi limpa automaticamente para que a referência com problema não seja reutilizada. Nenhum dado financeiro desse arquivo foi mantido pela aplicação.',
        technical: message,
        clearFiles: true,
      };
    }

    if (message.includes('Não consegui identificar com segurança')) {
      return {
        title: 'Não foi possível identificar os dados',
        summary: 'A planilha foi lida, porém a estrutura encontrada ainda não correspondeu a um modelo financeiro reconhecido com segurança.',
        steps: [
          'Confira se o consolidado contém Título, Cód Fornecedor, Fornecedor, Data e Situação FC.',
          'O consolidado pode usar Previsto/Realizado ou Valor/Valor2. No modelo Valor/Valor2, Valor alimenta PREVISTO e Valor2 alimenta REALIZADO somente depois de a Situação FC confirmar o tipo da linha.',
          'Se a planilha tiver outro padrão, não troque colunas por tentativa. Utilize um modelo conhecido ou encaminhe o layout para inclusão de um novo mapeamento determinístico.',
        ],
        footer: 'Nenhum valor é estimado a partir de coluna ambígua. A validação é interrompida para evitar um relatório financeiramente incorreto.',
        technical: message,
        clearFiles: false,
      };
    }

    if (context === 'base') {
      return {
        title: 'Não foi possível atualizar a Base de Dados',
        summary: 'A base enviada não pôde ser confirmada com segurança. A base anterior foi preservada e continua ativa.',
        steps: [
          'Confira se a planilha contém Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria.',
          'Se o arquivo estiver aberto, em rede ou sincronizado, feche-o e tente novamente usando uma cópia em Downloads ou Área de Trabalho.',
          'Se o erro continuar, preserve a base atual e encaminhe os detalhes técnicos abaixo para análise antes de substituir qualquer informação.',
        ],
        footer: 'A Base de Dados anterior não é substituída quando a nova planilha falha na validação.',
        technical: message,
        clearFiles: false,
      };
    }

    return {
      title: context === 'generate' ? 'Não foi possível gerar o relatório' : 'Não foi possível concluir',
      summary: 'A operação foi interrompida antes de continuar com dados possivelmente incorretos.',
      steps: [
        'Confira se o arquivo continua disponível e não está aberto ou bloqueado por outro programa.',
        'Se a origem for rede, OneDrive/SharePoint ou pasta sincronizada, tente novamente usando uma cópia em Downloads ou Área de Trabalho.',
        'Se o erro continuar, preserve o arquivo original e encaminhe os detalhes técnicos exibidos abaixo para análise.',
      ],
      footer: 'Os arquivos originais e a BASE DADOS não são modificados pela validação.',
      technical: message,
      clearFiles: false,
    };
  }

  function guideHtml(guide) {
    return `<div class="error-guide">
      <p class="error-summary">${esc(guide.summary)}</p>
      <ol class="error-steps">${guide.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ol>
      <p class="error-footer">${esc(guide.footer)}</p>
      <details class="error-technical"><summary>Detalhes técnicos</summary><pre>${esc(guide.technical)}</pre></details>
    </div>`;
  }

  function showGuidedError(guide) {
    el('messageTitle').textContent = guide.title;
    el('messageText').innerHTML = guideHtml(guide);
    el('messageDialog').showModal();
  }

  async function probeFileReadable(file) {
    try {
      const probeSize = Math.min(file.size || 0, 64 * 1024);
      if (probeSize > 0) await file.slice(0, probeSize).arrayBuffer();
      return true;
    } catch (_) {
      return false;
    }
  }

  const textEncoder = new TextEncoder();

  function toBase64(value) {
    const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  async function ensureSecurity(force = false) {
    if (!force && state.security && state.serverPublicKey) return state.security;
    if (!window.crypto || !window.crypto.subtle) {
      throw new Error('Este navegador não oferece os recursos criptográficos necessários. Use uma versão atual do Edge, Chrome ou Firefox.');
    }
    const response = await fetch('/api/security/bootstrap', {credentials:'same-origin', cache:'no-store'});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `Falha HTTP ${response.status}`);
    state.security = payload;
    state.serverPublicKey = await crypto.subtle.importKey(
      'jwk', payload.public_key_jwk,
      {name:'RSA-OAEP', hash:'SHA-256'}, false, ['encrypt']
    );
    return payload;
  }

  async function api(url, options = {}, retried = false) {
    const method = String(options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    if (['POST','PUT','PATCH','DELETE'].includes(method)) {
      await ensureSecurity();
      headers.set('X-CSRF-Token', state.security.csrf_token);
    }
    const response = await fetch(url, {credentials:'same-origin', cache:'no-store', ...options, headers});
    let payload = null;
    try { payload = await response.json(); } catch (_) { payload = null; }
    if (!response.ok) {
      if (response.status === 401) {
        window.location.replace('/');
        throw new Error('Sua sessão expirou. Faça login novamente.');
      }
      if (response.status === 403 && payload && payload.code === 'CSRF_REFRESH_REQUIRED' && !retried) {
        state.security = null;
        state.serverPublicKey = null;
        await ensureSecurity(true);
        return api(url, options, true);
      }
      throw new Error((payload && payload.detail) || `Falha HTTP ${response.status}`);
    }
    return payload;
  }

  async function discardUploads(uploadIds) {
    if (!uploadIds || !uploadIds.length) return;
    try {
      await api('/api/uploads/discard', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({upload_ids:uploadIds}),
      });
    } catch (_) {}
  }

  async function stageEncryptedFile(file, purpose = 'financial') {
    const securityInfo = await ensureSecurity();
    if (file.size > securityInfo.max_upload_bytes) {
      throw new Error(`O arquivo ${file.name} excede o limite de ${Math.round(securityInfo.max_upload_bytes / 1024 / 1024)} MB por planilha.`);
    }
    const aesKey = await crypto.subtle.generateKey({name:'AES-GCM', length:256}, true, ['encrypt']);
    const rawKey = await crypto.subtle.exportKey('raw', aesKey);
    const wrappedKey = await crypto.subtle.encrypt({name:'RSA-OAEP'}, state.serverPublicKey, rawKey);
    let uploadId = '';
    try {
      const init = await api('/api/uploads/init', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          filename:file.name,
          size:file.size,
          purpose,
          encrypted_key:toBase64(wrappedKey),
        }),
      });
      uploadId = init.upload_id;
      const chunkBytes = Number(init.chunk_bytes) || securityInfo.upload_chunk_bytes;
      const totalChunks = Number(init.total_chunks) || Math.ceil(file.size / chunkBytes);
      for (let index = 0; index < totalChunks; index += 1) {
        const start = index * chunkBytes;
        const end = Math.min(file.size, start + chunkBytes);
        const plain = await file.slice(start, end).arrayBuffer();
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const aad = textEncoder.encode(`cap-upload-v1|${uploadId}|${index}|${plain.byteLength}`);
        const cipher = await crypto.subtle.encrypt(
          {name:'AES-GCM', iv, additionalData:aad, tagLength:128}, aesKey, plain
        );
        await api(`/api/uploads/${uploadId}/chunk/${index}`, {
          method:'POST',
          headers:{
            'Content-Type':'application/octet-stream',
            'X-Chunk-IV':toBase64(iv),
            'X-Plain-Size':String(plain.byteLength),
          },
          body:cipher,
        });
        // Libera o event loop entre blocos para manter a interface responsiva.
        await new Promise(resolve => setTimeout(resolve, 0));
      }
      await api(`/api/uploads/${uploadId}/complete`, {method:'POST'});
      return uploadId;
    } catch (error) {
      if (uploadId) await discardUploads([uploadId]);
      throw error;
    }
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

  async function addFiles(fileList) {
    let added = 0;
    const existing = new Set(state.files.map(f => `${f.name.toLowerCase()}|${f.size}|${f.lastModified}`));
    for (const file of Array.from(fileList || [])) {
      const ext = file.name.includes('.') ? `.${file.name.split('.').pop().toLowerCase()}` : '';
      if (!supported.has(ext)) continue;

      if (!(await probeFileReadable(file))) {
        clearFilesAfterReadFailure();
        showGuidedError(errorGuide(new Error('The requested file could not be read. The browser did not retain permission to access the selected file.')));
        return;
      }

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
    const autoAdded = Number(summary.base_health?.auto_added_suppliers || 0);
    html += `<tr><td><b>BASE DADOS</b></td><td>${summary.base} registros${autoAdded ? ` • ${autoAdded} complementado(s) automaticamente pela planilha` : ''}</td></tr>`;
    html += `<tr><td><b>Período</b></td><td>${esc(summary.period)}</td></tr></table>`;
    if (summary.base_health && summary.base_health.status === 'attention') {
      const names = (summary.base_health.suppliers || []).map(esc).join(', ');
      html += '<p><b class="warning">Classificação incompleta após complemento automático</b></p>';
      html += `<div class="analysis-placeholder"><b>${esc(summary.base_health.message)}</b>${names ? `<br><span>Fornecedor(es) ainda sem classificação segura: ${names}</span>` : ''}<br><span>Confira no arquivo importado se <b>Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria</b> estão preenchidos e consistentes. Corrija a própria planilha e valide novamente.</span></div>`;
    } else if (summary.base_health && summary.base_health.status === 'ok') {
      html += `<p class="good"><b>${esc(summary.base_health.message)}</b></p>`;
    }
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
    const staged = [];
    try {
      setAnalysis('ANALISANDO', 'Protegendo o envio e identificando o formato financeiro com segurança...');
      for (const file of state.files) staged.push(await stageEncryptedFile(file, 'financial'));
      setAnalysis('ANALISANDO', 'Identificando o formato financeiro e separando PREVISTO/REALIZADO com segurança...');
      const result = await api('/api/validate', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({upload_ids:staged}),
      });
      renderValidation(result.summary);
      state.validated = true;
      setAnalysis('VALIDADO', 'Validação concluída. Revise o resumo abaixo; se estiver de acordo, o botão Gerar relatório já está liberado.');
    } catch (error) {
      await discardUploads(staged);
      state.validated = false;
      const guide = errorGuide(error, 'validate');
      if (guide.clearFiles) clearFilesAfterReadFailure();
      setAnalysis('ATENÇÃO', 'A automação interrompeu a etapa para evitar gerar um relatório com dados possivelmente incorretos.');
      el('analysisDetails').innerHTML = `<div><p><b class="danger">Como resolver</b></p>${guideHtml(guide)}</div>`;
      showGuidedError(guide);
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
      const guide = errorGuide(error, 'generate');
      setAnalysis('ATENÇÃO', 'A automação interrompeu a etapa para evitar gerar um relatório com dados possivelmente incorretos.');
      el('analysisDetails').innerHTML = `<div><p><b class="danger">Como resolver</b></p>${guideHtml(guide)}</div>`;
      showGuidedError(guide);
      setBusy(false);
    }
  }

  async function loadState() {
    try {
      await ensureSecurity();
      const result = await api('/api/state');
      el('baseInfo').textContent = `BASE DADOS ativa: ${result.base.rows} registros • ${result.base.origin}${result.base.revision && result.base.revision !== 'padrao' ? ` • revisão ${result.base.revision}` : ''}`;
      state.validated = !!result.validated;
      state.reportUrl = result.report_url || '';
      state.pdfUrl = result.pdf_url || '';
      syncSteps();
    } catch (error) {
      el('baseInfo').textContent = `ERRO NA BASE DADOS: ${error.message}`;
    }
  }

  async function logout() {
    if (state.busy) return;
    setBusy(true);
    try {
      await api('/api/auth/logout', {method:'POST'});
      window.location.replace('/');
    } catch (error) {
      setBusy(false);
      showGuidedError(errorGuide(error));
    }
  }

  async function openBaseDialog() {
    if (state.busy) return;
    el('baseDialogInfo').textContent = 'Carregando BASE DADOS...';
    el('baseTableBody').innerHTML = '<tr><td colspan="4">Carregando...</td></tr>';
    el('baseDialog').showModal();
    try {
      const data = await api('/api/base');
      state.baseItems = data.items;
      state.baseEditing = false;
      renderBaseTable(data);
    } catch (error) {
      el('baseTableBody').innerHTML = `<tr><td colspan="4" class="danger">${esc(error.message)}</td></tr>`;
    }
  }

  function renderBaseTable(data = null) {
    if (data) {
      el('baseDialogInfo').textContent = `BASE DADOS ativa: ${data.rows} registros • ${data.origin}${data.revision && data.revision !== 'padrao' ? ` • revisão ${data.revision}` : ''}`;
    }
    const editable = state.baseEditing;
    el('editBaseBtn').hidden = editable;
    el('saveBaseBtn').hidden = !editable;
    el('cancelBaseEditBtn').hidden = !editable;
    el('importBaseBtn').disabled = editable;
    el('baseTableBody').innerHTML = state.baseItems.map((row, index) => {
      const cells = ['supplier_code','supplier','flow','category'].map(field => editable
        ? `<td><input class="base-cell-input" data-row="${index}" data-field="${field}" value="${esc(row[field])}" /></td>`
        : `<td>${esc(row[field])}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
  }

  function collectEditedBase() {
    return state.baseItems.map((row, index) => {
      const updated = {...row};
      document.querySelectorAll(`#baseTableBody [data-row="${index}"]`).forEach(input => {
        updated[input.dataset.field] = input.value.trim();
      });
      return updated;
    });
  }

  async function saveBaseEdits() {
    if (state.busy || !state.baseEditing) return;
    setBusy(true);
    try {
      const items = collectEditedBase();
      const result = await api('/api/base', {
        method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items}),
      });
      state.baseEditing = false;
      await openBaseDialogRefresh();
      invalidateValidation('BASE DADOS alterada e salva com segurança. Os arquivos financeiros protegidos podem ser reprocessados sem novo envio.');
      showMessage('Base atualizada', `As alterações foram validadas e salvas na BASE DADOS persistente (${result.base.rows} registros).`);
    } catch (error) {
      showGuidedError(errorGuide(error, 'base'));
    } finally {
      setBusy(false);
    }
  }

  async function submitBaseImport(uploadId, mode, duplicateAction = 'ask', editedDuplicates = []) {
    const result = await api('/api/base/import', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        upload_id:uploadId,
        mode,
        duplicate_action:duplicateAction,
        edited_duplicates:editedDuplicates,
      }),
    });
    if (result.requires_resolution) {
      state.pendingBaseUploadId = uploadId;
      state.pendingBaseConflicts = result.conflicts || [];
      renderBaseConflicts(result.new_rows || 0);
      el('baseConflictDialog').showModal();
      return false;
    }
    state.pendingBaseUploadId = '';
    state.pendingBaseConflicts = [];
    el('baseInfo').textContent = `BASE DADOS ativa: ${result.base.rows} registros • ${result.base.origin}${result.base.revision && result.base.revision !== 'padrao' ? ` • revisão ${result.base.revision}` : ''}`;
    invalidateValidation('BASE DADOS alterada e salva com segurança. Os arquivos financeiros protegidos podem ser reprocessados sem novo envio.');
    await openBaseDialogRefresh();
    showMessage('Base atualizada', `${result.added} registro(s) adicionado(s), ${result.ignored || 0} semelhante(s) ignorado(s). A Base persistente agora possui ${result.base.rows} registros.`);
    return true;
  }

  function renderBaseConflicts(newRows) {
    el('baseConflictInfo').textContent = `${state.pendingBaseConflicts.length} semelhante(s) encontrado(s); ${newRows} linha(s) realmente nova(s).`;
    el('baseConflictBody').innerHTML = state.pendingBaseConflicts.map(item => {
      const sent = item.uploaded || {};
      const current = item.current || {};
      const currentText = `${current.supplier_code || ''} • ${current.supplier || ''} • ${current.flow || ''} • ${current.category || ''}`;
      const input = (field) => `<input class="base-cell-input" data-conflict-row="${item.row_index}" data-field="${field}" value="${esc(sent[field] || '')}" />`;
      return `<tr><td>${esc(item.reason)}</td><td>${input('supplier_code')}</td><td>${input('supplier')}</td><td>${input('flow')}</td><td>${input('category')}</td><td>${esc(currentText)}</td></tr>`;
    }).join('');
  }

  function collectEditedConflicts() {
    return state.pendingBaseConflicts.map(conflict => {
      const row = {row_index:conflict.row_index};
      document.querySelectorAll(`[data-conflict-row="${conflict.row_index}"]`).forEach(input => { row[input.dataset.field] = input.value.trim(); });
      return row;
    });
  }

  async function importBase(file, mode) {
    let uploadId = '';
    try {
      uploadId = await stageEncryptedFile(file, 'base');
      await submitBaseImport(uploadId, mode);
    } catch (error) {
      if (uploadId) await discardUploads([uploadId]);
      state.pendingBaseUploadId = '';
      showGuidedError(errorGuide(error, 'base'));
    }
  }

  async function openBaseDialogRefresh() {
    try {
      const data = await api('/api/base');
      state.baseItems = data.items;
      state.baseEditing = false;
      renderBaseTable(data);
    } catch (_) {}
  }

  el('pickBtn').addEventListener('click', () => el('fileInput').click());
  el('dropArea').addEventListener('click', () => el('fileInput').click());
  el('fileInput').addEventListener('change', async event => { const files = Array.from(event.target.files || []); event.target.value = ''; await addFiles(files); });
  el('dropArea').addEventListener('dragover', event => { event.preventDefault(); if (!state.busy) el('dropArea').classList.add('dragover'); });
  el('dropArea').addEventListener('dragleave', () => el('dropArea').classList.remove('dragover'));
  el('dropArea').addEventListener('drop', async event => { event.preventDefault(); el('dropArea').classList.remove('dragover'); if (!state.busy) await addFiles(event.dataTransfer.files); });

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
  el('logoutBtn').addEventListener('click', logout);
  el('baseClose').addEventListener('click', () => el('baseDialog').close());
  el('editBaseBtn').addEventListener('click', () => { state.baseEditing = true; renderBaseTable(); });
  el('cancelBaseEditBtn').addEventListener('click', () => { state.baseEditing = false; renderBaseTable(); });
  el('saveBaseBtn').addEventListener('click', saveBaseEdits);
  el('importBaseBtn').addEventListener('click', () => el('baseFileInput').click());
  el('baseFileInput').addEventListener('change', event => {
    const file = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!file) return;
    state.pendingBaseFile = file;
    el('confirmBaseDialog').showModal();
  });
  el('replaceBaseBtn').addEventListener('click', () => {
    el('confirmBaseDialog').close();
    const file = state.pendingBaseFile;
    state.pendingBaseFile = null;
    if (file) importBase(file, 'replace');
  });
  el('appendBaseBtn').addEventListener('click', () => {
    el('confirmBaseDialog').close();
    const file = state.pendingBaseFile;
    state.pendingBaseFile = null;
    if (file) importBase(file, 'append');
  });
  el('confirmBaseDialog').addEventListener('close', () => { if (el('confirmBaseDialog').returnValue === 'cancel') state.pendingBaseFile = null; });
  el('ignoreBaseConflictsBtn').addEventListener('click', async () => {
    if (!state.pendingBaseUploadId) return;
    try {
      const done = await submitBaseImport(state.pendingBaseUploadId, 'append', 'ignore');
      if (done) el('baseConflictDialog').close();
    } catch (error) { showGuidedError(errorGuide(error, 'base')); }
  });
  el('saveEditedConflictsBtn').addEventListener('click', async () => {
    if (!state.pendingBaseUploadId) return;
    try {
      const done = await submitBaseImport(state.pendingBaseUploadId, 'append', 'edit', collectEditedConflicts());
      if (done) el('baseConflictDialog').close();
    } catch (error) { showGuidedError(errorGuide(error, 'base')); }
  });
  async function cancelBaseConflicts() {
    const uploadId = state.pendingBaseUploadId;
    state.pendingBaseUploadId = '';
    state.pendingBaseConflicts = [];
    if (uploadId) await discardUploads([uploadId]);
    el('baseConflictDialog').close();
  }
  el('baseConflictClose').addEventListener('click', cancelBaseConflicts);
  el('cancelBaseConflictsBtn').addEventListener('click', cancelBaseConflicts);

  renderFiles();
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  loadState();
})();
