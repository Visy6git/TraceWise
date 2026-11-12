export type StageId = 'claims' | 'rules' | 'evaluation';
export type StageStatus =
  | 'locked'
  | 'ready'
  | 'running'
  | 'review'
  | 'approved'
  | 'changes_requested'
  | 'complete'
  | 'error'
  | 'paused'
  | 'placeholder';
export type ClaimStatus =
  | 'draft'
  | 'hinted'
  | 'in_progress'
  | 'verified'
  | 'artifact_ready'
  | 'pass'
  | 'discrepancy'
  | 'failed'
  | 'needs_review'
  | 'unresolved';
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

export interface ChildClaim {
  child_claim_id: string;
  raw_statement: string;
  normalized_statement: string;
  claim_type: string;
  entity_unit: string;
  reported_value: string | number;
  unit?: string | null;
  numerator?: string | null;
  denominator?: string | null;
  relationship: string;
  search_criteria?: string | null;
  verified?: boolean | null;
  computed_value?: string | number | null;
  verification_notes?: string | null;
}

export interface VerificationResult {
  verified: boolean;
  status: string;
  parent_computed_value?: string | number | null;
  parent_reported_value?: string | number | null;
  children_results?: Array<Record<string, unknown>>;
  discrepancy_summary?: string | null;
  script_path?: string | null;
  result_artifact_id?: string | null;
  data_available?: boolean | null;
  data_artifact_id?: string | null;
  verified_at?: string | null;
}

export interface ClaimDataTable {
  child_claim_id?: string;
  label: string;
  source_file?: string | null;
  sheet?: string | null;
  row_count: number;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  truncated: boolean;
}

export interface ClaimData {
  run_id: string;
  claim_id: string;
  parent: ClaimDataTable | null;
  children: ClaimDataTable[];
}

export interface ClaimSheet {
  source_file: string;
  sheet?: string | null;
  header_row_index: number;
  row_count: number;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  offset?: number;
  truncated: boolean;
  error?: string;
}

export interface ClaimSourceData {
  run_id: string;
  claim_id: string;
  sheets: ClaimSheet[];
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
  numerator?: string;
  denominator?: string;
  status: ClaimStatus;
  hint: EvidenceHint;
  childrenClaims: ChildClaim[];
  searchCriteria?: string;
  sourceDocumentMapped?: string[];
  verificationResult?: VerificationResult | null;
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
  placeholder?: boolean;
}

export interface RuntimeConfig {
  mode: string;
  llm_provider: string;
  model_id: string;
  stage_3_placeholder: boolean;
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
