import * as React from 'react';
import { useMemo, useRef, useState } from 'react';
import {
  Activity, AlertCircle, AlertTriangle, ArrowDownUp, ArrowLeft, ArrowRight, ArrowUpRight,
  BookOpen, Bot, Check, CheckCheck, CheckCircle2, ChevronDown, ChevronRight, ChevronUp,
  CircleDashed, CircleHelp, Clock3, CloudUpload, Code2, Command, Copy, Database, Download,
  File, FileArchive, FileCheck2, FileCode2, FileJson, FileSearch, FileSpreadsheet, FileText,
  Filter, FolderOpen, GitBranch, GitCommitHorizontal, HardDrive, History, Layers3, Lock,
  MoreHorizontal, Network, PanelLeftClose, PanelRightClose, Pause, Play, Plus, RefreshCw,
  Search, Send, Settings2, ShieldCheck, Sparkles, Square, Terminal, Upload, Workflow, X,
  Zap,
} from 'lucide-react';
import { demoRun } from './data/demo';
import { useAguiEvents } from './lib/agui';
import { api, apiMode } from './lib/api';
import type { ActivityItem, ArtifactItem, Claim, DocumentBlock, RunSnapshot, SectionNode, StageId, StageStatus } from './types/domain';

const stageOrder: StageId[] = ['claims', 'rules', 'evaluation'];
const stageLabel: Record<StageId, string> = { claims: 'Claims', rules: 'Rules', evaluation: 'Evaluator' };

function cx(...parts: Array<string | false | undefined>) { return parts.filter(Boolean).join(' '); }
function fileIcon(kind: string) {
  if (kind === 'xlsx' || kind === 'xls' || kind === 'csv') return <FileSpreadsheet size={16} />;
  if (kind === 'pdf') return <FileText size={16} />;
  if (kind === 'docx') return <BookOpen size={16} />;
  return <File size={16} />;
}
function statusLabel(status: string) {
  const labels: Record<string, string> = { review: 'In review', locked: 'Locked', ready: 'Ready', running: 'Running', approved: 'Approved', complete: 'Complete', error: 'Error', changes_requested: 'Changes requested', pass: 'Pass', discrepancy: 'Discrepancy', needs_review: 'Needs review', artifact_ready: 'Artifacts ready', hinted: 'Hinted', draft: 'Draft', in_progress: 'In progress', unresolved: 'Unresolved' };
  return labels[status] || status.replaceAll('_', ' ');
}
function StatusDot({ status }: { status: string }) {
  const cls = ['done', 'approved', 'complete', 'pass', 'indexed'].includes(status) ? 'green' : ['running', 'in_progress', 'indexing'].includes(status) ? 'blue' : ['error', 'fail', 'warning', 'discrepancy'].includes(status) ? 'red' : ['review', 'needs_review', 'changes_requested'].includes(status) ? 'amber' : 'gray';
  return <span className={`status-dot ${cls}`} />;
}
function StagePill({ status }: { status: string }) {
  return <span className={`stage-pill ${status}`}><StatusDot status={status} />{statusLabel(status)}</span>;
}
function Avatar({ initials, tone = 'violet', size = 'sm' }: { initials: string; tone?: string; size?: string }) {
  return <span className={`avatar ${tone} ${size}`}>{initials}</span>;
}
function IconButton({ children, onClick, title, disabled = false }: { children: React.ReactNode; onClick?: () => void; title: string; disabled?: boolean }) {
  return <button className="icon-button" title={title} aria-label={title} disabled={disabled} onClick={onClick}>{children}</button>;
}

function emptyRun(): RunSnapshot {
  const run = structuredClone(demoRun);
  return {
    ...run,
    runId: '',
    name: 'Create a live run',
    product: '',
    period: '',
    status: 'Upload a DOCX target and XLSX/CSV sources to start',
    createdAt: '',
    targetDocument: 'No target uploaded',
    sources: [],
    sections: [],
    claims: [],
    stages: run.stages.map(stage => ({ ...stage, status: 'locked', progress: 0, agents: 0, subagents: 0, artifacts: 0 })),
    agents: [],
    activity: [],
    artifacts: [],
    activeStage: 'claims',
    documentBlocks: [],
  };
}

function mapServerClaim(value: Record<string, unknown>): Claim {
  const hint = value.evidence_hint && typeof value.evidence_hint === 'object'
    ? value.evidence_hint as Record<string, unknown>
    : {};
  const facts = (items: unknown) => Array.isArray(items)
    ? items.map(item => typeof item === 'object' && item !== null
      ? String((item as Record<string, unknown>).statement || '')
      : String(item))
    : [];
  const locator = value.target_locator && typeof value.target_locator === 'object'
    ? value.target_locator as Record<string, unknown>
    : {};
  return {
    id: String(value.claim_id || ''),
    sectionId: String(value.section_id || ''),
    sectionNumber: String(value.section_number || ''),
    sectionTitle: '',
    statement: String(value.normalized_statement || value.raw_statement || ''),
    reportedValue: value.reported_value == null ? '' : String(value.reported_value),
    unit: String(value.unit || ''),
    entity: String(value.entity_unit || ''),
    status: String(value.status || 'hinted') as Claim['status'],
    hint: {
      text: String(hint.text || ''),
      observed: facts(hint.observed),
      inferred: facts(hint.inferred),
      unknowns: Array.isArray(hint.unknowns) ? hint.unknowns.map(String) : [],
    },
    sourceIds: Array.isArray(hint.source_refs) ? hint.source_refs.map(String) : [],
    artifacts: [],
    period: String((value.reporting_period as Record<string, unknown> | undefined)?.value || ''),
    locator: [locator.document_id, locator.block_id].filter(Boolean).join(' · '),
    version: Number(value.version || 1),
  };
}

function mapServerSections(values: Record<string, unknown>[]): SectionNode[] {
  const nodes = new Map<string, SectionNode>();
  const parents = new Map<string, string | null>();
  for (const value of values) {
    const id = String(value.section_id || '');
    nodes.set(id, {
      id,
      number: String(value.number || ''),
      title: String(value.title || ''),
      level: Number(value.level || 0),
      children: [],
    });
    parents.set(id, value.parent_id ? String(value.parent_id) : null);
  }
  const roots: SectionNode[] = [];
  for (const [id, node] of nodes) {
    const parentId = parents.get(id);
    const parent = parentId ? nodes.get(parentId) : undefined;
    if (parent) parent.children!.push(node);
    else roots.push(node);
  }
  return roots;
}

function mapServerSource(value: Record<string, unknown>): RunSnapshot['sources'][number] {
  const format = String(value.format || '').toLowerCase();
  const kind = ['xlsx', 'csv', 'pdf', 'docx', 'xls'].includes(format) ? format : 'other';
  return {
    id: String(value.source_id || value.original_filename || ''),
    name: String(value.original_filename || ''),
    kind: kind as RunSnapshot['sources'][number]['kind'],
    sizeLabel: `${(Number(value.size_bytes || 0) / 1024 / 1024).toFixed(1)} MB`,
    status: value.extraction_status === 'complete' ? 'indexed' : 'pending',
    hash: value.sha256 ? String(value.sha256) : undefined,
    usedBy: 0,
    sourceNote: Array.isArray(value.limitations) ? value.limitations.map(String).join('; ') : undefined,
  };
}

function mapServerArtifact(value: Record<string, unknown>): ArtifactItem {
  const logicalPath = String(value.logical_path || '');
  const stage = String(value.stage || 'claims') as StageId;
  return {
    id: String(value.artifact_id || logicalPath),
    name: logicalPath,
    type: logicalPath.split('.').pop()?.toUpperCase() || 'Artifact',
    stage,
    size: `${Math.ceil(Number(value.size_bytes || 0) / 1024)} KB`,
    version: `v${Number(value.version || 1)}`,
    status: 'ready',
    claimId: value.claim_id ? String(value.claim_id) : undefined,
    updated: String(value.created_at || 'just now'),
  };
}

