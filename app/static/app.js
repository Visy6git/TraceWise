const $ = id => document.getElementById(id);

const state = {
  tenants: [],
  tenantId: 'demo-tenant',
  tenantName: 'Demo tenant',
  health: null,
  templates: [],
  selectedTemplateType: 'generic',
  docxFiles: [],
  excelFiles: [],
  templateRunId: null,
  generatorRunId: null,
  templateRunPaused: false,
  generatorRunPaused: false,
  activeTemplate: null,
  workingSchema: null,
  unsavedChanges: false,
  inspectedTableIndex: 0,
  approvedTemplates: [],
  historyFilter: 'all',
  topicFilter: 'all',
  generatorResult: null,
  sourceFileStates: {},
  sourceFileOrder: [],
  templateEvents: null,
  generatorEvents: null,
  templatePollTimer: null,
  generatorPollTimer: null,
  generated: null,
  currentArtifactRaw: ''
};

const ROLE_LABELS = {
  case_id: ['Case identifier', 'Case/ICSR number used as the counting key'],
  event_term: ['Event term / MedDRA PT', 'Event preferred term or equivalent field'],
  source_category: ['Primary source category', 'Spontaneous versus other-study source grouping'],
  initial_flag: ['Initial / follow-up flag', 'Filter to initial records when available'],
  approval_date: ['Initial approval / receipt date', 'Reporting-period date filter'],
  seriousness: ['Seriousness', 'Optional serious/non-serious information'],
  fatal_outcome: ['Fatal outcome', 'Optional fatal/death information'],
  denominator_case_id: ['Separate denominator case ID', 'Optional case cohort in another workbook/sheet; used for distinct-case denominator'],
  denominator_initial_flag: ['Denominator initial/follow-up flag', 'Initial-only filter in the separate denominator source'],
  denominator_approval_date: ['Denominator reporting date', 'Reporting interval date in the separate denominator source']
};

/* ==================== UTILITIES ==================== */
function toast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.remove('show'), 3200);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function fmtSize(b) {
  return b < 1024 * 1024 ? `${Math.max(1, Math.round(b / 1024))} KB` : `${(b / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return String(iso).slice(0, 10);
  }
}

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let message = await r.text();
    try { message = JSON.parse(message).detail || message; } catch {}
    throw new Error(message || `Request failed (${r.status})`);
  }
  const type = r.headers.get('content-type') || '';
  return type.includes('application/json') ? r.json() : r;
}

function fdFrom(fields, files, fieldName) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v ?? ''));
  files.forEach(f => fd.append(fieldName, f));
  return fd;
}

/* Lightweight safe Markdown -> HTML renderer for master.md & source dictionaries */
function renderMarkdown(md) {
  const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
  let html = '';
  let inUl = false;
  let inOl = false;

  const inline = txt => esc(txt)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');

  const closeLists = () => {
    if (inUl) { html += '</ul>'; inUl = false; }
    if (inOl) { html += '</ol>'; inOl = false; }
  };

  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      closeLists();
      i++;
      continue;
    }
    // Markdown tables: | col1 | col2 | followed by |---|---|
    if (trimmed.startsWith('|') && i + 1 < lines.length && /^\|[\s:-]+\|/.test(lines[i + 1].trim())) {
      closeLists();
      const splitRow = r => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
      const headers = splitRow(trimmed);
      i += 2; // skip header + separator
      const bodyRows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        bodyRows.push(splitRow(lines[i]));
        i++;
      }
      html += `<div class="md-table-wrap"><table><thead><tr>${headers.map(h => `<th>${inline(h)}</th>`).join('')}</tr></thead><tbody>${bodyRows.map(r => `<tr>${headers.map((_, ci) => `<td>${inline(r[ci] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
      continue;
    }
    if (/^###\s+/.test(trimmed)) {
      closeLists();
      html += `<h3>${inline(trimmed.replace(/^###\s+/, ''))}</h3>`;
    } else if (/^##\s+/.test(trimmed)) {
      closeLists();
      html += `<h2>${inline(trimmed.replace(/^##\s+/, ''))}</h2>`;
    } else if (/^#\s+/.test(trimmed)) {
      closeLists();
      html += `<h1>${inline(trimmed.replace(/^#\s+/, ''))}</h1>`;
    } else if (/^>\s*/.test(trimmed)) {
      closeLists();
      html += `<blockquote>${inline(trimmed.replace(/^>\s*/, ''))}</blockquote>`;
    } else if (/^[-*]\s+/.test(trimmed)) {
      if (inOl) { html += '</ol>'; inOl = false; }
      if (!inUl) { html += '<ul>'; inUl = true; }
      html += `<li>${inline(trimmed.replace(/^[-*]\s+/, ''))}</li>`;
    } else if (/^\d+\.\s+/.test(trimmed)) {
      if (inUl) { html += '</ul>'; inUl = false; }
      if (!inOl) { html += '<ol>'; inOl = true; }
      html += `<li>${inline(trimmed.replace(/^\d+\.\s+/, ''))}</li>`;
    } else {
      closeLists();
      html += `<p>${inline(trimmed)}</p>`;
    }
    i++;
  }
  closeLists();
  return html || '<p style="color:var(--muted)">No markdown content yet.</p>';
}

/* ==================== HEALTH / LLM ENGINE STATUS ==================== */
async function loadHealth() {
  try {
    const h = await api('/api/health');
    state.health = h;
    const llmReady = Boolean(h.llm_enabled);
    const provider = h.llm_provider || 'none';
    const modelId = h.llm_model_id || '';
    $('llmDot').classList.toggle('llm-active', llmReady);
    if (llmReady && provider === 'lmstudio') {
      $('sidebarLlmStatus').textContent = 'LM STUDIO ACTIVE';
      $('sidebarLlmDetail').textContent = modelId || h.lmstudio_base_url || 'Local LM Studio';
      $('engineStatusText').textContent = `LM Studio · ${modelId || 'local'}`;
    } else if (llmReady && provider === 'bedrock') {
      $('sidebarLlmStatus').textContent = 'BEDROCK LLM ACTIVE';
      $('sidebarLlmDetail').textContent = modelId || `Region: ${h.region || 'configured'}`;
      $('engineStatusText').textContent = 'Bedrock LLM';
    } else {
      $('sidebarLlmStatus').textContent = 'NO LLM ACTIVE';
      $('sidebarLlmDetail').textContent = 'Configure LM Studio or Bedrock in .env';
      $('engineStatusText').textContent = 'LLM Not Configured';
    }
  } catch (e) {
    $('sidebarLlmStatus').textContent = 'STATUS UNAVAILABLE';
  }
}

function openSystemStatusModal() {
  const h = state.health || {};
  const llmReady = Boolean(h.llm_enabled);
  const provider = h.llm_provider || 'none';
  $('systemStatusDetails').innerHTML = `
    <div class="status-kv"><small>API STATUS</small><b>${esc((h.status || 'ok').toUpperCase())}</b></div>
    <div class="status-kv"><small>ACTIVE PROVIDER</small><b>${esc(provider.toUpperCase())}</b></div>
    <div class="status-kv"><small>ACTIVE MODEL</small><b>${esc(h.llm_model_id || 'Not configured')}</b></div>
    <div class="status-kv"><small>LM STUDIO URL</small><b>${esc(h.lmstudio_base_url || '—')}</b></div>
    <div class="status-kv" style="grid-column:1/-1"><small>PROTOCOL &amp; MODE</small><b>${llmReady ? `AG-UI structured agents active via ${provider === 'lmstudio' ? 'LM Studio' : 'AWS Bedrock'}` : 'Enable LMSTUDIO_ENABLED=true or BEDROCK_ENABLED=true in .env'}</b></div>
  `;
  $('systemStatusModal').classList.remove('hidden');
}

/* ==================== FILE UPLOAD & REORDER ==================== */
function renderDocxFiles() {
  const host = $('docxFiles');
  if (!state.docxFiles.length) {
    host.innerHTML = '<div class="empty-row">No reference reports selected yet</div>';
  } else {
    host.innerHTML = state.docxFiles.map((f, i) => `
      <div class="file-pill">
        <span class="file-ext">DOCX</span>
        ${i === 0 ? '<span class="base-tag">BASE DOC</span>' : `<span class="ref-tag">REF ${i + 1}</span>`}
        <span class="file-name" title="${esc(f.name)}">${esc(f.name)}</span>
        <small>${fmtSize(f.size)}</small>
        ${i > 0 ? `<button class="file-reorder-btn" data-move-up="${i}" title="Move up (make base document)">↑</button>` : ''}
        <button class="file-remove" data-remove-docx="${i}" title="Remove file">×</button>
      </div>
    `).join('');
    host.querySelectorAll('[data-remove-docx]').forEach(b =>
      b.addEventListener('click', () => { state.docxFiles.splice(Number(b.dataset.removeDocx), 1); renderDocxFiles(); })
    );
    host.querySelectorAll('[data-move-up]').forEach(b =>
      b.addEventListener('click', () => {
        const idx = Number(b.dataset.moveUp);
        if (idx > 0) {
          [state.docxFiles[idx - 1], state.docxFiles[idx]] = [state.docxFiles[idx], state.docxFiles[idx - 1]];
          renderDocxFiles();
        }
      })
    );
  }
  $('analyzeTemplateBtn').disabled = !state.docxFiles.length;
}

function renderExcelFiles() {
  const host = $('excelFiles');
  if (!state.excelFiles.length) {
    host.innerHTML = '<div class="empty-row">No Excel source files selected</div>';
  } else {
    host.innerHTML = state.excelFiles.map((f, i) => `
      <div class="file-pill">
        <span class="file-ext xlsx-ext">${esc((f.name.split('.').pop() || 'XLSX').toUpperCase())}</span>
        <span class="file-name" title="${esc(f.name)}">${esc(f.name)}</span>
        <small>${fmtSize(f.size)}</small>
        <button class="file-remove" data-remove-excel="${i}" title="Remove file">×</button>
      </div>
    `).join('');
    host.querySelectorAll('[data-remove-excel]').forEach(b =>
      b.addEventListener('click', () => { state.excelFiles.splice(Number(b.dataset.removeExcel), 1); renderExcelFiles(); })
    );
  }
  updateGeneratorStart();
}

function addDrop(id, fn) {
  const el = $(id);
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('dragover'); });
  el.addEventListener('dragleave', () => el.classList.remove('dragover'));
  el.addEventListener('drop', e => {
    e.preventDefault();
    el.classList.remove('dragover');
    fn(Array.from(e.dataTransfer.files));
  });
}

addDrop('docxDrop', files => {
  const valid = files.filter(x => x.name.toLowerCase().endsWith('.docx'));
  if (valid.length < files.length) toast('Only .docx files are accepted for Template Generator');
  state.docxFiles.push(...valid);
  renderDocxFiles();
});

addDrop('excelDrop', files => {
  const valid = files.filter(x => /\.xlsx?$/.test(x.name.toLowerCase()));
  if (valid.length < files.length) toast('Only .xlsx or .xls workbooks are accepted');
  state.excelFiles.push(...valid);
  renderExcelFiles();
});

$('docxInput').addEventListener('change', e => {
  state.docxFiles.push(...Array.from(e.target.files));
  e.target.value = '';
  renderDocxFiles();
});

$('excelInput').addEventListener('change', e => {
  state.excelFiles.push(...Array.from(e.target.files));
  e.target.value = '';
  renderExcelFiles();
});

/* ==================== MODAL MANAGEMENT ==================== */
function openModal(id) { $(id).classList.remove('hidden'); }
function closeModal(id) { $(id).classList.add('hidden'); }
function closeAllModals() {
  document.querySelectorAll('.modal').forEach(m => m.classList.add('hidden'));
}

function isProductTemplate(obj) {
  const t = obj?.template_type || obj?.schema?.template_type || 'generic';
  return String(t).toLowerCase() === 'product';
}

function setSelectedTemplateType(type) {
  const norm = String(type || 'generic').toLowerCase() === 'product' ? 'product' : 'generic';
  state.selectedTemplateType = norm;
  document.querySelectorAll('#templateTypeGrid [data-template-type]').forEach(btn => {
    const active = btn.dataset.templateType === norm;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-checked', active ? 'true' : 'false');
  });
  const strip = $('uploadNoteStrip');
  const note = $('uploadNoteText');
  if (strip && note) {
    strip.classList.toggle('is-product-note', norm === 'product');
    note.textContent = norm === 'product'
      ? 'Product Template mode: Section 16.3 safety topic titles and MedDRA Search Criteria (PTs, HLTs, SMQs) are carried forward verbatim. Prior-period numeric counts and Evaluation/Conclusion narratives still become generic placeholders. Approved Product Templates are highlighted in blue.'
      : 'Generic Template mode: Only Section 16.3 table structure and conventions are inspected. All values including Search Criteria become generic placeholders; prior-period numbers and narratives are never carried forward.';
  }
  const btn = $('analyzeTemplateBtn');
  if (btn) {
    btn.innerHTML = norm === 'product'
      ? 'Build product template <span>→</span>'
      : 'Build table template <span>→</span>';
  }
}

document.querySelectorAll('#templateTypeGrid [data-template-type]').forEach(btn => {
  btn.addEventListener('click', () => setSelectedTemplateType(btn.dataset.templateType));
});

