import { Check, Code2, Copy, FileJson, FileText, X } from 'lucide-react';
import { useState } from 'react';

export interface OpenedArtifact {
  title: string;
  subtitle: string;
  mediaType: string;
  content: string;
  sha256?: string;
}

export function ArtifactViewerModal({
  artifact,
  loading,
  onClose,
}: {
  artifact: OpenedArtifact | null;
  loading: boolean;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  if (!artifact && !loading) return null;

  const isCode = artifact?.title.endsWith('.py') || artifact?.title.endsWith('.json') || artifact?.title.endsWith('.jsonl');
  const icon = artifact?.title.endsWith('.py')
    ? <Code2 size={18} />
    : artifact?.title.endsWith('.json')
      ? <FileJson size={18} />
      : <FileText size={18} />;

  async function handleCopy() {
    if (!artifact?.content || !navigator.clipboard) return;
    await navigator.clipboard.writeText(artifact.content).catch(() => {});
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal artifact-viewer-modal">
        <div className="modal-top">
          <span className="modal-kicker">ARTIFACT INSPECTOR</span>
          <button className="icon-button" onClick={onClose} aria-label="Close artifact viewer">
            <X size={17} />
          </button>
        </div>
        <div className="artifact-modal-head">
          <span className="artifact-file-icon large">{icon}</span>
          <div className="artifact-modal-meta">
            <h2>{loading ? 'Loading artifact…' : artifact?.title}</h2>
            <p>
              {artifact?.subtitle}
              {artifact?.sha256 ? ` · sha256:${artifact.sha256.slice(0, 12)}…` : ''}
            </p>
          </div>
          {!loading && artifact?.content && (
            <button className="button-secondary" onClick={() => void handleCopy()}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          )}
        </div>
        <div className={isCode ? 'artifact-code-body' : 'artifact-text-body'}>
          {loading ? (
            <div className="artifact-loading">Fetching artifact content…</div>
          ) : (
            <pre>{artifact?.content || ''}</pre>
          )}
        </div>
        <div className="modal-footer">
          <button className="button-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

