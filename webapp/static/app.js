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
    baseTableController: null,
    security: null,
    serverPublicKey: null,
  };
  const spinnerFrames = ['◜','◝','◞','◟'];
  const actionFeedback = window.ActionFeedback.create();

  function esc(value) {
    return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function fileKey(file, index) {
    return `${index}|${file.name}|${file.size}|${file.lastModified}`;
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
    const baseHealth = summary.base_health || null;
    const baseNeedsAttention = baseHealth?.status === 'attention';
    const notes = Array.isArray(summary.notes) ? summary.notes : [];
    const warnings = Array.isArray(summary.warnings) ? summary.warnings : [];
    const autoAdded = Number(baseHealth?.auto_added_suppliers || 0);
    const count = value => (Number(value) || 0).toLocaleString('pt-BR');
    const sectionTitle = (number, title) => `<div class="analysis-group-title"><span aria-hidden="true">${number}</span><h4>${title}</h4></div>`;

    let html = '<div class="analysis-summary">';
    html += `<section class="analysis-group analysis-found">${sectionTitle(1, 'O que foi encontrado')}<div class="analysis-facts">`;
    html += `<div class="analysis-fact"><span>PREVISTO</span><strong>${count(summary.previsto)} registro(s)</strong><small>Encontrado(s) em ${count(summary.previsto_tables)} tabela(s).</small></div>`;
    html += `<div class="analysis-fact"><span>REALIZADO</span><strong>${count(summary.realizado)} registro(s)</strong><small>Encontrado(s) em ${count(summary.realizado_tables)} tabela(s).</small></div>`;
    html += `<div class="analysis-fact"><span>BASE DE DADOS</span><strong>${count(summary.base)} registro(s)</strong><small>${autoAdded ? `${count(autoAdded)} fornecedor(es) novo(s) complementado(s) com dados completos da planilha.` : 'Base utilizada para conferir as classificações.'}</small></div>`;
    html += `<div class="analysis-fact"><span>PERÍODO</span><strong>${esc(summary.period)}</strong><small>Período identificado nos arquivos validados.</small></div></div></section>`;

    html += `<section class="analysis-group analysis-correct">${sectionTitle(2, 'O que está correto')}<ul class="analysis-check-list">`;
    html += '<li>Os arquivos foram lidos e a validação terminou sem modificar os documentos originais.</li>';
    if (baseHealth?.status === 'ok') html += `<li>${esc(baseHealth.message)}</li>`;
    if (!warnings.length) html += '<li>Nenhum aviso de consistência foi identificado nesta validação.</li>';
    html += '</ul></section>';

    html += `<section class="analysis-group analysis-attention">${sectionTitle(3, 'O que precisa de atenção')}`;
    if (baseNeedsAttention) {
      const names = (baseHealth.suppliers || []).map(esc).join(', ');
      html += `<div class="analysis-alert"><strong>Algumas classificações continuam incompletas.</strong><p>${esc(baseHealth.message)}</p>${names ? `<p><b>Fornecedores que precisam ser conferidos:</b> ${names}</p>` : ''}</div>`;
    }
    if (warnings.length) {
      html += '<ul class="analysis-attention-list">';
      html += warnings.map(warning => `<li><strong>${esc(warning.title)}</strong><span>${esc(warning.summary)}</span></li>`).join('');
      html += '</ul>';
    }
    if (!baseNeedsAttention && !warnings.length) html += '<p class="analysis-no-attention">Nenhum ponto de atenção foi indicado.</p>';
    html += '</section>';

    html += `<section class="analysis-group analysis-meaning">${sectionTitle(4, 'O que isso significa')}<p>Os dados reconhecidos acima estão prontos para compor o relatório. Informações ausentes ou ambíguas não são preenchidas automaticamente.</p>`;
    if (notes.length) {
      html += '<div class="analysis-reading-notes"><b>Observações sobre a leitura dos arquivos:</b><ul>';
      html += notes.map(note => `<li>${esc(note)}</li>`).join('');
      html += '</ul></div>';
    } else {
      html += '<p class="analysis-muted">Não houve observações adicionais sobre a leitura.</p>';
    }
    html += '</section>';

    html += `<section class="analysis-group analysis-next">${sectionTitle(5, 'O que o usuário deve fazer')}<ol class="analysis-action-list">`;
    html += '<li>Confira se as quantidades e o período encontrados correspondem aos arquivos enviados.</li>';
    if (baseNeedsAttention) html += '<li>Complete na planilha os campos Cód Fornecedor, Fornecedor, Fluxo JMM e Categoria indicados acima e valide o arquivo novamente.</li>';
    if (warnings.length) html += '<li>Leia os pontos de atenção. Se algum deles indicar uma informação ausente ou incorreta, corrija o arquivo de origem e valide novamente.</li>';
    html += `<li>${baseNeedsAttention || warnings.length ? 'Se os avisos forem esperados e os dados encontrados estiverem corretos, clique em Gerar relatório.' : 'Se estiver tudo correto, clique em Gerar relatório.'}</li>`;
    html += '</ol></section></div>';
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
    el('baseTableBody').innerHTML = '<tr><td colspan="5">Carregando...</td></tr>';
    el('baseDialog').showModal();
    try {
      const data = await api('/api/base');
      state.baseItems = data.items;
      state.baseEditing = false;
      renderBaseTable(data);
    } catch (error) {
      el('baseTableBody').innerHTML = `<tr><td colspan="5" class="danger">${esc(error.message)}</td></tr>`;
    }
  }

  function syncBaseEditing(editable) {
    state.baseEditing = editable;
    el('editBaseBtn').hidden = editable;
    el('saveBaseBtn').hidden = !editable;
    el('cancelBaseEditBtn').hidden = !editable;
    el('importBaseBtn').disabled = editable;
  }

  function getBaseTableController() {
    if (!state.baseTableController) {
      state.baseTableController = window.BaseTableComponent.create({
        body: el('baseTableBody'),
        filterInputs: document.querySelectorAll('#baseDialog [data-base-column-filter]'),
        status: el('baseTableStatus'),
        selectPage: el('baseSelectPage'),
        previous: el('basePreviousPage'),
        next: el('baseNextPage'),
        add: el('addBaseRowBtn'),
        remove: el('removeBaseRowsBtn'),
        inputClass: 'base-cell-input',
        checkboxClass: 'base-row-check',
        columns: 5,
        pageSize: 200,
        showError: message => actionFeedback.error(message, 'base-editor'),
        onEditingChange: syncBaseEditing,
      });
    }
    return state.baseTableController;
  }

  function renderBaseTable(data = null) {
    if (data) {
      el('baseDialogInfo').textContent = `BASE DADOS ativa: ${data.rows} registros • ${data.origin}${data.revision && data.revision !== 'padrao' ? ` • revisão ${data.revision}` : ''}`;
    }
    getBaseTableController().load(state.baseItems);
  }

  function collectEditedBase() {
    return getBaseTableController().getItems();
  }

  async function saveBaseEdits() {
    if (state.busy || !state.baseEditing) return;
    actionFeedback.started('Salvando as alterações da Base de Dados...', 'base-save');
    setBusy(true);
    try {
      const items = collectEditedBase();
      const result = await api('/api/base', {
        method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({items}),
      });
      state.baseEditing = false;
      await openBaseDialogRefresh();
      invalidateValidation('BASE DADOS alterada e salva com segurança. Os arquivos financeiros protegidos podem ser reprocessados sem novo envio.');
      actionFeedback.success(`Alterações salvas. A Base de Dados agora possui ${result.base.rows} registros.`, 'base-save');
    } catch (error) {
      actionFeedback.error('Não foi possível salvar as alterações da Base de Dados.', 'base-save');
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
      actionFeedback.noChange('A importação aguarda sua escolha sobre os registros semelhantes. Nenhuma alteração foi feita ainda.', 'base-import');
      return false;
    }
    state.pendingBaseUploadId = '';
    state.pendingBaseConflicts = [];
    el('baseInfo').textContent = `BASE DADOS ativa: ${result.base.rows} registros • ${result.base.origin}${result.base.revision && result.base.revision !== 'padrao' ? ` • revisão ${result.base.revision}` : ''}`;
    invalidateValidation('BASE DADOS alterada e salva com segurança. Os arquivos financeiros protegidos podem ser reprocessados sem novo envio.');
    await openBaseDialogRefresh();
    if (Number(result.added) > 0) {
      actionFeedback.success(`Arquivo importado com sucesso. ${result.added} registro(s) adicionado(s) e ${result.ignored || 0} semelhante(s) ignorado(s).`, 'base-import');
    } else {
      actionFeedback.noChange(`Nenhum novo registro precisava ser adicionado. ${result.ignored || 0} semelhante(s) foram mantidos sem alteração.`, 'base-import');
    }
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
    actionFeedback.started('Protegendo e importando a nova Base de Dados...', 'base-import');
    try {
      uploadId = await stageEncryptedFile(file, 'base');
      await submitBaseImport(uploadId, mode);
    } catch (error) {
      if (uploadId) await discardUploads([uploadId]);
      state.pendingBaseUploadId = '';
      actionFeedback.error('Não foi possível importar a Base de Dados.', 'base-import');
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
  el('editBaseBtn').addEventListener('click', () => getBaseTableController().startEditing());
  el('cancelBaseEditBtn').addEventListener('click', () => getBaseTableController().cancelEditing());
  el('saveBaseBtn').addEventListener('click', saveBaseEdits);
  el('exportBaseBtn').addEventListener('click', () => actionFeedback.info('Download da Base de Dados solicitado ao navegador.', 'base-export'));
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
    actionFeedback.started('Concluindo a importação da Base de Dados...', 'base-import');
    try {
      const done = await submitBaseImport(state.pendingBaseUploadId, 'append', 'ignore');
      if (done) el('baseConflictDialog').close();
    } catch (error) {
      actionFeedback.error('Não foi possível concluir a importação da Base de Dados.', 'base-import');
      showGuidedError(errorGuide(error, 'base'));
    }
  });
  el('saveEditedConflictsBtn').addEventListener('click', async () => {
    if (!state.pendingBaseUploadId) return;
    actionFeedback.started('Validando as linhas editadas e concluindo a importação...', 'base-import');
    try {
      const done = await submitBaseImport(state.pendingBaseUploadId, 'append', 'edit', collectEditedConflicts());
      if (done) el('baseConflictDialog').close();
    } catch (error) {
      actionFeedback.error('Não foi possível concluir a importação da Base de Dados.', 'base-import');
      showGuidedError(errorGuide(error, 'base'));
    }
  });
  async function cancelBaseConflicts() {
    const uploadId = state.pendingBaseUploadId;
    state.pendingBaseUploadId = '';
    state.pendingBaseConflicts = [];
    if (uploadId) await discardUploads([uploadId]);
    el('baseConflictDialog').close();
    actionFeedback.noChange('Importação cancelada. Nenhuma alteração foi feita.', 'base-import');
  }
  el('baseConflictClose').addEventListener('click', cancelBaseConflicts);
  el('cancelBaseConflictsBtn').addEventListener('click', cancelBaseConflicts);

  renderFiles();
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  loadState();
})();