$('openUploadModalBtn').addEventListener('click', () => {
  updateTenantDisplay();
  setSelectedTemplateType(state.selectedTemplateType || 'generic');
  openModal('uploadTemplateModal');
  $('templateRunName').focus();
});
$('emptyUploadBtn').addEventListener('click', () => {
  updateTenantDisplay();
  setSelectedTemplateType(state.selectedTemplateType || 'generic');
  openModal('uploadTemplateModal');
});
$('emptyBrowseHistoryBtn').addEventListener('click', () => showSubtab('templateHistory'));
$('closeUploadModal').addEventListener('click', () => closeModal('uploadTemplateModal'));
$('cancelUploadBtn').addEventListener('click', () => closeModal('uploadTemplateModal'));

function openGeneratorUploadModal(preselectTemplateId = '') {
  openModal('generatorUploadModal');
  if (preselectTemplateId) {
    $('generatorTemplateSelect').value = preselectTemplateId;
    checkSelectedTemplateInterval(preselectTemplateId);
  }
  updateGeneratorStart();
  $('generatorRunName').focus();
}

$('openGeneratorModalBtn').addEventListener('click', () => openGeneratorUploadModal());
$('emptyStartGenBtn').addEventListener('click', () => openGeneratorUploadModal());
$('closeGeneratorModal').addEventListener('click', () => closeModal('generatorUploadModal'));
$('cancelGeneratorModalBtn').addEventListener('click', () => closeModal('generatorUploadModal'));

$('templatePauseBtn')?.addEventListener('click', async () => {
  if (!state.templateRunId) return;
  const isPaused = state.templateRunPaused;
  const action = isPaused ? 'resume' : 'pause';
  try {
    const res = await api(`/api/template-runs/${state.templateRunId}/${action}`, { method: 'POST' });
    setTemplatePausedState(res.status === 'paused');
    toast(res.status === 'paused' ? 'Template learning paused' : 'Template learning resumed');
  } catch (e) {
    toast(e.message || `Failed to ${action} template run`);
  }
});

$('generatorPauseBtn')?.addEventListener('click', async () => {
  if (!state.generatorRunId) return;
  const isPaused = state.generatorRunPaused;
  const action = isPaused ? 'resume' : 'pause';
  try {
    const res = await api(`/api/generator-runs/${state.generatorRunId}/${action}`, { method: 'POST' });
    setGeneratorPausedState(res.status === 'paused');
    toast(res.status === 'paused' ? 'Generation run paused' : 'Generation run resumed');
  } catch (e) {
    toast(e.message || `Failed to ${action} generation run`);
  }
});

$('closeTableDetailModal').addEventListener('click', () => closeModal('tableDetailModal'));
$('tableDetailPrevBtn').addEventListener('click', () => {
  const total = getMergedBlueprintTables(state.workingSchema).length;
  if (total && state.inspectedTableIndex > 0) openTableDetailModal(state.inspectedTableIndex - 1);
});
$('tableDetailNextBtn').addEventListener('click', () => {
  const total = getMergedBlueprintTables(state.workingSchema).length;
  if (total && state.inspectedTableIndex < total - 1) openTableDetailModal(state.inspectedTableIndex + 1);
});

$('addTenantBtn').addEventListener('click', () => { openModal('tenantModal'); $('newTenantId').focus(); });
$('closeTenantModal').addEventListener('click', () => closeModal('tenantModal'));
$('helpBtn').addEventListener('click', () => openModal('helpModal'));
$('closeHelpModal').addEventListener('click', () => closeModal('helpModal'));
$('closeArtifactModal').addEventListener('click', () => closeModal('artifactModal'));
$('closeSystemStatusModal').addEventListener('click', () => closeModal('systemStatusModal'));
$('engineStatusBadge').addEventListener('click', openSystemStatusModal);
$('sidebarEngineBtn').addEventListener('click', openSystemStatusModal);

// Backdrop click & Escape to close modals
document.querySelectorAll('.modal').forEach(modal => {
  modal.addEventListener('click', e => {
    if (e.target === modal) modal.classList.add('hidden');
  });
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeAllModals();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    const onTemplates = $('templatesPage').classList.contains('active');
    if (onTemplates && state.activeTemplate && state.activeTemplate.status !== 'approved') {
      e.preventDefault();
      saveTemplateEdits();
    }
  }
});

/* ==================== NAVIGATION ==================== */
function showTab(tab) {
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $('templatesPage').classList.toggle('active', tab === 'templates');
  $('generatorPage').classList.toggle('active', tab === 'generator');
  $('breadcrumbCurrent').textContent = tab === 'templates' ? 'Template Generator' : 'Generator';
  if (tab === 'generator') refreshApprovedTemplates();
}

document.querySelectorAll('.nav-item').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

function showSubtab(id) {
  document.querySelectorAll('.subnav-item').forEach(b => b.classList.toggle('active', b.dataset.subtab === id));
  document.querySelectorAll('.subpage').forEach(p => p.classList.toggle('active', p.id === id));
  if (id === 'templateHistory') loadTemplateHistory();
}

document.querySelectorAll('.subnav-item').forEach(b => b.addEventListener('click', () => showSubtab(b.dataset.subtab)));

/* ==================== TENANTS ==================== */
async function loadTenants() {
  const data = await api('/api/tenants');
  state.tenants = data.tenants || [];
  $('tenantSelect').innerHTML = state.tenants.map(t =>
    `<option value="${esc(t.tenant_id)}">${esc(t.display_name)}</option>`
  ).join('');
  const selected = state.tenants.find(t => t.tenant_id === state.tenantId) || state.tenants[0];
  if (selected) {
    state.tenantId = selected.tenant_id;
    state.tenantName = selected.display_name;
    $('tenantSelect').value = selected.tenant_id;
  }
  updateTenantDisplay();
}

function updateTenantDisplay() {
  $('templateTenantLabel').textContent = state.tenantName;
  $('topbarTenantName').textContent = state.tenantName;
}

$('tenantSelect').addEventListener('change', async e => {
  const t = state.tenants.find(x => x.tenant_id === e.target.value);
  if (!t) return;
  state.tenantId = t.tenant_id;
  state.tenantName = t.display_name;
  state.activeTemplate = null;
  state.workingSchema = null;
  state.generatorRunId = null;
  state.generatorResult = null;
  $('generatorWorkspace').classList.add('hidden');
  $('generatorReadySection').classList.remove('hidden');
  $('kpiGenWorkbooks').textContent = '0';
  $('kpiGenMappedRoles').textContent = '0 / 10';
  $('kpiGenCandidates').textContent = '0';
  setUnsaved(false);
  updateTenantDisplay();
  await loadTemplateHistory(true);
  await refreshApprovedTemplates();
});

$('createTenantBtn').addEventListener('click', async () => {
  try {
    const t = await api('/api/tenants', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: $('newTenantId').value,
        display_name: $('newTenantName').value
      })
    });
    closeModal('tenantModal');
    $('newTenantId').value = '';
    $('newTenantName').value = '';
    await loadTenants();
    $('tenantSelect').value = t.tenant_id;
    state.tenantId = t.tenant_id;
    state.tenantName = t.display_name;
    state.activeTemplate = null;
    updateTenantDisplay();
    await loadTemplateHistory(true);
    await refreshApprovedTemplates();
    toast('Tenant workspace created');
  } catch (e) {
    toast(e.message);
  }
});

/* ==================== TEMPLATE GENERATOR WORKFLOW ==================== */
function setUnsaved(flag) {
  state.unsavedChanges = flag;
  $('unsavedBadge').classList.toggle('hidden', !flag);
}

function getMergedBlueprintTables(schema) {
  const raw = schema?.base_tables || [];
  const merged = [];
  const byId = new Map();
  let lastParent = null;

  for (const t of raw) {
    const isCont = Boolean(t.continuation_of_previous);
    const parent = isCont ? (byId.get(t.parent_topic_table_id) || lastParent) : null;

    if (isCont && parent) {
      // Fold continuation rows & fields directly into the original table instead of forming a new table
      parent.row_count = Number(parent.row_count || 0) + Number(t.row_count || 0);
      parent.column_count = Math.max(Number(parent.column_count || 0), Number(t.column_count || 0));
      parent.merged_table_ids.push(t.table_id);
      if (t.docx_table_index !== undefined && t.docx_table_index !== null) {
        parent.merged_docx_indices.push(t.docx_table_index);
      }

      const existingKeys = new Set((parent.fields || []).map(f => f.key));
      for (const f of (t.fields || [])) {
        if (!existingKeys.has(f.key)) {
          parent.fields.push(structuredClone(f));
          existingKeys.add(f.key);
        }
      }

      const existingPreviewKeys = new Set((parent.generic_preview || []).map(g => g.key));
      for (const g of (t.generic_preview || [])) {
        if (!existingPreviewKeys.has(g.key)) {
          parent.generic_preview.push(structuredClone(g));
          existingPreviewKeys.add(g.key);
        }
      }
      continue;
    }

    const copy = structuredClone(t);
    copy.continuation_of_previous = false;
    copy.fields = Array.isArray(copy.fields) ? copy.fields : [];
    copy.generic_preview = Array.isArray(copy.generic_preview) ? copy.generic_preview : [];
    copy.merged_table_ids = [t.table_id];
    copy.merged_docx_indices = t.docx_table_index !== undefined && t.docx_table_index !== null ? [t.docx_table_index] : [];
    merged.push(copy);
    if (t.table_id) byId.set(t.table_id, copy);
    lastParent = copy;
  }

  return merged;
}

function getMergedTopicMetrics(metrics) {
  const merged = [];
  let lastParent = null;

  for (const m of (metrics || [])) {
    if (m.continuation && lastParent) {
      lastParent.linked_table_ids.push(m.table_id);
      continue;
    }
    const copy = structuredClone(m);
    copy.linked_table_ids = [m.table_id];
    merged.push(copy);
    lastParent = copy;
  }
  return merged;
}

function updateKpiStrip() {
  const items = state.templates || [];
  const approved = items.filter(t => t.status === 'approved').length;
  const drafts = items.filter(t => t.status === 'draft').length;
  const activeSchema = state.workingSchema || state.activeTemplate?.schema;
  const activeTables = activeSchema ? getMergedBlueprintTables(activeSchema).length : 0;

  $('kpiTotalTemplates').textContent = items.length;
  $('kpiApprovedTemplates').textContent = approved;
  $('kpiDraftTemplates').textContent = drafts;
  $('kpiActiveTables').textContent = activeTables;
}

function showStudioWorkspace(show) {
  $('studioEmptyState').classList.toggle('hidden', show);
  $('templateWorkspace').classList.toggle('hidden', !show);
}

function setTemplatePausedState(isPaused) {
  state.templateRunPaused = Boolean(isPaused);
  const btn = $('templatePauseBtn');
  if (btn) {
    btn.classList.toggle('is-paused', isPaused);
    const icon = btn.querySelector('.pause-icon');
    const label = btn.querySelector('.pause-label');
    if (icon) icon.textContent = isPaused ? '▶' : '⏸';
    if (label) label.textContent = isPaused ? 'Resume' : 'Pause';
    btn.title = isPaused ? 'Resume template learning' : 'Pause template learning';
  }
  const statusPill = $('templateStatus');
  if (statusPill) {
    if (isPaused) {
      statusPill.className = 'status-pill paused';
      statusPill.innerHTML = '<i></i> PAUSED';
    } else {
      const isProduct = isProductTemplate(state.workingSchema);
      statusPill.className = 'status-pill running';
      statusPill.innerHTML = isProduct ? '<i></i> Learning product blueprint' : '<i></i> Learning blueprint';
    }
  }
  const strip = $('templateProgressStrip');
  if (strip) {
    strip.querySelector('.live-dot')?.classList.toggle('paused', isPaused);
    $('templateProgressFill')?.classList.toggle('paused', isPaused);
    if (isPaused) {
      $('templateLiveMessage').textContent = 'Run paused — click Resume to continue';
    }
  }
}

function setGeneratorPausedState(isPaused) {
  state.generatorRunPaused = Boolean(isPaused);
  const btn = $('generatorPauseBtn');
  if (btn) {
    btn.classList.toggle('is-paused', isPaused);
    const icon = btn.querySelector('.pause-icon');
    const label = btn.querySelector('.pause-label');
    if (icon) icon.textContent = isPaused ? '▶' : '⏸';
    if (label) label.textContent = isPaused ? 'Resume' : 'Pause';
    btn.title = isPaused ? 'Resume generation run' : 'Pause generation run';
  }
  const statusPill = $('generatorStatus');
  if (statusPill) {
    if (isPaused) {
      statusPill.className = 'status-pill paused';
      statusPill.innerHTML = '<i></i> PAUSED';
    } else {
      statusPill.className = 'status-pill running';
      statusPill.innerHTML = '<i></i> Agents working';
    }
  }
  const strip = $('generatorProgressStrip');
  if (strip) {
    strip.querySelector('.live-dot')?.classList.toggle('paused', isPaused);
    $('generatorProgressFill')?.classList.toggle('paused', isPaused);
    if (isPaused) {
      $('generatorLiveMessage').textContent = 'Run paused — click Resume to continue';
    }
  }
}

