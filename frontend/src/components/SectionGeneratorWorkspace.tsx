import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, CloudUpload, Download, FileSpreadsheet, FileText, GitCompareArrows, LoaderCircle, Play, RefreshCw, ShieldCheck, Workflow } from 'lucide-react';
import { generatorApi } from '../lib/generatorApi';
import { useAguiEvents } from '../lib/agui';
import type { AGUIEvent } from '../types/agui';
import type { BlueprintSummary, GenerationSummary } from '../types/blueprint';
import '../styles/generator.css';

function Status({ value }: { value: string }) {
  const good = ['approved', 'complete', 'compatible', 'output_review'].includes(value);
  const bad = ['failed', 'blocked', 'compatibility_review'].includes(value);
  return <span className={`tw-status ${good ? 'good' : bad ? 'warn' : ''}`}>{value.replaceAll('_', ' ')}</span>;
}

export function SectionGeneratorWorkspace() {
  const [blueprints, setBlueprints] = useState<BlueprintSummary[]>([]);
  const [selectedBlueprint, setSelectedBlueprint] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [runName, setRunName] = useState('PBRER annual generation');
  const [periodStart, setPeriodStart] = useState('2025-01-01');
  const [periodEnd, setPeriodEnd] = useState('2025-12-31');
  const [asOfDate, setAsOfDate] = useState('');
  const [generations, setGenerations] = useState<GenerationSummary[]>([]);
  const [active, setActive] = useState<GenerationSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [liveEvents, setLiveEvents] = useState<AGUIEvent[]>([]);
  const connection = useAguiEvents(active?.generation_id || '', Boolean(active?.generation_id), event => {
    setLiveEvents(current => [...current.slice(-39), event]);
  });

  const blueprint = useMemo(() => blueprints.find(x => x.blueprint_id === selectedBlueprint) || blueprints[0], [blueprints, selectedBlueprint]);

  async function refresh() {
    setError('');
    try {
      const [bps, gens] = await Promise.all([generatorApi.listBlueprints(), generatorApi.listGenerations()]);
      setBlueprints(bps);
      setGenerations(gens);
      setSelectedBlueprint(current => current || bps[0]?.blueprint_id || '');
      if (active) {
        const fresh = await generatorApi.getGeneration(active.generation_id);
        setActive(fresh);
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  useEffect(() => {
    let mounted = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight || !mounted) return;
      inFlight = true;
      try {
        const [bps, gens] = await Promise.all([generatorApi.listBlueprints(), generatorApi.listGenerations()]);
        if (!mounted) return;
        setBlueprints(bps);
        setGenerations(gens);
        setSelectedBlueprint(current => current || bps[0]?.blueprint_id || '');
        if (active?.generation_id) {
          const fresh = await generatorApi.getGeneration(active.generation_id);
          if (mounted) setActive(fresh);
        }
      } catch (e) {
        if (mounted) setError(e instanceof Error ? e.message : String(e));
      } finally {
        inFlight = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 4000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, [active?.generation_id]);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const next = Array.from(list).filter(f => /\.(xlsx|csv)$/i.test(f.name));
    setFiles(current => [...current, ...next.filter(f => !current.some(x => x.name.toLowerCase() === f.name.toLowerCase()))]);
  }

  async function create() {
    if (!blueprint || !files.length) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const form = new FormData();
      form.set('blueprint_id', blueprint.blueprint_id);
      form.set('blueprint_version', String(blueprint.version));
      form.set('run_name', runName);
      form.set('reporting_period_start', periodStart);
      form.set('reporting_period_end', periodEnd);
      if (asOfDate) form.set('as_of_date', asOfDate);
      files.forEach(file => form.append('source_files', file));
      const created = await generatorApi.createGeneration(form);
      setActive(created);
      setNotice(`Generation run ${created.generation_id.slice(0, 8)} created. Source files are stored in an independent run boundary.`);
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function reviewOutput(decision: 'approve' | 'request_changes') {
    if (!active?.output_manifest_hash) return;
    setBusy(true); setError('');
    try {
      const updated = await generatorApi.reviewGeneration(active.generation_id, decision, active.output_manifest_hash,
        decision === 'approve' ? 'Section 16.3 output reviewed and approved.' : 'Please correct the generated section.');
      setActive(updated as GenerationSummary);
      setNotice(decision === 'approve' ? 'Generated Section 16.3 approved.' : 'Output marked for correction.');
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  async function start(id: string) {
    setBusy(true); setError('');
    try {
      await generatorApi.startGeneration(id);
      setActive(await generatorApi.getGeneration(id));
      setNotice('Generation started. Compatibility checks run before any report calculation.');
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <main className="tw-generator">
      <header className="tw-generator-head">
        <div><div className="tw-eyebrow">APPROVED METHODOLOGY</div><h1>Generate Section 16.3</h1><p>Bring new source extracts. The approved blueprint supplies the retrieval, calculation and presentation rules.</p></div>
        <button className="tw-icon-action" onClick={() => void refresh()} title="Refresh"><RefreshCw size={16}/></button>
      </header>
      {notice && <div className="tw-notice"><CheckCircle2 size={16}/>{notice}</div>}
      {error && <div className="tw-error"><AlertTriangle size={16}/>{error}</div>}
      <div className="tw-generator-grid">
        <section className="tw-card">
          <div className="tw-card-title"><ShieldCheck size={17}/><h2>Methodology</h2></div>
          {blueprints.length ? <>
            <label className="tw-label" htmlFor="tw-blueprint">Approved blueprint</label>
            <select id="tw-blueprint" value={blueprint?.blueprint_id || ''} onChange={e => setSelectedBlueprint(e.target.value)}>
              {blueprints.map(b => <option key={b.blueprint_id} value={b.blueprint_id}>{b.blueprint_id} · v{b.version}</option>)}
            </select>
            {blueprint && <div className="tw-blueprint-meta"><strong>{blueprint.blueprint_id}</strong><span>Version {blueprint.version}</span><Status value={blueprint.version_status}/><small>Learning run: {blueprint.source_learning_run_id}</small><code>{blueprint.manifest_hash.slice(0, 20)}…</code></div>}
          </> : <div className="tw-empty"><ShieldCheck size={24}/><strong>No approved blueprint yet</strong><span>Complete Stage 3 in a Learning Workbench run and approve its blueprint to unlock annual generation.</span></div>}
        </section>
        <section className="tw-card">
          <div className="tw-card-title"><CloudUpload size={17}/><h2>New source package</h2></div>
          <label className="tw-label">Generation name</label><input value={runName} onChange={e => setRunName(e.target.value)}/>
          <div className="tw-date-grid"><div><label className="tw-label">Period start</label><input type="date" value={periodStart} onChange={e => setPeriodStart(e.target.value)}/></div><div><label className="tw-label">Period end</label><input type="date" value={periodEnd} onChange={e => setPeriodEnd(e.target.value)}/></div></div>
          <label className="tw-label">Data as-of date (optional)</label><input type="date" value={asOfDate} onChange={e => setAsOfDate(e.target.value)}/>
          <label className="tw-dropzone"><CloudUpload size={26}/><strong>Choose XLSX / CSV files</strong><span>Source extracts only. No target PBRER is required.</span><input type="file" multiple accept=".xlsx,.csv" onChange={e => addFiles(e.target.files)}/></label>
          {!!files.length && <div className="tw-file-list">{files.map((f, i) => <div key={`${f.name}-${i}`}><FileSpreadsheet size={15}/><span>{f.name}</span><small>{(f.size/1024/1024).toFixed(1)} MB</small><button onClick={() => setFiles(prev => prev.filter((_,j) => j!==i))}>Remove</button></div>)}</div>}
          <button className="tw-primary" disabled={!blueprint || !files.length || busy} onClick={() => void create()}>{busy ? <LoaderCircle className="tw-spin" size={16}/> : <ArrowRight size={16}/>} Create generation run</button>
        </section>
      </div>
      <section className="tw-card tw-pipeline-card">
        <div className="tw-card-title"><Workflow size={17}/><h2>Generation runs</h2><span className="tw-count">{generations.length}</span><span className={`tw-connection ${connection}`}>{connection}</span></div>
        {!generations.length ? <div className="tw-empty compact">No annual generation runs yet.</div> : <div className="tw-generation-list">{generations.map(g => <button key={g.generation_id} className={active?.generation_id===g.generation_id?'selected':''} onClick={() => setActive(g)}><div><strong>{g.run_name}</strong><small>{g.generation_id.slice(0,12)} · Blueprint {g.blueprint_id} v{g.blueprint_version}</small></div><Status value={g.status}/><span>{g.reporting_period_start} → {g.reporting_period_end}</span><ArrowRight size={15}/></button>)}</div>}
      </section>
      {active && <section className="tw-card tw-run-detail">
        <div className="tw-card-title"><GitCompareArrows size={17}/><h2>Run details</h2><Status value={active.status}/></div>
        <div className="tw-run-stats"><div><small>Blueprint</small><strong>{active.blueprint_id} · v{active.blueprint_version}</strong></div><div><small>Reporting period</small><strong>{active.reporting_period_start} → {active.reporting_period_end}</strong></div><div><small>Source hash</small><code>{active.source_manifest_hash.slice(0,16)}…</code></div></div>
        {active.compatibility_json && <div className="tw-compat"><div><strong>Schema compatibility</strong><Status value={active.compatibility_json.status}/></div><p>{active.compatibility_json.source_profiles.length} header profile(s) inspected · {active.compatibility_json.drift.length} drift finding(s)</p>{active.compatibility_json.drift.map((d,i)=><div className="tw-drift" key={`${d.code}-${i}`}><AlertTriangle size={14}/><div><strong>{d.code} · {d.logical_field || d.dataset_id}</strong><small>{d.expected || 'Expected mapping'} → {d.observed || 'Missing/ambiguous'}</small><p>{d.suggested_action}</p></div></div>)}{(active.compatibility_json as any).mapping_proposal && <div className="tw-proposal"><strong>Harness proposal available</strong><p>The drift assistant can suggest field mappings, but cannot accept them. Review the proposal and create/approve a new blueprint version before retrying with a new generation run.</p></div>}</div>}
        {(active.status==='created' || active.status==='failed') && <button className="tw-primary" disabled={busy} onClick={() => void start(active.generation_id)}><Play size={15}/> Start compatibility & generation</button>}
        {active.status==='compatibility_review' && <div className="tw-warning"><AlertTriangle size={16}/>Generation is blocked until schema drift and semantic changes are reviewed. The approved blueprint has not been modified. Apply approved methodology changes through a new blueprint version, then create a new generation run against that version.</div>}
        {active.artifacts_json?.length ? <div className="tw-output-list"><h3>Generated artifacts</h3>{active.artifacts_json.map(a=><div key={a.artifact_id}><FileText size={15}/><strong>{a.logical_path}</strong><code>{a.sha256.slice(0,16)}…</code><Status value={a.status || 'ready'}/><a href={`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/generations/${encodeURIComponent(active.generation_id)}/artifacts/${encodeURIComponent(a.artifact_id)}/content`}>Download</a></div>)}</div> : null}
        {active.status==='output_review' && <div className="tw-output-review"><strong>Section output is ready for human sign-off.</strong><p>Review the DOCX and supporting lineage/result artifacts before approving the generation run.</p><div><button disabled={busy} onClick={() => void reviewOutput('request_changes')}>Request corrections</button><button disabled={busy} onClick={() => void reviewOutput('approve')}><CheckCircle2 size={14}/> Approve output</button></div></div>}
        {active.error_summary && <div className="tw-error">{active.error_summary}</div>}
        {!!liveEvents.length && <div className="tw-live-events"><h3>Live AG-UI event trace <span>{connection}</span></h3>{liveEvents.slice(-8).reverse().map((event,i)=><div key={`${event.type}-${i}`}><code>{event.type}</code><span>{event.type === 'CUSTOM' ? String((event as any).name || '') : String(event.stage || event.toolName || event.type)}</span></div>)}</div>}
      </section>}
      <footer className="tw-generator-foot"><ShieldCheck size={14}/> Separate generation run · Immutable source snapshot · Approved blueprint version · Isolated execution required</footer>
    </main>
  );
}
