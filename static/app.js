/**
 * Tracewise · PBRER Report Map Client
 * Live section status, evidence inspection, and workflow telemetry
 */

// Global State
let currentRunId = null;
let currentRunData = null;
let currentMappings = [];
let activeSourceFile = null;
let sourceManuallySelected = false;
let currentSourceProfile = null;
let activeSheetName = null;
let eventSource = null;
let lastEventIdx = 0;
let pollingInterval = null;
let activeFilter = 'all';
let seenEventIds = new Set();
let activeSectionIds = new Set();
let expandedSections = new Set();
let activeAgentIds = new Set();
let flowFocus = null;
let currentTargetDocument = null;
let lastMappingSnapshot = '';

// DOM Elements
const ingestionSection = document.querySelector('#ingestionSection');
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
const btnBackToUpload = document.querySelector('#btnBackToUpload');
const agUiFeed = document.querySelector('#agUiFeed');
const reportDocumentViewer = document.querySelector('#reportDocumentViewer');
const reportDocumentTitle = document.querySelector('#reportDocumentTitle');
const sandboxFilesList = document.querySelector('#sandboxFilesList');
const sandboxFilesCount = document.querySelector('#sandboxFilesCount');
const sourceFilesTabs = document.querySelector('#sourceFilesTabs');
const sourceDataInspector = document.querySelector('#sourceDataInspector');
const sourceCountBadge = document.querySelector('#sourceCountBadge');
const agentFocusBeacon = document.querySelector('#agentFocusBeacon');
const panelsGrid = document.querySelector('#panelsGrid');
const agentFlowOverlay = document.querySelector('#agentFlowOverlay');
const agentTokenLayer = document.querySelector('#agentTokenLayer');

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
  filterOutlineTree(e.target.value.toLowerCase().trim());
});

// File input handlers
targetFileInput.addEventListener('change', updateFileSelection);
sourceFilesInput.addEventListener('change', updateFileSelection);