function mapServerStatus(summary: Awaited<ReturnType<typeof api.getRun>>): Pick<RunSnapshot, 'stages' | 'activeStage' | 'stageManifestHashes' | 'status'> {
  const stageState: Record<string, { active: StageId; completed: StageId[]; ready?: StageId; review?: StageId }> = {
    READY_FOR_STAGE_1: { active: 'claims', completed: [], ready: 'claims' },
    CLAIMS_RUNNING: { active: 'claims', completed: [] },
    CLAIMS_AWAITING_REVIEW: { active: 'claims', completed: [], review: 'claims' },
    CLAIMS_APPROVED: { active: 'rules', completed: ['claims'], ready: 'rules' },
    RULES_RUNNING: { active: 'rules', completed: ['claims'] },
    RULES_AWAITING_REVIEW: { active: 'rules', completed: ['claims'], review: 'rules' },
    RULES_APPROVED: { active: 'evaluation', completed: ['claims', 'rules'], ready: 'evaluation' },
    EVALUATION_RUNNING: { active: 'evaluation', completed: ['claims', 'rules'] },
    EVALUATION_AWAITING_REVIEW: { active: 'evaluation', completed: ['claims', 'rules'], review: 'evaluation' },
    COMPLETE: { active: 'evaluation', completed: ['claims', 'rules', 'evaluation'] },
  };
  const state = stageState[summary.status];
  const isRunning = summary.status.endsWith('RUNNING');
  const stages = structuredClone(demoRun.stages).map(stage => ({
    ...stage,
    status: state?.completed.includes(stage.id) ? 'approved' as const
      : state?.review === stage.id ? 'review' as const
        : isRunning && state?.active === stage.id ? 'running' as const
          : state?.ready === stage.id ? 'ready' as const
            : summary.status === 'FAILED' && state?.active === stage.id ? 'error' as const
              : 'locked' as const,
    progress: state?.completed.includes(stage.id) || state?.review === stage.id ? 100 : 0,
  }));
  return {
    status: summary.status.replaceAll('_', ' '),
    activeStage: state?.active || 'claims',
    stages,
    stageManifestHashes: {
      claims: summary.stage_1_manifest_hash || undefined,
      rules: summary.stage_2_manifest_hash || undefined,
      evaluation: summary.stage_3_manifest_hash || undefined,
    },
  };
}

