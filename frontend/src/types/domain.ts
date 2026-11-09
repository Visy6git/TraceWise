export type StageId = 'claims' | 'rules' | 'evaluation';
export type StageStatus = 'locked' | 'ready' | 'running' | 'review' | 'approved' | 'changes_requested' | 'complete' | 'error';
export type ClaimStatus = 'draft' | 'hinted' | 'in_progress' | 'artifact_ready' | 'pass' | 'discrepancy' | 'needs_review' | 'unresolved';
export type EvaluationStatus = 'PASS' | 'DISCREPANCY' | 'FAIL' | 'INCONCLUSIVE' | 'NEEDS_HUMAN_REVIEW' | 'UNRESOLVED';
export type ConfidenceSource = 'observed' | 'inferred' | 'unknown';

export interface SourceFile {
  id: string;
  name: string;
  kind: 'xlsx' | 'csv' | 'pdf' | 'docx' | 'xls' | 'other';
  sizeLabel: string;
  rows?: number;
  sheets?: number;
  status: 'indexed' | 'indexing' | 'warning' | 'pending';
  hash?: string;
  usedBy: number;
  sourceNote?: string;
}

export interface SectionNode {
  id: string;
  number: string;
  title: string;
  level: number;
  children?: SectionNode[];
  selected?: boolean;
  claims?: number;
}

export interface EvidenceHint {
  text: string;
  observed: string[];
  inferred: string[];
  unknowns: string[];
}

export interface Claim {
  id: string;
  sectionId: string;
  sectionNumber: string;
  sectionTitle: string;
  statement: string;
  reportedValue: string;
  unit: string;
  entity: string;
  status: ClaimStatus;
  hint: EvidenceHint;
  sourceIds: string[];
  result?: string;
  evaluator?: EvaluationStatus;
  artifacts: string[];
  derivedFrom?: string[];
  period?: string;
  locator: string;
  version?: number;
}

export interface DocumentBlock {
  block_id: string;
  type: string;
  section_id?: string;
  section_number?: string;
  text?: string;
  headers?: string[];
  rows?: string[][];
}

export interface AgentInfo {
  id: string;
  name: string;
  role: string;
  stage: StageId;
  status: 'active' | 'idle' | 'done' | 'error';
  currentTask: string;
  elapsed: string;
  children: number;
}

export interface ActivityItem {
  id: string;
  stage: StageId;
  time: string;
  title: string;
  detail: string;
  kind: 'tool' | 'agent' | 'artifact' | 'gate' | 'system' | 'success' | 'warning';
  agent?: string;
  source?: string;
  artifact?: string;
  status?: 'running' | 'done' | 'warning' | 'error';
}

export interface ArtifactItem {
  id: string;
  name: string;
  type: string;
  stage: StageId;
  size: string;
  version: string;
  status: 'ready' | 'building' | 'review' | 'locked';
  claimId?: string;
  updated: string;
}

export interface StageInfo {
  id: StageId;
  number: string;
  title: string;
  subtitle: string;
  status: StageStatus;
  progress: number;
  agents: number;
  subagents: number;
  artifacts: number;
}

export interface RunSnapshot {
  runId: string;
  name: string;
  product: string;
  period: string;
  status: string;
  createdAt: string;
  targetDocument: string;
  sources: SourceFile[];
  sections: SectionNode[];
  claims: Claim[];
  stages: StageInfo[];
  agents: AgentInfo[];
  activity: ActivityItem[];
  artifacts: ArtifactItem[];
  activeStage: StageId;
  reviewNote?: string;
  inputManifestHash?: string;
  stageManifestHashes?: Partial<Record<StageId, string>>;
  documentBlocks?: DocumentBlock[];
}
