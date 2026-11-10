import {
  AlertCircle,
  ArrowRight,
  Check,
  CheckCircle2,
  CloudUpload,
  FileCheck2,
  FileSpreadsheet,
  Lock,
  Plus,
  ShieldCheck,
  Upload,
  X,
} from 'lucide-react';
import type * as React from 'react';
import type { Claim, RuntimeConfig, StageInfo } from '../types/domain';

export function ReviewModal({
  stage,
  note,
  setNote,
  onClose,
  onApprove,
  onRequestChanges,
}: {
  stage: StageInfo;
  note: string;
  setNote: (v: string) => void;
  onClose: () => void;
  onApprove: () => void;
  onRequestChanges: () => void;
}) {
  const isFinal = stage.id === 'evaluation';
  return (
    <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal review-modal">
        <div className="modal-top">
          <span className="modal-kicker">REVIEW GATE · {stage.number}</span>
          <button className="icon-button" onClick={onClose}><X size={17} /></button>
        </div>
        <div className="review-hero">
          <div className="review-icon"><ShieldCheck size={23} /></div>
          <div>
            <h2>{isFinal ? 'Final evaluation review' : `Approve ${stage.title}?`}</h2>
            <p>
              {isFinal
                ? 'Confirm the independent evaluation and close this review dossier.'
                : 'This approval freezes the current artifact versions and unlocks the next stage.'}
            </p>
          </div>
        </div>
        <div className="review-checklist">
          <div>
            <CheckCircle2 size={16} />
            <span>
              <strong>Version snapshot</strong>
              <small>Approval is bound to the current artifact manifest hash.</small>
            </span>
            <em>Ready</em>
          </div>
          <div>
            <CheckCircle2 size={16} />
            <span>
              <strong>Audit record</strong>
              <small>Reviewer identity, timestamp and note are persisted by the control plane.</small>
            </span>
            <em>Ready</em>
          </div>
          <div>
            <AlertCircle size={16} />
            <span>
              <strong>Stage transition</strong>
              <small>
                {isFinal
                  ? 'No further agent stage will start automatically.'
                  : 'The next stage remains stopped until explicitly started.'}
              </small>
            </span>
            <em>Manual</em>
          </div>
        </div>
        <label className="field-label">
          REVIEW NOTE <span>OPTIONAL</span>
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="Add rationale, requested corrections or approval context…"
            rows={3}
          />
        </label>
        <div className="modal-footer">
          <button className="button-secondary" onClick={onRequestChanges}>Request changes</button>
          <button className="button-primary" onClick={onApprove}>
            <Check size={15} />
            {isFinal ? 'Approve final evaluation' : 'Approve & freeze stage'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ClaimEditor({
  claim,
  draft,
  setDraft,
  onClose,
  onSave,
}: {
  claim: Claim;
  draft: { statement: string; reportedValue: string; unit: string; searchCriteria: string };
  setDraft: (v: { statement: string; reportedValue: string; unit: string; searchCriteria: string }) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal editor-modal">
        <div className="modal-top">
          <span className="modal-kicker">CLAIM REGISTER · {claim.id}</span>
          <button className="icon-button" onClick={onClose}><X size={17} /></button>
        </div>
        <h2>Edit claim</h2>
        <p className="modal-sub">Edits are versioned and persisted to the SQLite claim register.</p>
        <label className="field-label">
          PARENT STATEMENT
          <textarea rows={3} value={draft.statement} onChange={e => setDraft({ ...draft, statement: e.target.value })} />
        </label>
        <label className="field-label">
          SEARCH CRITERIA
          <input value={draft.searchCriteria} onChange={e => setDraft({ ...draft, searchCriteria: e.target.value })} />
        </label>
        <div className="field-pair">
          <label className="field-label">
            REPORTED VALUE
            <input value={draft.reportedValue} onChange={e => setDraft({ ...draft, reportedValue: e.target.value })} />
          </label>
          <label className="field-label">
            UNIT
            <input value={draft.unit} onChange={e => setDraft({ ...draft, unit: e.target.value })} />
          </label>
        </div>
        <div className="modal-footer">
          <button className="button-secondary" onClick={onClose}>Cancel</button>
          <button className="button-primary" onClick={onSave}>
            <Check size={15} />Save edit
          </button>
        </div>
      </div>
    </div>
  );
}

export function UploadModal({
  name,
  setName,
  targetFile,
  sourceFiles,
  error,
  inputTarget,
  inputSources,
  onAddFiles,
  onRemoveSource,
  onClose,
  onCreate,
  live,
  loading,
  runtimeConfig,
}: {
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
  runtimeConfig: RuntimeConfig | null;
}) {
  const targetAccept = live ? '.docx' : '.docx,.pdf';
  const sourceAccept = live ? '.xlsx,.csv' : '.xlsx,.xls,.csv,.pdf,.docx';
  const providerLabel =
    runtimeConfig?.llm_provider === 'bedrock'
      ? `AWS Bedrock (${runtimeConfig.model_id})`
      : runtimeConfig?.llm_provider === 'lmstudio' || runtimeConfig?.llm_provider === 'openai'
        ? `LM Studio (${runtimeConfig.model_id})`
        : 'Deterministic / Mock mode';

  return (
    <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal upload-modal">
        <div className="modal-top">
          <span className="modal-kicker">NEW RECONCILIATION RUN</span>
          <button className="icon-button" onClick={onClose}><X size={17} /></button>
        </div>
        <div className="upload-title">
          <div className="upload-title-icon"><CloudUpload size={22} /></div>
          <div>
            <h2>Start with your documents</h2>
            <p>Upload one target PBRER document and supporting Excel/CSV source files.</p>
          </div>
        </div>
        <label className="field-label">
          RUN NAME
          <input value={name} onChange={e => setName(e.target.value)} />
        </label>
        <div className="upload-block">
          <div className="upload-block-head">
            <div>
              <span className="step-number">01</span>
              <strong>Target report</strong>
              <small>Primary PBRER · {live ? 'DOCX' : 'DOCX or PDF'}</small>
            </div>
            <span className="required-label">REQUIRED</span>
          </div>
          <button
            className={`dropzone ${targetFile ? 'has-file' : ''}`}
            onClick={() => inputTarget.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault();
              onAddFiles(e.dataTransfer.files, true);
            }}
          >
            <input ref={inputTarget} type="file" accept={targetAccept} hidden onChange={e => onAddFiles(e.target.files, true)} />
            {targetFile ? (
              <>
                <span className="file-selected-icon"><FileCheck2 size={20} /></span>
                <span>
                  <strong>{targetFile.name}</strong>
                  <small>{(targetFile.size / 1024 / 1024).toFixed(2)} MB · selected</small>
                </span>
                <CheckCircle2 size={17} />
              </>
            ) : (
              <>
                <Upload size={19} />
                <span>
                  <strong>Drop the target document here</strong>
                  <small>or browse files · {targetAccept}</small>
                </span>
                <span className="browse-label">Browse</span>
              </>
            )}
          </button>
        </div>
        <div className="upload-block">
          <div className="upload-block-head">
            <div>
              <span className="step-number">02</span>
              <strong>Source documents</strong>
              <small>{live ? 'Excel workbooks and CSV data' : 'Workbooks, listings and CSV tables'}</small>
            </div>
            <span className="required-label">1+ REQUIRED</span>
          </div>
          <div className="source-file-picks">
            {sourceFiles.map((file, index) => (
              <div key={`${file.name}-${index}`} className="picked-file">
                <FileSpreadsheet size={15} />
                <span>
                  <strong>{file.name}</strong>
                  <small>{(file.size / 1024 / 1024).toFixed(2)} MB</small>
                </span>
                <button onClick={() => onRemoveSource(index)}><X size={13} /></button>
              </div>
            ))}
          </div>
          <button
            className="source-add-button"
            onClick={() => inputSources.current?.click()}
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault();
              onAddFiles(e.dataTransfer.files, false);
            }}
          >
            <input ref={inputSources} type="file" accept={sourceAccept} multiple hidden onChange={e => onAddFiles(e.target.files, false)} />
            <Plus size={15} />Add source files <span>· {sourceAccept.replaceAll(',', ' ')}</span>
          </button>
        </div>
        <div className="upload-privacy">
          <Lock size={13} />
          <span>
            {live
              ? `Files are stored immutably in local run storage. Active stage runtime: ${providerLabel}.`
              : 'Demo mode · uploaded files stay in browser memory unless VITE_API_MODE=api.'}
          </span>
        </div>
        {error && <div className="upload-error"><AlertCircle size={14} />{error}</div>}
        <div className="modal-footer">
          <button className="button-secondary" onClick={onClose}>Cancel</button>
          <button className="button-primary" onClick={onCreate} disabled={!targetFile || sourceFiles.length === 0 || loading}>
            {loading ? 'Uploading…' : 'Create run'} <ArrowRight size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}
