/**
 * Tracewise · PBRER Document Intelligence & Agent Autonomy Client
 * AG-UI Protocol Streaming, Bifurcated Target-Source Inspector, Sandboxed Code Execution Telemetry
 */

// Global State
let currentRunId = null;
let currentRunData = null;
let currentMappings = [];
let activeSourceFile = null;
let activeSheetName = null;
let eventSource = null;
let lastEventIdx = 0;
let pollingInterval = null;
let activeFilter = 'all';

// DOM Elements
const targetFileInput = document.querySelector('#targetFileInput');
const sourceFilesInput = document.querySelector('#sourceFilesInput');
const targetFileStatus = document.querySelector('#targetFileStatus');
const sourceFilesStatus = document.querySelector('#sourceFilesStatus');
const btnLaunchAgents = document.querySelector('#btnLaunchAgents');
const btnDemoBundle = document.querySelector('#btnDemoBundle');
const btnReset = document.querySelector('#btnReset');
const tenantInput = document.querySelector('#tenantInput');

const workspaceSection = document.querySelector('#workspaceSection');
const outlineContainer = document.querySelector('#outlineContainer');
const sectionCountBadge = document.querySelector('#sectionCountBadge');
const agUiFeed = document.querySelector('#agUiFeed');
const sandboxFilesList = document.querySelector('#sandboxFilesList');
const sandboxFilesCount = document.querySelector('#sandboxFilesCount');
const sourceFilesTabs = document.querySelector('#sourceFilesTabs');
const sourceDataInspector = document.querySelector('#sourceDataInspector');
const sourceCountBadge = document.querySelector('#sourceCountBadge');
const agentFocusBeacon = document.querySelector('#agentFocusBeacon');
const beaconStatusText = document.querySelector('#beaconStatusText');

// Modals
const sectionModal = document.querySelector('#sectionModal');
const modalCloseBtn = document.querySelector('#modalCloseBtn');
const modalSectionId = document.querySelector('#modalSectionId');
const modalSectionTitle = document.querySelector('#modalSectionTitle');
const modalSectionStatus = document.querySelector('#modalSectionStatus');
const modalSectionConfidence = document.querySelector('#modalSectionConfidence');
const modalTargetText = document.querySelector('#modalTargetText');
const modalMappedSources = document.querySelector('#modalMappedSources');
const modalRulesList = document.querySelector('#modalRulesList');
const modalPythonCode = document.querySelector('#modalPythonCode');
const modalExistingNotes = document.querySelector('#modalExistingNotes');
const modalNoteInput = document.querySelector('#modalNoteInput');
const btnSubmitNote = document.querySelector('#btnSubmitNote');
let activeModalSection = null;

const matrixModal = document.querySelector('#matrixModal');
const matrixCloseBtn = document.querySelector('#matrixCloseBtn');
const btnViewMatrix = document.querySelector('#btnViewMatrix');
const matrixTableBody = document.querySelector('#matrixTableBody');
const btnExportMatrix = document.querySelector('#btnExportMatrix');

// Filter Tabs
document.querySelectorAll('.filter-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    activeFilter = tab.dataset.filter;
    applyFeedFilter();
  });
});

// Search input
document.querySelector('#sectionSearchInput').addEventListener('input', (e) => {
  const query = e.target.value.toLowerCase().trim();
  document.querySelectorAll('.outline-card').forEach(card => {
    const title = card.querySelector('.section-card-title').textContent.toLowerCase();
    const id = card.querySelector('.section-id-tag').textContent.toLowerCase();
    card.style.display = (title.includes(query) || id.includes(query)) ? 'flex' : 'none';
  });
});

// File input handlers
targetFileInput.addEventListener('change', updateFileSelection);
sourceFilesInput.addEventListener('change', updateFileSelection);

function updateFileSelection() {
  const target = targetFileInput.files[0];
  const sources = [...sourceFilesInput.files];

  if (target) {
    targetFileStatus.textContent = `✓ ${target.name} (${(target.size / 1024).toFixed(1)} KB)`;
    targetFileStatus.className = 'file-status selected';
  } else {
    targetFileStatus.textContent = 'No target file chosen';
    targetFileStatus.className = 'file-status muted';
  }

  if (sources.length > 0) {
    sourceFilesStatus.textContent = `✓ ${sources.length} file(s) selected: ` + sources.map(s => s.name).join(', ');
    sourceFilesStatus.className = 'file-status selected';
  } else {
    sourceFilesStatus.textContent = 'No source files chosen';
    sourceFilesStatus.className = 'file-status muted';
  }

  btnLaunchAgents.disabled = !(target && sources.length > 0);
}