function updateTemplateProgress(agent, message, percent) {
  $('templateProgressStrip').classList.remove('hidden');
  $('templateLiveAgent').textContent = String(agent || 'agent').replaceAll('_', ' ');
  $('templateLiveMessage').textContent = message || 'Processing…';
  if (typeof percent === 'number') {
    $('templateProgressFill').style.width = `${Math.min(100, Math.max(8, percent))}%`;
  }
}

$('analyzeTemplateBtn').addEventListener('click', startTemplateRun);

async function startTemplateRun() {
  if (!state.docxFiles.length) return;
  $('analyzeTemplateBtn').disabled = true;
  try {
    const templateType = state.selectedTemplateType === 'product' ? 'product' : 'generic';
    const isProduct = templateType === 'product';
    const runName = $('templateRunName').value.trim() || (isProduct ? 'Section 16.3 — product template' : 'Section 16.3 — client template');
    const fd = fdFrom({ tenant_id: state.tenantId, run_name: runName, template_type: templateType }, state.docxFiles, 'files');
    const data = await api('/api/template-runs', { method: 'POST', body: fd });
    state.templateRunId = data.run_id;

    closeModal('uploadTemplateModal');
    showSubtab('createTemplate');
    showStudioWorkspace(true);
    clearAllSectionHighlights();
    state.activeTemplate = null;
    state.workingSchema = {
      template_type: templateType,
      base_document: state.docxFiles[0]?.name || '',
      document_profiles: [],
      base_tables: [],
      tables: [],
      common_fields: []
    };
    setSectionHighlight('reference_documents', true, 'Reading documents…');
    $('templateReview').classList.add('hidden');
    $('exportSchemaBtn').classList.add('hidden');
    $('forkActiveTemplateBtn').classList.add('hidden');
    $('useInGeneratorBtn').classList.add('hidden');
    $('templateWorkspaceHead')?.classList.remove('is-product-approved');
    $('templateReviewActions')?.classList.remove('is-product-approved');
    if ($('templateTypeBadge')) {
      $('templateTypeBadge').className = `badge-type ${templateType}`;
      $('templateTypeBadge').textContent = isProduct ? 'PRODUCT TEMPLATE' : 'GENERIC TEMPLATE';
    }
    if ($('blueprintPanelTitle')) {
      $('blueprintPanelTitle').textContent = isProduct ? 'PRODUCT TABLE BLUEPRINT' : 'GENERIC TABLE BLUEPRINT';
    }
    setUnsaved(false);

    $('templateWorkspaceTitle').textContent = runName;
    $('templateWorkspaceSub').textContent = isProduct
      ? 'Analyzing uploaded DOCX documents — carrying forward exact topic titles & MedDRA Search Criteria…'
      : 'Analyzing uploaded DOCX documents and assembling Section 16.3 table blueprints…';
    $('templateDocCount').textContent = state.docxFiles.length;
    $('templateStatus').className = 'status-pill running';
    $('templateStatus').innerHTML = isProduct ? '<i></i> Learning product blueprint' : '<i></i> Learning blueprint';
    setTemplatePausedState(false);
    $('templatePauseBtn')?.classList.remove('hidden');
    $('tableOutlineNav').innerHTML = '';

    $('templateDocOutline').innerHTML = state.docxFiles.map((f, i) => `
      <div class="doc-outline-card">
        <div class="doc-outline-top">
          <span class="doc-outline-name">${esc(f.name)}</span>
          ${i === 0 ? '<span class="base-tag">BASE</span>' : `<span class="ref-tag">REF</span>`}
        </div>
        <div class="doc-outline-meta">UPLOADED · READ-ONLY</div>
      </div>
    `).join('');

    $('genericTablePreview').innerHTML = `
      <div class="empty-panel">
        <div class="skeleton" style="width:60%"></div>
        <div class="skeleton short"></div>
        <p style="margin-top:12px">Extracting table blocks and dynamic fields…</p>
      </div>
    `;

    updateTemplateProgress('orchestrator', 'Created isolated template learning workspace', 18);

    state.templateEvents?.close();
    state.templateEvents = new EventSource(`/api/template-runs/${state.templateRunId}/events`);
    state.templateEvents.onmessage = e => handleTemplateEvent(JSON.parse(e.data));
    pollTemplateRun();

    // Reset upload queue for next modal open
    state.docxFiles = [];
    renderDocxFiles();
  } catch (e) {
    toast(e.message);
    $('analyzeTemplateBtn').disabled = false;
  }
}

function setSectionHighlight(target, active, label = '') {
  const map = {
    reference_documents: ['refDocsPanel', 'refDocsHighlightPill', 'refDocsHighlightLabel'],
    generic_table_blueprint: ['blueprintPanel', 'blueprintHighlightPill', 'blueprintHighlightLabel'],
    master_md: ['masterCard', 'masterHighlightPill', 'masterHighlightLabel']
  };
  const entry = map[target];
  if (!entry) return;
  const [panelId, pillId, labelId] = entry;
  $(panelId)?.classList.toggle('panel-reading-highlight', Boolean(active));
  $(pillId)?.classList.toggle('hidden', !active);
  if (active && label && $(labelId)) {
    $(labelId).textContent = label;
  }
}

function clearAllSectionHighlights() {
  setSectionHighlight('reference_documents', false);
  setSectionHighlight('generic_table_blueprint', false);
  setSectionHighlight('master_md', false);
}

function handleTemplateEvent(ev) {
  // Standard AG-UI Step Lifecycle
  if (ev.type === 'STEP_STARTED') {
    const pctMap = {
      read_section_16_3: 20,
      generate_generic_table_blueprint: 48,
      derive_detected_table_fields: 72,
      generate_master_md: 86
    };
    const msgMap = {
      read_section_16_3: 'Reading Section 16.3 from uploaded reference DOCX files…',
      generate_generic_table_blueprint: 'LLM agent generating structured Generic Table Blueprint…',
      derive_detected_table_fields: 'Deterministically calculating Detected Table Fields from blueprint…',
      generate_master_md: 'LLM agent writing master.md and selecting 2 best table summaries…'
    };
    if (pctMap[ev.stepName]) {
      updateTemplateProgress(ev.stepName, msgMap[ev.stepName], pctMap[ev.stepName]);
    }
  }

  // AG-UI State Snapshot after deterministic document reading
  if (ev.type === 'STATE_SNAPSHOT' && ev.snapshot?.document_profiles) {
    const partialSchema = {
      ...(state.workingSchema || {}),
      template_type: ev.snapshot.template_type || state.workingSchema?.template_type || 'generic',
      document_profiles: ev.snapshot.document_profiles,
      base_document: ev.snapshot.document_profiles[0]?.filename || ''
    };
    state.workingSchema = partialSchema;
    renderReferenceDocsOutline(partialSchema, []);
  }

  // Temporary AG-UI section highlight (e.g. "Reading documents…" in Reference Documents)
  if (ev.type === 'CUSTOM' && ev.name === 'ui.highlight') {
    const v = ev.value || {};
    setSectionHighlight(v.target, v.active, v.label || '');
  }

  if (ev.type === 'CUSTOM' && ev.name === 'agent.activity') {
    const v = ev.value || {};
    const stepPct = v.agent === 'document_reader' ? 26
      : (v.agent === 'blueprint_llm_agent' || v.agent === 'product_blueprint_llm_agent') ? 58
      : v.agent === 'field_aggregator' ? 76
      : v.agent === 'master_knowledge_agent' ? 90 : 30;
    updateTemplateProgress(v.agent, v.message, stepPct);
  }

  // Progressive table-by-table rendering: render each table card IMMEDIATELY as soon as it finishes!
  if (ev.type === 'CUSTOM' && ev.name === 'blueprint.table_ready') {
    const v = ev.value || {};
    const existing = Array.isArray(state.workingSchema?.base_tables) ? [...state.workingSchema.base_tables] : [];
    const tbl = v.table;
    if (tbl) {
      const idx = existing.findIndex(x => x.table_id === tbl.table_id);
      if (idx >= 0) existing[idx] = tbl;
      else existing.push(tbl);
    }
    state.workingSchema = {
      ...(state.workingSchema || {}),
      template_type: v.template_type || state.workingSchema?.template_type || 'generic',
      base_document: v.base_document || state.workingSchema?.base_document || '',
      document_profiles: v.document_profiles || state.workingSchema?.document_profiles || [],
      base_tables: existing,
      tables: existing,
      common_fields: state.workingSchema?.common_fields || []
    };
    const completed = Number(v.completed || existing.length);
    const total = Number(v.total || existing.length);
    const pct = Math.min(74, 24 + Math.round((completed / Math.max(1, total)) * 50));
    updateTemplateProgress(
      state.workingSchema.template_type === 'product' ? 'product_blueprint_llm_agent' : 'blueprint_llm_agent',
      `Rendered table ${completed} of ${total}: ${tbl?.topic_heading || ''}`,
      pct
    );
    renderReferenceDocsOutline(state.workingSchema, []);
    renderTemplateBlueprint(state.workingSchema);
    if (total > completed) {
      $('tableBlockCount').textContent = `${completed} / ${total} TABLES`;
    }
    updateKpiStrip();
  }

  // Progressive rendering: full Generic Table Blueprint ready
  if (ev.type === 'CUSTOM' && ev.name === 'blueprint.ready') {
    const v = ev.value || {};
    state.workingSchema = {
      ...(state.workingSchema || {}),
      template_type: v.template_type || state.workingSchema?.template_type || 'generic',
      base_document: v.base_document,
      document_profiles: v.document_profiles || state.workingSchema?.document_profiles || [],
      base_tables: v.base_tables || [],
      tables: v.base_tables || [],
      common_fields: state.workingSchema?.common_fields || []
    };
    renderReferenceDocsOutline(state.workingSchema, []);
    renderTemplateBlueprint(state.workingSchema);
    updateKpiStrip();
  }

  // Progressive rendering: Deterministically derived Detected Table Fields
  if (ev.type === 'CUSTOM' && ev.name === 'fields.derived') {
    const v = ev.value || {};
    state.workingSchema = {
      ...(state.workingSchema || {}),
      common_fields: v.common_fields || []
    };
    $('templateReview').classList.remove('hidden');
    renderFieldEditorRows(state.workingSchema, false);
  }

  // Progressive rendering: master.md + 2 best reference summaries
  if (ev.type === 'CUSTOM' && ev.name === 'master.ready') {
    const v = ev.value || {};
    $('templateReview').classList.remove('hidden');
    $('masterEditor').value = v.master_md || '';
    $('masterPreview').innerHTML = renderMarkdown($('masterEditor').value);
    updateMasterStats();
  }

  if (ev.type === 'CUSTOM' && ev.name === 'run.paused') {
    setTemplatePausedState(true);
  }

  if (ev.type === 'CUSTOM' && ev.name === 'run.resumed') {
    setTemplatePausedState(false);
  }

  if (ev.type === 'CUSTOM' && ev.name === 'template.ready') {
    state.templateEvents?.close();
    clearInterval(state.templatePollTimer);
    clearAllSectionHighlights();
    $('templatePauseBtn')?.classList.add('hidden');
    updateTemplateProgress('master_knowledge_agent', 'Template blueprint & master.md ready', 100);
    loadTemplateRun();
  }

  if (ev.type === 'RUN_ERROR') {
    state.templateEvents?.close();
    clearInterval(state.templatePollTimer);
    clearAllSectionHighlights();
    $('templatePauseBtn')?.classList.add('hidden');
    $('templateProgressStrip').classList.add('hidden');
    $('templateStatus').className = 'status-pill draft';
    $('templateStatus').textContent = 'Run failed';
    $('templateWorkspaceSub').textContent = ev.message || 'Template learning failed';
    toast(ev.message || 'Template learning failed');
  }
}

function pollTemplateRun() {
  clearInterval(state.templatePollTimer);
  state.templatePollTimer = setInterval(async () => {
    if (!state.templateRunId) { clearInterval(state.templatePollTimer); return; }
    try {
      const r = await api(`/api/template-runs/${state.templateRunId}`);
      if (r.status === 'paused') {
        setTemplatePausedState(true);
      } else if (r.status === 'running' && state.templateRunPaused) {
        setTemplatePausedState(false);
      }
      if (['completed', 'failed'].includes(r.status)) {
        clearInterval(state.templatePollTimer);
        state.templateEvents?.close();
        $('templatePauseBtn')?.classList.add('hidden');
        if (r.status === 'completed') await loadTemplateRun();
        else {
          $('templateProgressStrip').classList.add('hidden');
          $('templateStatus').className = 'status-pill draft';
          $('templateStatus').textContent = 'Run failed';
          toast(r.error || 'Template run failed');
        }
      }
    } catch {
      clearInterval(state.templatePollTimer);
    }
  }, 1000);
}

async function loadTemplateRun() {
  const data = await api(`/api/template-runs/${state.templateRunId}`);
  if (data.status !== 'completed') return;
  const result = data.result;
  $('templateProgressStrip').classList.add('hidden');
  $('templatePauseBtn')?.classList.add('hidden');
  mountTemplateInStudio(result.template);
  await loadTemplateHistory(false);
  toast('Template blueprint ready for review');
}

