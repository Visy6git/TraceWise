import { BookOpen, CheckCircle2, Copy, FileSpreadsheet, FileText, Lock, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { Claim, SourceFile } from '../types/domain';

export function SourceDrawer({
  runId,
  source,
  claims,
  live,
  onSelectClaim,
  onClose,
}: {
  runId: string;
  source: SourceFile;
  claims: Claim[];
  live: boolean;
  onSelectClaim: (claimId: string) => void;
  onClose: () => void;
}) {
  const [summaryMd, setSummaryMd] = useState<string | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);

  const linkedClaims = claims.filter(
    c => c.sourceIds.includes(source.id) || (c.sourceDocumentMapped || []).includes(source.name),
  );

  useEffect(() => {
    if (!live || !runId) {
      setSummaryMd(null);
      return;
    }
    let cancelled = false;
    setLoadingSummary(true);
    api
      .getSourceSummary(runId, source.name || source.id)
      .then(res => {
        if (!cancelled) setSummaryMd(res.content);
      })
      .catch(() => {
        if (!cancelled) setSummaryMd(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingSummary(false);
      });
    return () => {
      cancelled = true;
    };
  }, [live, runId, source.id, source.name]);

  return (
    <div className="drawer-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <aside className="source-drawer">
        <div className="drawer-header">
          <div>
            <span className="modal-kicker">SOURCE INTELLIGENCE</span>
            <h2>{source.name}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close source drawer">
            <X size={17} />
          </button>
        </div>

        <div className="source-drawer-body">
          <div className="source-file-hero">
            <div className={`file-icon large ${source.kind}`}>
              {source.kind === 'docx' ? <BookOpen size={16} /> : source.kind === 'pdf' ? <FileText size={16} /> : <FileSpreadsheet size={16} />}
            </div>
            <div>
              <strong>{source.name}</strong>
              <span>{source.kind.toUpperCase()} · {source.sizeLabel}</span>
            </div>
          </div>

          <div className="drawer-stats">
            <div><span>RECORDS</span><strong>{source.rows?.toLocaleString() || '—'}</strong></div>
            <div><span>WORKSHEETS</span><strong>{source.sheets || '—'}</strong></div>
            <div><span>CLAIMS LINKED</span><strong>{linkedClaims.length || source.usedBy}</strong></div>
          </div>

          <div className="drawer-section">
            <h3>Integrity</h3>
            <div className="integrity-row">
              <Lock size={13} />Immutable source snapshot <CheckCircle2 size={14} />
            </div>
            <div className="hash-box">
              <span>SHA-256</span>
              <code>{source.hash || 'Generated at ingestion'}</code>
              <button
                title="Copy hash"
                onClick={() => source.hash && navigator.clipboard?.writeText(source.hash).catch(() => {})}
              >
                <Copy size={12} />
              </button>
            </div>
          </div>

          <div className="drawer-section">
            <h3>Harness Markdown Summary (.md)</h3>
            {loadingSummary ? (
              <p className="muted-copy">Loading Stage 1 exploration summary…</p>
            ) : summaryMd ? (
              <pre className="drawer-markdown-preview">{summaryMd}</pre>
            ) : (
              <p>{source.sourceNote || 'Run Stage 1 to explore the first 100 rows, column types, unique values, and Markdown summary.'}</p>
            )}
          </div>

          <div className="drawer-section">
            <h3>Linked claims ({linkedClaims.length})</h3>
            {linkedClaims.length ? (
              <div className="source-linked-claims">
                {linkedClaims.map(c => (
                  <button
                    key={c.id}
                    className="linked-claim-pill"
                    onClick={() => {
                      onSelectClaim(c.id);
                      onClose();
                    }}
                  >
                    <span>{c.id}</span>
                    <strong>{c.statement}</strong>
                  </button>
                ))}
              </div>
            ) : (
              <p className="muted-copy">No claims mapped to this file yet.</p>
            )}
          </div>
        </div>

        <div className="drawer-footer">
          <button className="button-secondary full-width" onClick={onClose}>Close source inspector</button>
        </div>
      </aside>
    </div>
  );
}