// Reset button
btnReset.addEventListener('click', () => {
  if (confirm('Reset workspace and clear current run?')) {
    window.location.reload();
  }
});

// One-Click Demo Bundle Loader
btnDemoBundle.addEventListener('click', async () => {
  try {
    btnDemoBundle.disabled = true;
    btnDemoBundle.innerHTML = '<span class="pulse-dot"></span> Generating PBRER Data…';

    const formData = new FormData();
    formData.append('tenant_id', tenantInput.value.trim() || 'Apex-PBRER-Demo');

    const res = await fetch('/api/runs/demo', {
      method: 'POST',
      body: formData
    });

    if (!res.ok) throw new Error('Failed to load sample bundle');
    const data = await res.json();
    setupRunUI(data);

    // Auto-launch agents for smooth demo experience
    launchAgentsExecution();
  } catch (err) {
    alert('Error generating sample bundle: ' + err.message);
  } finally {
    btnDemoBundle.disabled = false;
    btnDemoBundle.innerHTML = '<span class="btn-icon">⚡</span> Load PBRER Sample Bundle';
  }
});

// Launch Agents button
btnLaunchAgents.addEventListener('click', async () => {
  if (!currentRunId) {
    // Need to upload files first
    await uploadAndProfileFiles();
  }
  launchAgentsExecution();
});

async function uploadAndProfileFiles() {
  btnLaunchAgents.disabled = true;
  btnLaunchAgents.innerHTML = '<span class="pulse-dot"></span> Profiling Documents…';

  const formData = new FormData();
  formData.append('tenant_id', tenantInput.value.trim() || 'Tenant-PBRER');
  formData.append('target', targetFileInput.files[0]);
  [...sourceFilesInput.files].forEach(f => formData.append('sources', f));

  try {
    const res = await fetch('/api/runs', { method: 'POST', body: formData });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Upload failed');
    }
    const data = await res.json();
    setupRunUI(data);
  } catch (err) {
    alert('Upload error: ' + err.message);
    btnLaunchAgents.disabled = false;
    btnLaunchAgents.innerHTML = '<span>Launch Autonomous Agents</span> <span class="arrow">➔</span>';
    throw err;
  }
}

function setupRunUI(data) {
  currentRunId = data.run_id;
  currentRunData = data;

  // Reveal workspace
  workspaceSection.classList.remove('hidden');
  workspaceSection.scrollIntoView({ behavior: 'smooth' });

  // Update run labels
  document.querySelector('#runIdDisplay').textContent = `Run ${currentRunId.slice(0, 8)}`;
  document.querySelector('#runStatsDisplay').textContent = `${data.files.length} files profiled • ${data.target_outline.length} sections detected`;

  // Render Left Panel (Outline)
  renderOutline(data.target_outline);

  // Render Right Panel (Source files tabs)
  renderSourceTabs(data.files.filter(f => f.role === 'source'));
}

async function launchAgentsExecution() {
  if (!currentRunId) return;

  btnLaunchAgents.disabled = true;
  btnLaunchAgents.innerHTML = '<span class="pulse-dot"></span> Agents Investigating…';

  try {
    const res = await fetch(`/api/runs/${currentRunId}/launch-agents`, { method: 'POST' });
    if (!res.ok) throw new Error('Could not launch agents');

    // Connect to AG-UI Stream
    connectAgUiStream(currentRunId);
    startPolling(currentRunId);
  } catch (err) {
    alert('Agent launch error: ' + err.message);
    btnLaunchAgents.disabled = false;
  }
}

// AG-UI PROTOCOL STREAMING (SSE + POLLING FALLBACK)
function connectAgUiStream(runId) {
  if (eventSource) {
    eventSource.close();
  }

  // Clear feed placeholder
  agUiFeed.innerHTML = '';

  eventSource = new EventSource(`/api/runs/${runId}/stream`);

  eventSource.onmessage = (event) => {
    try {
      const evt = JSON.parse(event.data);
      handleAgUiEvent(evt);
    } catch (e) {
      console.warn('SSE parse error:', e);
    }
  };

  eventSource.onerror = () => {
    // Fall back smoothly to polling
    console.log('SSE connection dropped or waiting, polling active.');
  };
}