function updateFileSelection() {
  const target = targetFileInput.files[0];
  const sources = [...sourceFilesInput.files];

  if (target) {
    targetFileStatus.textContent = `✓ ${target.name} (${(target.size / 1024).toFixed(1)} KB)`;
    targetFileStatus.title = target.name;
    targetFileStatus.className = 'file-status selected';
  } else {
    targetFileStatus.textContent = 'No target file chosen';
    targetFileStatus.removeAttribute('title');
    targetFileStatus.className = 'file-status muted';
  }

  if (sources.length > 0) {
    sourceFilesStatus.textContent = `✓ ${sources.length} source file(s) selected`;
    sourceFilesStatus.title = sources.map(source => source.name).join('\n');
    sourceFilesStatus.className = 'file-status selected';
  } else {
    sourceFilesStatus.textContent = 'No source files chosen';
    sourceFilesStatus.removeAttribute('title');
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

btnBackToUpload.addEventListener('click', () => {
  if (eventSource) eventSource.close();
  if (pollingInterval) clearInterval(pollingInterval);
  eventSource = null;
  pollingInterval = null;
  currentRunId = null;
  currentRunData = null;
  currentMappings = [];
  lastMappingSnapshot = '';
  activeSourceFile = null;
  sourceManuallySelected = false;
  currentSourceProfile = null;
  ingestionSection.classList.remove('hidden');
  workspaceSection.classList.add('hidden');
  document.body.classList.remove('run-active');
  btnLaunchAgents.disabled = !(targetFileInput.files[0] && sourceFilesInput.files.length);
  btnLaunchAgents.innerHTML = '<span>Run report review</span> <span class="arrow">➔</span>';
  window.scrollTo({ top: 0, behavior: 'smooth' });
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

    const data = await readApiResponse(res, 'Sample bundle generation');
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
  if (!currentRunData?.target_outline?.length) return;
  await launchAgentsExecution();
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
    const data = await readApiResponse(res, 'Upload');
    setupRunUI(data);
  } catch (err) {
    alert('Upload error: ' + err.message);
    btnLaunchAgents.disabled = false;
    btnLaunchAgents.innerHTML = '<span>Launch Autonomous Agents</span> <span class="arrow">➔</span>';
    throw err;
  }
}

async function readApiResponse(response, operation) {
  const body = await response.text();
  let data;
  try {
    data = body ? JSON.parse(body) : {};
  } catch {
    const message = body.trim().slice(0, 300) || response.statusText;
    throw new Error(`${operation} failed (HTTP ${response.status}): ${message}`);
  }
  if (!response.ok) {
    throw new Error(data.detail || data.message || `${operation} failed (HTTP ${response.status})`);
  }
  return data;
}

function setupRunUI(data) {
  currentRunId = data.run_id;
  currentRunData = data;
  currentMappings = [];
  activeSectionIds.clear();
  activeAgentIds.clear();
  expandedSections.clear();
  seenEventIds.clear();
  lastEventIdx = 0;
  flowFocus = null;
  currentTargetDocument = null;
  agUiFeed.innerHTML = '';
  agentTokenLayer.replaceChildren();
  agentFlowOverlay.replaceChildren();
  document.querySelector('#parallelAgentCount').textContent = '0 specialists';
  document.querySelector('#activityCount').textContent = '0 events';

  ingestionSection.classList.add('hidden');
  workspaceSection.classList.remove('hidden');
  document.body.classList.add('run-active');
  window.scrollTo({ top: 0, behavior: 'smooth' });

  document.querySelector('#runIdDisplay').textContent = `Run ${currentRunId.slice(0, 8)}`;
  document.querySelector('#runStatsDisplay').textContent = `${data.files.length} files · focused on Section 16.3`;
  document.querySelector('#runPhaseStatus').textContent = 'Ready to run';
  agentFocusBeacon.textContent = 'Waiting for parallel review';
  document.querySelector('#runLivePill').classList.remove('complete');
  document.querySelector('#workspaceSubtitle').textContent = data.target_outline.length
    ? `${data.target_outline.length} Section 16.3 entries · ${data.files.filter(file => file.role === 'source').length} evidence files`
    : 'Section 16.3 was not detected; the complete report is still available to inspect.';

  renderOutline(data.target_outline);
  renderSourceTabs(data.files.filter(f => f.role === 'source'));
  loadTargetDocument(currentRunId);
  if (!data.target_outline.length) {
    btnLaunchAgents.disabled = true;
    document.querySelector('#runPhaseStatus').textContent = 'Section 16.3 not found';
  }
}

async function launchAgentsExecution() {
  if (!currentRunId) return;

  btnLaunchAgents.disabled = true;
  btnLaunchAgents.innerHTML = '<span class="pulse-dot"></span> Reviewing report…';
  document.querySelector('#runPhaseStatus').textContent = 'Review in progress';

  try {
    const res = await fetch(`/api/runs/${currentRunId}/launch-agents`, { method: 'POST' });
    if (!res.ok) {
      const error = await res.json();
      throw new Error(error.detail || 'Could not launch agents');
    }

    // Connect to AG-UI Stream
    connectAgUiStream(currentRunId);
    startPolling(currentRunId);
  } catch (err) {
    agentFocusBeacon.textContent = `Could not start · ${err.message}`;
    btnLaunchAgents.disabled = true;
    document.querySelector('#runPhaseStatus').textContent = 'Could not start';
  }
}

async function loadTargetDocument(runId) {
  reportDocumentViewer.innerHTML = '<div class="document-loading">Rendering the complete report…</div>';
  try {
    const res = await fetch(`/api/runs/${runId}/target-document`);
    if (!res.ok) throw new Error('Could not load the target report');
    currentTargetDocument = await res.json();
    renderTargetDocument(currentTargetDocument);
  } catch (err) {
    reportDocumentViewer.textContent = err.message;
  }
}

function renderTargetDocument(report) {
  reportDocumentTitle.textContent = report.filename || 'Full report';
  reportDocumentViewer.replaceChildren();
  if (report.kind === 'docx') {
    (report.blocks || []).forEach((block) => {
      if (block.type === 'table') {
        const wrapper = document.createElement('div');
        wrapper.className = 'report-table-block';
        wrapper.dataset.table = block.table;
        const label = document.createElement('span');
        label.className = 'report-table-label';
        label.textContent = `Table ${block.table}`;
        wrapper.append(label, createReportTable(block.rows || []));
        reportDocumentViewer.appendChild(wrapper);
        return;
      }

      const levelMatch = String(block.style || '').match(/(?:heading\s*(\d+)|(\d+)(?:st|nd|rd|th)?\s+level)/i);
      const level = Math.min(6, Math.max(2, Number(levelMatch?.[1] || levelMatch?.[2] || 2) + 1));
      const element = document.createElement(`h${level}`);
      element.className = 'report-paragraph';
      element.dataset.paragraph = block.paragraph;
      element.textContent = block.text || '';
      reportDocumentViewer.appendChild(element);
    });
  } else {
    (report.pages || []).forEach((page) => {
      const section = document.createElement('section');
      section.className = 'report-pdf-page';
      section.dataset.page = page.page;
      const heading = document.createElement('h2');
      heading.textContent = `Page ${page.page}`;
      const text = document.createElement('p');
      text.textContent = page.text || '';
      section.append(heading, text);
      reportDocumentViewer.appendChild(section);
    });
  }
  if (!reportDocumentViewer.childElementCount) {
    reportDocumentViewer.textContent = 'No readable report text was extracted.';
  }
  redrawAgentFlow();
}

function createReportTable(rows) {
  const table = document.createElement('table');
  table.className = 'report-table';
  rows.forEach((row, rowIndex) => {
    const tr = document.createElement('tr');
    row.forEach((value) => {
      const cell = document.createElement(rowIndex === 0 ? 'th' : 'td');
      cell.textContent = value || '';
      tr.appendChild(cell);
    });
    table.appendChild(tr);
  });
  return table;
}

async function checkModelStatus() {
  const badge = document.querySelector('#modelBadge');
  const label = document.querySelector('#modelBadgeLabel');
  try {
    const res = await fetch('/api/health');
    if (!res.ok) throw new Error('Health check failed');
    const health = await res.json();
    const enabled = health.bedrock_enabled && health.bedrock_configured;
    label.textContent = enabled
        ? `Sonnet enabled · ${health.bedrock_model_id}`
      : 'Local workflow · Bedrock disabled';
    badge.classList.toggle('model-offline', !enabled);
    badge.title = health.bedrock_message || '';
  } catch (err) {
    label.textContent = 'Workflow status unavailable';
    badge.classList.add('model-offline');
    badge.title = err.message;
  }
}

checkModelStatus();

// AG-UI PROTOCOL STREAMING (SSE + POLLING FALLBACK)
function connectAgUiStream(runId) {
  if (eventSource) {
    eventSource.close();
  }

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
  if (evt.event_id && seenEventIds.has(evt.event_id)) return;
  if (evt.event_id) seenEventIds.add(evt.event_id);
  const eventIndex = Number(evt.event_id?.match(/^evt_(\d+)_/)?.[1]);
  lastEventIdx = Number.isFinite(eventIndex) ? Math.max(lastEventIdx, eventIndex + 1) : lastEventIdx + 1;

  highlightActiveAgent(evt.agent_id);
  if (evt.agent_id && evt.agent_id.startsWith('section_agent_')) {
    activeAgentIds.add(evt.agent_id);
    document.querySelector('#parallelAgentCount').textContent = `${activeAgentIds.size} specialists`;
  }

  if (evt.event_type === 'file_focus' || evt.event_type === 'agent_filtering') {
    updateFocusBeacon(evt);
  }

  renderTelemetryCard(evt);
  document.querySelector('#activityCount').textContent =
    `${agUiFeed.querySelectorAll('.telemetry-card').length} events`;

  const sectionId = evt.details?.section_id;
  if (evt.event_type === 'section_started' && sectionId) {
    activeSectionIds.add(sectionId);
    updateSectionStatus(sectionId, 'active');
    fetchMappings(evt.run_id);
  }
  if (evt.event_type === 'section_mapped' && sectionId) {
    activeSectionIds.delete(sectionId);
    updateSectionStatus(sectionId, 'completed');
    fetchMappings(evt.run_id);
  } else if (evt.event_type === 'agent_error' && sectionId) {
    activeSectionIds.delete(sectionId);
    updateSectionStatus(sectionId, 'failed');
  } else if (evt.event_type === 'rule_created') {
    fetchMappings(evt.run_id);
  }

  if (evt.event_type === 'orchestration_status') {
    const status = evt.details?.status || 'completed';
    const complete = status === 'completed';
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    document.querySelector('#runPhaseStatus').textContent = complete
      ? 'Review complete'
      : status === 'failed' ? 'Review failed' : 'Review needs attention';
    document.querySelector('#runLivePill').classList.toggle('complete', complete);
    document.querySelector('#runStatsDisplay').textContent = complete
      ? 'Section 16.3 evidence review finished'
      : `${evt.details?.failed_agents || 0} specialist(s) need attention`;
    btnLaunchAgents.innerHTML = complete
      ? '<span>Review complete ✓</span>'
      : '<span>Review finished with issues</span>';
    btnLaunchAgents.disabled = true;
    fetchMappings(evt.run_id);
    clearInterval(pollingInterval);
  }
  updateAgentFlow(evt);
}

function highlightActiveAgent(agentId) {
  document.querySelector('#chip-orchestrator').classList.toggle('active', agentId === 'orchestrator');
}

function updateFocusBeacon(evt) {
  const details = evt.details || {};
  const fileName = details.filename || details.file || 'Source File';
  const sheet = details.sheet ? ` · ${details.sheet}` : '';
  const op = details.operation || (evt.event_type === 'agent_filtering' ? 'Filtering' : 'Reading');

  agentFocusBeacon.textContent = `${evt.agent_name} · ${op} ${fileName}${sheet}`;

  document.querySelectorAll('.source-icon.agent-focused').forEach((icon) => icon.classList.remove('agent-focused'));
  const matchingTab = [...document.querySelectorAll('.source-icon')].find(t => t.dataset.filename === fileName);
  if (matchingTab) {
    matchingTab.classList.add('agent-focused');
  }
}

function updateAgentFlow(evt) {
  const details = evt.details || {};
  const sectionId = details.section_id;
  const agentId = evt.agent_id;
  if (!agentId || !agentId.startsWith('section_agent_')) {
    redrawAgentFlow();
    return;
  }

  const sourceName = details.filename || details.file || flowFocus?.[agentId]?.sourceName || null;
  const type = ['file_focus', 'agent_filtering'].includes(evt.event_type)
    ? 'source'
    : sectionId ? 'section' : 'document';
  flowFocus = flowFocus || {};
  flowFocus[agentId] = {
    agentName: evt.agent_name,
    sectionId: sectionId || flowFocus[agentId]?.sectionId,
    sourceName,
    type,
  };
  positionAgentToken(agentId);
  redrawAgentFlow();
}

function flowTarget(focus) {
  if (!focus) return null;
  if (focus.type === 'source' && focus.sourceName) {
    const source = [...document.querySelectorAll('.source-icon')]
      .find((icon) => icon.dataset.filename === focus.sourceName);
    if (source) return source;
  }
  if (focus.type === 'section' && focus.sectionId) {
    const section = [...document.querySelectorAll('.outline-row')]
      .find((row) => row.dataset.sectionId === focus.sectionId);
    if (section) return section;
  }
  if (focus.sectionId) {
    const section = currentRunData?.target_outline?.find((item) => item.id === focus.sectionId);
    const paragraph = section?.source?.match(/paragraph\s+(\d+)/i);
    if (paragraph) {
      const block = reportDocumentViewer.querySelector(`[data-paragraph="${paragraph[1]}"]`);
      if (block) return block;
    }
  }
  return document.querySelector('#orchestratorAgent');
}

function positionAgentToken(agentId) {
  const focus = flowFocus?.[agentId];
  if (!focus) return;
  let token = agentTokenLayer.querySelector(`[data-agent-id="${agentId}"]`);
  if (!token) {
    token = document.createElement('span');
    token.className = 'moving-agent-token';
    token.dataset.agentId = agentId;
    agentTokenLayer.appendChild(token);
  }
  token.textContent = '✦';
  token.title = focus.agentName || agentId;
  const target = flowTarget(focus);
  const position = relativeCenter(target);
  if (!position) return;
  token.style.left = `${position.x}px`;
  token.style.top = `${position.y}px`;
}

function relativeCenter(element) {
  if (!element || !panelsGrid) return null;
  const rect = element.getBoundingClientRect();
  const grid = panelsGrid.getBoundingClientRect();
  return {
    x: rect.left + rect.width / 2 - grid.left,
    y: rect.top + rect.height / 2 - grid.top,
  };
}

function redrawAgentFlow() {
  if (!agentFlowOverlay || !panelsGrid || workspaceSection.classList.contains('hidden')) return;
  // Clear visual connector lines to keep agents independent and floating
  agentFlowOverlay.replaceChildren();

  Object.entries(flowFocus || {}).forEach(([agentId, focus]) => {
    positionAgentToken(agentId);
  });
}

function addFlowPath(from, to, className) {
  // Connector lines disabled for cleaner multi-agent display
}

window.addEventListener('resize', () => requestAnimationFrame(redrawAgentFlow));
[reportDocumentViewer, outlineContainer, sourceFilesTabs].forEach((element) => {
  element.addEventListener('scroll', () => requestAnimationFrame(redrawAgentFlow), { passive: true });
});
if (window.ResizeObserver) {
  new ResizeObserver(() => requestAnimationFrame(redrawAgentFlow)).observe(panelsGrid);
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
  typeBadge.textContent = getEventLabel(evt.event_type);

  agent.append(agentBadge, typeBadge);

  const timeSpan = document.createElement('span');
  timeSpan.className = 'telemetry-time';
  const dt = new Date(evt.timestamp);
  timeSpan.textContent = dt.toLocaleTimeString();

  top.append(agent, timeSpan);

  const summary = document.createElement('div');
  summary.className = 'telemetry-summary';
  summary.textContent = evt.summary.length > 180 ? `${evt.summary.slice(0, 177)}…` : evt.summary;

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

  if (activeFilter !== 'all' && !card.classList.contains(`filter-item-${activeFilter}`)) {
    card.style.display = 'none';
  }
  while (agUiFeed.querySelectorAll('.telemetry-card').length > 100) {
    agUiFeed.querySelector('.telemetry-card').remove();
  }
}

function getEventLabel(type) {
  const labels = {
    section_started: 'Section active',
    section_mapped: 'Section complete',
    rule_created: 'Lineage rule',
    code_execution: 'Calculation',
    code_generating: 'Script',
    a2a_message: 'Workflow',
    agent_thought: 'Progress',
    agent_error: 'Agent error',
    agent_warning: 'Citation warning',
    file_focus: 'Source opened',
    agent_filtering: 'Evidence filter',
    orchestration_status: 'Run status',
  };
  return labels[type] || type.replaceAll('_', ' ');
}

function getFilterCategory(type) {
  if (type === 'code_generating' || type === 'code_execution') return 'code';
  if (type === 'a2a_message' || type === 'agent_thought') return 'a2a';
  if (type === 'rule_created' || type === 'section_mapped' || type === 'section_started') return 'rules';
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
  if (agentId.includes('section_agent')) return '✦';
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
  currentMappings = outline.map((section) => ({
    section_id: section.id,
    section_title: section.title,
    status: 'pending',
    confidence: 1,
    mapped_sources: [],
    rules: [],
    user_notes: [],
  }));
  const childrenByParent = new Map();
  outline.forEach((section) => {
    const parentId = section.parent_id || null;
    if (!childrenByParent.has(parentId)) childrenByParent.set(parentId, []);
    childrenByParent.get(parentId).push(section);
  });

  const tree = document.createElement('div');
  tree.className = 'outline-tree';
  if (outline[0] && outline.some((section) => section.parent_id === outline[0].id)) {
    expandedSections.add(outline[0].id);
  }
  renderOutlineNodes(childrenByParent.get(null) || [], childrenByParent, tree);
  if (outline.length) {
    outlineContainer.appendChild(tree);
  } else {
    const empty = document.createElement('div');
    empty.className = 'outline-empty';
    empty.textContent = 'No section headings were found in this report.';
    outlineContainer.appendChild(empty);
  }
  document.querySelector('#totalSectionCount').textContent = outline.length;
  updateProgressCounts();
  filterOutlineTree(document.querySelector('#sectionSearchInput').value.toLowerCase().trim());
}

function renderOutlineNodes(sections, childrenByParent, container) {
  sections.forEach((section) => {
    const node = document.createElement('div');
    node.className = 'outline-node';
    node.dataset.sectionId = section.id;
    node.dataset.search = `${section.title} ${section.section_number || ''}`.toLowerCase();

    const row = document.createElement('div');
    row.className = 'outline-row';
    row.dataset.sectionId = section.id;

    const children = childrenByParent.get(section.id) || [];
    if (children.length) {
      const toggle = document.createElement('button');
      toggle.className = 'outline-toggle';
      toggle.type = 'button';
      toggle.textContent = expandedSections.has(section.id) ? '⌄' : '›';
      toggle.setAttribute('aria-label', `${expandedSections.has(section.id) ? 'Collapse' : 'Expand'} ${section.title}`);
      toggle.setAttribute('aria-expanded', String(expandedSections.has(section.id)));
      toggle.addEventListener('click', () => {
        if (expandedSections.has(section.id)) expandedSections.delete(section.id);
        else expandedSections.add(section.id);
        const expanded = expandedSections.has(section.id);
        toggle.textContent = expanded ? '⌄' : '›';
        toggle.setAttribute('aria-label', `${expanded ? 'Collapse' : 'Expand'} ${section.title}`);
        toggle.setAttribute('aria-expanded', String(expanded));
        node.querySelector(':scope > .outline-children').hidden = !expanded;
      });
      row.appendChild(toggle);
    } else {
      const spacer = document.createElement('span');
      spacer.className = 'outline-toggle-spacer';
      row.appendChild(spacer);
    }

    const main = document.createElement('button');
    main.className = 'outline-main';
    main.type = 'button';
    main.title = 'Open section evidence and reviewer notes';

    const idTag = document.createElement('span');
    idTag.className = 'section-id-tag';
    idTag.textContent = section.section_number || String(currentRunData.target_outline.indexOf(section) + 1);

    const title = document.createElement('span');
    title.className = 'section-card-title';
    title.textContent = section.title;
    main.append(idTag, title);
    main.addEventListener('click', () => {
      document.querySelectorAll('.outline-row.selected').forEach((selected) => selected.classList.remove('selected'));
      row.classList.add('selected');
      if (children.length) toggleOutlineNode(section, node);
      jumpToDocumentSection(section);
      renderSectionClaimsRegister(section.id);
      updateAgentFlow({
        agent_id: 'orchestrator',
        event_type: 'section_selected',
        details: { section_id: section.id },
      });
    });
    row.appendChild(main);

    const status = document.createElement('span');
    status.className = 'section-status-tag status-pending';
    status.dataset.statusFor = section.id;
    status.textContent = 'Pending';
    row.appendChild(status);
    node.appendChild(row);

    if (children.length) {
      const childList = document.createElement('div');
      childList.className = 'outline-children';
      childList.hidden = !expandedSections.has(section.id);
      renderOutlineNodes(children, childrenByParent, childList);
      node.appendChild(childList);
    }
    container.appendChild(node);
  });
}

function toggleOutlineNode(section, node) {
  const children = node.querySelector(':scope > .outline-children');
  if (!children) return;
  const expanded = !expandedSections.has(section.id);
  if (expanded) expandedSections.add(section.id);
  else expandedSections.delete(section.id);
  children.hidden = !expanded;
  const toggle = node.querySelector(':scope > .outline-row .outline-toggle');
  if (toggle) {
    toggle.textContent = expanded ? '⌄' : '›';
    toggle.setAttribute('aria-expanded', String(expanded));
  }
}

function jumpToDocumentSection(section) {
  const source = section.source || '';
  const paragraph = source.match(/paragraph\s+(\d+)/i);
  const page = source.match(/page\s+(\d+)/i);
  const target = paragraph
    ? reportDocumentViewer.querySelector(`[data-paragraph="${paragraph[1]}"]`)
    : page ? reportDocumentViewer.querySelector(`[data-page="${page[1]}"]`) : null;
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.add('report-focus');
    window.setTimeout(() => target.classList.remove('report-focus'), 1600);
  }
}

function filterOutlineTree(query) {
  const visit = (node) => {
    const ownMatch = !query || node.dataset.search.includes(query);
    const children = [...node.querySelectorAll(':scope > .outline-children > .outline-node')];
    const childMatch = children.map(visit).some(Boolean);
    node.hidden = !ownMatch && !childMatch;
    const childList = node.querySelector(':scope > .outline-children');
    if (childList && query && childMatch) childList.hidden = false;
    else if (childList) childList.hidden = !expandedSections.has(node.dataset.sectionId);
    return ownMatch || childMatch;
  };
  outlineContainer.querySelectorAll(':scope > .outline-tree > .outline-node').forEach(visit);
}

function mappingStatus(status) {
  if (status === 'rules_compiled' || status === 'verified' || status === 'completed') return 'completed';
  if (status === 'inspecting' || status === 'active') return 'active';
  if (status === 'failed') return 'failed';
  return 'pending';
}

function updateSectionStatus(sectionId, status) {
  const tag = [...outlineContainer.querySelectorAll('[data-status-for]')]
    .find((element) => element.dataset.statusFor === sectionId);
  if (tag) {
    tag.className = `section-status-tag status-${status}`;
    tag.textContent = status[0].toUpperCase() + status.slice(1);
  }
  const mapping = currentMappings.find((item) => item.section_id === sectionId);
  if (mapping) {
    mapping.status = status === 'completed' ? 'rules_compiled'
      : status === 'active' ? 'inspecting'
        : status === 'failed' ? 'failed' : 'pending';
  }
  updateProgressCounts();
}

function updateProgressCounts() {
  const counts = { completed: 0, active: 0, pending: 0, failed: 0 };
  currentMappings.forEach((mapping) => {
    const status = activeSectionIds.has(mapping.section_id) ? 'active' : mappingStatus(mapping.status);
    counts[status] = (counts[status] || 0) + 1;
    updateStatusTag(mapping.section_id, status);
  });
  const total = currentMappings.length;
  document.querySelector('#completedSectionCount').textContent = counts.completed;
  document.querySelector('#completedCount').textContent = counts.completed;
  document.querySelector('#activeCount').textContent = counts.active;
  document.querySelector('#pendingCount').textContent = counts.pending + counts.failed;
  document.querySelector('#totalSectionCount').textContent = total;
  document.querySelector('#sectionProgressBar').style.width = `${total ? (counts.completed / total) * 100 : 0}%`;
}

function updateStatusTag(sectionId, status) {
  const tag = [...outlineContainer.querySelectorAll('[data-status-for]')]
    .find((element) => element.dataset.statusFor === sectionId);
  if (!tag) return;
  tag.className = `section-status-tag status-${status}`;
  tag.textContent = status[0].toUpperCase() + status.slice(1);
}

// FETCH MAPPINGS FROM BACKEND
async function fetchMappings(runId) {
  try {
    const res = await fetch(`/api/runs/${runId}/mappings`);
    if (!res.ok) return;
    const data = await res.json();
    currentMappings = data.mappings || [];
    const snapshot = JSON.stringify(currentMappings);
    const mappingsChanged = snapshot !== lastMappingSnapshot;
    lastMappingSnapshot = snapshot;
    updateProgressCounts();
    if (mappingsChanged) {
      if (!sourceManuallySelected) selectFirstLinkedSource();
      if (activeSourceFile && currentSourceProfile) renderSelectedSource();
    }
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
  const status = mappingStatus(mapping.status);
  modalSectionStatus.textContent = status[0].toUpperCase() + status.slice(1);
  modalSectionStatus.className = `status-pill status-${status}`;
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
      modalSectionStatus.textContent = 'Completed';
      modalSectionStatus.className = 'status-pill status-completed';
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
    const tab = document.createElement('button');
    const selected = activeSourceFile ? activeSourceFile === f.filename : idx === 0;
    tab.className = `source-icon ${selected ? 'active' : ''}`;
    tab.type = 'button';
    tab.dataset.filename = f.filename;
    tab.dataset.storedName = f.stored_name;
    tab.textContent = sourceTypeLabel(f.filename);
    tab.title = f.filename;
    tab.setAttribute('aria-label', f.filename);

    tab.addEventListener('click', () => {
      selectSourceFile(f, true);
    });

    sourceFilesTabs.appendChild(tab);
  });

  const selected = sourceFiles.find((file) => file.filename === activeSourceFile) || sourceFiles[0];
  if (selected) {
    activeSourceFile = selected.filename;
    inspectSourceFile(selected.stored_name, selected.filename);
  }
}

