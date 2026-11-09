import type { DocumentBlock, StageId } from '../types/domain';

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
  input_manifest_hash: string;
  stage_1_manifest_hash?: string | null;
  stage_2_manifest_hash?: string | null;
  stage_3_manifest_hash?: string | null;
}

/** API client used when live mode is selected. */
export const api = {
  createRun: (body: FormData) => request<RunSummary>('/api/runs/upload', { method: 'POST', body }),
  getRun: (runId: string) => request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`),
  listClaims: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/stage-1/claims`),
  getSections: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/sections`),
  listSources: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/sources`),
  getDocument: (runId: string) => request<{ blocks: DocumentBlock[] }>(`/api/runs/${encodeURIComponent(runId)}/document`),
  listArtifacts: (runId: string) => request<Record<string, unknown>[]>(`/api/runs/${encodeURIComponent(runId)}/artifacts`),
  startStage: (runId: string, stage: StageId, expectedInputManifestHash: string, idempotencyKey: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/start`, {
      method: 'POST', body: JSON.stringify({ expected_input_manifest_hash: expectedInputManifestHash, idempotency_key: idempotencyKey }),
    }),
  reviewStage: (runId: string, stage: StageId, decision: 'approve' | 'request_changes', expectedManifestHash: string, reviewerNote?: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/review`, {
      method: 'POST', body: JSON.stringify({ decision, expected_manifest_hash: expectedManifestHash, reviewer_note: reviewerNote }),
    }),
  updateClaim: (runId: string, claimId: string, body: Record<string, unknown>) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stage-1/claims/${encodeURIComponent(claimId)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
};

export const apiMode = import.meta.env.VITE_API_MODE === 'api';