function mountTemplateInStudio(template) {
  if (!template) return;
  clearAllSectionHighlights();
  $('templatePauseBtn')?.classList.add('hidden');
  state.activeTemplate = template;
  state.workingSchema = structuredClone(template.schema || {});
  setUnsaved(false);

  showStudioWorkspace(true);
  $('templateProgressStrip').classList.add('hidden');
  $('templateReview').classList.remove('hidden');

  const locked = template.status === 'approved';
  const isProduct = isProductTemplate(template);
  const templateType = isProduct ? 'product' : 'generic';
  const baseCount = getMergedBlueprintTables(state.workingSchema).length;
  const refCount = (state.workingSchema.reference_tables || []).filter(t => !t.continuation_of_previous).length;

  $('templateWorkspaceTitle').textContent = template.name;
  $('templateWorkspaceSub').textContent = `${baseCount} unified Section 16.3 topic table${baseCount === 1 ? '' : 's'}${refCount ? ` · ${refCount} reference table${refCount === 1 ? '' : 's'}` : ''}${isProduct ? ' · Fixed topics & MedDRA criteria carried forward' : ''} · Tenant: ${state.tenantName}`;

  if ($('templateTypeBadge')) {
    $('templateTypeBadge').className = `badge-type ${templateType}`;
    $('templateTypeBadge').textContent = isProduct ? 'PRODUCT TEMPLATE' : 'GENERIC TEMPLATE';
  }
  if ($('blueprintPanelTitle')) {
    $('blueprintPanelTitle').textContent = isProduct ? 'PRODUCT TABLE BLUEPRINT' : 'GENERIC TABLE BLUEPRINT';
  }

  const approvedClass = isProduct ? 'approved-product' : 'complete';
  $('templateStatus').className = `status-pill ${locked ? approvedClass : 'draft'}`;
  $('templateStatus').textContent = locked
    ? (isProduct ? 'APPROVED · PRODUCT' : 'APPROVED')
    : (isProduct ? 'DRAFT · PRODUCT' : 'DRAFT · IN REVIEW');
  $('templateReviewStatus').className = `status-pill ${locked ? approvedClass : 'draft'}`;
  $('templateReviewStatus').textContent = locked
    ? (isProduct ? 'APPROVED · PRODUCT (READ ONLY)' : 'APPROVED · READ ONLY')
    : (isProduct ? 'DRAFT · PRODUCT' : 'DRAFT');

  $('templateWorkspaceHead')?.classList.toggle('is-product-approved', locked && isProduct);
  $('templateReviewActions')?.classList.toggle('is-product-approved', locked && isProduct);

  $('exportSchemaBtn').classList.remove('hidden');
  $('forkActiveTemplateBtn').classList.toggle('hidden', !locked);
  $('useInGeneratorBtn').classList.toggle('hidden', !locked);

  if ($('quickTemplateSelect')) {
    $('quickTemplateSelect').value = template.template_id;
  }

  renderReferenceDocsOutline(state.workingSchema, template.source_docs || []);
  renderTemplateBlueprint(state.workingSchema);
  renderTemplateEditor(template, state.workingSchema);
  updateKpiStrip();
}

function renderReferenceDocsOutline(schema, fallbackDocs) {
  const profiles = schema.document_profiles || [];
  const baseDoc = schema.base_document || (profiles[0]?.filename || fallbackDocs[0] || '');
  const docsToRender = profiles.length
    ? profiles
    : fallbackDocs.map(name => ({ filename: name, tables: [], section_16_3_found: true }));

  $('templateDocCount').textContent = docsToRender.length;
  $('templateDocOutline').innerHTML = docsToRender.length
    ? docsToRender.map(d => {
        const isBase = d.filename === baseDoc;
        const tableCount = (d.tables || []).filter(t => !t.continuation_of_previous).length;
        const styles = (d.styles || []).filter(Boolean).slice(0, 2).join(', ');
        return `
          <div class="doc-outline-card">
            <div class="doc-outline-top">
              <span class="doc-outline-name" title="${esc(d.filename)}">${esc(d.filename)}</span>
              ${isBase ? '<span class="base-tag">BASE</span>' : '<span class="ref-tag">REF</span>'}
            </div>
            <div class="doc-outline-meta">
              ${tableCount ? `${tableCount} tables · ` : ''}${d.section_16_3_found === false ? 'Fallback match' : 'Section 16.3'}
              ${styles ? `<br>Style: ${esc(styles)}` : ''}
            </div>
          </div>
        `;
      }).join('')
    : '<div class="empty-row">No document metadata</div>';

  // Jump outline (unified tables with continuations folded into their original table)
  const tables = getMergedBlueprintTables(schema);
  const jumpHost = $('tableOutlineNav');
  if (!tables.length) {
    jumpHost.innerHTML = '<div class="empty-row" style="padding:6px">No table blocks</div>';
  } else {
    jumpHost.innerHTML = tables.map((t, idx) => `
      <button type="button" class="table-jump-btn" data-jump-table="bp-table-${idx}">
        <span class="table-jump-num">T${idx + 1}</span>
        <span class="table-jump-label">${esc(t.topic_heading || `Section 16.3 Table ${idx + 1}`)}</span>
      </button>
    `).join('');
    jumpHost.querySelectorAll('[data-jump-table]').forEach(btn => {
      btn.addEventListener('click', () => {
        const target = document.getElementById(btn.dataset.jumpTable);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          target.classList.add('highlight-pulse');
          setTimeout(() => target.classList.remove('highlight-pulse'), 1300);
        }
      });
    });
  }
}

/* ==================== GENERIC TABLE BLUEPRINT RENDERER ==================== */
function getDynamicPlaceholder(field, genericEntry) {
  if (field?.placeholder) return field.placeholder;
  if (genericEntry?.placeholder) return genericEntry.placeholder;
  return `{{${field?.key || 'field'}}}`;
}

function buildTableFieldsForPreview(table, schema) {
  const commonByKey = new Map((schema.common_fields || []).map(f => [f.key, f]));
  const previewList = table.generic_preview || [];
  const tableFields = table.fields || [];

  const source = previewList.length ? previewList : tableFields;
  const rows = source.map(item => {
    const tf = tableFields.find(x => x.key === item.key) || {};
    const cf = commonByKey.get(item.key) || {};
    const carriedForward = Boolean(tf.carried_forward ?? item.carried_forward ?? false);
    // For carried-forward fields (e.g. Product Template MedDRA Search Criteria), ALWAYS preserve the table's exact verbatim value!
    const placeholder = carriedForward
      ? getDynamicPlaceholder(tf, item)
      : getDynamicPlaceholder(cf.placeholder ? cf : tf, item);
    return {
      key: item.key,
      label: cf.label || tf.label || item.label || item.key,
      type: cf.type || tf.type || item.type || 'custom',
      required: cf.required ?? tf.required ?? item.required ?? false,
      carried_forward: carriedForward,
      placeholder,
      source_intent: cf.source_intent ?? tf.source_intent ?? item.source_intent ?? ''
    };
  });

  // Include any newly added custom fields in common_fields not yet on table
  const seenKeys = new Set(rows.map(r => r.key));
  for (const cf of (schema.common_fields || [])) {
    if (!seenKeys.has(cf.key) && cf._added_by_user) {
      rows.push({
        key: cf.key,
        label: cf.label,
        type: cf.type || 'custom',
        required: Boolean(cf.required),
        carried_forward: Boolean(cf.carried_forward),
        placeholder: cf.placeholder || `{{${cf.key}}}`,
        source_intent: cf.source_intent || ''
      });
    }
  }
  return rows;
}

function renderTemplateBlueprint(schema) {
  const tables = getMergedBlueprintTables(schema);
  const isProduct = isProductTemplate(schema);
  const query = ($('blueprintSearch')?.value || '').trim().toLowerCase();
  const host = $('genericTablePreview');

  $('tableBlockCount').textContent = `${tables.length} TABLE${tables.length === 1 ? '' : 'S'}`;

  if (!tables.length) {
    host.innerHTML = `
      <div class="empty-panel">
        <b>No Section 16.3 tables detected</b>
        <p>Check the uploaded DOCX headings or upload another reference report containing native Word tables.</p>
      </div>
    `;
    return;
  }

  const filtered = tables.map((t, idx) => ({ t, idx })).filter(({ t }) => {
    if (!query) return true;
    const hay = [
      t.topic_heading,
      t.criterion_type,
      ...(t.criterion_terms || []),
      ...(t.fields || []).map(f => `${f.label} ${f.key} ${f.type} ${f.placeholder || ''}`)
    ].join(' ').toLowerCase();
    return hay.includes(query);
  });

  if (!filtered.length) {
    host.innerHTML = `<div class="empty-panel"><b>No tables match "${esc(query)}"</b><p>Try clearing the filter to view all ${tables.length} detected tables.</p></div>`;
    return;
  }

  host.innerHTML = `<div class="blueprint-card-grid">${filtered.map(({ t, idx }) => {
    const rows = buildTableFieldsForPreview(t, schema);
    const reqCount = rows.filter(r => r.required).length;
    const carriedCount = rows.filter(r => r.carried_forward).length;
    const terms = (t.criterion_terms || []).filter(Boolean);
    const tableIsProduct = isProduct || t.template_type === 'product';
    return `
      <div class="bp-grid-card" id="bp-table-${idx}" data-inspect-table="${idx}">
        <div class="bp-grid-top">
          <div class="bp-grid-badges">
            <span class="topic-badge ${tableIsProduct ? 'is-product' : ''}">TABLE ${idx + 1}</span>
            ${tableIsProduct ? '<span class="meta-pill criteria-pill">FIXED TOPIC</span>' : ''}
            ${t.criterion_type && t.criterion_type !== 'manual' ? `<span class="meta-pill criteria-pill">${esc(t.criterion_type)}</span>` : ''}
          </div>
          <span class="bp-grid-dims">${Number(t.row_count || 0)}×${Number(t.column_count || 0)}</span>
        </div>
        <h3 title="${esc(t.topic_heading || 'Section 16.3 topic')}">${esc(t.topic_heading || `Section 16.3 Table ${idx + 1}`)}</h3>
        <p class="bp-grid-sub">${rows.length} field${rows.length === 1 ? '' : 's'} · ${reqCount} required${carriedCount ? ` · ${carriedCount} carried MedDRA` : ''}${t.table_style ? ` · ${esc(t.table_style)}` : ''}</p>
        <div class="bp-grid-tokens">
          ${rows.slice(0, 3).map(f => {
            const snippet = f.carried_forward && f.placeholder.length > 42
              ? `${f.placeholder.slice(0, 40)}…`
              : f.placeholder;
            return `<span class="bp-token-mini ${f.carried_forward ? 'is-carried' : ''}" title="${esc(f.label)}: ${esc(f.placeholder)}">${esc(snippet)}</span>`;
          }).join('')}
          ${rows.length > 3 ? `<span class="bp-token-more">+${rows.length - 3} more</span>` : ''}
        </div>
        <div class="bp-grid-meta">
          <span>${terms.length ? `${terms.length} MEDDRA TERM${terms.length === 1 ? '' : 'S'}` : 'SECTION 16.3'}</span>
          ${t.requires_reporting_interval ? '<span>INTERVAL REQ</span>' : ''}
          <span>DOCX IDX ${(t.merged_docx_indices || []).length ? t.merged_docx_indices.join('+') : Number(t.docx_table_index ?? idx)}</span>
        </div>
        <div class="bp-grid-actions">
          <button type="button" class="btn-primary btn-xs" data-inspect-btn="${idx}">Inspect</button>
        </div>
      </div>
    `;
  }).join('')}</div>`;

  host.querySelectorAll('[data-inspect-table]').forEach(card => {
    card.addEventListener('click', () => {
      openTableDetailModal(Number(card.dataset.inspectTable));
    });
  });
}

