import type { Claim, RunSnapshot, StageId } from '../types/domain';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || payload));
  }
  return response.json() as Promise<T>;
}

/** API client contract. Demo UI uses local fixture state until VITE_API_MODE=api. */
export const api = {
  getRun: (runId: string) => request<RunSnapshot>(`/api/runs/${encodeURIComponent(runId)}`),
  listClaims: (runId: string) => request<Claim[]>(`/api/runs/${encodeURIComponent(runId)}/stage-1/claims`),
  startStage: (runId: string, stage: StageId, expectedInputManifestHash: string, idempotencyKey: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/start`, {
      method: 'POST', body: JSON.stringify({ expected_input_manifest_hash: expectedInputManifestHash, idempotency_key: idempotencyKey }),
    }),
  reviewStage: (runId: string, stage: StageId, decision: 'approve' | 'request_changes', expectedManifestHash: string, reviewerNote?: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/${stage}/review`, {
      method: 'POST', body: JSON.stringify({ decision, expected_manifest_hash: expectedManifestHash, reviewer_note: reviewerNote }),
    }),
};

export const apiMode = import.meta.env.VITE_API_MODE === 'api';
