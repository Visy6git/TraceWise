import React, { useEffect, useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, FileJson, LoaderCircle, Play, ShieldCheck } from 'lucide-react';
import { generatorApi } from '../lib/generatorApi';
import type { BlueprintSummary } from '../types/blueprint';

export function Stage3BlueprintPanel({ runId, stage2ManifestHash, stageStatus, stage3ManifestHash, onUpdated }: {
  runId: string;
  stage2ManifestHash?: string;
  stageStatus: string;
  stage3ManifestHash?: string;
  onUpdated?: () => void;
}) {
  const [candidate, setCandidate] = useState<(BlueprintSummary & { blueprint?: Record<string, any> | null }) | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [reviewerNote, setReviewerNote] = useState('');

  async function refresh() {
    if (!runId) return;
    try { setCandidate(await generatorApi.getLearningBlueprint(runId) as BlueprintSummary & { blueprint?: Record<string, any> | null }); }
    catch { setCandidate(null); }
  }
  useEffect(() => { void refresh(); }, [runId, stageStatus]);

  async function start() {
    if (!stage2ManifestHash) return;
    setBusy(true); setError('');
    try { await generatorApi.startUnderstanding(runId, stage2ManifestHash); setNote('Understanding agent started. Inspect the AG-UI activity stream for tool, artifact and subagent events.'); onUpdated?.(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function review(decision: 'approve' | 'request_changes') {
    const hash = stage3ManifestHash || candidate?.manifest_hash;
    if (!hash) return;
    setBusy(true); setError('');
    try { await generatorApi.reviewUnderstanding(runId, decision, hash, reviewerNote || undefined); setNote(decision === 'approve' ? 'Blueprint version approved and unlocked in the Section Generator tab.' : 'Changes requested. The approved Stage 1/2 artifacts remain frozen.'); onUpdated?.(); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const blueprint = candidate?.blueprint || {};
  const validation = (blueprint.validation || {}) as Record<string, any>;
  const questions = [...(blueprint.open_questions || []), ...(validation.unresolved_items || [])];
  return <section className="tw-card tw-stage3-panel">
    <header><div><span className="tw-eyebrow">STAGE 03</span><h2>Build Section 16.3 understanding</h2><p>Learn the reusable method from frozen Claims and Rules artifacts.</p></div><ShieldCheck size={20}/></header>
    {stageStatus === 'ready' && <button className="tw-primary" disabled={busy || !stage2ManifestHash} onClick={() => void start()}><Play size={15}/> Start understanding agent</button>}
    {['running','EVALUATION_RUNNING'].includes(stageStatus) && <div className="tw-stage-state"><LoaderCircle className="tw-spin" size={16}/> Agent is mapping report structure, calculations, dependencies and future-year source contracts.</div>}
    {stageStatus === 'error' && <div className="tw-stage-state"><AlertTriangle size={16}/> Stage 3 failed or requires attention. <button className="tw-primary" disabled={busy || !stage2ManifestHash} onClick={() => void start()}><Play size={14}/> Retry understanding</button></div>}
    {stageStatus === 'approved' && <div className="tw-stage-state"><CheckCircle2 size={16}/> Blueprint approved and immutable. Section Generator workspace is unlocked.</div>}
    {candidate && <>
      <div className="tw-stage-blueprint-meta"><FileJson size={17}/><div><strong>{candidate.blueprint_id} · v{candidate.version}</strong><small>Manifest {candidate.manifest_hash.slice(0,20)}…</small></div><span>{candidate.version_status || candidate.status}</span></div>
      <div className="tw-stage-kpis"><div><strong>{blueprint.claims?.length ?? '—'}</strong><small>Claims mapped</small></div><div><strong>{blueprint.datasets?.length ?? '—'}</strong><small>Logical datasets</small></div><div><strong>{blueprint.section_structure?.length ?? '—'}</strong><small>Section blocks</small></div></div>
      {!!questions.length && <div className="tw-stage-questions"><strong><AlertTriangle size={14}/> Open methodology questions ({questions.length})</strong>{questions.slice(0,12).map((q:string,i)=><p key={i}>{q}</p>)}</div>}
      <div className="tw-stage-validation"><strong>Blueprint validation</strong><span>{validation.status || 'not recorded'}</span><small>Reproduction tested: {validation.reproduction_tested ? 'Yes' : 'No'} · Executable: {validation.executable_present ? 'Yes' : 'No'}</small></div>
    </>}
    {stageStatus === 'review' && <div className="tw-stage-review"><label>Reviewer note</label><textarea value={reviewerNote} onChange={e=>setReviewerNote(e.target.value)} placeholder="Record methodology decisions, unresolved mappings or required changes"/><div><button disabled={busy} onClick={()=>void review('request_changes')}>Request changes</button><button disabled={busy || !candidate} onClick={()=>void review('approve')}><CheckCircle2 size={14}/> Approve blueprint</button></div></div>}
    {note && <p className="tw-stage-note"><CheckCircle2 size={14}/>{note}</p>}{error && <p className="tw-stage-error">{error}</p>}
  </section>;
}