function startPolling(runId) {
  if (pollingInterval) clearInterval(pollingInterval);
  pollingInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/events?since_idx=${lastEventIdx}`);
      if (res.ok) {
        const data = await res.json();
        data.events.forEach(evt => handleAgUiEvent(evt));
      }
      // Also poll mappings and sandbox files
      fetchMappings(runId);
      fetchSandboxFiles(runId);
    } catch (e) {
      console.warn('Polling error:', e);
    }
  }, 1200);
}

function handleAgUiEvent(evt) {
  lastEventIdx++;

  // Update Agent Roster Chip
  highlightActiveAgent(evt.agent_id);

  // Update Agent Focus Beacon (Right panel)
  if (evt.event_type === 'file_focus' || evt.event_type === 'agent_filtering') {
    updateFocusBeacon(evt);
  }

  // Render Telemetry Card in Feed
  renderTelemetryCard(evt);

  // If section mapped, refresh left panel outline
  if (evt.event_type === 'section_mapped' || evt.event_type === 'rule_created') {
    fetchMappings(evt.run_id);
  }

  // If completed, update banner
  if (evt.event_type === 'orchestration_status') {
    document.querySelector('#runStatsDisplay').textContent = 'Orchestration & Verification Complete (100% Deterministic)';
    btnLaunchAgents.innerHTML = '<span>Agents Completed ✓</span>';
    btnLaunchAgents.disabled = false;
    clearInterval(pollingInterval);
  }
}

function highlightActiveAgent(agentId) {
  document.querySelectorAll('.agent-chip').forEach(c => c.classList.remove('active'));
  let targetId = 'chip-orchestrator';
  if (agentId.includes('exposure')) targetId = 'chip-exposure';
  else if (agentId.includes('safety')) targetId = 'chip-safety';
  else if (agentId.includes('signal')) targetId = 'chip-signals';
  else if (agentId.includes('auditor')) targetId = 'chip-auditor';

  const el = document.getElementById(targetId);
  if (el) el.classList.add('active');
}

function updateFocusBeacon(evt) {
  agentFocusBeacon.className = 'agent-focus-beacon active';
  const fileName = evt.details.filename || evt.details.file || 'Source File';
  const sheet = evt.details.sheet ? ` [Sheet: ${evt.details.sheet}]` : '';
  const op = evt.details.operation || (evt.event_type === 'agent_filtering' ? 'Filtering criteria' : 'Reading');

  beaconStatusText.innerHTML = `<b>${evt.agent_name}</b> is ${op} in <u>${fileName}</u>${sheet}`;

  // Switch to this file tab if not already active
  const matchingTab = [...document.querySelectorAll('.source-tab')].find(t => t.dataset.filename === fileName);
  if (matchingTab && !matchingTab.classList.contains('active')) {
    matchingTab.click();
  }
}

// Render Telemetry Card
function renderTelemetryCard(evt) {
  const card = document.createElement('div');
  card.className = `telemetry-card filter-item-${getFilterCategory(evt.event_type)}`;
  card.dataset.type = evt.event_type;

  const top = document.createElement('div');
  top.className = 'telemetry-top';

  const agent = document.createElement('div');
  agent.className = 'telemetry-agent';

  const agentBadge = document.createElement('span');
  agentBadge.className = 'agent-badge';
  agentBadge.textContent = `${getAgentIcon(evt.agent_id)} ${evt.agent_name}`;

  const typeBadge = document.createElement('span');
  typeBadge.className = `event-type-badge type-${getTypeClass(evt.event_type)}`;
  typeBadge.textContent = evt.event_type.replaceAll('_', ' ');

  agent.append(agentBadge, typeBadge);

  const timeSpan = document.createElement('span');
  timeSpan.className = 'telemetry-time';
  const dt = new Date(evt.timestamp);
  timeSpan.textContent = dt.toLocaleTimeString();

  top.append(agent, timeSpan);

  const summary = document.createElement('div');
  summary.className = 'telemetry-summary';
  summary.textContent = evt.summary;

  card.append(top, summary);

  // If code generating: show code block
  if (evt.event_type === 'code_generating' && evt.details.code) {
    const codeBox = document.createElement('pre');
    codeBox.className = 'telemetry-codebox';
    codeBox.textContent = evt.details.code;
    card.append(codeBox);
  }

  // If code execution: show terminal output
  if (evt.event_type === 'code_execution') {
    const term = document.createElement('div');
    term.className = 'telemetry-terminal';
    term.innerHTML = `<strong>SANDBOX EXECUTION (${evt.details.duration_ms || 0} ms, Exit ${evt.details.exit_code}):</strong><br>${escapeHtml(evt.details.stdout || 'Program completed without output')}`;
    card.append(term);
  }

  // If A2A message: show flow details
  if (evt.event_type === 'a2a_message' && evt.details.from) {
    const a2aBox = document.createElement('div');
    a2aBox.className = 'telemetry-terminal';
    a2aBox.style.borderLeftColor = 'var(--accent-purple)';
    a2aBox.innerHTML = `<strong>A2A DISPATCH:</strong> ${evt.details.from} ➔ ${evt.details.to} <br><em>Intent: ${evt.details.intent || 'orchestrate'}</em>`;
    card.append(a2aBox);
  }

  agUiFeed.appendChild(card);
  agUiFeed.scrollTop = agUiFeed.scrollHeight;

  // Apply current filter
  if (activeFilter !== 'all' && !card.classList.contains(`filter-item-${activeFilter}`)) {
    card.style.display = 'none';
  }
}

function getFilterCategory(type) {
  if (type === 'code_generating' || type === 'code_execution') return 'code';
  if (type === 'a2a_message' || type === 'agent_thought') return 'a2a';
  if (type === 'rule_created' || type === 'section_mapped') return 'rules';
  return 'other';
}

function applyFeedFilter() {
  document.querySelectorAll('.telemetry-card').forEach(card => {
    if (activeFilter === 'all') {
      card.style.display = 'flex';
    } else if (card.classList.contains(`filter-item-${activeFilter}`)) {
      card.style.display = 'flex';
    } else {
      card.style.display = 'none';
    }
  });
}

function getAgentIcon(agentId) {
  if (agentId.includes('exposure')) return '📊';
  if (agentId.includes('safety')) return '🛡️';
  if (agentId.includes('signal')) return '🚨';
  if (agentId.includes('auditor')) return '🔍';
  if (agentId.includes('user')) return '👤';
  return '👔';
}

function getTypeClass(type) {
  if (type.includes('thought')) return 'thought';
  if (type.includes('a2a')) return 'a2a';
  if (type.includes('focus')) return 'focus';
  if (type.includes('filter')) return 'filter';
  if (type.includes('code')) return 'code';
  if (type.includes('exec')) return 'exec';
  if (type.includes('rule')) return 'rule';
  if (type.includes('note')) return 'guidance';
  return 'thought';
}

// LEFT PANEL: TARGET REPORT OUTLINE
function renderOutline(outline) {
  sectionCountBadge.textContent = `${outline.length} sections`;
  outlineContainer.innerHTML = '';

  outline.forEach(sec => {
    const card = document.createElement('div');
    card.className = 'outline-card';
    card.dataset.sectionId = sec.id;

    const top = document.createElement('div');
    top.className = 'outline-card-top';

    const idTag = document.createElement('span');
    idTag.className = 'section-id-tag';
    idTag.textContent = sec.id.toUpperCase();

    const statusTag = document.createElement('span');
    statusTag.className = 'section-status-tag status-pending';
    statusTag.textContent = 'Pending';
    statusTag.id = `status-tag-${sec.id.replace('.', '_')}`;

    top.append(idTag, statusTag);

    const title = document.createElement('div');
    title.className = 'section-card-title';
    title.textContent = sec.title;

    const meta = document.createElement('div');
    meta.className = 'section-source-meta';
    meta.textContent = `Target Source: ${sec.source || 'Report text'}`;

    card.append(top, title, meta);
    card.addEventListener('click', () => openSectionModal(sec.id));

    outlineContainer.appendChild(card);
  });
}

// FETCH MAPPINGS FROM BACKEND
async function fetchMappings(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}/mappings`);
    if (!res.ok) return;
    const data = await res.json();
    currentMappings = data.mappings || [];

    currentMappings.forEach(m => {
      const tag = document.querySelector(`#status-tag-${m.section_id.replace('.', '_')}`);
      if (tag) {
        if (m.status === 'rules_compiled') {
          tag.className = 'section-status-tag status-compiled';
          tag.textContent = 'Rules Compiled';
        } else if (m.status === 'verified') {
          tag.className = 'section-status-tag status-verified';
          tag.textContent = 'Reviewer Verified';
        }
      }
    });
  } catch (e) {
    console.warn('Fetch mappings error:', e);
  }
}