function selectSourceFile(file, manual) {
  sourceManuallySelected = manual;
  activeSourceFile = file.filename;
  document.querySelectorAll('.source-icon').forEach((icon) => {
    icon.classList.toggle('active', icon.dataset.filename === file.filename);
  });
  inspectSourceFile(file.stored_name, file.filename);
  redrawAgentFlow();
}

function selectFirstLinkedSource() {
  const source = currentMappings.flatMap((mapping) => mapping.mapped_sources || [])[0];
  if (!source || source.filename === activeSourceFile) return;
  const file = currentRunData.files.find((item) => item.filename === source.filename);
  if (file) selectSourceFile(file, false);
}

function sourceTypeLabel(filename) {
  const extension = filename.split('.').pop().toLowerCase();
  if (['xlsx', 'xls', 'csv'].includes(extension)) return 'XLS';
  if (extension === 'pdf') return 'PDF';
  if (['docx', 'doc'].includes(extension)) return 'DOC';
  return 'FILE';
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
    sourceDataInspector.textContent = `Could not load preview: ${err.message}`;
  }
}

function renderSectionClaimsRegister(sectionId) {
  const mapping = currentMappings.find(m => m.section_id === sectionId);
  if (!mapping) return;

  sourceDataInspector.innerHTML = '';

  const container = document.createElement('div');
  container.className = 'claims-register-view';

  // Section Header
  const header = document.createElement('div');
  header.className = 'claims-register-header';
  const h4 = document.createElement('h4');
  h4.textContent = `${mapping.section_id.replace('sec-', '')} · ${mapping.section_title}`;
  const sub = document.createElement('div');
  sub.className = 'section-subtitle';
  sub.textContent = mapping.status === 'rules_compiled' ? 'Review completed' : 'Review in progress';
  header.append(h4, sub);
  container.appendChild(header);

  // Summary Metrics
  const claims = mapping.claims || [];
  const validatedCount = claims.filter(c => c.status === 'VALIDATED').length;
  const metrics = document.createElement('div');
  metrics.className = 'claims-summary-metrics';
  metrics.innerHTML = `
    <div class="metric-item">
      <span class="metric-label">Claims Discovered</span>
      <span class="metric-value">${claims.length}</span>
    </div>
    <div class="metric-item">
      <span class="metric-label">Validated</span>
      <span class="metric-value" style="color: #4ade80;">${validatedCount}</span>
    </div>
    <div class="metric-item">
      <span class="metric-label">Lineage Confidence</span>
      <span class="metric-value">${Math.round((mapping.confidence || 0) * 100)}%</span>
    </div>
  `;
  container.appendChild(metrics);

  // Claims Matrix Table (CLAIMS | EVIDENCE | RULES)
  const tableWrap = document.createElement('div');
  tableWrap.className = 'claims-table-wrapper';
  const table = document.createElement('table');
  table.className = 'claims-matrix-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th style="width: 38%;">Claims</th>
        <th style="width: 32%;">Evidence</th>
        <th style="width: 30%;">Rules & Execution</th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  const tbody = table.querySelector('tbody');

  if (!claims.length) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="3" style="text-align: center; color: #94a3b8; padding: 20px;">Review in progress: extracting atomic figures for this subsection...</td>`;
    tbody.appendChild(tr);
  } else {
    claims.forEach((claim) => {
      const tr = document.createElement('tr');
      const valStatus = (claim.status || 'PENDING').toLowerCase();
      const stPill = `<span class="claim-status-pill status-${valStatus}">${valStatus}</span>`;
      const repVal = claim.reported_value ? `<strong>${claim.reported_value} ${claim.unit || ''}</strong>` : '';

      const evItem = (claim.evidence && claim.evidence[0]) || null;
      const evText = evItem
        ? `<div class="evidence-cell"><span class="ds-name">${evItem.candidate_datasets?.[0] || 'Source Dataset'}</span><br><span>${evItem.total_matching_rows || 0} matching rows</span></div>`
        : `<div class="evidence-cell" style="color: #64748b;">Awaiting source records</div>`;

      const ruleItem = claim.rule;
      const ruleResult = claim.calculation_result;
      const calcVal = ruleResult?.computed_value !== undefined ? `Result: <b>${ruleResult.computed_value}</b>` : '';
      const ruleText = ruleItem
        ? `<div class="rule-cell"><span class="rule-logic">${ruleItem.aggregation || 'distinct_count'}</span><br>${calcVal}</div>`
        : `<div class="rule-cell" style="color: #64748b;">Awaiting rule</div>`;

      tr.innerHTML = `
        <td class="claim-title-cell">
          <strong>${claim.normalized_statement || claim.raw_text}</strong>
          ${repVal}
          <div>${stPill}</div>
        </td>
        <td>${evText}</td>
        <td>${ruleText}</td>
      `;

      tr.addEventListener('click', () => {
        openSectionModal(mapping.section_id);
      });

      tbody.appendChild(tr);
    });
  }

  tableWrap.appendChild(table);
  container.appendChild(tableWrap);
  sourceDataInspector.appendChild(container);
}

function renderSheetInspector(profile, filename) {
  currentSourceProfile = profile;
  activeSourceFile = filename;
  renderSelectedSource();
}

function renderSelectedSource() {
  const previewWasOpen = sourceDataInspector.querySelector('.source-preview-details')?.open || false;
  sourceDataInspector.innerHTML = '';
  const profile = currentSourceProfile;
  const filename = activeSourceFile;
  if (!profile || !filename) return;

  const heading = document.createElement('div');
  heading.className = 'selected-source-heading';
  const typeMark = document.createElement('span');
  typeMark.className = 'source-type-mark';
  typeMark.textContent = sourceTypeLabel(filename);
  const headingName = document.createElement('strong');
  headingName.textContent = filename;
  heading.append(typeMark, headingName);
  sourceDataInspector.appendChild(heading);

  const linked = currentMappings.flatMap((mapping) =>
    (mapping.mapped_sources || [])
      .filter((source) => source.filename === filename)
      .map((source) => ({ mapping, source }))
  );
  const linkedTitle = document.createElement('div');
  linkedTitle.className = 'inspector-section-title';
  linkedTitle.textContent = linked.length ? `${linked.length} linked evidence item${linked.length === 1 ? '' : 's'}` : 'No linked evidence yet';
  sourceDataInspector.appendChild(linkedTitle);

  if (!linked.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-inspector';
    empty.textContent = 'A specialist has not linked evidence from this file yet.';
    sourceDataInspector.appendChild(empty);
  }

  linked.forEach(({ mapping, source }) => {
    const card = document.createElement('article');
    card.className = 'evidence-link-card';
    const title = document.createElement('strong');
    title.textContent = `${mapping.section_id.replace('sec-', '')} · ${mapping.section_title}`;
    card.appendChild(title);

    const artifact = document.createElement('div');
    artifact.className = 'evidence-artifact';
    artifact.textContent = [source.sheet, source.rows_range].filter(Boolean).join(' · ');
    card.appendChild(artifact);

    const filters = document.createElement('div');
    filters.className = 'evidence-filters';
    const terms = source.filters_applied?.match_any_terms || [];
    filters.textContent = `Filter: ${terms.length ? terms.join(' OR ') : 'none'} · ${source.filters_applied?.rows_matched || 0} matched / ${source.filters_applied?.rows_scanned || 0} preview rows`;
    card.appendChild(filters);

    (source.claims || []).forEach((claim) => {
      const claimNode = document.createElement('blockquote');
      claimNode.className = 'evidence-claim';
      claimNode.textContent = `${claim.text} · Row ${claim.row}`;
      card.appendChild(claimNode);
    });
    if (!(source.claims || []).length) {
      const noClaims = document.createElement('div');
      noClaims.className = 'evidence-no-claim';
      noClaims.textContent = 'No model claim cited to this source row.';
      card.appendChild(noClaims);
    }
    sourceDataInspector.appendChild(card);
  });

  const previewDetails = document.createElement('details');
  previewDetails.className = 'source-preview-details';
  previewDetails.open = previewWasOpen;
  const previewSummary = document.createElement('summary');
  previewSummary.textContent = 'Source preview';
  previewDetails.appendChild(previewSummary);
  const previewRoot = document.createElement('div');
  previewRoot.className = 'source-preview-root';
  previewDetails.appendChild(previewRoot);
  sourceDataInspector.appendChild(previewDetails);

  if (profile.kind === 'excel') {
    const sheets = profile.sheets || [];
    if (!sheets.length) {
      previewRoot.textContent = 'No sheets found.';
      return;
    }
    const pillRow = document.createElement('div');
    pillRow.className = 'sheet-selector-row';
    sheets.forEach((sheet, index) => {
      const pill = document.createElement('button');
      pill.className = `sheet-pill ${index === 0 ? 'active' : ''}`;
      pill.textContent = `${sheet.sheet} (${sheet.row_count})`;
      pill.addEventListener('click', () => {
        pillRow.querySelectorAll('.sheet-pill').forEach((button) => button.classList.remove('active'));
        pill.classList.add('active');
        renderTableData(sheet, previewRoot);
      });
      pillRow.appendChild(pill);
    });
    previewRoot.appendChild(pillRow);
    renderTableData(sheets[0], previewRoot);
  } else if (profile.kind === 'csv') {
    renderTableData(profile, previewRoot);
  } else if (profile.kind === 'docx') {
    (profile.paragraphs || []).slice(0, 12).forEach((paragraph) => {
      const text = document.createElement('p');
      text.className = 'source-document-paragraph';
      text.textContent = paragraph.text;
      previewRoot.appendChild(text);
    });
  } else if (profile.kind === 'pdf') {
    (profile.pages || []).slice(0, 5).forEach((page) => {
      const pageText = document.createElement('p');
      pageText.className = 'source-document-paragraph';
      pageText.textContent = `Page ${page.page}: ${page.text}`;
      previewRoot.appendChild(pageText);
    });
  } else {
    previewRoot.textContent = `${profile.kind.toUpperCase()} document content is profiled.`;
  }
}

function renderTableData(sheetObj, mount = sourceDataInspector) {
  const existingTable = mount.querySelector('.data-table-wrapper');
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
  mount.appendChild(wrapper);
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
