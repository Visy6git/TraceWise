import * as React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowRight, ArrowUpRight,
  BookOpen, Bot, Check, CheckCheck, CheckCircle2, ChevronDown, ChevronRight,
  CircleDashed, Clock3, Code2, Command, File, FileCheck2, FileCode2, FileJson,
  FileSpreadsheet, FileText, Filter, FolderOpen, GitBranch, GitCommitHorizontal,
  HardDrive, History, Layers3, Lock, MoreHorizontal, Network, PanelLeftClose, PanelRightClose,
  PauseCircle, Play, Plus, RefreshCw, RotateCcw, Search, Settings2, ShieldCheck, Sparkles, Terminal,
  Workflow, X, Zap,
} from 'lucide-react';
import { ArtifactViewerModal, type OpenedArtifact } from './components/ArtifactViewerModal';
import { ClaimDataModal } from './components/ClaimDataModal';
import { ClaimInspector } from './components/ClaimInspector';
import { ClaimEditor, ReviewModal, UploadModal } from './components/Modals';
import { SourceDrawer } from './components/SourceDrawer';
import { demoRun } from './data/demo';
import { useAguiEvents } from './lib/agui';
import { api, apiMode, type RunSummary } from './lib/api';
import { WorkspaceModeTabs, type WorkspaceMode } from './components/WorkspaceModeTabs';
import { Stage3BlueprintPanel } from './components/Stage3BlueprintPanel';
import { SectionGeneratorWorkspace } from './components/SectionGeneratorWorkspace';
import { generatorApi } from './lib/generatorApi';
import './styles/generator.css';
import type {
  ActivityItem,
  ArtifactItem,
  ChildClaim,
  Claim,
  ClaimData,
  ClaimSourceData,
  DocumentBlock,
  RunSnapshot,
  RuntimeConfig,
  SectionNode,
  StageId,
  VerificationResult,
} from './types/domain';

const stageOrder: StageId[] = ['claims', 'rules', 'evaluation'];
const stageLabel: Record<StageId, string> = {
  claims: 'Claims & exploration',
  rules: 'Rules engineering',
  evaluation: 'Section 16.3 Understanding',
};

function mapLegacyEvaluationStatusToUnderstanding(status: string, activeStage?: string | null): string {
  const s = status.toUpperCase().replaceAll(' ', '_');
  if (s === 'RULES_APPROVED' || s.includes('RULES_APPROVED')) return 'ready';
  if (s === 'EVALUATION_RUNNING' || s.includes('UNDERSTANDING_RUNNING')) return 'running';
  if (s === 'EVALUATION_AWAITING_REVIEW' || s.includes('UNDERSTANDING_REVIEW')) return 'review';
  if (s === 'COMPLETE' || s.includes('APPROVED')) return 'approved';
  if ((s === 'FAILED' || s.includes('ERROR')) && activeStage === 'evaluation') return 'error';
  return 'locked';
}

function cx(...parts: Array<string | false | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function fileIcon(kind: string) {
  if (kind === 'xlsx' || kind === 'xls' || kind === 'csv') return <FileSpreadsheet size={16} />;
  if (kind === 'pdf') return <FileText size={16} />;
  if (kind === 'docx') return <BookOpen size={16} />;
  return <File size={16} />;
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    review: 'In review',
    locked: 'Locked',
    ready: 'Ready',
    running: 'Running',
    approved: 'Approved',
    complete: 'Complete',
    error: 'Error',
    paused: 'Paused',
    placeholder: 'Placeholder',
    changes_requested: 'Changes requested',
    verified: 'Verified',
    pass: 'Pass',
    discrepancy: 'Discrepancy',
    failed: 'Failed',
    needs_review: 'Needs review',
    artifact_ready: 'Artifacts ready',
    hinted: 'Hinted',
    draft: 'Draft',
    in_progress: 'Verifying…',
    unresolved: 'Unresolved',
  };
  return labels[status] || status.replaceAll('_', ' ');
}

function StatusDot({ status }: { status: string }) {
  const cls = ['done', 'approved', 'complete', 'pass', 'verified', 'indexed'].includes(status)
    ? 'green'
    : ['running', 'in_progress', 'indexing'].includes(status)
      ? 'blue'
      : ['error', 'fail', 'failed', 'warning', 'discrepancy'].includes(status)
        ? 'red'
        : ['review', 'needs_review', 'changes_requested', 'placeholder'].includes(status)
          ? 'amber'
          : 'gray';
  return <span className={`status-dot ${cls}`} />;
}

function StagePill({ status }: { status: string }) {
  return (
    <span className={`stage-pill ${status}`}>
      <StatusDot status={status} />
      {statusLabel(status)}
    </span>
  );
}

function Avatar({ initials, tone = 'violet', size = 'sm' }: { initials: string; tone?: string; size?: string }) {
  return <span className={`avatar ${tone} ${size}`}>{initials}</span>;
}

function IconButton({
  children,
  onClick,
  title,
  disabled = false,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  title: string;
  disabled?: boolean;
}) {
  return (
    <button className="icon-button" title={title} aria-label={title} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  );
}

function emptyRun(): RunSnapshot {
  const run = structuredClone(demoRun);
  return {
    ...run,
    runId: '',
    name: 'Create a reconciliation run',
    product: '',
    period: '',
    status: 'Upload a DOCX target and XLSX/CSV sources to start',
    createdAt: '',
    targetDocument: 'No target uploaded',
    sources: [],
    sections: [],
    claims: [],
    stages: run.stages.map(stage => ({
      ...stage,
      status: stage.id === 'evaluation' ? 'placeholder' : 'locked',
      progress: 0,
      agents: 0,
      subagents: 0,
      artifacts: 0,
    })),
    agents: [],
    activity: [],
    artifacts: [],
    activeStage: 'claims',
    documentBlocks: [],
  };
}

function mapServerClaim(value: Record<string, unknown>): Claim {
  const hint =
    value.evidence_hint && typeof value.evidence_hint === 'object'
      ? (value.evidence_hint as Record<string, unknown>)
      : {};
  const facts = (items: unknown) =>
    Array.isArray(items)
      ? items.map(item =>
          typeof item === 'object' && item !== null
            ? String((item as Record<string, unknown>).statement || '')
            : String(item),
        )
      : [];
  const locator =
    value.target_locator && typeof value.target_locator === 'object'
      ? (value.target_locator as Record<string, unknown>)
      : {};
  const childrenClaims: ChildClaim[] = Array.isArray(value.children_claims)
    ? (value.children_claims as ChildClaim[])
    : [];
  const sourceMapped = Array.isArray(value.source_document_mapped)
    ? value.source_document_mapped.map(String)
    : [];
  const hintRefs = Array.isArray(hint.source_refs) ? hint.source_refs.map(String) : [];
  const combinedSourceIds = Array.from(new Set([...sourceMapped, ...hintRefs]));
  const vr =
    value.verification_result && typeof value.verification_result === 'object'
      ? (value.verification_result as VerificationResult)
      : null;

  return {
    id: String(value.claim_id || ''),
    sectionId: String(value.section_id || ''),
    sectionNumber: String(value.section_number || ''),
    sectionTitle: String(value.section_title || ''),
    statement: String(value.normalized_statement || value.raw_statement || ''),
    reportedValue: value.reported_value == null ? '' : String(value.reported_value),
    unit: String(value.unit || ''),
    entity: String(value.entity_unit || ''),
    numerator: value.numerator != null ? String(value.numerator) : undefined,
    denominator: value.denominator != null ? String(value.denominator) : undefined,
    status: String(value.status || 'hinted') as Claim['status'],
    hint: {
      text: String(hint.text || ''),
      observed: facts(hint.observed),
      inferred: facts(hint.inferred),
      unknowns: Array.isArray(hint.unknowns) ? hint.unknowns.map(String) : [],
    },
    childrenClaims,
    searchCriteria: value.search_criteria ? String(value.search_criteria) : undefined,
    sourceDocumentMapped: sourceMapped,
    verificationResult: vr,
    sourceIds: combinedSourceIds,
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
    sizeLabel: `${(Number(value.size_bytes || 0) / 1024 / 1024).toFixed(2)} MB`,
    status: value.extraction_status === 'explored' || value.extraction_status === 'complete' ? 'indexed' : 'pending',
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
    size: `${Math.max(1, Math.ceil(Number(value.size_bytes || 0) / 1024))} KB`,
    version: `v${Number(value.version || 1)}`,
    status: 'ready',
    claimId: value.claim_id ? String(value.claim_id) : undefined,
    updated: String(value.created_at || 'just now'),
  };
}