// FETCH SANDBOX FILES
async function fetchSandboxFiles(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}/sandbox-files`);
    if (!res.ok) return;
    const data = await res.json();
    const files = data.files || [];
    sandboxFilesCount.textContent = `${files.length} files`;

    sandboxFilesList.innerHTML = '';
    files.forEach(f => {
      const chip = document.createElement('span');
      chip.className = 'sandbox-file-chip';
      chip.textContent = `${f.is_script ? '🐍' : '📄'} ${f.name}`;
      chip.title = `Click to inspect ${f.name} (${f.size} bytes)`;
      chip.addEventListener('click', () => inspectSandboxFile(runId, f.name));
      sandboxFilesList.appendChild(chip);
    });
  } catch (e) {
    console.warn('Sandbox files error:', e);
  }
}

async function inspectSandboxFile(runId, filename) {
  try {
    const res = await fetch(`/api/runs/${runId}/sandbox-files/${filename}`);
    if (!res.ok) throw new Error('File not found');
    const data = await res.json();
    alert(`--- ${filename} ---\n\n` + data.content.slice(0, 1500) + (data.content.length > 1500 ? '\n...[truncated]' : ''));
  } catch (e) {
    alert(e.message);
  }
}

// SECTION DETAIL DRAWER / MODAL
function openSectionModal(sectionId) {
  const mapping = currentMappings.find(m => m.section_id === sectionId) || {
    section_id: sectionId,
    section_title: 'PBRER Section',
    status: 'pending',
    confidence: 1.0,
    mapped_sources: [],
    rules: [],
    python_script: '# Agent investigation in progress...'
  };

  activeModalSection = sectionId;

  modalSectionId.textContent = mapping.section_id.toUpperCase();
  modalSectionTitle.textContent = mapping.section_title;
  modalSectionStatus.textContent = mapping.status === 'rules_compiled' ? 'Rules Compiled' : (mapping.status === 'verified' ? 'Reviewer Verified' : 'Pending');
  modalSectionConfidence.textContent = `${Math.round(mapping.confidence * 100)}%`;

  modalTargetText.textContent = mapping.section_title;

  // Mapped Sources
  modalMappedSources.innerHTML = '';
  if (mapping.mapped_sources && mapping.mapped_sources.length > 0) {
    mapping.mapped_sources.forEach(src => {
      const c = document.createElement('div');
      c.className = 'mapped-source-card';
      c.innerHTML = `
        <div><b>Source File:</b> ${src.filename} &bull; <b>Sheet:</b> ${src.sheet}</div>
        <div><b>Columns:</b> ${src.columns ? src.columns.join(', ') : 'All'} &bull; <b>Cell Range:</b> ${src.rows_range || 'All rows'}</div>
        <div><b>Data Derivation:</b> ${src.formula || 'Direct mapping'}</div>
      `;
      modalMappedSources.appendChild(c);
    });
  } else {
    modalMappedSources.innerHTML = '<span class="text-dim">No source files mapped yet.</span>';
  }

  // Rules
  modalRulesList.innerHTML = '';
  if (mapping.rules && mapping.rules.length > 0) {
    mapping.rules.forEach(r => {
      const rc = document.createElement('div');
      rc.className = 'rule-card';
      rc.innerHTML = `
        <div><b>${r.rule_id}: ${r.name}</b></div>
        <div>${r.description}</div>
        <div><code>Logic: ${r.logic}</code></div>
      `;
      modalRulesList.appendChild(rc);
    });
  } else {
    modalRulesList.innerHTML = '<span class="text-dim">Rules will appear once agent finishes analysis.</span>';
  }

  // Python Code
  modalPythonCode.textContent = mapping.python_script || '# Script will be displayed once generated by agent';

  // Notes
  renderModalNotes(mapping.user_notes || []);

  sectionModal.classList.remove('hidden');
}

modalCloseBtn.addEventListener('click', () => {
  sectionModal.classList.add('hidden');
});

function renderModalNotes(notes) {
  modalExistingNotes.innerHTML = '';
  if (!notes || notes.length === 0) {
    modalExistingNotes.innerHTML = '<span class="text-dim" style="font-size: 11px;">No reviewer feedback added for this section yet.</span>';
    return;
  }
  notes.forEach(n => {
    const div = document.createElement('div');
    div.className = 'note-item';
    div.textContent = `Reviewer Note: ${n}`;
    modalExistingNotes.appendChild(div);
  });
}

// Submit Reviewer Note / Steering Guidance
btnSubmitNote.addEventListener('click', async () => {
  const noteText = modalNoteInput.value.trim();
  if (!noteText || !activeModalSection || !currentRunId) return;

  btnSubmitNote.disabled = true;
  btnSubmitNote.textContent = 'Submitting to Agent…';

  try {
    const res = await fetch(`/api/runs/${currentRunId}/user-notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_id: activeModalSection, note: noteText })
    });

    if (!res.ok) throw new Error('Failed to submit note');
    modalNoteInput.value = '';

    // Add note locally to view
    const m = currentMappings.find(x => x.section_id === activeModalSection);
    if (m) {
      if (!m.user_notes) m.user_notes = [];
      m.user_notes.push(noteText);
      renderModalNotes(m.user_notes);
      modalSectionStatus.textContent = 'Reviewer Verified';
    }

    // Refresh
    fetchMappings(currentRunId);
  } catch (err) {
    alert('Note submission error: ' + err.message);
  } finally {
    btnSubmitNote.disabled = false;
    btnSubmitNote.textContent = 'Submit Guidance to Agent';
  }
});