function openTableDetailModal(idx) {
  const tables = getMergedBlueprintTables(state.workingSchema);
  const t = tables[idx];
  if (!t) return;
  state.inspectedTableIndex = idx;
  const rows = buildTableFieldsForPreview(t, state.workingSchema);
  const terms = (t.criterion_terms || []).filter(Boolean);
  const isProduct = isProductTemplate(state.workingSchema) || t.template_type === 'product';

  $('tableDetailBadges').innerHTML = `
    <span class="topic-badge ${isProduct ? 'is-product' : ''}">TABLE ${idx + 1} OF ${tables.length}</span>
    ${isProduct ? '<span class="badge-type product">PRODUCT · FIXED TOPIC &amp; MEDDRA</span>' : ''}
    ${t.criterion_type && t.criterion_type !== 'manual' ? `<span class="meta-pill criteria-pill">${esc(t.criterion_type)}</span>` : ''}
    ${t.table_style ? `<span class="meta-pill">${esc(t.table_style)}</span>` : ''}
  `;
  $('tableDetailTitle').textContent = t.topic_heading || `Section 16.3 Table ${idx + 1}`;
  $('tableDetailSub').textContent = `${Number(t.row_count || 0)} rows · ${Number(t.column_count || 0)} cols · ${rows.length} detected fields · Source: ${t.source_file || state.workingSchema?.base_document || 'Base DOCX'}`;
  $('tableDetailPrevBtn').disabled = idx <= 0;
  $('tableDetailNextBtn').disabled = idx >= tables.length - 1;

  $('tableDetailBody').innerHTML = `
    ${terms.length ? `
      <div class="criteria-terms-bar">
        <span class="criteria-terms-label">${esc(t.criterion_type || 'MEDDRA TERMS')}${isProduct ? ' (CARRIED FORWARD)' : ''}</span>
        ${terms.map(term => `<span class="term-chip">${esc(term)}</span>`).join('')}
      </div>
    ` : ''}
    <div class="table-detail-table-wrap">
      <table class="blueprint-table">
        <thead>
          <tr>
            <th>FIELD LABEL</th>
            <th>KEY</th>
            <th>TYPE</th>
            <th>${isProduct ? 'VALUE / PLACEHOLDER' : 'GENERIC PLACEHOLDER'}</th>
            <th>SOURCE INTENT</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(f => `
            <tr>
              <td>${esc(f.label)}${f.required ? '<span class="req-star">*</span>' : ''}</td>
              <td><code style="font-family:var(--mono);font-size:11.5px;color:var(--muted)">${esc(f.key)}</code></td>
              <td><span class="field-type-badge">${esc(f.type)}</span></td>
              <td>${f.carried_forward
                ? `<div class="carried-value-wrap"><span class="carried-tag">CARRIED FORWARD · MEDDRA</span><div class="carried-value">${esc(f.placeholder)}</div></div>`
                : `<span class="token">${esc(f.placeholder)}</span>`}</td>
              <td style="font-size:12px;color:var(--muted)">${esc(f.source_intent || '—')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;

  openModal('tableDetailModal');
}

$('blueprintSearch').addEventListener('input', () => {
  if (state.workingSchema) renderTemplateBlueprint(state.workingSchema);
});

/* ==================== DETECTED TABLE FIELDS & MASTER.MD EDITOR ==================== */
function renderTemplateEditor(template, schema) {
  const locked = template.status === 'approved';
  $('templateNameEdit').value = template.name || '';
  $('masterEditor').value = template.master_md || '';
  $('masterPreview').innerHTML = renderMarkdown($('masterEditor').value);
  updateMasterStats();

  renderFieldEditorRows(schema, locked);

  $('approveTemplateBtn').disabled = locked;
  $('approveTemplateBtn').innerHTML = locked ? 'Template approved <span>✓</span>' : 'Approve template <span>✓</span>';
  $('saveTemplateBtn').disabled = locked;
  $('addFieldBtn').disabled = locked;
  $('templateNameEdit').readOnly = locked;
  $('masterEditor').readOnly = locked;
}

function renderFieldEditorRows(schema, locked) {
  const fields = schema.common_fields || [];
  const q = ($('fieldSearch')?.value || '').trim().toLowerCase();
  $('detectedFieldCount').textContent = fields.length;

  const visible = fields.map((f, i) => ({ f, i })).filter(({ f }) => {
    if (!q) return true;
    return `${f.label} ${f.key} ${f.type} ${f.source_intent || ''}`.toLowerCase().includes(q);
  });

  if (!visible.length) {
    $('fieldEditor').innerHTML = '<div class="empty-row" style="padding:14px">No matching fields.</div>';
    return;
  }

  $('fieldEditor').innerHTML = visible.map(({ f, i }) => {
    const placeholder = f.placeholder || `{{${f.key}}}`;
    const isCarried = Boolean(f.carried_forward);
    return `
      <div class="field-edit-card ${isCarried ? 'is-carried-field' : ''}" data-field-index="${i}">
        <div class="field-edit-top">
          <input type="text" data-field-prop="label" data-idx="${i}" value="${esc(f.label)}" placeholder="Field label" aria-label="Field label" ${locked ? 'disabled' : ''}>
          <input type="text" list="fieldTypeSuggestions" data-field-prop="type" data-idx="${i}" value="${esc(f.type || 'custom')}" placeholder="Field type" aria-label="Field type" ${locked ? 'disabled' : ''}>
          <label class="req-toggle">
            <input type="checkbox" data-field-prop="required" data-idx="${i}" ${f.required ? 'checked' : ''} ${locked ? 'disabled' : ''}>
            Req
          </label>
          <button type="button" class="field-remove-btn" data-remove-field="${i}" title="Remove field" ${locked ? 'disabled' : ''}>×</button>
        </div>
        <div class="field-edit-bottom">
          <input type="text" class="mono-input" data-field-prop="placeholder" data-idx="${i}" value="${esc(placeholder)}" placeholder="{{placeholder_token}}" aria-label="Placeholder token" ${locked || isCarried ? 'disabled' : ''}>
          <input type="text" data-field-prop="source_intent" data-idx="${i}" value="${esc(f.source_intent || '')}" placeholder="Source intent / semantic guidance" aria-label="Source intent" ${locked ? 'disabled' : ''}>
        </div>
        <div class="field-meta-line">
          <span>Key: <b>${esc(f.key)}</b></span>
          ${isCarried ? '<span class="carried-tag">CARRIED FORWARD · PER TOPIC</span>' : ''}
          <span>${f.occurrences ? `Observed in ${f.occurrences} table${f.occurrences === 1 ? '' : 's'}` : 'Custom tenant field'}</span>
        </div>
      </div>
    `;
  }).join('');

  $('fieldEditor').querySelectorAll('[data-field-prop]').forEach(el => {
    const handler = () => {
      const idx = Number(el.dataset.idx);
      const prop = el.dataset.fieldProp;
      const field = state.workingSchema.common_fields[idx];
      if (!field) return;
      field[prop] = el.type === 'checkbox' ? el.checked : el.value;
      syncCommonFieldToTables(field);
      setUnsaved(true);
      renderTemplateBlueprint(state.workingSchema);
    };
    el.addEventListener(el.type === 'checkbox' ? 'change' : 'input', handler);
  });

  $('fieldEditor').querySelectorAll('[data-remove-field]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (locked) return;
      const idx = Number(btn.dataset.removeField);
      const removed = state.workingSchema.common_fields.splice(idx, 1)[0];
      if (removed) {
        for (const listName of ['tables', 'base_tables']) {
          for (const t of (state.workingSchema[listName] || [])) {
            t.fields = (t.fields || []).filter(x => x.key !== removed.key);
            if (t.generic_preview) {
              t.generic_preview = t.generic_preview.filter(x => x.key !== removed.key);
            }
          }
        }
      }
      setUnsaved(true);
      renderFieldEditorRows(state.workingSchema, locked);
      renderTemplateBlueprint(state.workingSchema);
      toast(`Removed field "${removed?.label || ''}"`);
    });
  });
}

function syncCommonFieldToTables(f) {
  for (const listName of ['tables', 'base_tables']) {
    for (const t of (state.workingSchema[listName] || [])) {
      const tf = (t.fields || []).find(x => x.key === f.key);
      if (tf) {
        tf.label = f.label;
        tf.type = f.type;
        tf.required = f.required;
        tf.source_intent = f.source_intent;
        if (f.placeholder && !tf.carried_forward) tf.placeholder = f.placeholder;
      }
      const gp = (t.generic_preview || []).find(x => x.key === f.key);
      if (gp) {
        gp.label = f.label;
        gp.type = f.type;
        gp.required = f.required;
        if (f.placeholder && !gp.carried_forward && !tf?.carried_forward) gp.placeholder = f.placeholder;
      }
    }
  }
}

$('addFieldBtn').addEventListener('click', () => {
  if (!state.activeTemplate || state.activeTemplate.status === 'approved') return;
  const count = (state.workingSchema.common_fields || []).length + 1;
  const key = `custom_field_${count}`;
  state.workingSchema.common_fields = state.workingSchema.common_fields || [];
  state.workingSchema.common_fields.push({
    key,
    label: `New Tenant Field ${count}`,
    type: 'custom',
    required: false,
    placeholder: `{{${key}}}`,
    source_intent: 'Client-specific table field',
    occurrences: 0,
    _added_by_user: true
  });
  setUnsaved(true);
  renderFieldEditorRows(state.workingSchema, false);
  renderTemplateBlueprint(state.workingSchema);
  $('fieldEditor').scrollTop = $('fieldEditor').scrollHeight;
  toast('Added new custom field to draft schema');
});

$('fieldSearch').addEventListener('input', () => {
  if (!state.activeTemplate || !state.workingSchema) return;
  renderFieldEditorRows(state.workingSchema, state.activeTemplate.status === 'approved');
});

$('templateNameEdit').addEventListener('input', () => setUnsaved(true));
$('masterEditor').addEventListener('input', () => {
  setUnsaved(true);
  updateMasterStats();
});

function updateMasterStats() {
  const txt = $('masterEditor').value || '';
  const words = txt.trim() ? txt.trim().split(/\s+/).length : 0;
  const lines = txt ? txt.split('\n').length : 0;
  $('masterWordCount').textContent = `${words} words · ${lines} lines`;
}

document.querySelectorAll('[data-md-view]').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.dataset.mdView;
    document.querySelectorAll('[data-md-view]').forEach(b => b.classList.toggle('active', b.dataset.mdView === mode));
    const isPreview = mode === 'preview';
    $('masterEditor').classList.toggle('hidden', isPreview);
    $('masterPreview').classList.toggle('hidden', !isPreview);
    if (isPreview) {
      $('masterPreview').innerHTML = renderMarkdown($('masterEditor').value);
    }
  });
});

$('copyMasterBtn').addEventListener('click', () => {
  navigator.clipboard.writeText($('masterEditor').value || '').then(() => toast('master.md copied to clipboard'));
});

$('downloadMasterBtn').addEventListener('click', () => {
  if (!state.activeTemplate) return;
  window.open(`/api/templates/${state.activeTemplate.template_id}/master.md?tenant_id=${encodeURIComponent(state.tenantId)}`, '_blank');
});