function mapServerStatus(
  summary: Awaited<ReturnType<typeof api.getRun>>,
): Pick<RunSnapshot, 'stages' | 'activeStage' | 'stageManifestHashes' | 'status'> {
  const stageState: Record<string, { active: StageId; completed: StageId[]; ready?: StageId; review?: StageId }> = {
    READY_FOR_STAGE_1: { active: 'claims', completed: [], ready: 'claims' },
    CLAIMS_RUNNING: { active: 'claims', completed: [] },
    CLAIMS_AWAITING_REVIEW: { active: 'claims', completed: [], review: 'claims' },
    CLAIMS_APPROVED: { active: 'rules', completed: ['claims'], ready: 'rules' },
    RULES_RUNNING: { active: 'rules', completed: ['claims'] },
    RULES_AWAITING_REVIEW: { active: 'rules', completed: ['claims'], review: 'rules' },
    RULES_APPROVED: { active: 'rules', completed: ['claims', 'rules'] },
    EVALUATION_RUNNING: { active: 'evaluation', completed: ['claims', 'rules'] },
    EVALUATION_AWAITING_REVIEW: { active: 'evaluation', completed: ['claims', 'rules'], review: 'evaluation' },
    COMPLETE: { active: 'evaluation', completed: ['claims', 'rules', 'evaluation'] },
  };
  const state = stageState[summary.status];
  const isRunning = summary.status.endsWith('RUNNING');
  // FAILED and PAUSED both record the affected stage in `active_stage`. Earlier stages
  // stay approved; the affected stage is shown as error (resume via Rerun) or paused
  // (resume via Resume) so it can be continued in place without restarting Stage 1.
  const stageOrder: StageId[] = ['claims', 'rules', 'evaluation'];
  const interruptedStatus: 'error' | 'paused' | null =
    summary.status === 'FAILED' ? 'error' : summary.status === 'PAUSED' ? 'paused' : null;
  const interruptedStage: StageId | null =
    interruptedStatus ? ((summary.active_stage as StageId) || 'claims') : null;
  const interruptedIndex = interruptedStage ? stageOrder.indexOf(interruptedStage) : -1;
  const stages = structuredClone(demoRun.stages).map(stage => {
    if (stage.id === 'evaluation') {
      const isApproved = state?.completed.includes(stage.id) || summary.status === 'COMPLETE';
      const isReview = state?.review === stage.id || summary.status === 'EVALUATION_AWAITING_REVIEW';
      const isRunningNow = (isRunning && state?.active === stage.id) || summary.status === 'EVALUATION_RUNNING';
      const isReadyNow = state?.ready === stage.id || summary.status === 'RULES_APPROVED';
      const isError = summary.status === 'FAILED' && summary.active_stage === 'evaluation';
      const isPaused = summary.status === 'PAUSED' && summary.active_stage === 'evaluation';
      return {
        ...stage,
        title: 'Section 16.3 Understanding',
        subtitle: 'Reproduction blueprint builder',
        status: isApproved
          ? ('approved' as const)
          : isReview
            ? ('review' as const)
            : isRunningNow
              ? ('running' as const)
              : isError
                ? ('error' as const)
                : isPaused
                  ? ('paused' as const)
                  : isReadyNow
                    ? ('ready' as const)
                    : ('locked' as const),
        progress: isApproved || isReview ? 100 : isRunningNow ? 40 : 0,
        placeholder: false,
      };
    }
    if (interruptedStage && interruptedStatus) {
      const idx = stageOrder.indexOf(stage.id);
      const st =
        stage.id === interruptedStage ? interruptedStatus : idx < interruptedIndex ? 'approved' : 'locked';
      return { ...stage, status: st as 'error' | 'paused' | 'approved' | 'locked', progress: st === 'approved' ? 100 : 0 };
    }
    return {
      ...stage,
      status: state?.completed.includes(stage.id)
        ? ('approved' as const)
        : state?.review === stage.id
          ? ('review' as const)
          : isRunning && state?.active === stage.id
            ? ('running' as const)
            : state?.ready === stage.id
              ? ('ready' as const)
              : ('locked' as const),
      progress: state?.completed.includes(stage.id) || state?.review === stage.id ? 100 : 0,
    };
  });
  return {
    status: summary.status.replaceAll('_', ' '),
    activeStage: interruptedStage || state?.active || 'claims',
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
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(null);
  const [activeSection, setActiveSection] = useState('s163');
  const [selectedClaim, setSelectedClaim] = useState<string | null>(apiMode ? null : 'CLM-0001');
  const [activeTab, setActiveTab] = useState<'activity' | 'document' | 'artifacts'>('activity');
  const [rightTab, setRightTab] = useState<'claims' | 'agents'>('claims');
  const [searchText, setSearchText] = useState('');
  const [claimStatusFilter, setClaimStatusFilter] = useState('all');
  const [showUpload, setShowUpload] = useState(false);
  const [showClaimEditor, setShowClaimEditor] = useState(false);
  const [showReview, setShowReview] = useState(false);
  const [claimDataView, setClaimDataView] = useState<{ claimId: string } | null>(null);
  const [claimData, setClaimData] = useState<ClaimData | null>(null);
  const [claimSourceData, setClaimSourceData] = useState<ClaimSourceData | null>(null);
  const [claimDataLoading, setClaimDataLoading] = useState(false);
  const [claimDataError, setClaimDataError] = useState<string | null>(null);
  const [showSourcePanel, setShowSourcePanel] = useState(false);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState('');
  const [showAllActivity, setShowAllActivity] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [leftTab, setLeftTab] = useState<'workspace' | 'history'>('workspace');
  const [sessionHistory, setSessionHistory] = useState<RunSummary[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [claimDraft, setClaimDraft] = useState({ statement: '', reportedValue: '', unit: '', searchCriteria: '' });
  const [notice, setNotice] = useState('');
  const [newRunName, setNewRunName] = useState('PBRER · New run');
  const [targetFile, setTargetFile] = useState<File | null>(null);
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const [uploadError, setUploadError] = useState('');
  const [loadingStage, setLoadingStage] = useState(false);
  const [openedArtifact, setOpenedArtifact] = useState<OpenedArtifact | null>(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const uploadInput = useRef<HTMLInputElement>(null);
  const sourceInput = useRef<HTMLInputElement>(null);
  const lastRefreshRef = useRef(0);

  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>('learning');
  const [approvedBlueprintAvailable, setApprovedBlueprintAvailable] = useState(false);

  useEffect(() => {
    if (!apiMode) return;
    let cancelled = false;
    const refresh = () =>
      generatorApi
        .listBlueprints()
        .then(items => {
          if (!cancelled) setApprovedBlueprintAvailable(items.length > 0);
        })
        .catch(() => {
          if (!cancelled) setApprovedBlueprintAvailable(false);
        });
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  async function loadSessionHistory() {
    setHistoryLoading(true);
    setHistoryError('');
    try {
      setSessionHistory(await api.listRuns());
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : String(error));
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    if (!apiMode) return;
    api.getConfig().then(setRuntimeConfig).catch(() => {});
  }, []);

  useEffect(() => {
    if (!apiMode || leftTab !== 'history') return;
    void loadSessionHistory();
  }, [apiMode, leftTab]);

  const currentStage = run.stages.find(s => s.id === run.activeStage) || run.stages[0];
  const selectedClaimData = run.claims.find(c => c.id === selectedClaim) || null;
  const activeSource = run.sources.find(s => s.id === selectedSource || s.name === selectedSource) || null;
  const verifiedCount = useMemo(
    () => run.claims.filter(c => c.status === 'verified' || c.verificationResult?.verified === true).length,
    [run.claims],
  );
  const filteredClaims = useMemo(
    () =>
      run.claims.filter(claim => {
        const matchesText = `${claim.id} ${claim.statement} ${claim.sectionNumber} ${claim.searchCriteria || ''}`
          .toLowerCase()
          .includes(searchText.toLowerCase());
        const matchesStatus = claimStatusFilter === 'all' || claim.status === claimStatusFilter;
        return matchesText && matchesStatus;
      }),
    [run.claims, searchText, claimStatusFilter],
  );
  const activityItems = showAllActivity ? [...run.activity].reverse() : [...run.activity].slice(-8).reverse();

  function pushActivity(item: Omit<ActivityItem, 'id' | 'time'>) {
    const now = new Date().toLocaleTimeString('en-GB', { hour12: false });
    setRun(prev => ({
      ...prev,
      activity: [
        ...prev.activity,
        { ...item, id: `ev-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`, time: now },
      ],
    }));
  }

  function patchStage(stageId: StageId, patch: Partial<RunSnapshot['stages'][number]>) {
    setRun(prev => ({
      ...prev,
      stages: prev.stages.map(s => (s.id === stageId ? { ...s, ...patch } : s)),
    }));
  }

  async function refreshLiveRun(runId: string) {
    const [summary, claims, sections, sources, artifacts, document] = await Promise.all([
      api.getRun(runId).catch(() => null),
      api.listClaims(runId).catch(() => [] as Record<string, unknown>[]),
      api.getSections(runId).catch(() => [] as Record<string, unknown>[]),
      api.listSources(runId).catch(() => [] as Record<string, unknown>[]),
      api.listArtifacts(runId).catch(() => [] as Record<string, unknown>[]),
      api.getDocument(runId).catch(() => ({ blocks: [] as DocumentBlock[] })),
    ]);
    setRun(prev => {
      const mappedClaims = claims.map(mapServerClaim);
      const mappedSources = sources.length ? sources.map(mapServerSource) : prev.sources;
      const mappedArtifacts = artifacts.map(mapServerArtifact);
      const artifactsByStage = mappedArtifacts.reduce<Record<string, number>>((acc, a) => {
        acc[a.stage] = (acc[a.stage] || 0) + 1;
        return acc;
      }, {});
      const next: RunSnapshot = {
        ...prev,
        claims: mappedClaims.length ? mappedClaims : prev.claims,
        sections: sections.length ? mapServerSections(sections) : prev.sections,
        sources: mappedSources,
        artifacts: mappedArtifacts,
        documentBlocks: (document as { blocks: DocumentBlock[] }).blocks?.length
          ? (document as { blocks: DocumentBlock[] }).blocks
          : prev.documentBlocks,
      };
      if (summary) {
        const mapped = mapServerStatus(summary);
        next.stages = mapped.stages.map(stage => {
          const prevStage = prev.stages.find(p => p.id === stage.id);
          return {
            ...stage,
            progress:
              stage.status === 'running' ? Math.max(prevStage?.progress ?? 8, stage.progress) : stage.progress,
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

  async function reopenSession(session: RunSummary) {
    setLoadingStage(true);
    setHistoryError('');
    setNotice('');
    try {
      const summary = await api.getRun(session.run_id);
      const mapped = mapServerStatus(summary);
      const reopened = emptyRun();
      reopened.runId = summary.run_id;
      reopened.name = summary.run_name;
      reopened.createdAt = summary.created_at;
      reopened.product = summary.product_name || '';
      reopened.period = [summary.reporting_period_start, summary.reporting_period_end]
        .filter(Boolean)
        .join(' – ');
      reopened.targetDocument = summary.target_document_filename || 'Previously uploaded target';
      reopened.inputManifestHash = summary.input_manifest_hash;
      reopened.stageManifestHashes = mapped.stageManifestHashes;
      reopened.stages = mapped.stages;
      reopened.activeStage = mapped.activeStage;
      reopened.status = mapped.status;
      setRun(reopened);
      setSelectedClaim(null);
      setSelectedSource(null);
      setActiveSection('');
      setActiveTab('activity');
      setLeftTab('workspace');
      setShowReview(false);
      await refreshLiveRun(summary.run_id);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingStage(false);
    }
  }

  function scheduleRefresh(runId: string, force = false) {
    if (!runId) return;
    const now = Date.now();
    if (force || now - lastRefreshRef.current > 1000) {
      lastRefreshRef.current = now;
      void refreshLiveRun(runId).catch(() => {});
    }
  }

  async function getCurrentStageManifest(stageId: StageId) {
    if (!run.runId) return undefined;
    const summary = await api.getRun(run.runId);
    const mapped = mapServerStatus(summary);
    setRun(prev => ({ ...prev, ...mapped }));
    return mapped.stageManifestHashes?.[stageId];
  }

  async function openArtifact(artifact: ArtifactItem) {
    if (!apiMode || !run.runId) {
      setOpenedArtifact({
        title: artifact.name,
        subtitle: `${artifact.type} · ${artifact.size} · ${artifact.version}`,
        mediaType: artifact.name.endsWith('.py') ? 'text/x-python' : 'text/markdown',
        content:
          `Preview placeholder for demo mode artifact "${artifact.name}".\n` +
          `Start the FastAPI backend (VITE_API_MODE=api) to inspect real generated .py, .md, and .json artifacts.`,
      });
      return;
    }
    setArtifactLoading(true);
    try {
      const data = await api.getArtifactContent(run.runId, artifact.id);
      setOpenedArtifact({
        title: data.logical_path,
        subtitle: `${data.media_type} · ${Math.max(1, Math.ceil(data.size_bytes / 1024))} KB`,
        mediaType: data.media_type,
        sha256: data.sha256,
        content: data.content,
      });
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err));
    } finally {
      setArtifactLoading(false);
    }
  }

  async function openClaimData(claim: Claim) {
    setClaimDataView({ claimId: claim.id });
    setClaimData(null);
    setClaimSourceData(null);
    setClaimDataError(null);
    if (!apiMode || !run.runId) {
      setClaimDataError('Source data is available only for live runs. Start the FastAPI backend and run Stage 2.');
      return;
    }
    setClaimDataLoading(true);
    try {
      // Full source sheet(s) are the primary view; the agent's matched subset is supplementary.
      const [sourceRes, matchedRes] = await Promise.allSettled([
        api.getClaimSourceData(run.runId, claim.id),
        api.getClaimData(run.runId, claim.id),
      ]);
      if (sourceRes.status === 'fulfilled') setClaimSourceData(sourceRes.value);
      if (matchedRes.status === 'fulfilled') setClaimData(matchedRes.value);
      if (sourceRes.status === 'rejected' && matchedRes.status === 'rejected') {
        const reason = sourceRes.reason;
        setClaimDataError(reason instanceof Error ? reason.message : String(reason));
      }
    } catch (err) {
      setClaimDataError(err instanceof Error ? err.message : String(err));
    } finally {
      setClaimDataLoading(false);
    }
  }

  async function openMasterSummary() {
    if (!apiMode || !run.runId) {
      setOpenedArtifact({
        title: 'stage_1_claims/master_source_summary.md',
        subtitle: 'text/markdown · Master summary of source documents',
        mediaType: 'text/markdown',
        content:
          '# Master Summary of Source Documents\n\n' +
          'Synthesized after the per-file Agentic Harness finishes exploring every uploaded file.',
      });
      return;
    }
    setArtifactLoading(true);
    try {
      const res = await api.getMasterSummary(run.runId);
      setOpenedArtifact({
        title: res.logical_path,
        subtitle: 'text/markdown · Master summary of all source documents',
        mediaType: 'text/markdown',
        content: res.content,
      });
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err));
    } finally {
      setArtifactLoading(false);
    }
  }

  async function beginLiveStage(stageId: StageId) {
    if (stageId === 'evaluation') {
      if (!run.runId) {
        setNotice('Create a run with your DOCX and XLSX/CSV files first.');
        return;
      }
      setLoadingStage(true);
      try {
        const summary = await api.getRun(run.runId);
        const mapped = mapServerStatus(summary);
        setRun(prev => ({ ...prev, ...mapped }));
        if (summary.status !== 'RULES_APPROVED') {
          setNotice(`Stage 3 requires Stage 2 approval. Current run status: ${summary.status.replaceAll('_', ' ')}.`);
          return;
        }
        const rulesHash = summary.stage_2_manifest_hash;
        if (!rulesHash) {
          setNotice('Stage 2 rules manifest is missing. Rerun or approve Stage 2 first.');
          return;
        }
        await generatorApi.startUnderstanding(run.runId, rulesHash);
        setNotice('Section 16.3 Understanding started — streaming blueprint authoring activity.');
        await refreshLiveRun(run.runId);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      } finally {
        setLoadingStage(false);
      }
      return;
    }
    if (!run.runId) {
      setNotice('Create a run with your DOCX and XLSX/CSV files first.');
      return;
    }
    setLoadingStage(true);
    try {
      const summary = await api.getRun(run.runId);
      const mapped = mapServerStatus(summary);
      setRun(prev => ({
        ...prev,
        ...mapped,
        inputManifestHash: summary.input_manifest_hash,
      }));

      if (stageId === 'rules' && summary.status !== 'CLAIMS_APPROVED') {
        setNotice(`Stage 2 requires Stage 1 approval. Current run status: ${summary.status.replaceAll('_', ' ')}.`);
        return;
      }

      const inputHash =
        stageId === 'claims' ? summary.input_manifest_hash : summary.stage_1_manifest_hash;
      if (!inputHash) {
        setNotice(
          `No completed Stage 1 manifest is recorded for run ${run.runId.slice(0, 8)}. Refresh the run or rerun Stage 1.`,
        );
        return;
      }

      setRun(prev => ({
        ...prev,
        activeStage: stageId,
        status: `${stageLabel[stageId]} · Running`,
        agents: [],
        stages: prev.stages.map(stage =>
          stage.id === stageId ? { ...stage, status: 'running', progress: 8, subagents: 0, agents: 0 } : stage,
        ),
      }));
      await api.startStage(run.runId, stageId, inputHash, crypto.randomUUID());
      setNotice(`${stageLabel[stageId]} started — streaming live harness & Strands activity.`);
    } catch (error) {
      await refreshLiveRun(run.runId);
      setNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingStage(false);
    }
  }

  async function rerunLiveStage(stageId: StageId) {
    if (stageId === 'evaluation') {
      if (!run.runId) {
        setNotice('No active run to rerun. Create or reopen a run first.');
        return;
      }
      setLoadingStage(true);
      try {
        const summary = await api.getRun(run.runId);
        const rulesHash = summary.stage_2_manifest_hash;
        if (!rulesHash) {
          setNotice('Stage 2 rules manifest is missing. Rerun or approve Stage 2 first.');
          return;
        }
        await generatorApi.startUnderstanding(run.runId, rulesHash);
        setNotice('Section 16.3 Understanding re-running.');
        await refreshLiveRun(run.runId);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      } finally {
        setLoadingStage(false);
      }
      return;
    }
    if (!run.runId) {
      setNotice('No active run to rerun. Create or reopen a run first.');
      return;
    }
    setLoadingStage(true);
    try {
      const summary = await api.getRun(run.runId);
      const inputHash =
        stageId === 'claims' ? summary.input_manifest_hash : summary.stage_1_manifest_hash;
      if (!inputHash) {
        setNotice(
          `Cannot rerun ${stageLabel[stageId]} — its input manifest is missing. Rerun the previous stage first.`,
        );
        return;
      }
      setRun(prev => ({
        ...prev,
        activeStage: stageId,
        status: `${stageLabel[stageId]} · Re-running`,
        agents: [],
        stages: prev.stages.map(stage =>
          stage.id === stageId ? { ...stage, status: 'running', progress: 8, subagents: 0, agents: 0 } : stage,
        ),
      }));
      await api.rerunStage(run.runId, stageId, inputHash, crypto.randomUUID());
      setNotice(`${stageLabel[stageId]} re-running — streaming live harness & Strands activity.`);
    } catch (error) {
      await refreshLiveRun(run.runId);
      setNotice(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingStage(false);
    }
  }

  function rerunStage(stageId: StageId) {
    if (apiMode) {
      void rerunLiveStage(stageId);
      return;
    }
    // Demo mode: reset the stage then replay the simulation.
    setRun(prev => ({
      ...prev,
      stages: prev.stages.map(s => (s.id === stageId ? { ...s, status: 'ready' } : s)),
    }));
    beginStage(stageId);
  }

  async function pauseStage(stageId: StageId) {
    if (!apiMode || !run.runId) {
      setNotice('Pausing a session is available only for live runs.');
      return;
    }
    try {
      await api.pauseStage(run.runId, stageId);
      setNotice(`Pause requested — ${stageLabel[stageId]} will stop after the current claim. Use Resume to continue.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  function beginStage(stageId: StageId) {
    const stage = run.stages.find(s => s.id === stageId);
    if (!stage || stage.status === 'locked' || stage.status === 'running') return;
    if (stageId === 'rules' && run.stages[0].status !== 'approved') return;
    if (apiMode) {
      void beginLiveStage(stageId);
      return;
    }

    // Demo UI simulation showing Stage 1 exploration -> Strands claims and Stage 2 per-claim harness verification
    setLoadingStage(true);
    setRun(prev => ({
      ...prev,
      activeStage: stageId,
      stages: prev.stages.map(s => (s.id === stageId ? { ...s, status: 'running', progress: 15 } : s)),
      status: `${stageLabel[stageId]} · Running`,
    }));
    if (stageId === 'rules') {
      pushActivity({
        stage: 'rules',
        title: 'Rules Harness verifying claims',
        detail: 'Running Agentic Harness per claim using per-file .md summaries + claim hierarchy.',
        kind: 'agent',
        agent: 'RuleHarness',
        status: 'running',
      });
      setTimeout(() => {
        const newArtifacts: ArtifactItem[] = run.claims.flatMap(c => [
          {
            id: `py-${c.id}`,
            name: `stage_2_rules/claims/${c.id}/analysis.py`,
            type: 'Python rule script',
            stage: 'rules' as const,
            size: '3 KB',
            version: 'v1',
            status: 'ready' as const,
            claimId: c.id,
            updated: 'just now',
          },
          {
            id: `res-${c.id}`,
            name: `stage_2_rules/claims/${c.id}/result.json`,
            type: 'Verification result',
            stage: 'rules' as const,
            size: '1 KB',
            version: 'v1',
            status: 'ready' as const,
            claimId: c.id,
            updated: 'just now',
          },
        ]);
        setRun(prev => ({
          ...prev,
          status: 'Rules Engineering · In review',
          artifacts: [...prev.artifacts, ...newArtifacts],
          stages: prev.stages.map(s =>
            s.id === 'rules' ? { ...s, progress: 100, status: 'review', artifacts: newArtifacts.length } : s,
          ),
          claims: prev.claims.map((c, idx) => ({
            ...c,
            status: idx < prev.claims.length - 1 ? 'verified' : 'discrepancy',
            childrenClaims: c.childrenClaims.map(ch => ({
              ...ch,
              verified: idx < prev.claims.length - 1,
              computed_value: ch.reported_value,
            })),
            verificationResult: {
              verified: idx < prev.claims.length - 1,
              status: idx < prev.claims.length - 1 ? 'verified' : 'discrepancy',
              parent_computed_value: idx < prev.claims.length - 1 ? c.reportedValue : '12380',
              parent_reported_value: c.reportedValue,
              discrepancy_summary: idx < prev.claims.length - 1 ? null : `Computed 12380 vs reported ${c.reportedValue}`,
            },
          })),
        }));
        pushActivity({
          stage: 'rules',
          title: 'Stage 2 complete — claims verified',
          detail: 'Verified claims are marked green in the Claim Register.',
          kind: 'success',
          status: 'done',
        });
        setLoadingStage(false);
      }, 1500);
    } else {
      setTimeout(() => {
        patchStage(stageId, { progress: 100, status: 'review' });
        setLoadingStage(false);
      }, 1000);
    }
  }

  async function approveStage(stageId: StageId) {
    if (stageId === 'evaluation') {
      if (!run.runId) {
        setShowReview(false);
        return;
      }
      try {
        const expectedManifest = await getCurrentStageManifest(stageId);
        if (!expectedManifest) {
          setNotice('No completed stage 3 blueprint manifest is recorded. Rerun understanding first.');
          return;
        }
        await generatorApi.reviewUnderstanding(run.runId, 'approve', expectedManifest, reviewNote || undefined);
        const summary = await api.getRun(run.runId);
        setRun(prev => ({ ...prev, ...mapServerStatus(summary) }));
        setShowReview(false);
        setReviewNote('');
        setNotice('Section 16.3 Reproduction Blueprint approved. Section Generator unlocked.');
        void generatorApi.listBlueprints().then(items => setApprovedBlueprintAvailable(items.length > 0));
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    if (apiMode) {
      if (!run.runId) {
        setNotice('No run is selected; approval was not sent.');
        return;
      }
      try {
        const expectedManifest = await getCurrentStageManifest(stageId);
        if (!expectedManifest) {
          setNotice('No completed stage manifest is recorded. If the stage was interrupted, rerun it before approval.');
          return;
        }
        await api.reviewStage(run.runId, stageId, 'approve', expectedManifest, reviewNote || undefined);
        const summary = await api.getRun(run.runId);
        setRun(prev => ({ ...prev, ...mapServerStatus(summary) }));
        setShowReview(false);
        setReviewNote('');
        setNotice(`${stageLabel[stageId]} approved.`);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    const stageIndex = stageOrder.indexOf(stageId);
    const nextStage = stageOrder[stageIndex + 1];
    patchStage(stageId, { status: 'approved' });
    pushActivity({
      stage: stageId,
      title: `${stageLabel[stageId]} approved by reviewer`,
      detail: 'Approval recorded. Next stage unlocked.',
      kind: 'gate',
      status: 'done',
    });
    setRun(prev => ({
      ...prev,
      status: nextStage === 'evaluation' ? 'Rules Approved · Stage 3 Ready' : `${stageLabel[nextStage]} · Ready`,
      activeStage: nextStage === 'evaluation' ? 'evaluation' : nextStage,
      stages: prev.stages.map(s =>
        s.id === nextStage ? { ...s, status: 'ready' } : s,
      ),
    }));
    setShowReview(false);
    setReviewNote('');
  }

  async function requestChanges(stageId: StageId) {
    if (stageId === 'evaluation' && apiMode) {
      if (!run.runId) {
        setNotice('No run is selected; review changes were not sent.');
        return;
      }
      try {
        const expectedManifest = await getCurrentStageManifest(stageId);
        if (!expectedManifest) {
          setNotice('No completed stage 3 blueprint manifest is recorded.');
          return;
        }
        await generatorApi.reviewUnderstanding(run.runId, 'request_changes', expectedManifest, reviewNote || undefined);
        const summary = await api.getRun(run.runId);
        setRun(prev => ({ ...prev, ...mapServerStatus(summary), reviewNote }));
        setShowReview(false);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    if (apiMode) {
      if (!run.runId) {
        setNotice('No run is selected; review changes were not sent.');
        return;
      }
      try {
        const expectedManifest = await getCurrentStageManifest(stageId);
        if (!expectedManifest) {
          setNotice('No completed stage manifest is recorded. Refresh the run or rerun the interrupted stage before review.');
          return;
        }
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
    setRun(prev => ({ ...prev, status: `${stageLabel[stageId]} · Changes requested`, reviewNote }));
    setShowReview(false);
  }

  function editClaim(claim: Claim) {
    setClaimDraft({
      statement: claim.statement,
      reportedValue: claim.reportedValue,
      unit: claim.unit,
      searchCriteria: claim.searchCriteria || '',
    });
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
        const updated = (await api.updateClaim(run.runId, selectedClaim, {
          expected_version: claim.version,
          reviewer_reason: 'Reviewer updated claim details in workspace',
          normalized_statement: claimDraft.statement,
          reported_value: claimDraft.reportedValue,
          unit: claimDraft.unit,
          search_criteria: claimDraft.searchCriteria,
        })) as Record<string, unknown>;
        setRun(prev => ({
          ...prev,
          claims: prev.claims.map(item => (item.id === selectedClaim ? mapServerClaim(updated) : item)),
        }));
        pushActivity({
          stage: 'claims',
          title: `Claim ${selectedClaim} updated`,
          detail: 'Claim edit saved via API.',
          kind: 'system',
          status: 'done',
        });
        setShowClaimEditor(false);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
      return;
    }
    setRun(prev => ({
      ...prev,
      claims: prev.claims.map(c => (c.id === selectedClaim ? { ...c, ...claimDraft } : c)),
    }));
    setShowClaimEditor(false);
  }

  function addFiles(files: FileList | null, isTarget: boolean) {
    if (!files) return;
    setUploadError('');
    const allowed = apiMode ? (isTarget ? ['.docx'] : ['.xlsx', '.csv']) : isTarget ? ['.docx', '.pdf'] : ['.xlsx', '.xls', '.csv', '.pdf', '.docx'];
    const list = Array.from(files);
    const invalid = list.find(f => !allowed.some(ext => f.name.toLowerCase().endsWith(ext)));
    if (invalid) {
      setUploadError(`${invalid.name} is not a supported ${isTarget ? 'target report' : 'source'} file.`);
      return;
    }
    if (isTarget) setTargetFile(list[0]);
    else setSourceFiles(prev => [...prev, ...list]);
  }

  const aguiConnection = useAguiEvents(run.runId, apiMode, event => {
    const runId = run.runId;
    if (event.type === 'CUSTOM' && event.name === 'tracewise.activity') {
      const value = (event.value || {}) as Record<string, unknown>;
      const stage = (value.stage as StageId) || run.activeStage;
      pushActivity({
        stage,
        title: String(value.title || 'Agent activity'),
        detail: String(value.detail || 'Operational event received from AG-UI stream.'),
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
        stages: prev.stages.map(s =>
          s.id === stage
            ? {
                ...s,
                status:
                  status === 'placeholder'
                    ? 'placeholder'
                    : status === 'review'
                      ? 'review'
                      : status === 'error'
                        ? 'error'
                        : status === 'paused'
                          ? 'paused'
                          : status === 'running'
                            ? 'running'
                            : s.status,
                progress: status === 'review' ? 100 : Math.max(s.progress, progress),
              }
            : s,
        ),
      }));
      scheduleRefresh(runId, status === 'review' || status === 'error' || status === 'paused');
    } else if (event.type === 'CUSTOM' && event.name === 'tracewise.claim') {
      const value = (event.value || {}) as Record<string, unknown>;
      if (value.claim && typeof value.claim === 'object') {
        const mapped = mapServerClaim(value.claim as Record<string, unknown>);
        setRun(prev => {
          const exists = prev.claims.some(c => c.id === mapped.id);
          return {
            ...prev,
            claims: exists ? prev.claims.map(c => (c.id === mapped.id ? mapped : c)) : [...prev.claims, mapped],
          };
        });
        setSelectedClaim(prev => prev || mapped.id);
      }
      scheduleRefresh(runId);
    } else if (event.type === 'CUSTOM' && event.name === 'tracewise.artifact') {
      scheduleRefresh(runId);
    } else if (event.type === 'TOOL_CALL_START') {
      pushActivity({
        stage: run.activeStage,
        title: `Tool · ${String(event.toolName || 'tool')}`,
        detail: 'Scoped harness tool invoked.',
        kind: 'tool',
        status: 'running',
      });
    } else if (event.type === 'RUN_ERROR') {
      pushActivity({
        stage: run.activeStage,
        title: 'Stage execution error',
        detail: String(event.message || 'The stage agent returned an error.'),
        kind: 'warning',
        status: 'error',
      });
      scheduleRefresh(runId, true);
    }
  });

  async function createDemoRun() {
    if (!targetFile) {
      setUploadError('Add one target PBRER document to continue.');
      return;
    }
    if (!sourceFiles.length) {
      setUploadError('Add at least one source document to continue.');
      return;
    }
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
          kind: (file.name.split('.').pop()?.toLowerCase() || 'other') as RunSnapshot['sources'][number]['kind'],
          sizeLabel: `${(file.size / 1024 / 1024).toFixed(2)} MB`,
          status: 'pending',
          usedBy: 0,
        }));
        liveRun.inputManifestHash = created.input_manifest_hash;
        liveRun.stages = liveRun.stages.map((stage, index) => ({
          ...stage,
          status: stage.id === 'evaluation' ? 'placeholder' : index === 0 ? 'ready' : 'locked',
        }));
        liveRun.status = 'Ready for Stage 1';
        setRun(liveRun);
        setShowUpload(false);
        setSelectedClaim(null);
        setActiveSection('');
        pushActivity({
          stage: 'claims',
          title: 'Live run created',
          detail: 'Target DOCX and source files saved immutably. Start Stage 1 to explore files.',
          kind: 'system',
          status: 'done',
        });
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
    newRun.sources = sourceFiles.map((f, i) => ({
      id: `uploaded-${i}`,
      name: f.name,
      kind: (f.name.split('.').pop()?.toLowerCase() || 'other') as RunSnapshot['sources'][number]['kind'],
      sizeLabel: `${(f.size / 1024 / 1024).toFixed(2)} MB`,
      status: 'pending',
      usedBy: 0,
    }));
    newRun.claims = [];
    newRun.agents = [];
    newRun.activity = [];
    newRun.artifacts = [];
    newRun.activeStage = 'claims';
    newRun.status = 'Ready for Stage 1';
    setRun(newRun);
    setShowUpload(false);
    setSelectedClaim(null);
    setTargetFile(null);
    setSourceFiles([]);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark"><GitBranch size={18} strokeWidth={2.3} /></div>
          <div className="brand-name">tracewise<span>WORKSPACE</span></div>
        </div>
        <div className="topbar-divider" />
        <div className="run-selector">
          <span className="run-breadcrumb">PROJECT</span>
          <ChevronRight size={13} />
          <strong>{run.runId || 'NEW RUN'}</strong>
        </div>
        <div className="topbar-spacer" />
        <span className="demo-chip">
          <span />
          {apiMode
            ? `LIVE API · ${(runtimeConfig?.llm_provider || 'backend').toUpperCase()}`
            : 'DEMO DATA'}
        </span>
        <button className="top-icon" title="Command palette"><Command size={16} /><kbd>⌘ K</kbd></button>
        <button className="top-icon" title="Settings"><Settings2 size={17} /></button>
        <div className="topbar-divider short" />
        <Avatar initials="AR" tone="dark" size="md" />
      </header>

      <WorkspaceModeTabs
        mode={workspaceMode}
        onChange={setWorkspaceMode}
        generatorEnabled={approvedBlueprintAvailable}
      />

      {workspaceMode === 'generator' ? (
        <SectionGeneratorWorkspace />
      ) : (
        <div className="app-body">
        <aside className={cx('left-rail', leftCollapsed && 'collapsed')}>
          <div className="rail-topline">
            <span>RUN WORKSPACE</span>
            <IconButton
              title={leftCollapsed ? 'Expand left panel' : 'Collapse left panel'}
              onClick={() => setLeftCollapsed(!leftCollapsed)}
            >
              <PanelLeftClose size={15} />
            </IconButton>
          </div>
          {!leftCollapsed && (
            <>
              <div className="run-summary">
                <div className="run-summary-icon"><FileCheck2 size={18} /></div>
                <div className="run-summary-copy">
                  <strong>{run.name}</strong>
                  <span>{run.period || 'PBRER Section 16.3'}</span>
                </div>
              </div>
              <div className="rail-tabs" role="tablist" aria-label="Run navigation">
                <button
                  className={leftTab === 'workspace' ? 'active' : ''}
                  role="tab"
                  aria-selected={leftTab === 'workspace'}
                  onClick={() => setLeftTab('workspace')}
                >
                  <FolderOpen size={13} />Workspace
                </button>
                <button
                  className={leftTab === 'history' ? 'active' : ''}
                  role="tab"
                  aria-selected={leftTab === 'history'}
                  onClick={() => setLeftTab('history')}
                >
                  <History size={13} />History
                </button>
              </div>
              {leftTab === 'history' ? (
                <div className="session-history" role="tabpanel">
                  <div className="rail-section-head">
                    <span>PREVIOUS RUNS</span>
                    <button
                      className="mini-add"
                      onClick={() => void loadSessionHistory()}
                      title="Refresh session history"
                    >
                      <RefreshCw size={12} />
                    </button>
                  </div>
                  {historyLoading ? (
                    <div className="history-message">Loading saved runs…</div>
                  ) : historyError ? (
                    <div className="history-message error">{historyError}</div>
                  ) : sessionHistory.length === 0 ? (
                    <div className="history-message">No saved runs yet. Uploaded runs will appear here.</div>
                  ) : (
                    <div className="session-history-list">
                      {sessionHistory.map(session => (
                        <button
                          key={session.run_id}
                          className={cx('session-history-item', session.run_id === run.runId && 'selected')}
                          disabled={loadingStage}
                          onClick={() => void reopenSession(session)}
                          title={`Reopen ${session.run_name}`}
                        >
                          <span className="session-history-item-top">
                            <strong>{session.run_name}</strong>
                            <StatusDot
                              status={
                                session.status.includes('AWAITING_REVIEW')
                                  ? 'review'
                                  : session.status.toLowerCase()
                              }
                            />
                          </span>
                          <span className="session-history-status">{statusLabel(session.status)}</span>
                          <span className="session-history-date">
                            {new Date(session.created_at).toLocaleString()}
                          </span>
                          <span className="session-history-id">{session.run_id}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {loadingStage && <div className="history-message">Reopening saved run…</div>}
                </div>
              ) : (
                <>
              <div className="rail-section-head">
                <span>DOCUMENT STRUCTURE</span>
                <span className="tiny-count">{run.sections.length}</span>
              </div>
              <div className="tree-tools">
                <span className="outline-search">
                  <Search size={13} />
                  <input placeholder="Find section" />
                </span>
              </div>
              <div className="tree-list">
                <SectionTree
                  nodes={run.sections}
                  activeId={activeSection}
                  onSelect={id => {
                    setActiveSection(id);
                    setActiveTab('document');
                  }}
                />
              </div>
              <div className="rail-section-head source-head">
                <span>SOURCE FILES</span>
                <span className="tiny-count">{run.sources.length}</span>
                <button className="mini-add" onClick={() => setShowUpload(true)} title="Upload files">
                  <Plus size={13} />
                </button>
              </div>
              <div className="source-list">
                {run.sources.map(source => (
                  <button
                    className={cx('source-row', selectedSource === source.id && 'selected')}
                    key={source.id}
                    onClick={() => {
                      setSelectedSource(source.id);
                      setShowSourcePanel(true);
                    }}
                  >
                    <span className={`file-icon ${source.kind}`}>{fileIcon(source.kind)}</span>
                    <span className="source-row-copy">
                      <strong>{source.name}</strong>
                      <small>{source.sizeLabel}</small>
                    </span>
                    <StatusDot status={source.status} />
                  </button>
                ))}
              </div>
              <div className="storage-card">
                <div className="storage-icon"><HardDrive size={15} /></div>
                <div>
                  <strong>Input snapshot</strong>
                  <span>Read-only · SHA-256 locked</span>
                </div>
                <span className="secure-tag"><Lock size={10} />LOCKED</span>
              </div>
                </>
              )}
            </>
          )}
        </aside>

        <main className="main-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                PBRER SECTION 16.3 <span className="eyebrow-sep">/</span> 3-STAGE PIPELINE
              </div>
              <div className="heading-line">
                <h1>{run.name}</h1>
                <span className="run-status-tag">
                  <StatusDot status={currentStage?.status || 'ready'} />
                  {run.status}
                </span>
              </div>
              <p className="heading-sub">
                {run.targetDocument} <span>·</span> {run.sources.length} source(s)
              </p>
            </div>
            <div className="heading-actions">
              <button className="button-secondary" onClick={() => setShowUpload(true)}>
                <Plus size={15} />Upload files
              </button>
              <button
                className="button-primary"
                onClick={() => setShowReview(true)}
                disabled={currentStage?.status !== 'review'}
              >
                <ShieldCheck size={15} />Review stage
              </button>
            </div>
          </div>

          <StageRail
            stages={run.stages}
            active={run.activeStage}
            onSelect={id => {
              const target = run.stages.find(s => s.id === id);
              if (target && target.status !== 'locked' && target.status !== 'placeholder') {
                setRun(prev => ({ ...prev, activeStage: id }));
              } else if (target?.status === 'placeholder') {
                setNotice('Stage 3 (Independent Evaluation) is currently left as a placeholder.');
              }
            }}
          />

          <div className="metric-strip">
            <Metric icon={<FileText size={16} />} label="SOURCE FILES" value={String(run.sources.length).padStart(2, '0')} sub="Harness cataloged" />
            <Metric icon={<Layers3 size={16} />} label="SECTION 16.3" value={String(run.sections.length).padStart(2, '0')} sub="Scoped sections" />
            <Metric icon={<CheckCheck size={16} />} label="CLAIM GROUPS" value={String(run.claims.length).padStart(2, '0')} sub="Parent + children" />
            <Metric icon={<CheckCircle2 size={16} />} label="VERIFIED CLAIMS" value={`${verifiedCount}/${run.claims.length}`} sub="Stage 2 Python check" />
            <Metric icon={<FileCode2 size={16} />} label="ARTIFACTS" value={String(run.artifacts.length).padStart(2, '0')} sub=".py · .md · .json" />
          </div>

          <div className="workbench-grid">
            <section className="centre-column">
              <div className="panel main-panel">
                <div className="panel-header">
                  <div className="panel-title">
                    <span className="panel-icon"><Activity size={16} /></span>
                    <div>
                      <h2>
                        {activeTab === 'activity'
                          ? 'Agent & harness activity'
                          : activeTab === 'document'
                            ? 'Target document viewer'
                            : 'Artifact explorer'}
                      </h2>
                      <p>
                        {activeTab === 'activity'
                          ? 'Per-file harness · Strands claims · Stage 2 Python rule verification'
                          : activeTab === 'document'
                            ? 'Section 16.3 full subsection context'
                            : 'Inspect generated .py scripts, per-file .md files, master summary, and result.json'}
                      </p>
                    </div>
                  </div>
                  <div className="panel-header-actions">
                    <span className="live-indicator">
                      <span />
                      {run.stages.some(s => s.status === 'running') ? 'LIVE' : 'TRACE'}
                    </span>
                    <IconButton
                      title="Refresh run data"
                      onClick={() => (apiMode && run.runId ? void refreshLiveRun(run.runId) : setNotice('Up to date.'))}
                    >
                      <RefreshCw size={15} />
                    </IconButton>
                  </div>
                </div>

                <div className="content-tabs">
                  <button className={activeTab === 'activity' ? 'active' : ''} onClick={() => setActiveTab('activity')}>
                    <Activity size={14} />Activity <span className="tab-count">{run.activity.length}</span>
                  </button>
                  <button className={activeTab === 'document' ? 'active' : ''} onClick={() => setActiveTab('document')}>
                    <BookOpen size={14} />Document
                  </button>
                  <button className={activeTab === 'artifacts' ? 'active' : ''} onClick={() => setActiveTab('artifacts')}>
                    <FolderOpen size={14} />Artifacts <span className="tab-count">{run.artifacts.length}</span>
                  </button>
                </div>

                {activeTab === 'activity' && (
                  <ActivityView
                    items={activityItems}
                    onSource={id => {
                      setSelectedSource(id);
                      setShowSourcePanel(true);
                    }}
                    onArtifact={() => setActiveTab('artifacts')}
                    showAll={showAllActivity}
                    setShowAll={setShowAllActivity}
                  />
                )}
                {activeTab === 'document' && (
                  <DocumentView
                    run={run}
                    activeSection={activeSection}
                    onSection={setActiveSection}
                    onClaim={id => setSelectedClaim(id)}
                    live={apiMode}
                  />
                )}
                {activeTab === 'artifacts' && (
                  <ArtifactView
                    artifacts={run.artifacts}
                    onOpen={a => void openArtifact(a)}
                    onOpenMasterSummary={() => void openMasterSummary()}
                  />
                )}
              </div>

              <div className="panel stage-panel">
                <div className="panel-header compact">
                  <div className="panel-title">
                    <span className="panel-icon muted"><Workflow size={16} /></span>
                    <div>
                      <h2>Stage control</h2>
                      <p>Stage 1 Exploration · Stage 2 Rules Engineering · Stage 3 Section 16.3 Understanding</p>
                    </div>
                  </div>
                  <span className="control-plane-label"><Lock size={11} />CONTROL PLANE</span>
                </div>
                <div className="stage-control-list">
                  <StageControl
                    stage={run.stages[0]}
                    icon={<Sparkles size={16} />}
                    actionLabel={
                      run.stages[0].status === 'ready'
                        ? 'Start Stage 1'
                        : run.stages[0].status === 'review'
                          ? 'Review & approve'
                          : run.stages[0].status === 'error'
                            ? 'Rerun Stage 1'
                            : run.stages[0].status === 'paused'
                              ? 'Resume Stage 1'
                              : run.stages[0].status === 'changes_requested'
                                ? 'Run corrections'
                                : statusLabel(run.stages[0].status)
                    }
                    actionType={run.stages[0].status === 'review' ? 'review' : 'start'}
                    onAction={() =>
                      run.stages[0].status === 'review'
                        ? setShowReview(true)
                        : run.stages[0].status === 'error' || run.stages[0].status === 'paused'
                          ? rerunStage('claims')
                          : beginStage('claims')
                    }
                    onRerun={() => rerunStage('claims')}
                    onPause={() => void pauseStage('claims')}
                    disabled={['locked', 'running', 'approved'].includes(run.stages[0].status)}
                  />
                  <StageControl
                    stage={run.stages[1]}
                    icon={<Code2 size={16} />}
                    actionLabel={
                      run.stages[1].status === 'locked'
                        ? 'Await Stage 1'
                        : run.stages[1].status === 'ready'
                          ? 'Start Stage 2'
                          : run.stages[1].status === 'review'
                            ? 'Review & approve'
                            : run.stages[1].status === 'error'
                              ? 'Rerun Stage 2'
                              : run.stages[1].status === 'paused'
                                ? 'Resume Stage 2'
                                : run.stages[1].status === 'changes_requested'
                                  ? 'Run corrections'
                                  : statusLabel(run.stages[1].status)
                    }
                    actionType={run.stages[1].status === 'review' ? 'review' : 'start'}
                    onAction={() =>
                      run.stages[1].status === 'review'
                        ? setShowReview(true)
                        : run.stages[1].status === 'error' || run.stages[1].status === 'paused'
                          ? rerunStage('rules')
                          : beginStage('rules')
                    }
                    onRerun={() => rerunStage('rules')}
                    onPause={() => void pauseStage('rules')}
                    disabled={['locked', 'running', 'approved'].includes(run.stages[1].status)}
                  />
                  <StageControl
                    stage={run.stages[2]}
                    icon={<ShieldCheck size={16} />}
                    actionLabel={
                      run.stages[2].status === 'locked'
                        ? 'Await Stage 2'
                        : run.stages[2].status === 'ready'
                          ? 'Start Stage 3'
                          : run.stages[2].status === 'review'
                            ? 'Review & approve'
                            : run.stages[2].status === 'error'
                              ? 'Rerun Stage 3'
                              : run.stages[2].status === 'paused'
                                ? 'Resume Stage 3'
                                : run.stages[2].status === 'approved'
                                  ? 'Approved'
                                  : statusLabel(run.stages[2].status)
                    }
                    actionType={run.stages[2].status === 'review' ? 'review' : 'start'}
                    onAction={() =>
                      run.stages[2].status === 'review'
                        ? setShowReview(true)
                        : run.stages[2].status === 'error' || run.stages[2].status === 'paused'
                          ? rerunStage('evaluation')
                          : beginStage('evaluation')
                    }
                    onRerun={() => rerunStage('evaluation')}
                    onPause={() => void pauseStage('evaluation')}
                    disabled={['locked', 'running', 'approved'].includes(run.stages[2].status)}
                  />
                </div>
                {Boolean(run.runId) &&
                  (run.stages[1].status === 'approved' ||
                    ['ready', 'running', 'review', 'approved', 'error'].includes(run.stages[2].status)) && (
                  <div className="stage-blueprint-container" style={{ marginTop: '16px' }}>
                    <Stage3BlueprintPanel
                      runId={run.runId}
                      stage2ManifestHash={run.stageManifestHashes?.rules}
                      stageStatus={mapLegacyEvaluationStatusToUnderstanding(run.status, run.activeStage)}
                      stage3ManifestHash={run.stageManifestHashes?.evaluation}
                      onUpdated={() => {
                        if (run.runId) void refreshLiveRun(run.runId);
                        void generatorApi.listBlueprints().then(items => setApprovedBlueprintAvailable(items.length > 0));
                      }}
                    />
                  </div>
                )}
              </div>
            </section>

            <aside className={cx('right-column', rightCollapsed && 'collapsed')}>
              <div className="panel register-panel">
                <div className="panel-header register-head">
                  <div className="panel-title">
                    <span className="panel-icon"><Layers3 size={16} /></span>
                    <div>
                      <h2>Claim register</h2>
                      <p>{verifiedCount} verified · hierarchical parent + children</p>
                    </div>
                  </div>
                  <IconButton title="Collapse right panel" onClick={() => setRightCollapsed(true)}>
                    <PanelRightClose size={15} />
                  </IconButton>
                </div>

                <div className="register-tabs">
                  <button className={rightTab === 'claims' ? 'active' : ''} onClick={() => setRightTab('claims')}>
                    Claims <span>{run.claims.length}</span>
                  </button>
                  <button className={rightTab === 'agents' ? 'active' : ''} onClick={() => setRightTab('agents')}>
                    Agents <span>{run.agents.length}</span>
                  </button>
                </div>

                {rightTab === 'claims' ? (
                  <>
                    <div className="claim-search-row">
                      <label>
                        <Search size={14} />
                        <input
                          value={searchText}
                          onChange={e => setSearchText(e.target.value)}
                          placeholder="Search claims or criteria"
                        />
                      </label>
                      <select
                        value={claimStatusFilter}
                        onChange={e => setClaimStatusFilter(e.target.value)}
                        aria-label="Filter claims"
                      >
                        <option value="all">All</option>
                        <option value="verified">Verified</option>
                        <option value="discrepancy">Discrepancy</option>
                        <option value="failed">Failed</option>
                        <option value="hinted">Hinted</option>
                        <option value="in_progress">Verifying</option>
                      </select>
                    </div>
                    <div className="claim-register-list">
                      {filteredClaims.length ? (
                        filteredClaims.map(claim => (
                          <ClaimRow
                            key={claim.id}
                            claim={claim}
                            active={selectedClaim === claim.id}
                            onClick={() => setSelectedClaim(claim.id)}
                          />
                        ))
                      ) : (
                        <EmptyState icon={<Search size={18} />} title="No claims match" detail="Upload files and run Stage 1." />
                      )}
                    </div>
                    {selectedClaimData && (
                      <ClaimInspector
                        claim={selectedClaimData}
                        sources={run.sources}
                        artifacts={run.artifacts}
                        onEdit={editClaim}
                        onOpenSource={sourceId => {
                          setSelectedSource(sourceId);
                          setShowSourcePanel(true);
                        }}
                        onOpenLocation={secId => {
                          setActiveTab('document');
                          setActiveSection(secId);
                        }}
                        onOpenArtifact={art => void openArtifact(art)}
                        onViewData={c => void openClaimData(c)}
                      />
                    )}
                  </>
                ) : (
                  <AgentView agents={run.agents} />
                )}
              </div>
            </aside>
          </div>

          <footer className="workspace-footer">
            <span><Lock size={11} />Original inputs immutable</span>
            <span><GitCommitHorizontal size={12} />Artifact snapshots versioned</span>
            <span><Activity size={12} />AG-UI {aguiConnection === 'disabled' ? 'demo mode' : aguiConnection}</span>
            <span className="footer-spacer" />
            <span>TRACEWISE <b>0.2.0</b></span>
          </footer>
        </main>
      </div>
      )}

      {rightCollapsed && (
        <button className="expand-right" onClick={() => setRightCollapsed(false)}>
          <PanelRightClose size={15} />Show claims
        </button>
      )}

      {notice && (
        <div className="toast">
          <CheckCircle2 size={16} />
          {notice}
          <button onClick={() => setNotice('')}><X size={14} /></button>
        </div>
      )}

      {showReview && (
        <ReviewModal
          stage={currentStage}
          note={reviewNote}
          setNote={setReviewNote}
          onClose={() => setShowReview(false)}
          onApprove={() => void approveStage(currentStage.id)}
          onRequestChanges={() => void requestChanges(currentStage.id)}
        />
      )}

      {showClaimEditor && selectedClaimData && (
        <ClaimEditor
          claim={selectedClaimData}
          draft={claimDraft}
          setDraft={setClaimDraft}
          onClose={() => setShowClaimEditor(false)}
          onSave={() => void saveClaim()}
        />
      )}

      {showSourcePanel && activeSource && (
        <SourceDrawer
          runId={run.runId}
          source={activeSource}
          claims={run.claims}
          live={apiMode}
          onSelectClaim={id => setSelectedClaim(id)}
          onClose={() => setShowSourcePanel(false)}
        />
      )}

      {showUpload && (
        <UploadModal
          name={newRunName}
          setName={setNewRunName}
          targetFile={targetFile}
          sourceFiles={sourceFiles}
          error={uploadError}
          inputTarget={uploadInput}
          inputSources={sourceInput}
          onAddFiles={addFiles}
          onRemoveSource={i => setSourceFiles(prev => prev.filter((_, idx) => idx !== i))}
          onClose={() => setShowUpload(false)}
          onCreate={() => void createDemoRun()}
          live={apiMode}
          loading={loadingStage}
          runtimeConfig={runtimeConfig}
        />
      )}

      <ArtifactViewerModal
        artifact={openedArtifact}
        loading={artifactLoading}
        onClose={() => setOpenedArtifact(null)}
      />

      {claimDataView && (
        <ClaimDataModal
          claimId={claimDataView.claimId}
          sourceData={claimSourceData}
          data={claimData}
          loading={claimDataLoading}
          error={claimDataError}
          csvUrlFor={sheet =>
            api.claimSourceCsvUrl(
              run.runId,
              claimDataView.claimId,
              sheet.source_file,
              sheet.sheet,
            )}
          onClose={() => {
            setClaimDataView(null);
            setClaimData(null);
            setClaimSourceData(null);
            setClaimDataError(null);
          }}
        />
      )}
    </div>
  );
}

function SectionTree({
  nodes,
  activeId,
  onSelect,
}: {
  nodes: RunSnapshot['sections'];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <>
      {nodes.map(node => (
        <SectionNodeView key={node.id} node={node} activeId={activeId} onSelect={onSelect} />
      ))}
    </>
  );
}

function SectionNodeView({
  node,
  activeId,
  onSelect,
}: {
  node: RunSnapshot['sections'][number];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = !!node.children?.length;
  return (
    <div className="section-node">
      <button
        className={cx('tree-item', activeId === node.id && 'active', node.number === '16.3' && 'target-node')}
        onClick={() => onSelect(node.id)}
        style={{ paddingLeft: `${9 + node.level * 13}px` }}
      >
        {hasChildren ? (
          <span
            className="tree-chevron"
            onClick={e => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>
        ) : (
          <span className="tree-leaf" />
        )}
        <span className="tree-number">{node.number}</span>
        <span className="tree-title">{node.title}</span>
        {node.claims ? <span className="tree-claim-count">{node.claims}</span> : null}
      </button>
      {hasChildren && expanded && (
        <div className="tree-children">
          {node.children!.map(child => (
            <SectionNodeView key={child.id} node={child} activeId={activeId} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub: string }) {
  return (
    <div className="metric">
      <span className="metric-icon">{icon}</span>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{sub}</small>
      </div>
    </div>
  );
}

function StageRail({
  stages,
  active,
  onSelect,
}: {
  stages: RunSnapshot['stages'];
  active: StageId;
  onSelect: (id: StageId) => void;
}) {
  return (
    <div className="stage-rail">
      {stages.map((stage, i) => (
        <div className="stage-wrap" key={stage.id}>
          <button
            className={cx(
              'stage-card',
              active === stage.id && 'active',
              (stage.status === 'locked' || stage.status === 'placeholder') && 'locked',
            )}
            onClick={() => onSelect(stage.id)}
          >
            <div className="stage-card-top">
              <span className="stage-number">{stage.number}</span>
              <StagePill status={stage.status} />
            </div>
            <strong>{stage.title}</strong>
            <small>{stage.subtitle}</small>
            <div className="stage-progress">
              <span style={{ width: `${stage.progress}%` }} />
            </div>
            <div className="stage-card-meta">
              <span><FileText size={12} />{stage.artifacts} artifacts</span>
              <b>{stage.status === 'placeholder' ? 'Placeholder' : `${stage.progress}%`}</b>
            </div>
          </button>
          {i < stages.length - 1 && (
            <div className={cx('stage-connector', stage.status === 'approved' && 'complete')}>
              <ArrowRight size={14} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ActivityView({
  items,
  onSource,
  onArtifact,
  showAll,
  setShowAll,
}: {
  items: ActivityItem[];
  onSource: (id: string) => void;
  onArtifact: () => void;
  showAll: boolean;
  setShowAll: (v: boolean) => void;
}) {
  const iconFor = (kind: ActivityItem['kind']) =>
    kind === 'agent' ? (
      <Bot size={14} />
    ) : kind === 'artifact' ? (
      <FileCheck2 size={14} />
    ) : kind === 'gate' ? (
      <ShieldCheck size={14} />
    ) : kind === 'success' ? (
      <Check size={14} />
    ) : kind === 'warning' ? (
      <AlertTriangle size={14} />
    ) : kind === 'tool' ? (
      <Terminal size={14} />
    ) : (
      <Zap size={14} />
    );

  return (
    <div className="activity-view">
      <div className="activity-summary">
        <div className="activity-summary-title">
          <span className="pulse-dot" />
          {showAll ? 'All run events' : 'Latest events'}
          <span className="activity-total">{items.length} events shown</span>
        </div>
        <div className="activity-actions">
          <span className="filter-chip"><Filter size={12} />All activity</span>
          <button className="plain-link" onClick={() => setShowAll(!showAll)}>
            {showAll ? 'Show latest' : 'View all'}
            <ArrowRight size={12} />
          </button>
        </div>
      </div>
      <div className="timeline">
        {items.map(item => (
          <div className="timeline-item" key={item.id}>
            <div className={`timeline-icon ${item.kind}`}>{iconFor(item.kind)}</div>
            <div className="timeline-body">
              <div className="timeline-title-row">
                <strong>{item.title}</strong>
                <time>{item.time}</time>
              </div>
              <p>{item.detail}</p>
              <div className="timeline-meta">
                {item.agent && <span className="agent-tag"><Bot size={11} />{item.agent}</span>}
                {item.source && (
                  <button className="source-tag" onClick={() => onSource(item.source!)}>
                    <FileSpreadsheet size={11} />{item.source}
                  </button>
                )}
                {item.artifact && (
                  <button className="artifact-tag" onClick={onArtifact}>
                    <FileCode2 size={11} />{item.artifact}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="trace-footnote">
        <ShieldCheck size={13} />
        <span>Activity trace streams harness file exploration, Strands tool calls, and Stage 2 verification outcomes.</span>
      </div>
    </div>
  );
}

function DocumentView({
  run,
  activeSection,
  onSection,
  onClaim,
  live,
}: {
  run: RunSnapshot;
  activeSection: string;
  onSection: (id: string) => void;
  onClaim: (id: string) => void;
  live: boolean;
}) {
  if (live) {
    return (
      <div className="document-view">
        <div className="document-toolbar">
          <div>
            <span className="doc-icon"><BookOpen size={14} /></span>
            <strong>{run.targetDocument}</strong>
            <span className="doc-page">SECTION 16.3 FULL CONTEXT</span>
          </div>
        </div>
        <div className="document-canvas">
          <div className="document-page">
            {run.documentBlocks?.length ? (
              run.documentBlocks.map(block =>
                block.type === 'table' ? (
                  <table className="doc-live-table" key={block.block_id}>
                    <tbody>
                      {[block.headers || [], ...(block.rows || [])].map((row, rowIndex) => (
                        <tr key={`${block.block_id}-${rowIndex}`}>
                          {row.map((cell, cellIndex) => (
                            <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p key={block.block_id}>{block.text}</p>
                ),
              )
            ) : (
              <p>Start Stage 1 to extract Section 16.3 subsections and complete tables from your uploaded DOCX.</p>
            )}
          </div>
        </div>
        <div className="document-footer">
          <span><Lock size={11} />Read-only extracted input</span>
          <span>{run.documentBlocks?.length || 0} blocks</span>
          <span className="footer-spacer" />
          <button onClick={() => onSection(run.sections[0]?.id || '')}>Sections: {run.sections.length}</button>
        </div>
      </div>
    );
  }

  const claim = run.claims.find(c => c.sectionId === activeSection) || run.claims[0];
  return (
    <div className="document-view">
      <div className="document-toolbar">
        <div>
          <span className="doc-icon"><BookOpen size={14} /></span>
          <strong>{run.targetDocument}</strong>
          <span className="doc-page">SECTION 16.3 PREVIEW</span>
        </div>
      </div>
      <div className="document-canvas">
        <div className="document-page">
          <div className="doc-running-head">PERIODIC BENEFIT-RISK EVALUATION REPORT <span>DEMO PREVIEW</span></div>
          <div className="doc-rule" />
          <div className="doc-section-number">{claim?.sectionNumber || '16.3.1.1'}</div>
          <h3>{claim?.sectionTitle || 'Hepatic events'}</h3>
          <div className="doc-highlight">
            <span className="highlight-label">PARENT CLAIM · {claim?.id || 'CLM-0001'}</span>
            <p>{claim?.statement}</p>
            <button onClick={() => claim && onClaim(claim.id)}>
              Inspect claim <ArrowUpRight size={12} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ArtifactView({
  artifacts,
  onOpen,
  onOpenMasterSummary,
}: {
  artifacts: ArtifactItem[];
  onOpen: (artifact: ArtifactItem) => void;
  onOpenMasterSummary: () => void;
}) {
  const groups: StageId[] = ['claims', 'rules', 'evaluation'];
  const hasMaster = artifacts.some(a => a.name.endsWith('master_source_summary.md'));
  return (
    <div className="artifact-view">
      {hasMaster && (
        <div className="master-summary-banner">
          <div>
            <strong>Master Summary of Source Documents</strong>
            <small>Combined Markdown report synthesized after exploring every uploaded source file.</small>
          </div>
          <button className="button-secondary" onClick={onOpenMasterSummary}>
            <FileText size={14} /> View master_source_summary.md
          </button>
        </div>
      )}
      {groups.map(stage => {
        const list = artifacts.filter(a => a.stage === stage);
        return (
          <div className="artifact-group" key={stage}>
            <div className="artifact-group-head">
              <span className={`stage-mini ${stage}`}>{stage === 'claims' ? '01' : stage === 'rules' ? '02' : '03'}</span>
              <strong>{stageLabel[stage]}</strong>
              <span>{stage === 'evaluation' ? 'Placeholder' : `${list.length} artifacts`}</span>
            </div>
            {list.length ? (
              list.map(a => (
                <button className="artifact-row" key={a.id} onClick={() => onOpen(a)}>
                  <span className="artifact-file-icon">
                    {a.name.endsWith('.py') ? (
                      <Code2 size={16} />
                    ) : a.name.endsWith('.json') ? (
                      <FileJson size={16} />
                    ) : (
                      <FileText size={16} />
                    )}
                  </span>
                  <span className="artifact-row-copy">
                    <strong>{a.name}</strong>
                    <small>{a.type} · {a.size} · {a.version}</small>
                  </span>
                  <span className={`artifact-status ${a.status}`}>{statusLabel(a.status)}</span>
                  <ArrowUpRight size={14} />
                </button>
              ))
            ) : (
              <div className="artifact-empty">
                <Lock size={13} />
                {stage === 'evaluation'
                  ? 'Stage 3 is left as a placeholder'
                  : 'No artifacts yet · start stage to generate'}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StageControl({
  stage,
  icon,
  actionLabel,
  actionType,
  onAction,
  onRerun,
  onPause,
  disabled,
}: {
  stage: RunSnapshot['stages'][number];
  icon: React.ReactNode;
  actionLabel: string;
  actionType: 'start' | 'review';
  onAction: () => void;
  onRerun?: () => void;
  onPause?: () => void;
  disabled: boolean;
}) {
  // Offer a dedicated rerun when the stage awaits review (rerun instead of approving).
  // For an errored/paused stage the primary action already reruns/resumes it.
  const showSecondaryRerun = Boolean(onRerun) && stage.status === 'review';
  const showPause = Boolean(onPause) && stage.status === 'running';
  const isResumeLike = stage.status === 'error' || stage.status === 'paused';
  return (
    <div className="stage-control-row">
      <div className={`stage-control-icon ${stage.id}`}>{icon}</div>
      <div className="stage-control-copy">
        <strong>{stage.number} / {stage.title}</strong>
        <span>{stage.subtitle}</span>
      </div>
      <StagePill status={stage.status} />
      <div className="control-progress">
        <span style={{ width: `${stage.progress}%` }} />
      </div>
      {showPause && (
        <button className="stage-action pause" onClick={onPause} title="Pause this run after the current claim">
          <PauseCircle size={13} />
          Pause
        </button>
      )}
      {showSecondaryRerun && (
        <button className="stage-action rerun" onClick={onRerun} title="Re-run this stage without restarting Stage 1">
          <RotateCcw size={13} />
          Rerun
        </button>
      )}
      <button
        className={cx('stage-action', actionType, isResumeLike && 'rerun', disabled && 'disabled')}
        disabled={disabled}
        onClick={onAction}
      >
        {actionType === 'review' ? (
          <ShieldCheck size={13} />
        ) : stage.status === 'running' ? (
          <CircleDashed size={13} />
        ) : isResumeLike ? (
          <RotateCcw size={13} />
        ) : (
          <Play size={13} />
        )}
        {actionLabel}
      </button>
    </div>
  );
}

function ClaimRow({ claim, active, onClick }: { claim: Claim; active: boolean; onClick: () => void }) {
  const isVerified = claim.status === 'verified' || claim.verificationResult?.verified === true;
  const childCount = claim.childrenClaims?.length || 0;
  return (
    <button className={cx('claim-row', active && 'active', isVerified && 'verified-row')} onClick={onClick}>
      <div className="claim-row-top">
        <span className="claim-id">{claim.id}</span>
        <span className="claim-section">
          {claim.sectionNumber}
          {childCount > 0 ? ` · ${childCount} child` : ''}
        </span>
      </div>
      <strong>{claim.statement}</strong>
      <div className="claim-row-bottom">
        <span className="claim-value">
          {claim.reportedValue} <small>{claim.unit}</small>
        </span>
        <span className={`claim-state ${claim.status}`}>
          {isVerified && <Check size={10} />}
          {statusLabel(claim.status)}
        </span>
        <ChevronRight size={13} />
      </div>
    </button>
  );
}

function AgentView({ agents }: { agents: RunSnapshot['agents'] }) {
  return (
    <div className="agent-view">
      {agents.length ? (
        agents.map(agent => (
          <div className="agent-row" key={agent.id}>
            <Avatar
              initials={agent.name.split(' ').map(p => p[0]).slice(0, 2).join('')}
              tone={agent.stage === 'claims' ? 'violet' : 'blue'}
            />
            <div className="agent-row-copy">
              <div>
                <strong>{agent.name}</strong>
                <StagePill status={agent.status} />
              </div>
              <small>{agent.role}</small>
              <p>{agent.currentTask}</p>
              <div className="agent-meta">
                <span><Clock3 size={11} />{agent.elapsed}</span>
                <span><Network size={11} />{agent.children} workers</span>
              </div>
            </div>
          </div>
        ))
      ) : (
        <EmptyState icon={<Bot size={18} />} title="No agents active yet" detail="Start Stage 1 or Stage 2 to stream harness execution." />
      )}
    </div>
  );
}

function EmptyState({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return (
    <div className="empty-state">
      <span>{icon}</span>
      <strong>{title}</strong>
      <small>{detail}</small>
    </div>
  );
}

export default App;