// RIGHT PANEL: SOURCE FILES & DATA INSPECTOR
function renderSourceTabs(sourceFiles) {
  sourceCountBadge.textContent = `${sourceFiles.length} files`;
  sourceFilesTabs.innerHTML = '';

  sourceFiles.forEach((f, idx) => {
    const tab = document.createElement('div');
    tab.className = `source-tab ${idx === 0 ? 'active' : ''}`;
    tab.dataset.filename = f.filename;
    tab.dataset.storedName = f.stored_name;
    tab.textContent = `▧ ${f.filename}`;

    tab.addEventListener('click', () => {
      document.querySelectorAll('.source-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      inspectSourceFile(f.stored_name, f.filename);
    });

    sourceFilesTabs.appendChild(tab);
  });

  if (sourceFiles.length > 0) {
    inspectSourceFile(sourceFiles[0].stored_name, sourceFiles[0].filename);
  }
}

async function inspectSourceFile(storedName, originalFilename) {
  if (!currentRunId) return;
  activeSourceFile = originalFilename;

  try {
    const res = await fetch(`/api/runs/${currentRunId}/sources/${storedName}/preview`);
    if (!res.ok) throw new Error('Could not load file profile');
    const profile = await res.json();

    renderSheetInspector(profile, originalFilename);
  } catch (err) {
    sourceDataInspector.innerHTML = `<div class="empty-inspector">Could not load preview: ${err.message}</div>`;
  }
}

function renderSheetInspector(profile, filename) {
  sourceDataInspector.innerHTML = '';

  if (profile.kind === 'excel') {
    const sheets = profile.sheets || [];
    if (sheets.length === 0) {
      sourceDataInspector.innerHTML = '<div class="empty-inspector">No sheets found in Excel file</div>';
      return;
    }

    // Sheet pills selector
    const pillRow = document.createElement('div');
    pillRow.className = 'sheet-selector-row';

    sheets.forEach((s, idx) => {
      const pill = document.createElement('button');
      pill.className = `sheet-pill ${idx === 0 ? 'active' : ''}`;
      pill.textContent = `${s.sheet} (${s.row_count} rows)`;
      pill.addEventListener('click', () => {
        pillRow.querySelectorAll('.sheet-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        renderTableData(s);
      });
      pillRow.appendChild(pill);
    });

    sourceDataInspector.appendChild(pillRow);

    // Initial table render for sheet 0
    renderTableData(sheets[0]);
  } else if (profile.kind === 'csv') {
    renderTableData(profile);
  } else {
    sourceDataInspector.innerHTML = `<div class="empty-inspector">${profile.kind.toUpperCase()} document content is profiled.</div>`;
  }
}

function renderTableData(sheetObj) {
  const existingTable = sourceDataInspector.querySelector('.data-table-wrapper');
  if (existingTable) existingTable.remove();

  const wrapper = document.createElement('div');
  wrapper.className = 'data-table-wrapper';

  const table = document.createElement('table');
  table.className = 'source-table';

  const thead = document.createElement('thead');
  const htr = document.createElement('tr');
  const cols = sheetObj.columns || [];

  cols.forEach(col => {
    const th = document.createElement('th');
    th.textContent = col;
    // Check if column is relevant to active PV agent filters
    if (col.toLowerCase().includes('case') || col.toLowerCase().includes('pt') || col.toLowerCase().includes('exposure') || col.toLowerCase().includes('serious')) {
      th.className = 'active-col';
      th.title = 'Active column analyzed by autonomous agent';
    }
    htr.appendChild(th);
  });
  thead.appendChild(htr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  const preview = sheetObj.preview || [];

  preview.slice(0, 15).forEach(row => {
    const tr = document.createElement('tr');
    if (Array.isArray(row)) {
      row.forEach(val => {
        const td = document.createElement('td');
        td.textContent = val !== null && val !== undefined ? val : '';
        tr.appendChild(td);
      });
    } else if (typeof row === 'object') {
      cols.forEach(c => {
        const td = document.createElement('td');
        td.textContent = row[c] !== undefined ? row[c] : '';
        tr.appendChild(td);
      });
    }
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  wrapper.appendChild(table);
  sourceDataInspector.appendChild(wrapper);
}

// FULL LINEAGE MATRIX MODAL
btnViewMatrix.addEventListener('click', () => {
  renderMatrixTable();
  matrixModal.classList.remove('hidden');
});

matrixCloseBtn.addEventListener('click', () => {
  matrixModal.classList.add('hidden');
});

function renderMatrixTable() {
  matrixTableBody.innerHTML = '';
  if (!currentMappings || currentMappings.length === 0) {
    matrixTableBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-dim);">No lineage rules compiled yet.</td></tr>';
    return;
  }

  currentMappings.forEach(m => {
    const tr = document.createElement('tr');

    const tdSec = document.createElement('td');
    tdSec.innerHTML = `<strong>${m.section_id.toUpperCase()}</strong><br><small>${m.section_title}</small>`;

    const tdStatus = document.createElement('td');
    tdStatus.innerHTML = `<span class="status-pill ${m.status === 'verified' ? 'status-verified' : 'green'}">${m.status}</span>`;

    const tdSrc = document.createElement('td');
    if (m.mapped_sources && m.mapped_sources.length > 0) {
      tdSrc.innerHTML = m.mapped_sources.map(s => `<b>${s.filename}</b> [${s.sheet}]`).join('<br>');
    } else {
      tdSrc.textContent = 'Report Structure';
    }

    const tdCoord = document.createElement('td');
    if (m.mapped_sources && m.mapped_sources.length > 0) {
      tdCoord.innerHTML = m.mapped_sources.map(s => `${s.rows_range || 'All rows'}<br><small>(${s.columns ? s.columns.slice(0, 2).join(', ') : 'Columns'})</small>`).join('<br>');
    } else {
      tdCoord.textContent = 'N/A';
    }

    const tdRule = document.createElement('td');
    if (m.rules && m.rules.length > 0) {
      tdRule.innerHTML = m.rules.map(r => `<code>${r.name}: ${r.logic}</code>`).join('<br>');
    } else {
      tdRule.textContent = 'Qualitative regulatory lineage';
    }

    const tdNotes = document.createElement('td');
    if (m.user_notes && m.user_notes.length > 0) {
      tdNotes.innerHTML = m.user_notes.map(n => `<small style="color: #FDE68A;">• ${n}</small>`).join('<br>');
    } else {
      tdNotes.innerHTML = '<small class="text-dim">None</small>';
    }

    tr.append(tdSec, tdStatus, tdSrc, tdCoord, tdRule, tdNotes);
    matrixTableBody.appendChild(tr);
  });
}

// Download Matrix JSON
btnExportMatrix.addEventListener('click', () => {
  const jsonStr = JSON.stringify(currentMappings, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `PBRER_Lineage_Traceability_Matrix_${currentRunId ? currentRunId.slice(0, 8) : 'export'}.json`;
  a.click();
  URL.revokeObjectURL(url);
});

// Helper
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