$('exportSchemaBtn').addEventListener('click', () => {
  if (!state.workingSchema) return;
  const blob = new Blob([JSON.stringify(state.workingSchema, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${(state.activeTemplate?.name || 'template').replace(/[^a-z0-9_-]+/gi, '_')}.schema.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast('Exported template.schema.json');
});

$('saveTemplateBtn').addEventListener('click', saveTemplateEdits);

async function saveTemplateEdits() {
  if (!state.activeTemplate || state.activeTemplate.status === 'approved') return false;
  try {
    const payload = {
      name: $('templateNameEdit').value.trim() || state.activeTemplate.name,
      schema: state.workingSchema,
      master_md: $('masterEditor').value
    };
    const saved = await api(
      `/api/templates/${state.activeTemplate.template_id}?tenant_id=${encodeURIComponent(state.tenantId)}`,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }
    );
    mountTemplateInStudio(saved);
    await loadTemplateHistory(false);
    toast('Template changes saved');
    return true;
  } catch (e) {
    toast(e.message);
    return false;
  }
}

$('approveTemplateBtn').addEventListener('click', async () => {
  if (!state.activeTemplate) return;
  try {
    const saved = await saveTemplateEdits();
    if (!saved) return;
    const r = await api(
      `/api/templates/${state.activeTemplate.template_id}/approve?tenant_id=${encodeURIComponent(state.tenantId)}`,
      { method: 'POST' }
    );
    state.activeTemplate.status = r.status;
    mountTemplateInStudio(state.activeTemplate);
    toast('Template approved and unlocked in Generator');
    await loadTemplateHistory(false);
    await refreshApprovedTemplates();
  } catch (e) {
    toast(e.message);
  }
});

$('forkActiveTemplateBtn').addEventListener('click', () => {
  if (state.activeTemplate) forkHistoryTemplate(state.activeTemplate.template_id);
});

$('useInGeneratorBtn').addEventListener('click', async () => {
  if (!state.activeTemplate) return;
  const id = state.activeTemplate.template_id;
  showTab('generator');
  await refreshApprovedTemplates();
  openGeneratorUploadModal(id);
});

/* ==================== TEMPLATE HISTORY / LIBRARY ==================== */
async function loadTemplateHistory(autoSelectFirst = false) {
  try {
    const data = await api(`/api/templates?tenant_id=${encodeURIComponent(state.tenantId)}`);
    const items = data.templates || [];
    state.templates = items;
    $('templateHistoryCount').textContent = items.length;
    $('emptyBrowseHistoryBtn').classList.toggle('hidden', !items.length);

    // Populate quick template switcher
    const switcher = $('quickTemplateSelect');
    if (!items.length) {
      switcher.innerHTML = '<option value="">No templates yet</option>';
    } else {
      switcher.innerHTML = '<option value="">Select a template blueprint…</option>' + items.map(t => {
        const typeTag = isProductTemplate(t) ? 'PRODUCT' : 'GENERIC';
        return `<option value="${t.template_id}" ${state.activeTemplate?.template_id === t.template_id ? 'selected' : ''}>${esc(t.name)} [${typeTag} · ${t.status.toUpperCase()} · ${t.table_count} tables]</option>`;
      }).join('');
    }

    renderTemplateHistoryCards();
    updateKpiStrip();

    // Auto-showcase the latest template so the redesigned UI immediately shines!
    if (autoSelectFirst) {
      if (items.length && !state.activeTemplate) {
        await openTemplate(items[0].template_id, false);
      } else if (!items.length) {
        showStudioWorkspace(false);
      }
    }
  } catch (e) {
    console.warn(e);
  }
}

function renderTemplateHistoryCards() {
  const items = state.templates || [];
  const q = ($('historySearch')?.value || '').trim().toLowerCase();
  const filtered = items.filter(t => {
    if (state.historyFilter !== 'all' && t.status !== state.historyFilter) return false;
    if (q && !`${t.name} ${t.template_id} ${t.status} ${t.template_type || 'generic'}`.toLowerCase().includes(q)) return false;
    return true;
  });

  if (!filtered.length) {
    $('templateHistoryList').innerHTML = `
      <div class="empty-panel" style="grid-column:1/-1">
        <div class="empty-glyph">◷</div>
        <b>${items.length ? 'No matching templates' : 'No templates yet'}</b>
        <p>${items.length ? 'Try adjusting your search or status filter.' : 'Click Upload DOCX in the top-right corner to build your first Section 16.3 blueprint.'}</p>
      </div>
    `;
    return;
  }

  $('templateHistoryList').innerHTML = filtered.map(t => {
    const isActive = state.activeTemplate?.template_id === t.template_id;
    const isProduct = isProductTemplate(t);
    const isApprovedProduct = t.status === 'approved' && isProduct;
    const badgeClass = isApprovedProduct ? 'approved-product' : esc(t.status);
    const badgeLabel = isApprovedProduct ? 'APPROVED · PRODUCT' : t.status.toUpperCase();
    return `
      <div class="history-card ${isActive ? 'is-active-card' : ''} ${isApprovedProduct ? 'is-product-approved' : ''}">
        <div class="history-card-top">
          <div class="history-card-badges">
            <span class="badge-status ${badgeClass}">${badgeLabel}</span>
            ${!isApprovedProduct ? `<span class="badge-type ${isProduct ? 'product' : 'generic'}">${isProduct ? 'PRODUCT' : 'GENERIC'}</span>` : ''}
          </div>
          <small class="history-meta">${fmtDate(t.created_at)}</small>
        </div>
        <h3>${esc(t.name)}</h3>
        <p>ID ${esc(t.template_id.slice(0, 12))} · Section 16.3 · ${t.table_count} table block${t.table_count === 1 ? '' : 's'}${isProduct ? ' · Fixed MedDRA' : ''}</p>
        <div class="history-meta">
          <span>${esc(t.source_doc_count || 0)} DOCX REF${t.source_doc_count === 1 ? '' : 'S'}</span>
          <span>${esc(t.tenant_id)}</span>
        </div>
        <div class="history-actions">
          <button class="btn-primary btn-xs" data-template-view="${t.template_id}">${t.status === 'approved' ? 'Inspect' : 'Open & edit'}</button>
          ${t.status === 'approved'
            ? `<button class="btn-secondary btn-xs" data-template-use="${t.template_id}">Use →</button>
               <button class="btn-ghost btn-xs" data-template-fork="${t.template_id}">Fork draft</button>`
            : `<button class="btn-secondary btn-xs" data-template-approve="${t.template_id}">Approve</button>`}
          <button class="btn-ghost btn-xs" data-template-delete="${t.template_id}">Remove</button>
        </div>
      </div>
    `;
  }).join('');

  document.querySelectorAll('[data-template-view]').forEach(b =>
    b.addEventListener('click', () => openTemplate(b.dataset.templateView, true))
  );
  document.querySelectorAll('[data-template-use]').forEach(b =>
    b.addEventListener('click', async () => {
      const id = b.dataset.templateUse;
      showTab('generator');
      await refreshApprovedTemplates();
      openGeneratorUploadModal(id);
    })
  );
  document.querySelectorAll('[data-template-fork]').forEach(b =>
    b.addEventListener('click', () => forkHistoryTemplate(b.dataset.templateFork))
  );
  document.querySelectorAll('[data-template-approve]').forEach(b =>
    b.addEventListener('click', () => approveHistoryTemplate(b.dataset.templateApprove))
  );
  document.querySelectorAll('[data-template-delete]').forEach(b =>
    b.addEventListener('click', () => removeTemplate(b.dataset.templateDelete))
  );
}

$('quickTemplateSelect').addEventListener('change', e => {
  if (e.target.value) openTemplate(e.target.value, false);
});

$('historySearch').addEventListener('input', renderTemplateHistoryCards);
document.querySelectorAll('[data-history-filter]').forEach(btn => {
  btn.addEventListener('click', () => {
    state.historyFilter = btn.dataset.historyFilter;
    document.querySelectorAll('[data-history-filter]').forEach(b => b.classList.toggle('active', b === btn));
    renderTemplateHistoryCards();
  });
});

async function openTemplate(id, switchToStudio = true) {
  try {
    const t = await api(`/api/templates/${id}?tenant_id=${encodeURIComponent(state.tenantId)}`);
    if (switchToStudio) showSubtab('createTemplate');
    mountTemplateInStudio(t);
    renderTemplateHistoryCards();
  } catch (e) {
    toast(e.message);
  }
}

async function forkHistoryTemplate(id) {
  try {
    const fd = new FormData();
    fd.append('tenant_id', state.tenantId);
    fd.append('name', '');
    const clone = await api(`/api/templates/${id}/fork?tenant_id=${encodeURIComponent(state.tenantId)}`, { method: 'POST', body: fd });
    await openTemplate(clone.template_id, true);
    toast('Created editable draft copy; approved version remains immutable');
    await loadTemplateHistory(false);
  } catch (e) {
    toast(e.message);
  }
}

async function approveHistoryTemplate(id) {
  try {
    await api(`/api/templates/${id}/approve?tenant_id=${encodeURIComponent(state.tenantId)}`, { method: 'POST' });
    toast('Template approved');
    await loadTemplateHistory(false);
    await refreshApprovedTemplates();
    if (state.activeTemplate?.template_id === id) await openTemplate(id, false);
  } catch (e) {
    toast(e.message);
  }
}

async function removeTemplate(id) {
  if (!confirm('Remove this template from tenant history? Original uploaded files stay in the local workspace.')) return;
  try {
    await api(`/api/templates/${id}?tenant_id=${encodeURIComponent(state.tenantId)}`, { method: 'DELETE' });
    if (state.activeTemplate?.template_id === id) {
      state.activeTemplate = null;
      state.workingSchema = null;
      showStudioWorkspace(false);
    }
    toast('Template removed');
    await loadTemplateHistory(true);
    await refreshApprovedTemplates();
  } catch (e) {
    toast(e.message);
  }
}

$('refreshHistoryBtn').addEventListener('click', () => loadTemplateHistory(false));

/* ==================== GENERATOR WORKFLOW ==================== */
function setGeneratorStep(stepNum) {
  document.querySelectorAll('#generatorStepper .step-pill').forEach(el => {
    const n = Number(el.dataset.step);
    el.classList.toggle('done', n < stepNum);
    el.classList.toggle('active', n === stepNum);
  });
}

function updateGeneratorProgress(agent, message, percent) {
  $('generatorProgressStrip').classList.remove('hidden');
  $('generatorLiveAgent').textContent = String(agent || 'agent').replaceAll('_', ' ');
  $('generatorLiveMessage').textContent = message || 'Working…';
  if (typeof percent === 'number') {
    $('generatorProgressFill').style.width = `${Math.min(100, Math.max(8, percent))}%`;
  }
}

async function refreshApprovedTemplates() {
  try {
    const data = await api(`/api/templates?tenant_id=${encodeURIComponent(state.tenantId)}`);
    const approved = (data.templates || []).filter(t => t.status === 'approved');
    state.approvedTemplates = approved;
    $('kpiGenApprovedTemplates').textContent = approved.length;

    const prev = $('generatorTemplateSelect').value;
    $('generatorTemplateSelect').innerHTML =
      '<option value="">Select an approved template…</option>' +
      approved.map(t => {
        const typeTag = isProductTemplate(t) ? 'PRODUCT' : 'GENERIC';
        return `<option value="${t.template_id}">${esc(t.name)} [${typeTag}] · ${t.table_count} tables</option>`;
      }).join('');
    if (prev && approved.some(t => t.template_id === prev)) {
      $('generatorTemplateSelect').value = prev;
    }

    renderGeneratorApprovedCards(approved);
    updateGeneratorStart();
  } catch (e) {
    console.warn(e);
  }
}

function renderGeneratorApprovedCards(approved) {
  const host = $('generatorApprovedList');
  if (!host) return;
  if (!approved.length) {
    host.innerHTML = `
      <div class="empty-panel" style="grid-column:1/-1">
        <div class="empty-glyph">▤</div>
        <b>No approved templates yet for ${esc(state.tenantName)}</b>
        <p>Approve a Section 16.3 template blueprint in Template Generator first to unlock report generation.</p>
        <button type="button" class="btn-primary btn-sm" style="margin-top:14px" id="goToTemplatesFromGen">Go to Template Generator →</button>
      </div>
    `;
    $('goToTemplatesFromGen')?.addEventListener('click', () => showTab('templates'));
    return;
  }

  host.innerHTML = approved.map(t => {
    const isProduct = isProductTemplate(t);
    return `
      <div class="history-card ${isProduct ? 'is-product-approved' : ''}">
        <div class="history-card-top">
          <div class="history-card-badges">
            <span class="badge-status ${isProduct ? 'approved-product' : 'approved'}">${isProduct ? 'APPROVED · PRODUCT' : 'APPROVED'}</span>
            ${!isProduct ? '<span class="badge-type generic">GENERIC</span>' : ''}
          </div>
          <small class="history-meta">${fmtDate(t.created_at)}</small>
        </div>
        <h3>${esc(t.name)}</h3>
        <p>ID ${esc(t.template_id.slice(0, 12))} · Section 16.3 · ${t.table_count} table block${t.table_count === 1 ? '' : 's'}${isProduct ? ' · Fixed MedDRA' : ''}</p>
        <div class="history-meta">
          <span>${esc(t.source_doc_count || 0)} DOCX REF${t.source_doc_count === 1 ? '' : 'S'}</span>
          <span>${esc(t.tenant_id)}</span>
        </div>
        <div class="history-actions">
          <button type="button" class="btn-primary btn-xs" data-gen-launch="${t.template_id}">Upload Excel &amp; Run →</button>
          <button type="button" class="btn-ghost btn-xs" data-gen-inspect="${t.template_id}">Inspect blueprint</button>
        </div>
      </div>
    `;
  }).join('');

  host.querySelectorAll('[data-gen-launch]').forEach(btn => {
    btn.addEventListener('click', () => openGeneratorUploadModal(btn.dataset.genLaunch));
  });
  host.querySelectorAll('[data-gen-inspect]').forEach(btn => {
    btn.addEventListener('click', async () => {
      showTab('templates');
      await openTemplate(btn.dataset.genInspect, true);
    });
  });
}

async function checkSelectedTemplateInterval(templateId) {
  const note = $('periodRequirementNote');
  if (!templateId) {
    note.textContent = 'REQUIRED WHEN TEMPLATE DEFINES AN INTERVAL COUNT';
    note.classList.remove('is-required');
    return;
  }
  try {
    const t = await api(`/api/templates/${templateId}?tenant_id=${encodeURIComponent(state.tenantId)}`);
    if (t.schema?.reporting_interval_required) {
      note.textContent = 'REQUIRED BY THIS TEMPLATE';
      note.classList.add('is-required');
    } else {
      note.textContent = 'OPTIONAL FOR THIS TEMPLATE';
      note.classList.remove('is-required');
    }
  } catch {}
}

function updateGeneratorStart() {
  $('startGeneratorBtn').disabled = !(state.excelFiles.length && $('generatorTemplateSelect').value);
}

$('generatorTemplateSelect').addEventListener('change', e => {
  updateGeneratorStart();
  checkSelectedTemplateInterval(e.target.value);
});

// Reporting interval presets
document.querySelectorAll('[data-preset]').forEach(btn => {
  btn.addEventListener('click', () => {
    const p = btn.dataset.preset;
    if (p === 'clear') {
      $('periodStart').value = '';
      $('periodEnd').value = '';
      return;
    }
    const end = new Date();
    const start = new Date(end);
    if (p === '6m') start.setMonth(start.getMonth() - 6);
    if (p === '1y') start.setFullYear(start.getFullYear() - 1);
    if (p === 'ytd') start.setMonth(0, 1);
    const fmt = d => d.toISOString().slice(0, 10);
    $('periodStart').value = fmt(start);
    $('periodEnd').value = fmt(end);
  });
});

// Calculation unit visual card sync
document.querySelectorAll('#countModeCards .mode-option').forEach(btn => {
  btn.addEventListener('click', () => {
    const mode = btn.dataset.mode;
    $('countMode').value = mode;
    document.querySelectorAll('#countModeCards .mode-option').forEach(b =>
      b.classList.toggle('selected', b.dataset.mode === mode)
    );
  });
});

$('startGeneratorBtn').addEventListener('click', startGeneratorRun);

async function startGeneratorRun() {
  $('startGeneratorBtn').disabled = true;
  try {
    const runName = $('generatorRunName').value.trim() || 'PBRER Section 16.3 Run';
    const form = fdFrom({
      tenant_id: state.tenantId,
      run_name: runName,
      template_id: $('generatorTemplateSelect').value,
      period_start: $('periodStart').value,
      period_end: $('periodEnd').value
    }, state.excelFiles, 'files');

    const data = await api('/api/generator-runs', { method: 'POST', body: form });
    state.generatorRunId = data.run_id;

    closeModal('generatorUploadModal');
    $('generatorReadySection').classList.add('hidden');
    $('generatorWorkspace').classList.remove('hidden');
    $('generatorReview').classList.add('hidden');
    $('generatedResult').classList.add('hidden');
    $('openMasterSummaryBtn').classList.add('hidden');
    $('mapperEnginePill').classList.add('hidden');

    $('kpiGenWorkbooks').textContent = state.excelFiles.length;
    $('kpiGenMappedRoles').textContent = '0 / 10';
    $('kpiGenCandidates').textContent = '0';

    $('generatorWorkspaceTitle').textContent = runName;
    $('generatorWorkspaceSub').textContent = 'Stage 1 · parallel isolated Excel agents analyzing each workbook.';
    $('generatorStatus').className = 'status-pill running';
    $('generatorStatus').innerHTML = '<i></i> Agents working';
    setGeneratorPausedState(false);
    $('generatorPauseBtn')?.classList.remove('hidden');
    $('sourceFileCount').textContent = state.excelFiles.length;
    setGeneratorStep(1);

    state.sourceFileStates = {};
    state.sourceFileOrder = state.excelFiles.map(f => f.name);
    state.excelFiles.forEach(f => {
      state.sourceFileStates[f.name] = {
        filename: f.name,
        status: 'queued',
        message: 'Launching isolated explorer agent…',
        md_artifact: null,
        py_artifact: null,
        profile: null
      };
    });
    renderLiveSourceCards();

    $('mappingContent').innerHTML = `
      <div class="empty-panel">
        <div class="skeleton" style="width:62%"></div>
        <div class="skeleton short"></div>
        <p style="margin-top:10px">Parallel agents are analyzing each Excel workbook in isolated sandboxes…</p>
      </div>
    `;

    updateGeneratorProgress('orchestrator', `Launched ${state.excelFiles.length} parallel Excel explorer agent(s)`, 15);

    state.generatorEvents?.close();
    state.generatorEvents = new EventSource(`/api/generator-runs/${state.generatorRunId}/events`);
    state.generatorEvents.onmessage = e => handleGeneratorEvent(JSON.parse(e.data));
    pollGeneratorRun();
  } catch (e) {
    toast(e.message);
    $('startGeneratorBtn').disabled = false;
  }
}

const SOURCE_STATUS_LABELS = {
  queued: 'QUEUED',
  reading_context: 'READING 100 LINES',
  analyzing: 'AGENT ACTIVE',
  writing_code: 'WRITING PYTHON',
  editing_code: 'EDITING PYTHON',
  running_terminal: 'RUNNING TERMINAL',
  writing_report: 'WRITING .MD',
  completed: 'READY',
  failed: 'FAILED'
};

function renderLiveSourceCards() {
  const names = state.sourceFileOrder.length
    ? state.sourceFileOrder
    : Object.keys(state.sourceFileStates);
  $('sourceFileCount').textContent = names.length;

  $('sourceExplorer').innerHTML = names.map((fname, pi) => {
    const info = state.sourceFileStates[fname] || { filename: fname, status: 'queued', message: 'Waiting…' };
    const status = info.status || 'queued';
    const isWorking = !['completed', 'failed'].includes(status);
    const badgeText = SOURCE_STATUS_LABELS[status] || status.toUpperCase();
    const sheets = info.profile?.sheets || [];
    const mdArtifact = info.md_artifact;
    const pyArtifact = info.py_artifact;

    return `
      <div class="source-file-card ${isWorking ? 'agent-working' : ''} ${status === 'failed' ? 'agent-failed' : ''}">
        <div class="source-file-head">
          <span class="file-ext xlsx-ext">XLSX</span>
          <b title="${esc(fname)}">${esc(fname)}</b>
          <span class="file-agent-pill ${esc(status)}">${isWorking ? '<i></i>' : ''}${esc(badgeText)}</span>
        </div>
        ${isWorking || status === 'failed' ? `
          <div class="source-live-line">${esc(info.message || 'Working in isolated sandbox…')}</div>
        ` : ''}
        ${sheets.length ? `
          <div class="sheet-list">
            ${sheets.map((s, si) => {
              const cols = s.columns || [];
              const drawerId = `sheet-cols-${pi}-${si}`;
              return `
                <div class="sheet-row">
                  <div class="sheet-row-head" data-toggle-sheet="${drawerId}">
                    <div>
                      <b>${esc(s.sheet)}</b>
                      <small>${s.row_count} rows · ${cols.length} cols · header ${s.header_row || 'none'}</small>
                    </div>
                    <span class="pill-count">${cols.length} ▾</span>
                  </div>
                  <div class="sheet-cols-drawer hidden" id="${drawerId}">
                    ${cols.slice(0, 24).map(c => `<span class="col-chip">${esc(c.name || c.column)}<em>${esc(c.inferred_type || '')}</em></span>`).join('')}
                    ${cols.length > 24 ? `<span class="col-chip">+${cols.length - 24} more</span>` : ''}
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        ` : ''}
        ${(mdArtifact || pyArtifact) ? `
          <div class="source-card-md-bar">
            <span class="source-md-name" title="${esc(mdArtifact || pyArtifact)}">${esc(mdArtifact || pyArtifact)}</span>
            <div class="source-card-btns">
              ${pyArtifact ? `<button type="button" class="source-py-btn" data-open-artifact="${esc(pyArtifact)}" title="Inspect reusable analysis.py">analysis.py</button>` : ''}
              ${mdArtifact ? `<button type="button" class="source-md-btn" data-open-artifact="${esc(mdArtifact)}" title="Preview generated Markdown analysis">Preview .md</button>` : ''}
            </div>
          </div>
        ` : ''}
      </div>
    `;
  }).join('');

  $('sourceExplorer').querySelectorAll('[data-toggle-sheet]').forEach(head => {
    head.addEventListener('click', () => {
      document.getElementById(head.dataset.toggleSheet)?.classList.toggle('hidden');
    });
  });

  $('sourceExplorer').querySelectorAll('[data-open-artifact]').forEach(btn => {
    btn.addEventListener('click', () => openArtifactViewer(btn.dataset.openArtifact));
  });
}

function handleGeneratorEvent(ev) {
  if (ev.type === 'CUSTOM' && ev.name === 'run.paused') {
    setGeneratorPausedState(true);
  }
  if (ev.type === 'CUSTOM' && ev.name === 'run.resumed') {
    setGeneratorPausedState(false);
  }
  if (ev.type === 'CUSTOM' && ev.name === 'source.file_status') {
    const v = ev.value || {};
    if (v.filename) {
      if (!state.sourceFileOrder.includes(v.filename)) {
        state.sourceFileOrder.push(v.filename);
      }
      const prev = state.sourceFileStates[v.filename] || {};
      state.sourceFileStates[v.filename] = {
        ...prev,
        filename: v.filename,
        status: v.status || prev.status || 'analyzing',
        message: v.message || prev.message || '',
        md_artifact: v.md_artifact || prev.md_artifact || null,
        py_artifact: v.py_artifact || prev.py_artifact || null,
        profile: v.profile || prev.profile || null
      };
      renderLiveSourceCards();
      const total = Math.max(1, state.sourceFileOrder.length);
      const doneCount = Object.values(state.sourceFileStates).filter(x => x.status === 'completed').length;
      const pct = Math.min(55, 15 + Math.round((doneCount / total) * 40));
      updateGeneratorProgress(
        `explorer (${doneCount}/${total})`,
        `${v.filename}: ${v.message || v.status}`,
        pct
      );
    }
  }
  if (ev.type === 'CUSTOM' && ev.name === 'source.master_ready') {
    const summaryBtn = $('openMasterSummaryBtn');
    summaryBtn.classList.remove('hidden');
    summaryBtn.onclick = () => openArtifactViewer('master_summary.md');
  }
  if (ev.type === 'CUSTOM' && ev.name === 'agent.activity') {
    const v = ev.value || {};
    const isMap = v.agent === 'mapper_agent';
    if (isMap) setGeneratorStep(2);
    updateGeneratorProgress(v.agent, v.message, isMap ? 76 : undefined);
    if (v.details?.table_id) upsertLiveTopicCard(v.details);
  }
  if (ev.type === 'CUSTOM' && ev.name === 'mapping.ready') {
    state.generatorEvents?.close();
    clearInterval(state.generatorPollTimer);
    $('generatorPauseBtn')?.classList.add('hidden');
    updateGeneratorProgress('mapper_agent', 'Mapping proposals ready for review', 100);
    loadGeneratorRun();
  }
  if (ev.type === 'RUN_ERROR') {
    state.generatorEvents?.close();
    clearInterval(state.generatorPollTimer);
    $('generatorPauseBtn')?.classList.add('hidden');
    $('generatorProgressStrip').classList.add('hidden');
    $('generatorStatus').className = 'status-pill draft';
    $('generatorStatus').textContent = 'Run failed';
    toast(ev.message || 'Generator run failed');
  }
}

function pollGeneratorRun() {
  clearInterval(state.generatorPollTimer);
  state.generatorPollTimer = setInterval(async () => {
    if (!state.generatorRunId) { clearInterval(state.generatorPollTimer); return; }
    try {
      const r = await api(`/api/generator-runs/${state.generatorRunId}`);
      if (r.status === 'paused') {
        setGeneratorPausedState(true);
      } else if (r.status === 'running' && state.generatorRunPaused) {
        setGeneratorPausedState(false);
      }
      if (['completed', 'failed'].includes(r.status)) {
        clearInterval(state.generatorPollTimer);
        state.generatorEvents?.close();
        $('generatorPauseBtn')?.classList.add('hidden');
        if (r.status === 'completed') await loadGeneratorRun();
        else {
          $('generatorProgressStrip').classList.add('hidden');
          $('generatorStatus').className = 'status-pill draft';
          $('generatorStatus').textContent = 'Run failed';
          toast(r.error || 'Generator run failed');
        }
      }
    } catch {
      clearInterval(state.generatorPollTimer);
    }
  }, 1000);
}

async function loadGeneratorRun() {
  const data = await api(`/api/generator-runs/${state.generatorRunId}`);
  if (data.status !== 'completed') return;
  state.generatorResult = data.result;

  $('generatorPauseBtn')?.classList.add('hidden');
  $('generatorProgressStrip').classList.add('hidden');
  $('generatorStatus').className = 'status-pill complete';
  $('generatorStatus').textContent = 'Ready for review';
  $('generatorWorkspaceSub').textContent = 'Stage 1 & 2 complete · inspect data dictionaries, verify column mappings and approve calculation unit.';
  setGeneratorStep(3);

  $('generatorReview').classList.remove('hidden');
  renderSourceExplorer(data.result.profiles || []);
  renderMappingWorkspace(data.result.source_mapping || {}, data.result);
  $('startGeneratorBtn').disabled = false;
}

function findWorkbookArtifact(filename, artifacts, ext = '.md') {
  if (!filename || !artifacts?.length) return null;
  const stem = filename.replace(/\.[^.]+$/, '');
  const cleanStem = stem.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 80);
  const exact = ext === '.py' ? `${cleanStem}_analysis.py` : `${cleanStem}.md`;
  if (artifacts.includes(exact)) return exact;
  const altExact = ext === '.py' ? `${stem.slice(0, 80).replace(/ /g, '_')}_analysis.py` : `${stem.slice(0, 80).replace(/ /g, '_')}.md`;
  if (artifacts.includes(altExact)) return altExact;
  const norm = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '');
  const target = norm(stem);
  return artifacts.find(a => {
    if (a === 'master_summary.md' || !a.toLowerCase().endsWith(ext)) return false;
    const base = ext === '.py' ? a.replace(/_analysis\.py$/i, '').replace(/\.py$/i, '') : a.replace(/\.md$/i, '');
    return norm(base) === target;
  }) || null;
}

function renderSourceExplorer(profiles) {
  const arts = state.generatorResult?.artifacts || [];
  const hasMasterSummary = arts.includes('master_summary.md');
  const summaryBtn = $('openMasterSummaryBtn');
  summaryBtn.classList.toggle('hidden', !hasMasterSummary);
  summaryBtn.onclick = hasMasterSummary ? () => openArtifactViewer('master_summary.md') : null;

  state.sourceFileOrder = profiles.map(p => p.filename);
  profiles.forEach(p => {
    const prev = state.sourceFileStates[p.filename] || {};
    state.sourceFileStates[p.filename] = {
      ...prev,
      filename: p.filename,
      status: 'completed',
      message: 'Analysis complete',
      profile: p,
      md_artifact: prev.md_artifact || findWorkbookArtifact(p.filename, arts, '.md'),
      py_artifact: prev.py_artifact || findWorkbookArtifact(p.filename, arts, '.py')
    };
  });
  renderLiveSourceCards();
}

async function openArtifactViewer(filename) {
  const url = `/api/generator-runs/${state.generatorRunId}/artifact/${encodeURIComponent(filename)}`;
  const isCode = /\.(py|json|txt)$/i.test(filename);
  $('artifactModalTitle').textContent = filename;
  $('downloadArtifactBtn').href = url;
  $('artifactModalBody').innerHTML = '<div class="skeleton"></div><div class="skeleton short"></div>';
  openModal('artifactModal');
  try {
    const r = await fetch(url);
    const text = await r.text();
    state.currentArtifactRaw = text;
    if (isCode) {
      $('artifactModalBody').innerHTML = `<pre class="code-preview">${esc(text)}</pre>`;
    } else {
      $('artifactModalBody').innerHTML = renderMarkdown(text);
    }
  } catch (e) {
    $('artifactModalBody').innerHTML = `<p style="color:var(--red)">Could not load artifact: ${esc(e.message)}</p>`;
  }
}

$('copyArtifactBtn').addEventListener('click', () => {
  navigator.clipboard.writeText(state.currentArtifactRaw || '').then(() => toast('Artifact Markdown copied'));
});

function makeColumnValue(c) {
  return JSON.stringify({ source_file: c.source_file, sheet: c.sheet, column: c.column });
}

function updateRoleCoverage() {
  const selects = Array.from(document.querySelectorAll('[data-map-role]'));
  const mapped = selects.filter(s => s.value).length;
  $('roleCoveragePill').textContent = `${mapped} / ${selects.length} mapped`;
  $('kpiGenMappedRoles').textContent = `${mapped} / ${selects.length}`;
}

function renderRoleMapping(mapping, candidates, allColumns) {
  const roles = Object.keys(ROLE_LABELS);
  $('roleMappingEditor').innerHTML = roles.map(role => {
    const current = mapping[role];
    const selected = current ? makeColumnValue(current) : '';
    const conf = current?.confidence ? String(current.confidence) : '';
    return `
      <div class="mapping-role">
        <div>
          <b>
            ${esc(ROLE_LABELS[role][0])}
            ${conf ? `<span class="conf-badge ${esc(conf)}">${esc(conf)}</span>` : ''}
          </b>
          <small>${esc(current?.rationale || ROLE_LABELS[role][1])}</small>
        </div>
        <select data-map-role="${role}">
          <option value="">Not mapped</option>
          ${allColumns.map(c => {
            const val = makeColumnValue(c);
            return `<option value='${esc(val)}' ${val === selected ? 'selected' : ''}>${esc(c.source_file)} · ${esc(c.sheet)} · ${esc(c.column)} (${esc(c.inferred_type)})</option>`;
          }).join('')}
        </select>
      </div>
    `;
  }).join('');

  document.querySelectorAll('[data-map-role]').forEach(sel => {
    sel.addEventListener('change', updateRoleCoverage);
  });
  updateRoleCoverage();
}

function upsertLiveTopicCard(d) {
  // Do not create a separate card for a continuation of an existing topic table
  if (d.numerator === undefined && !d.reason && d.evidence_count === undefined) return;
  const host = $('mappingContent');
  if (host.querySelector('.empty-panel')) host.innerHTML = '';
  let card = host.querySelector(`[data-live-topic="${CSS.escape(d.table_id)}"]`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'live-mapping-card';
    card.dataset.liveTopic = d.table_id;
    host.appendChild(card);
  }
  const status = String(d.status || 'processing').replaceAll('_', ' ').toUpperCase();
  const count = d.numerator !== undefined ? `${d.numerator} / ${d.denominator ?? '—'}` : (d.reason || 'Collecting source data');
  card.innerHTML = `
    <div class="live-mapping-head">
      <b>${esc(d.topic || 'Section 16.3 topic')}</b>
      <span>${esc(status)}</span>
    </div>
    <div class="live-mapping-count">${esc(count)}</div>
    <small>${esc(String(d.evidence_count ?? 0))} evidence rows prepared · ${esc(d.table_id)}</small>
  `;
}

function renderMappingWorkspace(mappingResult, result) {
  const metrics = getMergedTopicMetrics(mappingResult.topic_metrics || []);
  const mappedCount = Object.values(mappingResult.column_mapping || {}).filter(Boolean).length;
  const totalRoles = Object.keys(ROLE_LABELS).length;

  $('mappedTopicCount').textContent = `${metrics.length} TOPIC${metrics.length === 1 ? '' : 'S'}`;

  const enginePill = $('mapperEnginePill');
  enginePill.classList.remove('hidden');
  enginePill.textContent = mappingResult.bedrock_used ? 'Bedrock LLM Mapper' : 'Local Schema Mapper';

  renderRoleMapping(mappingResult.column_mapping || {}, mappingResult.mapping_candidates || {}, mappingResult.all_columns || []);

  const warningsHtml = (mappingResult.bedrock_warnings || []).length
    ? `<div class="bedrock-warnings-box"><b>Mapper notes:</b><br>${mappingResult.bedrock_warnings.map(w => `• ${esc(w)}`).join('<br>')}</div>`
    : '';

  const readyCount = metrics.filter(m => m.status === 'calculated_candidate').length;
  $('kpiGenWorkbooks').textContent = (result.profiles || []).length;
  $('kpiGenCandidates').textContent = `${readyCount} / ${metrics.length}`;
  $('mappingContent').innerHTML = `
    <div class="mapping-summary-banner">
      <div>
        <b>${mappedCount} of ${totalRoles} canonical roles mapped · ${readyCount} of ${metrics.length} topics calculated</b>
        <p>Inspect and adjust column mappings below, confirm your calculation unit, and enter updated narratives.</p>
      </div>
      <span class="status-pill complete">PROPOSALS READY</span>
    </div>
    ${warningsHtml}
    ${metrics.map((m, i) => {
      const ready = m.status === 'calculated_candidate';
      const val = ready ? `${m.numerator} / ${m.denominator} (${m.percentage ?? '—'}%)` : (m.reason || 'Requires manual review');
      return `
        <div class="live-mapping-card">
          <div class="live-mapping-head">
            <b>16.3 · ${i + 1} — ${esc(m.topic_heading || 'Topic table')}</b>
            <span>${ready ? 'CANDIDATE' : 'REVIEW'}</span>
          </div>
          <div class="live-mapping-count">${esc(val)}</div>
          <small>${ready ? `${esc(m.count_mode)} · ${esc(String(m.matched_records || 0))} matching rows` : 'Check criteria & role mapping below'}</small>
        </div>
      `;
    }).join('')}
  `;

  renderTopicReviewCards(metrics);
  $('generationReadiness').textContent = `${readyCount} calculated candidate${readyCount === 1 ? '' : 's'} · ${metrics.length} Section 16.3 topic block${metrics.length === 1 ? '' : 's'}`;
}

function renderTopicReviewCards(metrics) {
  $('topicReviewList').innerHTML = metrics.map((m, i) => {
    const warn = (m.warnings || []).concat(m.reason ? [m.reason] : []);
    const ready = m.status === 'calculated_candidate';
    const evidence = m.evidence || [];
    const extraEvidence = evidence.slice(3);
    const evId = `extra-ev-${i}`;
    return `
      <div class="topic-review-card" data-topic-status="${ready ? 'ready' : 'review'}" data-topic-title="${esc((m.topic_heading || '').toLowerCase())}">
        <div class="topic-card-head">
          <span class="topic-badge">16.3 · ${i + 1}</span>
          <b>${esc(m.topic_heading || 'Topic table')}</b>
          <small class="${ready ? '' : 'needs-review'}">${ready ? 'CANDIDATE' : 'REVIEW'}</small>
        </div>
        ${ready ? `
          <div class="metric-strip">
            <div class="metric-box"><small>TOPIC COUNT</small><b>${esc(String(m.numerator))}</b></div>
            <div class="metric-box"><small>TOTAL</small><b>${esc(String(m.denominator))}</b></div>
            <div class="metric-box"><small>PERCENT</small><b>${m.percentage === null ? '—' : esc(String(m.percentage)) + '%'}</b></div>
          </div>
        ` : ''}
        <div class="topic-review-body">
          ${warn.map(w => `<div class="metric-warning">${esc(w)}</div>`).join('')}
          ${ready ? `
            <div class="evidence-line">${esc(m.count_mode)} · ${esc(String(m.matched_records))} matching rows · ${esc(String(evidence.length))} evidence rows</div>
            ${evidence.slice(0, 3).map(e => `<div class="evidence-line">${esc(e.source_file)} · ${esc(e.sheet)} · row ${e.excel_row} · ${esc(e.case_cell)} / ${esc(e.event_cell)}</div>`).join('')}
            ${extraEvidence.length ? `
              <div class="hidden" id="${evId}">
                ${extraEvidence.map(e => `<div class="evidence-line">${esc(e.source_file)} · ${esc(e.sheet)} · row ${e.excel_row} · ${esc(e.case_cell)} / ${esc(e.event_cell)}</div>`).join('')}
              </div>
              <button type="button" class="evidence-more-btn" data-expand-ev="${evId}">+ Show ${extraEvidence.length} more evidence rows</button>
            ` : ''}
          ` : ''}
          <label class="narrative-label">EVALUATION · NEW INTERVAL</label>
          <textarea class="narrative-input" data-narrative="evaluation" data-table="${esc(m.table_id)}" data-linked-tables='${esc(JSON.stringify(m.linked_table_ids || [m.table_id]))}' placeholder="Enter updated evaluation text. Prior-period narrative is never copied automatically."></textarea>
          <label class="narrative-label">CONCLUSION · NEW INTERVAL</label>
          <textarea class="narrative-input" data-narrative="conclusion" data-table="${esc(m.table_id)}" data-linked-tables='${esc(JSON.stringify(m.linked_table_ids || [m.table_id]))}' placeholder="Enter updated conclusion for this topic."></textarea>
          <label class="narrative-label">DATA SOURCE REFERENCE</label>
          <input class="narrative-input" style="min-height:auto" data-narrative="data_source" data-table="${esc(m.table_id)}" data-linked-tables='${esc(JSON.stringify(m.linked_table_ids || [m.table_id]))}' placeholder="e.g. data on file, product, Tables X, Y">
        </div>
      </div>
    `;
  }).join('');

  $('topicReviewList').querySelectorAll('[data-expand-ev]').forEach(btn => {
    btn.addEventListener('click', () => {
      const box = document.getElementById(btn.dataset.expandEv);
      const isHidden = box.classList.toggle('hidden');
      btn.textContent = isHidden ? `+ Show more evidence rows` : '− Hide extra evidence rows';
    });
  });

  $('topicReviewList').querySelectorAll('[data-narrative]').forEach(inp => {
    inp.addEventListener('input', updateNarrativeProgress);
  });

  updateNarrativeProgress();
  applyTopicReviewFilters();
}

function updateNarrativeProgress() {
  const cards = document.querySelectorAll('#topicReviewList .topic-review-card');
  let filled = 0;
  cards.forEach(c => {
    const ev = c.querySelector('[data-narrative="evaluation"]')?.value.trim();
    const conc = c.querySelector('[data-narrative="conclusion"]')?.value.trim();
    if (ev || conc) filled++;
  });
  $('narrativeProgressPill').textContent = `${filled} / ${cards.length} narratives entered`;
}

function applyTopicReviewFilters() {
  const q = ($('topicReviewSearch')?.value || '').trim().toLowerCase();
  document.querySelectorAll('#topicReviewList .topic-review-card').forEach(card => {
    const statusOk = state.topicFilter === 'all' || card.dataset.topicStatus === state.topicFilter;
    const textOk = !q || (card.dataset.topicTitle || '').includes(q);
    card.classList.toggle('hidden', !(statusOk && textOk));
  });
}

$('topicReviewSearch').addEventListener('input', applyTopicReviewFilters);
document.querySelectorAll('[data-topic-filter]').forEach(btn => {
  btn.addEventListener('click', () => {
    state.topicFilter = btn.dataset.topicFilter;
    document.querySelectorAll('[data-topic-filter]').forEach(b => b.classList.toggle('active', b === btn));
    applyTopicReviewFilters();
  });
});

$('generateDocxBtn').addEventListener('click', generateReport);

async function generateReport() {
  if (!state.generatorRunId) return;
  if (!$('countMode').value) {
    toast('Choose the counting unit before approving generation.');
    $('countModeCards').scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }
  const mapping = {};
  document.querySelectorAll('[data-map-role]').forEach(el => {
    mapping[el.dataset.mapRole] = el.value ? JSON.parse(el.value) : null;
  });
  const narratives = {};
  document.querySelectorAll('[data-narrative]').forEach(el => {
    const key = el.dataset.narrative;
    let ids = [el.dataset.table];
    try {
      const parsed = JSON.parse(el.dataset.linkedTables || '[]');
      if (Array.isArray(parsed) && parsed.length) ids = parsed;
    } catch {}
    for (const id of ids) {
      narratives[id] ??= {};
      narratives[id][key] = el.value;
    }
  });

  $('generateDocxBtn').disabled = true;
  try {
    const data = await api(`/api/generator-runs/${state.generatorRunId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approved: true,
        count_mode: $('countMode').value,
        column_mapping: mapping,
        narratives
      })
    });
    state.generated = data;
    setGeneratorStep(4);
    $('generatorStatus').className = 'status-pill complete';
    $('generatorStatus').textContent = 'DOCX generated';
    $('generatedResult').classList.remove('hidden');
    $('generatedFilename').textContent = `${data.output_filename} · ${(data.render?.updated_tables || []).length} tables updated`;
    $('downloadGenerated').href = data.output_url;
    const warnings = (data.render?.warnings || []).concat(data.review_notes || []);
    $('generatedWarnings').innerHTML = warnings.map(w => `<div>• ${esc(w)}</div>`).join('');
    $('generatedResult').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    toast('DOCX report generated');
  } catch (e) {
    toast(e.message);
  } finally {
    $('generateDocxBtn').disabled = false;
  }
}

/* ==================== INIT ==================== */
(async function init() {
  try {
    await Promise.all([loadHealth(), loadTenants()]);
    await loadTemplateHistory(true);
    await refreshApprovedTemplates();
  } catch (e) {
    toast(`Startup error: ${e.message}`);
  }
})();