function App() {
  const [run, setRun] = useState<RunSnapshot>(apiMode ? emptyRun() : structuredClone(demoRun));
  const [activeSection, setActiveSection] = useState('s163');
  const [selectedClaim, setSelectedClaim] = useState<string | null>(apiMode ? null : 'CLM-001');
  const [activeTab, setActiveTab] = useState<'activity' | 'document' | 'artifacts'>('activity');
  const [rightTab, setRightTab] = useState<'claims' | 'agents'>('claims');
  const [searchText, setSearchText] = useState('');
  const [claimStatusFilter, setClaimStatusFilter] = useState('all');
  const [showUpload, setShowUpload] = useState(false);
  const [showClaimEditor, setShowClaimEditor] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const [showSourcePanel, setShowSourcePanel] = useState(false);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [showAllActivity, setShowAllActivity] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [claimDraft, setClaimDraft] = useState({ statement: '', reportedValue: '', unit: '' });
  const [notice, setNotice] = useState('');
  const [newRunName, setNewRunName] = useState('PBRER · New run');
  const [targetFile, setTargetFile] = useState<File | null>(null);
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const [uploadError, setUploadError] = useState('');
  const [loadingStage, setLoadingStage] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  const sourceInput = useRef<HTMLInputElement>(null);
  const lastRefreshRef = useRef(0);

  const currentStage = run.stages.find(s => s.id === run.activeStage)!;
  const selectedClaimData = run.claims.find(c => c.id === selectedClaim) || null;
  const activeSource = run.sources.find(s => s.id === selectedSource) || null;
  const filteredClaims = useMemo(() => run.claims.filter(claim => {
    const matchesText = `${claim.id} ${claim.statement} ${claim.sectionNumber}`.toLowerCase().includes(searchText.toLowerCase());
    const matchesStatus = claimStatusFilter === 'all' || claim.status === claimStatusFilter;
    return matchesText && matchesStatus;
  }), [run.claims, searchText, claimStatusFilter]);
  const activityItems = showAllActivity ? [...run.activity].reverse() : [...run.activity].slice(-5).reverse();
  const totalSubagents = apiMode
    ? run.agents.filter(a => a.stage === run.activeStage).length
    : run.agents.reduce((n, a) => n + a.children, 0);

  function pushActivity(item: Omit<ActivityItem, 'id' | 'time'>) {
    const now = new Date().toLocaleTimeString('en-GB', { hour12: false });
    setRun(prev => ({ ...prev, activity: [...prev.activity, { ...item, id: `ev-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`, time: now }] }));
  }
  function patchStage(stageId: StageId, patch: Partial<RunSnapshot['stages'][number]>) {
    setRun(prev => ({ ...prev, stages: prev.stages.map(s => s.id === stageId ? { ...s, ...patch } : s) }));
  }
  async function refreshLiveRun(runId: string) {
    // Resilient: individual resources may 404 mid-run (e.g. document not yet
    // extracted) — a miss on one must not drop the others.
    const [summary, claims, sections, sources, artifacts, document] = await Promise.all([
      api.getRun(runId).catch(() => null),
      api.listClaims(runId).catch(() => [] as Record<string, unknown>[]),
      api.getSections(runId).catch(() => [] as Record<string, unknown>[]),
      api.listSources(runId).catch(() => [] as Record<string, unknown>[]),
      api.listArtifacts(runId).catch(() => [] as Record<string, unknown>[]),
      api.getDocument(runId).catch(() => ({ blocks: [] as DocumentBlock[] })),
    ]);
    setRun(prev => {
      const mappedSources = sources.length ? sources.map(mapServerSource) : prev.sources;
      const mappedArtifacts = artifacts.map(mapServerArtifact);
      const artifactsByStage = mappedArtifacts.reduce<Record<string, number>>((acc, a) => {
        acc[a.stage] = (acc[a.stage] || 0) + 1; return acc;
      }, {});
      const next: RunSnapshot = {
        ...prev,
        claims: claims.map(mapServerClaim),
        sections: sections.length ? mapServerSections(sections) : prev.sections,
        sources: mappedSources,
        artifacts: mappedArtifacts,
        documentBlocks: (document as { blocks: DocumentBlock[] }).blocks?.length
          ? (document as { blocks: DocumentBlock[] }).blocks
          : prev.documentBlocks,
      };
      if (summary) {
        const mapped = mapServerStatus(summary);
        // Merge: keep live progress/subagent counts for the running stage, and
        // derive per-stage artifact counts from the refreshed artifact list.
        next.stages = mapped.stages.map(stage => {
          const prevStage = prev.stages.find(p => p.id === stage.id);
          return {
            ...stage,
            progress: stage.status === 'running'
              ? Math.max(prevStage?.progress ?? 8, stage.progress)
              : stage.progress,
            subagents: prevStage?.subagents ?? 0,
            agents: prevStage?.agents ?? 0,
            artifacts: artifactsByStage[stage.id] ?? prevStage?.artifacts ?? 0,
          };
        });
        next.activeStage = mapped.activeStage;
        next.status = mapped.status;
        next.stageManifestHashes = mapped.stageManifestHashes;
        next.inputManifestHash = summary.input_manifest_hash;
      }
      return next;
    });
  }
  function scheduleRefresh(runId: string, force = false) {
    if (!runId) return;
    const now = Date.now();
    if (force || now - lastRefreshRef.current > 1500) {
      lastRefreshRef.current = now;
      void refreshLiveRun(runId).catch(() => { /* resilient: ignore transient refresh errors */ });
    }
  }
  async function beginLiveStage(stageId: StageId) {
    if (!run.runId) {
      setNotice('Create a live run with your DOCX and XLSX/CSV files first.');
      return;
    }
    const inputHash = stageId === 'claims'
      ? run.inputManifestHash
      : stageId === 'rules'
        ? run.stageManifestHashes?.claims
        : run.stageManifestHashes?.rules;
    if (!inputHash) {
      setNotice(`The approved input manifest for ${stageLabel[stageId]} is missing.`);
      return;
    }
    setLoadingStage(true);
    // Reset per-stage live state; the stage runs in the background and streams
    // progress, subagent dispatch and tool calls over AG-UI.
    setRun(prev => ({
      ...prev,
      activeStage: stageId,
      status: `${stageLabel[stageId]} · Running`,
      agents: [],
      stages: prev.stages.map(stage => stage.id === stageId
        ? { ...stage, status: 'running', progress: 8, subagents: 0, agents: 0 }
        : stage),
    }));
    try {
      await api.startStage(run.runId, stageId, inputHash, crypto.randomUUID());
      setNotice(`${stageLabel[stageId]} stage started — streaming live agent activity below.`);
    } catch (error) {
      patchStage(stageId, { status: 'error' });
      setNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingStage(false);
    }
  }
  function beginStage(stageId: StageId) {
    const stage = run.stages.find(s => s.id === stageId);
    if (!stage || stage.status === 'locked' || stage.status === 'running') return;
    if (stageId === 'rules' && run.stages[0].status !== 'approved') return;
    if (stageId === 'evaluation' && run.stages[1].status !== 'approved') return;
    if (apiMode) {
      void beginLiveStage(stageId);
      return;
    }
    setLoadingStage(true);
    setRun(prev => ({ ...prev, activeStage: stageId, stages: prev.stages.map(s => s.id === stageId ? { ...s, status: 'running', progress: 8 } : s), status: `${stageLabel[stageId]} · Running` }));
    pushActivity({ stage: stageId, title: `${stageLabel[stageId]} Orchestrator started`, detail: 'New isolated stage context created by the Run Control Plane.', kind: 'agent', agent: `${stageLabel[stageId]} Orchestrator`, status: 'running' });
    const specialists = stageId === 'claims' ? ['Report Structure Specialist', 'Source Intelligence', 'Claim Atomizer'] : stageId === 'rules' ? ['Source Investigator', 'Rule Engineer', 'Test & Provenance Reviewer'] : ['Artifact Inspector', 'Independent Re-run', 'Lineage Auditor'];
    const agents = [{ id: `agt-${stageId}-main`, name: `${stageLabel[stageId]} Orchestrator`, role: `${stageLabel[stageId]} · primary`, stage: stageId, status: 'active' as const, currentTask: 'Coordinating stage work', elapsed: '00:01', children: specialists.length }, ...specialists.map((name, i) => ({ id: `agt-${stageId}-${i}`, name, role: 'Scoped specialist', stage: stageId, status: 'active' as const, currentTask: i === 0 ? 'Inspecting assigned inputs' : 'Queued · waiting for dispatch', elapsed: '00:00', children: 0 }))];
    setRun(prev => ({ ...prev, agents }));
    specialists.forEach((name, i) => pushActivity({ stage: stageId, title: 'Subagent dispatched', detail: `${name} · isolated task context · scoped access`, kind: 'agent', agent: name, status: i === 0 ? 'running' : 'done' }));
    [28, 56, 78].forEach((pct, i) => setTimeout(() => patchStage(stageId, { progress: pct }), 550 * (i + 1)));
    setTimeout(() => {
      patchStage(stageId, { progress: 100, status: 'review', agents: specialists.length + 1, subagents: specialists.length, artifacts: stageId === 'rules' ? run.claims.length * 3 : stageId === 'evaluation' ? run.claims.length : 4 });
      setRun(prev => ({ ...prev, status: `${stageLabel[stageId]} · In review`, agents: prev.agents.map(a => ({ ...a, status: 'done', currentTask: 'Stage output published · awaiting reviewer' })) }));
      pushActivity({ stage: stageId, title: `${stageLabel[stageId]} stage output ready`, detail: 'Artifacts versioned and frozen as a review candidate. Explicit reviewer approval required.', kind: 'gate', status: 'warning' });
      if (stageId === 'rules') {
        const newArtifacts: ArtifactItem[] = run.claims.flatMap((c, idx) => [
          { id: `plan-${c.id}`, name: `${c.id}/plan.md`, type: 'Investigation plan', stage: 'rules' as const, size: '2 KB', version: 'v1', status: 'ready' as const, claimId: c.id, updated: 'just now' },
          { id: `py-${c.id}`, name: `${c.id}/analysis.py`, type: 'Python analysis', stage: 'rules' as const, size: '4 KB', version: 'v1', status: 'ready' as const, claimId: c.id, updated: 'just now' },
          { id: `prov-${c.id}`, name: `${c.id}/provenance.json`, type: 'Data lineage', stage: 'rules' as const, size: '3 KB', version: 'v1', status: 'ready' as const, claimId: c.id, updated: 'just now' },
        ]);
        setRun(prev => ({ ...prev, artifacts: [...prev.artifacts, ...newArtifacts], claims: prev.claims.map(c => ({ ...c, status: 'artifact_ready' })) }));
        pushActivity({ stage: 'rules', title: 'Claim workspaces prepared', detail: `${run.claims.length} isolated claim workspaces · evidence bundles, rule specs, scripts and tests.`, kind: 'artifact', artifact: 'stage_2_rules/', status: 'done' });
      }
      if (stageId === 'evaluation') {
        setRun(prev => ({ ...prev, claims: prev.claims.map((c, i) => ({ ...c, evaluator: i === 0 ? 'PASS' : i === 1 ? 'DISCREPANCY' : 'NEEDS_HUMAN_REVIEW' })) }));
        pushActivity({ stage: 'evaluation', title: 'Independent reruns completed', detail: 'Fresh evaluator context · isolated sandbox · read-only original source snapshot.', kind: 'success', status: 'done' });
      }
      setLoadingStage(false);
    }, 2400);
  }
  async function approveStage(stageId: StageId) {
    if (apiMode) {
      const expectedManifest = run.stageManifestHashes?.[stageId];
      if (!run.runId || !expectedManifest) {
        setNotice('The stage manifest is unavailable; approval was not sent.');
        return;
      }
      try {
        await api.reviewStage(run.runId, stageId, 'approve', expectedManifest, reviewNote || undefined);
        const summary = await api.getRun(run.runId);
        setRun(prev => ({ ...prev, ...mapServerStatus(summary) }));
        setShowReview(false);
        setReviewNote('');
        setNotice(`${stageLabel[stageId]} approved by the API control plane.`);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    const stageIndex = stageOrder.indexOf(stageId);
    const nextStage = stageOrder[stageIndex + 1];
    patchStage(stageId, { status: 'approved' });
    pushActivity({ stage: stageId, title: `${stageLabel[stageId]} approved by reviewer`, detail: 'Approval recorded against the current artifact manifest version and hash.', kind: 'gate', status: 'done' });
    setRun(prev => ({ ...prev, status: nextStage ? `${stageLabel[nextStage]} · Ready` : 'Final review · Approved', activeStage: nextStage || stageId, stages: prev.stages.map(s => s.id === nextStage ? { ...s, status: 'ready' } : s) }));
    setShowReview(false);
    setReviewNote('');
    setNotice(nextStage ? `${stageLabel[stageId]} approved · ${stageLabel[nextStage]} is now unlocked.` : 'Final evaluation approved. Review dossier marked complete.');
    window.setTimeout(() => setNotice(''), 4000);
  }
  async function requestChanges(stageId: StageId) {
    if (apiMode) {
      const expectedManifest = run.stageManifestHashes?.[stageId];
      if (!run.runId || !expectedManifest) {
        setNotice('The stage manifest is unavailable; review changes were not sent.');
        return;
      }
      try {
        await api.reviewStage(run.runId, stageId, 'request_changes', expectedManifest, reviewNote || undefined);
        const summary = await api.getRun(run.runId);
        setRun(prev => ({ ...prev, ...mapServerStatus(summary), reviewNote }));
        setShowReview(false);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    patchStage(stageId, { status: 'changes_requested' });
    pushActivity({ stage: stageId, title: 'Reviewer requested changes', detail: reviewNote || 'Reviewer requested changes; see review note in the audit log.', kind: 'warning', status: 'warning' });
    setRun(prev => ({ ...prev, status: `${stageLabel[stageId]} · Changes requested`, reviewNote }));
    setShowReview(false);
  }
  function editClaim(claim: Claim) {
    setClaimDraft({ statement: claim.statement, reportedValue: claim.reportedValue, unit: claim.unit });
    setShowClaimEditor(true);
  }
  async function saveClaim() {
    if (!selectedClaim) return;
    if (apiMode) {
      const claim = run.claims.find(item => item.id === selectedClaim);
      if (!run.runId || !claim?.version) {
        setNotice('The claim version is unavailable; the edit was not saved.');
        return;
      }
      try {
        const updated = await api.updateClaim(run.runId, selectedClaim, {
          expected_version: claim.version,
          reviewer_reason: 'Reviewer updated claim details in the live workspace',
          normalized_statement: claimDraft.statement,
          reported_value: claimDraft.reportedValue,
          unit: claimDraft.unit,
        }) as Record<string, unknown>;
        setRun(prev => ({
          ...prev,
          claims: prev.claims.map(item => item.id === selectedClaim ? mapServerClaim(updated) : item),
        }));
        pushActivity({ stage: 'claims', title: `Claim ${selectedClaim} updated`, detail: 'Claim edit saved through the API.', kind: 'system', status: 'done' });
        setShowClaimEditor(false);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    setRun(prev => ({ ...prev, claims: prev.claims.map(c => c.id === selectedClaim ? { ...c, ...claimDraft } : c) }));
    pushActivity({ stage: 'claims', title: `Claim ${selectedClaim} edited`, detail: 'Reviewer edit saved as a new Claim Register draft version.', kind: 'system', status: 'done' });
    setShowClaimEditor(false);
  }
  function addFiles(files: FileList | null, isTarget: boolean) {
    if (!files) return;
    setUploadError('');
    const allowed = apiMode
      ? (isTarget ? ['.docx'] : ['.xlsx', '.csv'])
      : (isTarget ? ['.docx', '.pdf'] : ['.xlsx', '.xls', '.csv', '.pdf', '.docx']);
    const list = Array.from(files);
    const invalid = list.find(f => !allowed.some(ext => f.name.toLowerCase().endsWith(ext)));
    if (invalid) { setUploadError(`${invalid.name} is not a supported ${isTarget ? 'target report' : 'source'} file.`); return; }
    if (isTarget) setTargetFile(list[0]); else setSourceFiles(prev => [...prev, ...list]);
  }
  const aguiConnection = useAguiEvents(run.runId, apiMode, (event) => {
    const runId = run.runId;
    if (event.type === 'CUSTOM' && event.name === 'tracewise.activity') {
      const value = (event.value || {}) as Record<string, unknown>;
      const stage = (value.stage as StageId) || run.activeStage;
      pushActivity({
        stage,
        title: String(value.title || 'Agent activity'),
        detail: String(value.detail || 'Operational event received from the AG-UI stream.'),
        kind: (value.kind as ActivityItem['kind']) || 'tool',
        agent: value.agent ? String(value.agent) : undefined,
        source: value.source ? String(value.source) : undefined,
        artifact: value.artifact ? String(value.artifact) : undefined,
        status: (value.status as ActivityItem['status']) || 'done',
      });
    } else if (event.type === 'CUSTOM' && event.name === 'tracewise.stage') {
      const value = (event.value || {}) as Record<string, unknown>;
      const stage = (value.stage as StageId) || run.activeStage;
      const status = String(value.status || 'running');
      const progress = Number(value.progress || 0);
      setRun(prev => ({
        ...prev,
        stages: prev.stages.map(s => s.id === stage ? {
          ...s,
          status: status === 'review' ? 'review' : status === 'error' ? 'error'
            : status === 'running' ? 'running' : s.status,
          progress: status === 'review' ? 100 : Math.max(s.progress, progress),
        } : s),
      }));
      scheduleRefresh(runId, status === 'review' || status === 'error');
    } else if (event.type === 'CUSTOM' && (event.name === 'tracewise.artifact' || event.name === 'tracewise.claim')) {
      scheduleRefresh(runId);
    } else if (event.type === 'SUBAGENT_STARTED') {
      const stage = (event.stage as StageId) || run.activeStage;
      const id = String(event.subagentId || event.subagentRunId || `sub-${Date.now()}`);
      const name = String(event.name || 'Subagent');
      setRun(prev => {
        const agents = prev.agents.some(a => a.id === id) ? prev.agents : [...prev.agents, {
          id, name, role: String(event.role || 'subagent'), stage,
          status: 'active' as const, currentTask: String(event.detail || 'Working…'),
          elapsed: '—', children: 0,
        }];
        const count = agents.filter(a => a.stage === stage).length;
        return { ...prev, agents, stages: prev.stages.map(s => s.id === stage ? { ...s, subagents: count, agents: count } : s) };
      });
      pushActivity({ stage, title: `Subagent started · ${name}`, detail: String(event.detail || 'Isolated subsection extraction'), kind: 'agent', agent: name, status: 'running' });
    } else if (event.type === 'SUBAGENT_FINISHED') {
      const id = String(event.subagentId || event.subagentRunId || '');
      const claims = Number(event.claims || 0);
      setRun(prev => ({ ...prev, agents: prev.agents.map(a => a.id === id ? { ...a, status: 'done', currentTask: `${claims} claim(s) extracted` } : a) }));
    } else if (event.type === 'SUBAGENT_ERROR') {
      const id = String(event.subagentId || event.subagentRunId || '');
      setRun(prev => ({ ...prev, agents: prev.agents.map(a => a.id === id ? { ...a, status: 'error', currentTask: String(event.message || 'error') } : a) }));
    } else if (event.type === 'TOOL_CALL_START') {
      pushActivity({ stage: run.activeStage, title: `Tool · ${String(event.toolName || 'tool')}`, detail: 'Scoped tool invocation opened by the stage agent.', kind: 'tool', status: 'running' });
    } else if (event.type === 'RUN_ERROR') {
      pushActivity({ stage: run.activeStage, title: 'Agent run error', detail: String(event.message || 'The agent run returned an error.'), kind: 'warning', status: 'error' });
      scheduleRefresh(runId, true);
    }
  });

  async function createDemoRun() {
    if (!targetFile) { setUploadError('Add one target PBRER document to continue.'); return; }
    if (!sourceFiles.length) { setUploadError('Add at least one source document to continue.'); return; }
    if (apiMode) {
      const body = new FormData();
      body.append('run_name', newRunName);
      body.append('target_file', targetFile);
      sourceFiles.forEach(file => body.append('source_files', file));
      setLoadingStage(true);
      try {
        const created = await api.createRun(body);
        const liveRun = emptyRun();
        liveRun.runId = created.run_id;
        liveRun.name = created.run_name;
        liveRun.targetDocument = targetFile.name;
        liveRun.sources = sourceFiles.map((file, index) => ({
          id: `source-${index}`,
          name: file.name,
          kind: file.name.split('.').pop()?.toLowerCase() as RunSnapshot['sources'][number]['kind'],
          sizeLabel: `${(file.size / 1024 / 1024).toFixed(1)} MB`,
          status: 'pending',
          usedBy: 0,
        }));
        liveRun.inputManifestHash = created.input_manifest_hash;
        liveRun.stages = liveRun.stages.map((stage, index) => ({
          ...stage,
          status: index === 0 ? 'ready' : 'locked',
        }));
        liveRun.status = 'Ready for Stage 1';
        setRun(liveRun);
        setShowUpload(false);
        setSelectedClaim(null);
        setActiveSection('');
        pushActivity({ stage: 'claims', title: 'Live run created', detail: 'Uploaded files are stored by the API for this run.', kind: 'system', status: 'done' });
        setTargetFile(null);
        setSourceFiles([]);
      } catch (error) {
        setUploadError(error instanceof Error ? error.message : String(error));
      } finally {
        setLoadingStage(false);
      }
      return;
    }
    const newRun = structuredClone(demoRun);
    newRun.runId = `TW-26-${Date.now().toString().slice(-6)}`;
    newRun.name = newRunName;
    newRun.targetDocument = targetFile.name;
    newRun.sources = sourceFiles.map((f, i) => ({ id: `uploaded-${i}`, name: f.name, kind: f.name.split('.').pop()?.toLowerCase() as any, sizeLabel: `${(f.size / 1024 / 1024).toFixed(1)} MB`, status: 'pending', usedBy: 0 }));
    newRun.claims = [];
    newRun.stages = [{ id: 'claims', number: '01', title: 'Claims & sources', subtitle: 'Understand the report. Map evidence.', status: 'ready', progress: 0, agents: 0, subagents: 0, artifacts: 0 }, { id: 'rules', number: '02', title: 'Rules & evidence', subtitle: 'Investigate. Code. Reproduce.', status: 'locked', progress: 0, agents: 0, subagents: 0, artifacts: 0 }, { id: 'evaluation', number: '03', title: 'Independent evaluation', subtitle: 'Rerun. Verify. Reconcile.', status: 'locked', progress: 0, agents: 0, subagents: 0, artifacts: 0 }];
    newRun.agents = []; newRun.activity = []; newRun.artifacts = []; newRun.activeStage = 'claims'; newRun.status = 'Ready for Stage 1';
    setRun(newRun); setShowUpload(false); setSelectedClaim(null); setActiveSection('s163');
    pushActivity({ stage: 'claims', title: 'Run initialized', detail: 'Files staged in the local UI demo. Backend ingestion is not connected in this starter.', kind: 'system', status: 'warning' });
    setTargetFile(null); setSourceFiles([]);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup"><div className="brand-mark"><GitBranch size={18} strokeWidth={2.3} /></div><div className="brand-name">tracewise<span>WORKSPACE</span></div></div>
        <div className="topbar-divider" />
        <div className="run-selector"><span className="run-breadcrumb">PROJECT</span><ChevronRight size={13} /><strong>{run.runId}</strong><ChevronDown size={14} /></div>
        <div className="topbar-spacer" />
        <span className="demo-chip"><span />{apiMode ? 'LIVE API' : 'DEMO DATA'}</span>
        <button className="top-icon" title="Command palette"><Command size={16} /><kbd>⌘ K</kbd></button>
        <button className="top-icon" title="Settings"><Settings2 size={17} /></button>
        <div className="topbar-divider short" />
        <Avatar initials="AR" tone="dark" size="md" />
      </header>

      <div className="app-body">
        <aside className={cx('left-rail', leftCollapsed && 'collapsed')}>
          <div className="rail-topline"><span>RUN WORKSPACE</span><IconButton title={leftCollapsed ? 'Expand left panel' : 'Collapse left panel'} onClick={() => setLeftCollapsed(!leftCollapsed)}><PanelLeftClose size={15} /></IconButton></div>
          {!leftCollapsed && <>
            <div className="run-summary"><div className="run-summary-icon"><FileCheck2 size={18} /></div><div className="run-summary-copy"><strong>{run.name}</strong><span>{run.period}</span></div><button className="plain-icon"><MoreHorizontal size={16} /></button></div>
            <div className="rail-section-head"><span>DOCUMENT STRUCTURE</span><span className="tiny-count">{apiMode ? run.sections.length : 18}</span></div>
            <div className="tree-tools"><span className="outline-search"><Search size={13} /><input placeholder="Find section" /></span><IconButton title="Expand all"><ChevronDown size={14} /></IconButton></div>
            <div className="tree-list">
              <SectionTree nodes={run.sections} activeId={activeSection} onSelect={id => { setActiveSection(id); setActiveTab('document'); }} />
            </div>
            <div className="rail-section-head source-head"><span>SOURCE FILES</span><span className="tiny-count">{run.sources.length}</span><button className="mini-add" onClick={() => setShowUpload(true)} title="Add sources"><Plus size={13} /></button></div>
            <div className="source-list">
              {run.sources.map(source => <button className={cx('source-row', selectedSource === source.id && 'selected')} key={source.id} onClick={() => { setSelectedSource(source.id); setShowSourcePanel(true); }}>
                <span className={`file-icon ${source.kind}`}>{fileIcon(source.kind)}</span><span className="source-row-copy"><strong>{source.name}</strong><small>{source.sizeLabel}{source.rows ? ` · ${source.rows.toLocaleString()} rows` : ''}</small></span><StatusDot status={source.status} />
              </button>)}
            </div>
            <div className="storage-card"><div className="storage-icon"><HardDrive size={15} /></div><div><strong>Input snapshot</strong><span>Immutable · private</span></div><span className="secure-tag"><Lock size={10} />LOCKED</span></div>
          </>}
        </aside>

        <main className="main-content">
          <div className="page-heading">
            <div><div className="eyebrow">PBRER SECTION 16.3 <span className="eyebrow-sep">/</span> RECONCILIATION WORKSPACE</div><div className="heading-line"><h1>{run.name}</h1><span className="run-status-tag"><StatusDot status={run.stages.find(s => s.id === run.activeStage)?.status || 'ready'} />{run.status}</span></div><p className="heading-sub">{run.targetDocument} <span>·</span> {run.period} <span>·</span> Created {run.createdAt}</p></div>
            <div className="heading-actions"><button className="button-secondary" onClick={() => setShowUpload(true)}><Plus size={15} />Add files</button><button className="button-primary" onClick={() => setShowReview(true)} disabled={currentStage.status !== 'review'}><ShieldCheck size={15} />Review stage</button></div>
          </div>

          <StageRail stages={run.stages} active={run.activeStage} onSelect={id => { if (run.stages.find(s => s.id === id)?.status !== 'locked') setRun(prev => ({ ...prev, activeStage: id })); }} />

          <div className="metric-strip">
            <Metric icon={<FileText size={16} />} label="SOURCE FILES" value={String(run.sources.length).padStart(2, '0')} sub="All inventoried" />
            <Metric icon={<Layers3 size={16} />} label={apiMode ? 'SECTION 16.3 NODES' : 'LEAF SUBSECTIONS'} value={apiMode ? String(run.sections.length).padStart(2, '0') : '06'} sub={apiMode ? 'Scoped subtree' : 'Section 16.3'} />
            <Metric icon={<CheckCheck size={16} />} label="CLAIMS MAPPED" value={String(run.claims.length).padStart(2, '0')} sub="Atomic claim records" />
            <Metric icon={<Bot size={16} />} label="SUBAGENTS" value={String(totalSubagents).padStart(2, '0')} sub="Across active stage" />
            <Metric icon={<FileCode2 size={16} />} label="ARTIFACTS" value={String(run.artifacts.length).padStart(2, '0')} sub="Versioned outputs" />
          </div>

          <div className="workbench-grid">
            <section className="centre-column">
              <div className="panel main-panel">
                <div className="panel-header">
                  <div className="panel-title"><span className="panel-icon"><Activity size={16} /></span><div><h2>{activeTab === 'activity' ? 'Agent activity' : activeTab === 'document' ? 'Report viewer' : 'Artifact explorer'}</h2><p>{activeTab === 'activity' ? 'Live execution trace · tool calls · subagent dispatch' : activeTab === 'document' ? 'Full-document context with exact target locators' : 'Versioned outputs from each stage'}</p></div></div>
                  <div className="panel-header-actions"><span className="live-indicator"><span />{run.stages.some(s => s.status === 'running') ? 'LIVE' : 'TRACE'}</span><IconButton title="Refresh activity" onClick={() => setNotice('Activity is up to date.')}><RefreshCw size={15} /></IconButton><IconButton title="More options"><MoreHorizontal size={16} /></IconButton></div>
                </div>
                <div className="content-tabs">
                  <button className={activeTab === 'activity' ? 'active' : ''} onClick={() => setActiveTab('activity')}><Activity size={14} />Activity <span className="tab-count">{run.activity.length}</span></button>
                  <button className={activeTab === 'document' ? 'active' : ''} onClick={() => setActiveTab('document')}><BookOpen size={14} />Document</button>
                  <button className={activeTab === 'artifacts' ? 'active' : ''} onClick={() => setActiveTab('artifacts')}><FolderOpen size={14} />Artifacts <span className="tab-count">{run.artifacts.length}</span></button>
                </div>
                {activeTab === 'activity' && <ActivityView items={activityItems} onSource={id => { setSelectedSource(id); setShowSourcePanel(true); }} onArtifact={() => setActiveTab('artifacts')} showAll={showAllActivity} setShowAll={setShowAllActivity} />}
                {activeTab === 'document' && <DocumentView run={run} activeSection={activeSection} onSection={setActiveSection} onClaim={id => setSelectedClaim(id)} live={apiMode} />}
                {activeTab === 'artifacts' && <ArtifactView artifacts={run.artifacts} onOpen={a => { setSelectedClaim(a.claimId || selectedClaim); setActiveTab('activity'); setNotice(`${a.name} selected · artifact preview is a demo placeholder.`); }} />}
              </div>
              <div className="panel stage-panel">
                <div className="panel-header compact"><div className="panel-title"><span className="panel-icon muted"><Workflow size={16} /></span><div><h2>Stage control</h2><p>Sequential · reviewer-gated · no automatic handoff</p></div></div><span className="control-plane-label"><Lock size={11} />CONTROL PLANE</span></div>
                <div className="stage-control-list">
                  <StageControl stage={run.stages[0]} icon={<Sparkles size={16} />} actionLabel={run.stages[0].status === 'ready' ? 'Start Stage 1' : run.stages[0].status === 'review' ? 'Review & approve' : run.stages[0].status === 'changes_requested' ? 'Run corrections' : statusLabel(run.stages[0].status)} actionType={run.stages[0].status === 'review' ? 'review' : 'start'} onAction={() => run.stages[0].status === 'review' ? setShowReview(true) : beginStage('claims')} disabled={run.stages[0].status === 'running' || run.stages[0].status === 'approved'} />
                  <StageControl stage={run.stages[1]} icon={<Code2 size={16} />} actionLabel={run.stages[1].status === 'locked' ? 'Await Stage 1' : run.stages[1].status === 'ready' ? 'Start Stage 2' : run.stages[1].status === 'review' ? 'Review & approve' : run.stages[1].status === 'changes_requested' ? 'Run corrections' : statusLabel(run.stages[1].status)} actionType={run.stages[1].status === 'review' ? 'review' : 'start'} onAction={() => run.stages[1].status === 'review' ? setShowReview(true) : beginStage('rules')} disabled={['locked', 'running', 'approved'].includes(run.stages[1].status)} />
                  <StageControl stage={run.stages[2]} icon={<ShieldCheck size={16} />} actionLabel={run.stages[2].status === 'locked' ? 'Await Stage 2' : run.stages[2].status === 'ready' ? 'Start evaluator' : run.stages[2].status === 'review' ? 'Final review' : run.stages[2].status === 'changes_requested' ? 'Re-run evaluation' : statusLabel(run.stages[2].status)} actionType={run.stages[2].status === 'review' ? 'review' : 'start'} onAction={() => run.stages[2].status === 'review' ? setShowReview(true) : beginStage('evaluation')} disabled={['locked', 'running', 'approved'].includes(run.stages[2].status)} />
                </div>
              </div>
            </section>

            <aside className={cx('right-column', rightCollapsed && 'collapsed')}>
              <div className="panel register-panel">
                <div className="panel-header register-head"><div className="panel-title"><span className="panel-icon"><Layers3 size={16} /></span><div><h2>Run intelligence</h2><p>Claims · agents · evidence map</p></div></div><IconButton title="Collapse right panel" onClick={() => setRightCollapsed(true)}><PanelRightClose size={15} /></IconButton></div>
                <div className="register-tabs"><button className={rightTab === 'claims' ? 'active' : ''} onClick={() => setRightTab('claims')}>Claim register <span>{run.claims.length}</span></button><button className={rightTab === 'agents' ? 'active' : ''} onClick={() => setRightTab('agents')}>Agents <span>{run.agents.length}</span></button></div>
                {rightTab === 'claims' ? <>
                  <div className="claim-search-row"><label><Search size={14} /><input value={searchText} onChange={e => setSearchText(e.target.value)} placeholder="Search claims" /></label><select value={claimStatusFilter} onChange={e => setClaimStatusFilter(e.target.value)} aria-label="Filter claims"><option value="all">All</option><option value="hinted">Hinted</option><option value="artifact_ready">Artifacts ready</option><option value="pass">Pass</option><option value="discrepancy">Discrepancy</option><option value="needs_review">Needs review</option></select><IconButton title="Filter claims"><Filter size={14} /></IconButton></div>
                  <div className="claim-register-list">{filteredClaims.length ? filteredClaims.map(claim => <ClaimRow key={claim.id} claim={claim} active={selectedClaim === claim.id} onClick={() => setSelectedClaim(claim.id)} />) : <EmptyState icon={<Search size={18} />} title="No claims match" detail="Try another search or filter." />}</div>
                  {selectedClaimData && <div className="claim-inspector">
                    <div className="inspector-top"><span>SELECTED CLAIM</span><button className="plain-link" onClick={() => editClaim(selectedClaimData)}>Edit <ArrowUpRight size={12} /></button></div>
                    <div className="inspector-id"><strong>{selectedClaimData.id}</strong><span>{selectedClaimData.sectionNumber}</span></div>
                    <p className="inspector-statement">{selectedClaimData.statement}</p>
                    <div className="claim-value-row"><div><span>REPORTED VALUE</span><strong>{selectedClaimData.reportedValue} <small>{selectedClaimData.unit}</small></strong></div><div><span>ENTITY</span><strong>{selectedClaimData.entity}</strong></div></div>
                    <div className="inspector-divider" />
                    <div className="lineage-head"><span><GitBranch size={13} />LINEAGE PREVIEW</span><span className="lineage-count">{selectedClaimData.sourceIds.length} sources</span></div>
                    <div className="lineage-chips">{selectedClaimData.sourceIds.map(id => { const s = run.sources.find(x => x.id === id); return <button key={id} onClick={() => { setSelectedSource(id); setShowSourcePanel(true); }}><FileSpreadsheet size={12} />{s?.name || id}</button>; })}</div>
                    <div className="hint-block"><span className="hint-icon"><Sparkles size={12} /></span><div><strong>Evidence hint</strong><p>{selectedClaimData.hint.text}</p></div></div>
                    <div className="hint-markers"><span className="observed">● {selectedClaimData.hint.observed.length} observed</span><span className="inferred">● {selectedClaimData.hint.inferred.length} inferred</span><span className="unknown">● {selectedClaimData.hint.unknowns.length} unknown</span></div>
                    <button className="button-secondary full-width" onClick={() => { setActiveTab('document'); setActiveSection(selectedClaimData.sectionId); }}><BookOpen size={14} />Open target location <ArrowUpRight size={13} /></button>
                  </div>}
                </> : <AgentView agents={run.agents} />}
              </div>
            </aside>
          </div>
          <footer className="workspace-footer"><span><Lock size={11} />Original inputs immutable</span><span><GitCommitHorizontal size={12} />Artifact snapshots versioned</span><span><Activity size={12} />AG-UI {aguiConnection === 'disabled' ? 'ready · demo mode' : aguiConnection}</span><span className="footer-spacer" /><span>TRACEWISE <b>0.1.0</b></span></footer>
        </main>
      </div>

      {rightCollapsed && <button className="expand-right" onClick={() => setRightCollapsed(false)}><PanelRightClose size={15} />Show intelligence</button>}
      {notice && <div className="toast"><CheckCircle2 size={16} />{notice}<button onClick={() => setNotice('')}><X size={14} /></button></div>}
      {showReview && <ReviewModal stage={currentStage} note={reviewNote} setNote={setReviewNote} onClose={() => setShowReview(false)} onApprove={() => approveStage(currentStage.id)} onRequestChanges={() => requestChanges(currentStage.id)} />}
      {showClaimEditor && selectedClaimData && <ClaimEditor claim={selectedClaimData} draft={claimDraft} setDraft={setClaimDraft} onClose={() => setShowClaimEditor(false)} onSave={saveClaim} />}
      {showSourcePanel && activeSource && <SourceDrawer source={activeSource} onClose={() => setShowSourcePanel(false)} />}
      {showUpload && <UploadModal name={newRunName} setName={setNewRunName} targetFile={targetFile} sourceFiles={sourceFiles} error={uploadError} inputTarget={uploadInput} inputSources={sourceInput} onAddFiles={addFiles} onRemoveSource={i => setSourceFiles(prev => prev.filter((_, idx) => idx !== i))} onClose={() => setShowUpload(false)} onCreate={createDemoRun} live={apiMode} loading={loadingStage} />}
    </div>
  );
}

function SectionTree({ nodes, activeId, onSelect }: { nodes: RunSnapshot['sections']; activeId: string; onSelect: (id: string) => void }) {
  return <>{nodes.map(node => <SectionNodeView key={node.id} node={node} activeId={activeId} onSelect={onSelect} />)}</>;
}
function SectionNodeView({ node, activeId, onSelect }: { node: RunSnapshot['sections'][number]; activeId: string; onSelect: (id: string) => void }) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = !!node.children?.length;
  return <div className="section-node">
    <button className={cx('tree-item', activeId === node.id && 'active', node.number === '16.3' && 'target-node')} onClick={() => onSelect(node.id)} style={{ paddingLeft: `${9 + node.level * 13}px` }}>
      {hasChildren ? <span className="tree-chevron" onClick={e => { e.stopPropagation(); setExpanded(!expanded); }}>{expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span> : <span className="tree-leaf" />}
      <span className="tree-number">{node.number}</span><span className="tree-title">{node.title}</span>{node.claims ? <span className="tree-claim-count">{node.claims}</span> : null}
    </button>
    {hasChildren && expanded && <div className="tree-children">{node.children!.map(child => <SectionNodeView key={child.id} node={child} activeId={activeId} onSelect={onSelect} />)}</div>}
  </div>;
}
function Metric({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return <div className="metric"><span className="metric-icon">{icon}</span><div className="metric-copy"><span>{label}</span><strong>{value}</strong><small>{sub}</small></div></div>;
}
function StageRail({ stages, active, onSelect }: { stages: RunSnapshot['stages']; active: StageId; onSelect: (id: StageId) => void }) {
  return <div className="stage-rail">{stages.map((stage, i) => <div className="stage-wrap" key={stage.id}><button className={cx('stage-card', active === stage.id && 'active', stage.status === 'locked' && 'locked')} onClick={() => onSelect(stage.id)}><div className="stage-card-top"><span className="stage-number">{stage.number}</span><StagePill status={stage.status} /></div><strong>{stage.title}</strong><small>{stage.subtitle}</small><div className="stage-progress"><span style={{ width: `${stage.progress}%` }} /></div><div className="stage-card-meta"><span><Bot size={12} />{stage.subagents} subagents</span><span><FileText size={12} />{stage.artifacts} artifacts</span><b>{stage.progress}%</b></div></button>{i < stages.length - 1 && <div className={cx('stage-connector', stage.status === 'approved' && 'complete')}><ArrowRight size={14} /></div>}</div>)}</div>;
}
function ActivityView({ items, onSource, onArtifact, showAll, setShowAll }: { items: ActivityItem[]; onSource: (id: string) => void; onArtifact: () => void; showAll: boolean; setShowAll: (v: boolean) => void }) {
  const iconFor = (kind: ActivityItem['kind']) => kind === 'agent' ? <Bot size={14} /> : kind === 'artifact' ? <FileCheck2 size={14} /> : kind === 'gate' ? <ShieldCheck size={14} /> : kind === 'success' ? <Check size={14} /> : kind === 'warning' ? <AlertTriangle size={14} /> : kind === 'tool' ? <Terminal size={14} /> : <Zap size={14} />;
  return <div className="activity-view"><div className="activity-summary"><div className="activity-summary-title"><span className="pulse-dot" />{showAll ? 'All run events' : 'Latest events'}<span className="activity-total">{items.length} events shown</span></div><div className="activity-actions"><span className="filter-chip"><Filter size={12} />All activity</span><button className="plain-link" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show latest' : 'View all'}<ArrowRight size={12} /></button></div></div>
    <div className="timeline">{items.map((item, idx) => <div className="timeline-item" key={item.id}><div className={`timeline-icon ${item.kind}`}>{iconFor(item.kind)}</div><div className="timeline-body"><div className="timeline-title-row"><strong>{item.title}</strong><time>{item.time}</time></div><p>{item.detail}</p><div className="timeline-meta">{item.agent && <span className="agent-tag"><Bot size={11} />{item.agent}</span>}{item.source && <button className="source-tag" onClick={() => onSource(item.source!)}><FileSpreadsheet size={11} />{item.source}</button>}{item.artifact && <button className="artifact-tag" onClick={onArtifact}><FileCode2 size={11} />{item.artifact}</button>}{item.status === 'running' && <span className="running-tag"><span />In progress</span>}</div></div></div>)}</div>
    <div className="trace-footnote"><ShieldCheck size={13} /><span>Activity trace shows operations and tool outcomes only. Private model reasoning is never displayed.</span></div>
  </div>;
}
function DocumentView({ run, activeSection, onSection, onClaim, live }: { run: RunSnapshot; activeSection: string; onSection: (id: string) => void; onClaim: (id: string) => void; live: boolean }) {
  if (live) {
    return <div className="document-view">
      <div className="document-toolbar"><div><span className="doc-icon"><BookOpen size={14} /></span><strong>{run.targetDocument}</strong><span className="doc-page">EXTRACTED SOURCE</span></div></div>
      <div className="document-canvas"><div className="document-page">
        {run.documentBlocks?.length
          ? run.documentBlocks.map(block => block.type === 'table'
            ? <table key={block.block_id}><tbody>{[block.headers || [], ...(block.rows || [])].map((row, rowIndex) => <tr key={`${block.block_id}-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table>
            : <p key={block.block_id}>{block.text}</p>)
          : <p>Start Stage 1 to extract the uploaded report. No demo report content is shown in live mode.</p>}
      </div></div>
      <div className="document-footer"><span><Lock size={11} />Read-only extracted input</span><span>{run.documentBlocks?.length || 0} blocks</span><span className="footer-spacer" /><button onClick={() => onSection(run.sections[0]?.id || '')}>Sections: {run.sections.length}</button></div>
    </div>;
  }
  const claim = run.claims.find(c => c.sectionId === activeSection) || run.claims[0];
  return <div className="document-view"><div className="document-toolbar"><div><span className="doc-icon"><BookOpen size={14} /></span><strong>{run.targetDocument}</strong><span className="doc-page">PAGE 118 / 146</span></div><div><button className="doc-tool"><Search size={14} />Find</button><button className="doc-tool"><Download size={14} />Export excerpt</button></div></div><div className="document-canvas"><div className="document-page"><div className="doc-running-head">PERIODIC BENEFIT-RISK EVALUATION REPORT <span>CONFIDENTIAL</span></div><div className="doc-rule" /><div className="doc-section-number">16.3</div><h2>Benefit-risk evaluation</h2><p className="doc-intro">The benefit-risk profile of the product remains favourable when used in accordance with the approved product information. The following section provides an integrated evaluation of important identified risks, potential risks and missing information for the reporting interval.</p><div className="doc-section-number">16.3.1</div><h3>Important identified risks</h3><div className="doc-section-number">16.3.1.1</div><h4>Hepatic events</h4><p>During the reporting interval, hepatic events continued to be monitored through the global safety database and cumulative review of spontaneous and solicited safety information.</p><div className="doc-highlight"><span className="highlight-label">CLAIM · {claim?.id || 'CLM-001'}</span><p>{claim?.statement || 'Select a claim to inspect its source statement.'}</p><button onClick={() => claim && onClaim(claim.id)}>Inspect claim <ArrowUpRight size={12} /></button></div><p>A review of seriousness, expectedness and temporal association was conducted in line with the approved methodology. Relevant source coverage and coding criteria are described in the supporting data package.</p><div className="doc-table"><div><strong>Measure</strong><strong>Reporting interval</strong></div><div><span>Cases with hepatic events</span><span>184</span></div><div><span>Serious cases</span><span>39</span></div><div><span>Cases with outcome reported</span><span>—</span></div></div><div className="doc-footnote">This is illustrative viewer content for the starter UI. Uploaded report extraction and exact locators are not yet connected.</div><div className="doc-page-number">118</div></div></div><div className="document-footer"><span><Lock size={11} />Read-only original</span><span>Selected node: {run.sections.flatMap(s => [s, ...(s.children || []), ...(s.children || []).flatMap(c => c.children || [])]).find(s => s.id === activeSection)?.number || '16.3'}</span><span className="footer-spacer" /><button onClick={() => onSection('s163')}>Go to Section 16.3 <ArrowUpRight size={12} /></button></div></div>;
}
function ArtifactView({ artifacts, onOpen }: { artifacts: ArtifactItem[]; onOpen: (artifact: ArtifactItem) => void }) {
  const groups: StageId[] = ['claims', 'rules', 'evaluation'];
  return <div className="artifact-view">{groups.map(stage => { const list = artifacts.filter(a => a.stage === stage); return <div className="artifact-group" key={stage}><div className="artifact-group-head"><span className={`stage-mini ${stage}`}>{stage === 'claims' ? '01' : stage === 'rules' ? '02' : '03'}</span><strong>{stageLabel[stage]} stage</strong><span>{list.length} artifacts</span></div>{list.length ? list.map(a => <button className="artifact-row" key={a.id} onClick={() => onOpen(a)}><span className="artifact-file-icon">{a.name.endsWith('.py') ? <Code2 size={16} /> : a.name.endsWith('.json') ? <FileJson size={16} /> : <FileText size={16} />}</span><span className="artifact-row-copy"><strong>{a.name}</strong><small>{a.type} · {a.size} · {a.version}</small></span><span className={`artifact-status ${a.status}`}>{statusLabel(a.status)}</span><ArrowUpRight size={14} /></button>) : <div className="artifact-empty"><Lock size={13} />No artifacts yet · stage locked or not started</div>}</div>; })}</div>;
}
function StageControl({ stage, icon, actionLabel, actionType, onAction, disabled }: { stage: RunSnapshot['stages'][number]; icon: React.ReactNode; actionLabel: string; actionType: 'start' | 'review'; onAction: () => void; disabled: boolean }) {
  return <div className="stage-control-row"><div className={`stage-control-icon ${stage.id}`}>{icon}</div><div className="stage-control-copy"><strong>{stage.number} / {stage.title}</strong><span>{stage.subtitle} · {stage.subagents} subagents</span></div><StagePill status={stage.status} /><div className="control-progress"><span style={{ width: `${stage.progress}%` }} /></div><button className={cx('stage-action', actionType, disabled && 'disabled')} disabled={disabled} onClick={onAction}>{actionType === 'review' ? <ShieldCheck size={13} /> : stage.status === 'running' ? <CircleDashed size={13} /> : <Play size={13} />}{actionLabel}</button></div>;
}
function ClaimRow({ claim, active, onClick }: { claim: Claim; active: boolean; onClick: () => void }) {
  const status = claim.evaluator ? claim.evaluator.toLowerCase() : claim.status;
  return <button className={cx('claim-row', active && 'active')} onClick={onClick}><div className="claim-row-top"><span className="claim-id">{claim.id}</span><span className="claim-section">{claim.sectionNumber}</span></div><strong>{claim.statement}</strong><div className="claim-row-bottom"><span className="claim-value">{claim.reportedValue} <small>{claim.unit}</small></span><span className={`claim-state ${status}`}>{claim.evaluator || statusLabel(claim.status)}</span><ChevronRight size={13} /></div></button>;
}
function AgentView({ agents }: { agents: RunSnapshot['agents'] }) {
  return <div className="agent-view">{agents.length ? agents.map(agent => <div className="agent-row" key={agent.id}><Avatar initials={agent.name.split(' ').map(p => p[0]).slice(0, 2).join('')} tone={agent.stage === 'claims' ? 'violet' : agent.stage === 'rules' ? 'blue' : 'green'} /><div className="agent-row-copy"><div><strong>{agent.name}</strong><StagePill status={agent.status} /></div><small>{agent.role}</small><p>{agent.currentTask}</p><div className="agent-meta"><span><Clock3 size={11} />{agent.elapsed}</span><span><Network size={11} />{agent.children} subagents</span></div></div></div>) : <EmptyState icon={<Bot size={18} />} title="No agents running" detail="Agents appear here when a stage is started." />}</div>;
}
function EmptyState({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) { return <div className="empty-state"><span>{icon}</span><strong>{title}</strong><small>{detail}</small></div>; }

function ReviewModal({ stage, note, setNote, onClose, onApprove, onRequestChanges }: { stage: RunSnapshot['stages'][number]; note: string; setNote: (v: string) => void; onClose: () => void; onApprove: () => void; onRequestChanges: () => void }) {
  const isFinal = stage.id === 'evaluation';
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}><div className="modal review-modal"><div className="modal-top"><span className="modal-kicker">REVIEW GATE · {stage.number}</span><button className="icon-button" onClick={onClose}><X size={17} /></button></div><div className="review-hero"><div className="review-icon"><ShieldCheck size={23} /></div><div><h2>{isFinal ? 'Final evaluation review' : `Approve ${stage.title}?`}</h2><p>{isFinal ? 'Confirm the independent evaluation and close this review dossier.' : 'This approval freezes the current artifact versions and unlocks the next stage.'}</p></div></div><div className="review-checklist"><div><CheckCircle2 size={16} /><span><strong>Version snapshot</strong><small>Approval is bound to the current artifact manifest hash.</small></span><em>Ready</em></div><div><CheckCircle2 size={16} /><span><strong>Audit record</strong><small>Reviewer identity, timestamp and note are persisted by the control plane.</small></span><em>Ready</em></div><div><AlertCircle size={16} /><span><strong>Stage transition</strong><small>{isFinal ? 'No further agent stage will start automatically.' : 'The next stage remains stopped until explicitly started.'}</small></span><em>Manual</em></div></div><label className="field-label">REVIEW NOTE <span>OPTIONAL</span><textarea value={note} onChange={e => setNote(e.target.value)} placeholder="Add rationale, requested corrections or approval context…" rows={3} /></label><div className="modal-footer"><button className="button-secondary" onClick={onRequestChanges}>Request changes</button><button className="button-primary" onClick={onApprove}><Check size={15} />{isFinal ? 'Approve final evaluation' : 'Approve & freeze stage'}</button></div></div></div>;
}
function ClaimEditor({ claim, draft, setDraft, onClose, onSave }: { claim: Claim; draft: { statement: string; reportedValue: string; unit: string }; setDraft: (v: { statement: string; reportedValue: string; unit: string }) => void; onClose: () => void; onSave: () => void }) {
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}><div className="modal editor-modal"><div className="modal-top"><span className="modal-kicker">CLAIM REGISTER · {claim.id}</span><button className="icon-button" onClick={onClose}><X size={17} /></button></div><h2>Edit claim</h2><p className="modal-sub">Reviewer edits should be versioned and audited. This local starter stores the change in UI state only.</p><label className="field-label">SOURCE STATEMENT<textarea rows={4} value={draft.statement} onChange={e => setDraft({ ...draft, statement: e.target.value })} /></label><div className="field-pair"><label className="field-label">REPORTED VALUE<input value={draft.reportedValue} onChange={e => setDraft({ ...draft, reportedValue: e.target.value })} /></label><label className="field-label">UNIT<input value={draft.unit} onChange={e => setDraft({ ...draft, unit: e.target.value })} /></label></div><div className="modal-footer"><button className="button-secondary" onClick={onClose}>Cancel</button><button className="button-primary" onClick={onSave}><Check size={15} />Save draft edit</button></div></div></div>;
}
function SourceDrawer({ source, onClose }: { source: RunSnapshot['sources'][number]; onClose: () => void }) {
  return <div className="drawer-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}><aside className="source-drawer"><div className="drawer-header"><div><span className="modal-kicker">SOURCE INTELLIGENCE</span><h2>{source.name}</h2></div><button className="icon-button" onClick={onClose}><X size={17} /></button></div><div className="source-drawer-body"><div className="source-file-hero"><div className={`file-icon large ${source.kind}`}>{fileIcon(source.kind)}</div><div><strong>{source.name}</strong><span>{source.kind.toUpperCase()} · {source.sizeLabel}</span></div><StagePill status={source.status} /></div><div className="drawer-stats"><div><span>RECORDS</span><strong>{source.rows?.toLocaleString() || '—'}</strong></div><div><span>WORKSHEETS</span><strong>{source.sheets || '—'}</strong></div><div><span>CLAIMS LINKED</span><strong>{source.usedBy}</strong></div></div><div className="drawer-section"><h3>Integrity</h3><div className="integrity-row"><Lock size={13} />Immutable source snapshot <CheckCircle2 size={14} /></div><div className="hash-box"><span>SHA-256</span><code>{source.hash || 'Generated at ingestion'}</code><button title="Copy hash"><Copy size={12} /></button></div></div><div className="drawer-section"><h3>Source understanding</h3><p>{source.sourceNote || 'No source limitations recorded in the demo fixture.'}</p><div className="source-tags"><span>Schema profile</span><span>Column summary</span><span>Join candidates</span></div></div><div className="drawer-section"><h3>Used in claims</h3><p className="muted-copy">The real backend will derive this list from versioned evidence bundles. The demo displays the source usage count only.</p></div></div><div className="drawer-footer"><button className="button-secondary full-width" onClick={onClose}>Close source inspector</button></div></aside></div>;
}
function UploadModal({ name, setName, targetFile, sourceFiles, error, inputTarget, inputSources, onAddFiles, onRemoveSource, onClose, onCreate, live, loading }: {
  name: string;
  setName: (v: string) => void;
  targetFile: File | null;
  sourceFiles: File[];
  error: string;
  inputTarget: React.RefObject<HTMLInputElement>;
  inputSources: React.RefObject<HTMLInputElement>;
  onAddFiles: (files: FileList | null, target: boolean) => void;
  onRemoveSource: (i: number) => void;
  onClose: () => void;
  onCreate: () => void;
  live: boolean;
  loading: boolean;
}) {
  const targetAccept = live ? '.docx' : '.docx,.pdf';
  const sourceAccept = live ? '.xlsx,.csv' : '.xlsx,.xls,.csv,.pdf,.docx';
  return <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
    <div className="modal upload-modal">
      <div className="modal-top"><span className="modal-kicker">NEW RECONCILIATION RUN</span><button className="icon-button" onClick={onClose}><X size={17} /></button></div>
      <div className="upload-title"><div className="upload-title-icon"><CloudUpload size={22} /></div><div><h2>Start with your documents</h2><p>One target PBRER and all supporting source files. Nothing runs until you start Stage 1.</p></div></div>
      <label className="field-label">RUN NAME<input value={name} onChange={e => setName(e.target.value)} /></label>
      <div className="upload-block">
        <div className="upload-block-head"><div><span className="step-number">01</span><strong>Target report</strong><small>Primary PBRER · {live ? 'DOCX' : 'DOCX or PDF'}</small></div><span className="required-label">REQUIRED</span></div>
        <button className={cx('dropzone', targetFile ? 'has-file' : false)} onClick={() => inputTarget.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); onAddFiles(e.dataTransfer.files, true); }}>
          <input ref={inputTarget} type="file" accept={targetAccept} hidden onChange={e => onAddFiles(e.target.files, true)} />
          {targetFile ? <><span className="file-selected-icon"><FileCheck2 size={20} /></span><span><strong>{targetFile.name}</strong><small>{(targetFile.size / 1024 / 1024).toFixed(1)} MB · selected</small></span><CheckCircle2 size={17} /></> : <><Upload size={19} /><span><strong>Drop the target document here</strong><small>or browse files · {targetAccept}</small></span><span className="browse-label">Browse</span></>}
        </button>
      </div>
      <div className="upload-block">
        <div className="upload-block-head"><div><span className="step-number">02</span><strong>Source documents</strong><small>{live ? 'Excel workbooks and CSV data' : 'Workbooks, listings, reports and dictionaries'}</small></div><span className="required-label">1+ REQUIRED</span></div>
        <div className="source-file-picks">{sourceFiles.map((file, index) => <div key={`${file.name}-${index}`} className="picked-file"><FileSpreadsheet size={15} /><span><strong>{file.name}</strong><small>{(file.size / 1024 / 1024).toFixed(1)} MB</small></span><button onClick={() => onRemoveSource(index)}><X size={13} /></button></div>)}</div>
        <button className="source-add-button" onClick={() => inputSources.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); onAddFiles(e.dataTransfer.files, false); }}>
          <input ref={inputSources} type="file" accept={sourceAccept} multiple hidden onChange={e => onAddFiles(e.target.files, false)} />
          <Plus size={15} />Add source files <span>· {sourceAccept.replaceAll(',', ' ')}</span>
        </button>
      </div>
      <div className="upload-privacy"><Lock size={13} /><span>{live ? 'Files are stored in this run’s local storage; report text and selected metadata are sent to AWS Bedrock during live stages.' : 'Private by default. Files stay in browser memory and are not uploaded.'}</span></div>
      {error && <div className="upload-error"><AlertCircle size={14} />{error}</div>}
      <div className="modal-footer"><button className="button-secondary" onClick={onClose}>Cancel</button><button className="button-primary" onClick={onCreate} disabled={!targetFile || sourceFiles.length === 0 || loading}>{loading ? 'Uploading…' : 'Create run'} <ArrowRight size={15} /></button></div>
      <p className="demo-note">{live ? 'Live mode · real API and Bedrock calls' : 'Demo only · uploaded file bytes are not sent to a backend.'}</p>
    </div>
  </div>;
}

export default App;
