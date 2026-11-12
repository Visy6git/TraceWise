import type { ClaimData, ClaimSourceData, DocumentBlock, RuntimeConfig, StageId } from '../types/domain';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || payload));
  }
  return response.json() as Promise<T>;
}

export interface RunSummary {
  run_id: string;
  run_name: string;
  status: string;
  active_stage?: StageId | null;
  created_at: string;
  target_document_filename?: string | null;
  product_name?: string | null;
  reporting_period_start?: string | null;
  reporting_period_end?: string | null;
  input_manifest_hash: string;
  stage_1_manifest_hash?: string | null;
  stage_2_manifest_hash?: string | null;
  stage_3_manifest_hash?: string | null;
}

export interface ArtifactContentResponse {
  artifact_id: string;
  run_id: string;
  stage: string;
  claim_id?: string | null;
  logical_path: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  content: string;
}

/** API client communicating with the FastAPI backend. */
export const api = {
  getConfig: () => request<RuntimeConfig>('/api/config'),
  createRun: (body: FormData) => request<RunSummary>('/api/runs/upload', { method: 'POST', body }),
  listRuns: () => request<RunSummary[]>('/api/runs'),
  getRun: (runId: string) => request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`),
  listClaims: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/stage-1/claims`),
  getClaimData: (runId: string, claimId: string) =>
    request<ClaimData>(`/api/runs/${encodeURIComponent(runId)}/claims/${encodeURIComponent(claimId)}/data`),
  getClaimSourceData: (runId: string, claimId: string, limit = 500, offset = 0) =>
    request<ClaimSourceData>(
      `/api/runs/${encodeURIComponent(runId)}/claims/${encodeURIComponent(claimId)}/source-data?limit=${limit}&offset=${offset}`,
    ),
  claimSourceCsvUrl: (runId: string, claimId: string, file: string, sheet?: string | null) =>
    `${API_BASE}/api/runs/${encodeURIComponent(runId)}/claims/${encodeURIComponent(claimId)}/source-data.csv` +
    `?file=${encodeURIComponent(file)}${sheet ? `&sheet=${encodeURIComponent(sheet)}` : ''}`,
  getSections: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/sections`),
  listSources: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/sources`),
  getSourceKnowledge: (runId: string) => request<Record<string, unknown>>(`/api/runs/${encodeURIComponent(runId)}/stage-1/source-knowledge`),
  getMasterSummary: (runId: string) =>
    request<{ run_id: string; logical_path: string; content: string }>(`/api/runs/${encodeURIComponent(runId)}/stage-1/master-summary`),
  getSourceSummary: (runId: string, sourceId: string) =>
    request<{ run_id: string; source_id: string; filename: string; logical_path: string; content: string }>(
      `/api/runs/${encodeURIComponent(runId)}/stage-1/sources/${encodeURIComponent(sourceId)}/summary`,
    ),
  getDocument: (runId: string) => request<{ blocks: DocumentBlock[] }>(`/api/runs/${encodeURIComponent(runId)}/document`),
  listArtifacts: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/artifacts`),
  getArtifactContent: (runId: string, artifactId: string) =>
    request<ArtifactContentResponse>(`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}/content`),
  getEvaluationStatus: (runId: string) =>
    request<{ run_id: string; status: string; is_placeholder: boolean; message: string }>(
      `/api/runs/${encodeURIComponent(runId)}/stage-3/evaluation`,
    ),
  startStage: (runId: string, stage: StageId, expectedInputManifestHash: string, idempotencyKey: string) =>
    request<{ run_id: string; stage: StageId; status: string; accepted: boolean; message: string }>(
      `/api/runs/${encodeURIComponent(runId)}/stages/${stage}/start`,
      {
        method: 'POST',
        body: JSON.stringify({ expected_input_manifest_hash: expectedInputManifestHash, idempotency_key: idempotencyKey }),
      },
    ),
  pauseStage: (runId: string, stage: StageId) =>
    request<{ run_id: string; stage: StageId; status: string; accepted: boolean; message: string }>(
      `/api/runs/${encodeURIComponent(runId)}/stages/${stage}/pause`,
      { method: 'POST' },
    ),
  rerunStage: (runId: string, stage: StageId, expectedInputManifestHash: string, idempotencyKey: string) =>
    request<{ run_id: string; stage: StageId; status: string; accepted: boolean; message: string }>(
      `/api/runs/${encodeURIComponent(runId)}/stages/${stage}/rerun`,
      {
        method: 'POST',
        body: JSON.stringify({ expected_input_manifest_hash: expectedInputManifestHash, idempotency_key: idempotencyKey }),
      },
    ),
  reviewStage: (runId: string, stage: StageId, decision: 'approve' | 'request_changes', expectedManifestHash: string, reviewerNote?: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, expected_manifest_hash: expectedManifestHash, reviewer_note: reviewerNote }),
    }),
  updateClaim: (runId: string, claimId: string, body: Record<string, unknown>) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stage-1/claims/${encodeURIComponent(claimId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
};

export const apiMode = import.meta.env.VITE_API_MODE === 'api';
