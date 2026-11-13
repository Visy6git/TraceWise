import type { BlueprintSummary, GenerationSummary } from '../types/blueprint';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = typeof FormData !== 'undefined' && init?.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(!isForm ? { 'Content-Type': 'application/json' } : {}), ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail || body));
  }
  return response.json() as Promise<T>;
}

export const generatorApi = {
  listBlueprints: () => request<BlueprintSummary[]>('/api/blueprints'),
  getBlueprint: (id: string, version?: number) =>
    request<BlueprintSummary>(`/api/blueprints/${encodeURIComponent(id)}${version ? `?version=${version}` : ''}`),
  getLearningBlueprint: (runId: string) =>
    request<BlueprintSummary>(`/api/runs/${encodeURIComponent(runId)}/stage-3/blueprint`),
  startUnderstanding: (runId: string, stage2Hash: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/understanding/start`, {
      method: 'POST',
      body: JSON.stringify({ expected_input_manifest_hash: stage2Hash, idempotency_key: crypto.randomUUID() }),
    }),
  rerunUnderstanding: (runId: string, stage2Hash: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/understanding/rerun`, {
      method: 'POST',
      body: JSON.stringify({ expected_input_manifest_hash: stage2Hash, idempotency_key: crypto.randomUUID() }),
    }),
  reviewUnderstanding: (runId: string, decision: 'approve' | 'request_changes', manifestHash: string, reviewerNote?: string) =>
    request(`/api/runs/${encodeURIComponent(runId)}/stages/understanding/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, expected_manifest_hash: manifestHash, reviewer_note: reviewerNote }),
    }),
  createGeneration: (form: FormData) => request<GenerationSummary>('/api/generations', { method: 'POST', body: form }),
  listGenerations: (blueprintId?: string) =>
    request<GenerationSummary[]>(`/api/generations${blueprintId ? `?blueprint_id=${encodeURIComponent(blueprintId)}` : ''}`),
  getGeneration: (id: string) => request<GenerationSummary>(`/api/generations/${encodeURIComponent(id)}`),
  startGeneration: (id: string) =>
    request(`/api/generations/${encodeURIComponent(id)}/start`, { method: 'POST' }),
  reviewGeneration: (id: string, decision: 'approve' | 'request_changes', outputHash: string, note?: string) =>
    request(`/api/generations/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, expected_output_manifest_hash: outputHash, reviewer_note: note }),
    }),
  getGenerationArtifacts: (id: string) =>
    request<GenerationSummary['artifacts_json']>(`/api/generations/${encodeURIComponent(id)}/artifacts`),
};
