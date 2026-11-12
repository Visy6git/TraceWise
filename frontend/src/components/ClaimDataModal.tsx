import { AlertTriangle, Database, Download, FileSpreadsheet, GitBranch, Table2, X } from 'lucide-react';
import { useState } from 'react';
import type { ClaimData, ClaimDataTable, ClaimSheet, ClaimSourceData } from '../types/domain';

function cellText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function SheetTable({ columns, rows }: { columns: string[]; rows: Array<Record<string, unknown>> }) {
  return (
    <div className="claim-data-table-wrap">
      <table className="claim-data-table">
        <thead>
          <tr>
            <th className="row-idx">#</th>
            {columns.map(col => (
              <th key={col}>{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              <td className="row-idx">{i + 1}</td>
              {columns.map(col => {
                const text = cellText(row[col]);
                return (
                  <td key={col} title={text}>
                    {text || <span className="cell-empty">—</span>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FullSheetBlock({ sheet, csvUrl }: { sheet: ClaimSheet; csvUrl?: string }) {
  return (
    <div className="claim-data-block sheet">
      <div className="claim-data-block-head">
        <span className="claim-data-tag sheet"><Table2 size={12} />SOURCE SHEET</span>
        <strong>{sheet.sheet || sheet.source_file}</strong>
        <span className="claim-data-count">
          {sheet.row_count} row{sheet.row_count === 1 ? '' : 's'} × {sheet.columns.length} cols
          {sheet.truncated ? ` · preview ${sheet.rows.length}` : ''}
        </span>
        {csvUrl && (
          <a className="claim-data-download" href={csvUrl} download>
            <Download size={12} /> Download full sheet (CSV)
          </a>
        )}
      </div>
      <div className="claim-data-source">
        <FileSpreadsheet size={11} />
        {sheet.source_file}
        {sheet.sheet ? ` · ${sheet.sheet}` : ''}
        {` · header row ${sheet.header_row_index}`}
      </div>
      {sheet.error ? (
        <p className="claim-data-error"><AlertTriangle size={12} /> {sheet.error}</p>
      ) : sheet.rows.length ? (
        <SheetTable columns={sheet.columns} rows={sheet.rows} />
      ) : (
        <p className="claim-data-empty">Sheet has no data rows.</p>
      )}
      {sheet.truncated && (
        <p className="claim-data-trunc">
          <AlertTriangle size={11} /> Previewing first {sheet.rows.length} of {sheet.row_count} rows — download the
          CSV to inspect every row in Excel.
        </p>
      )}
    </div>
  );
}

function MatchedBlock({ table, kind }: { table: ClaimDataTable; kind: 'parent' | 'child' }) {
  const shown = table.rows.length;
  return (
    <div className={`claim-data-block ${kind}`}>
      <div className="claim-data-block-head">
        <span className="claim-data-tag">
          {kind === 'parent' ? <Database size={12} /> : <GitBranch size={12} />}
          {kind === 'parent' ? 'PARENT · MATCHED' : `${table.child_claim_id || 'CHILD'} · MATCHED`}
        </span>
        <strong>{table.label || (kind === 'parent' ? 'Matched rows' : 'Child rows')}</strong>
        <span className="claim-data-count">
          {table.row_count} row{table.row_count === 1 ? '' : 's'}
          {table.truncated ? ` · showing ${shown}` : ''}
        </span>
      </div>
      {shown ? (
        <SheetTable columns={table.columns} rows={table.rows} />
      ) : (
        <p className="claim-data-empty">No matched rows for this claim.</p>
      )}
    </div>
  );
}

export function ClaimDataModal({
  claimId,
  sourceData,
  data,
  loading,
  error,
  csvUrlFor,
  onClose,
}: {
  claimId: string;
  sourceData: ClaimSourceData | null;
  data: ClaimData | null;
  loading: boolean;
  error: string | null;
  csvUrlFor?: (sheet: ClaimSheet) => string;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<'sheet' | 'matched'>('matched');
  const hasMatched = Boolean(data && (data.parent || data.children.length));
  const showMatched = tab === 'matched' && hasMatched;

  return (
    <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className="modal claim-data-modal">
        <div className="modal-top">
          <span className="modal-kicker">CLAIM EVIDENCE DATA</span>
          <button className="icon-button" onClick={onClose} aria-label="Close claim data viewer">
            <X size={17} />
          </button>
        </div>
        <div className="artifact-modal-head">
          <span className="artifact-file-icon large"><Table2 size={18} /></span>
          <div className="artifact-modal-meta">
            <h2>{claimId} · matched source data</h2>
            <p>Rows matched for this claim; switch to the full source sheet to inspect the broader dataset.</p>
          </div>
        </div>

        {hasMatched && !loading && !error && (
          <div className="claim-data-tabs">
            <button className={tab === 'sheet' ? 'active' : ''} onClick={() => setTab('sheet')}>
              Full source sheet
            </button>
            <button className={tab === 'matched' ? 'active' : ''} onClick={() => setTab('matched')}>
              Rows the agent matched
            </button>
          </div>
        )}

        <div className="claim-data-body">
          {loading && <div className="artifact-loading">Loading source data…</div>}
          {error && !loading && (
            <div className="claim-data-error"><AlertTriangle size={14} /> {error}</div>
          )}
          {!loading && !error && !showMatched && (
            sourceData && sourceData.sheets.length ? (
              sourceData.sheets.map((s, i) => (
                <FullSheetBlock
                  key={`${s.source_file}-${s.sheet}-${i}`}
                  sheet={s}
                  csvUrl={csvUrlFor ? csvUrlFor(s) : undefined}
                />
              ))
            ) : (
              <p className="claim-data-empty">No mapped source sheet was found for this claim.</p>
            )
          )}
          {!loading && !error && showMatched && data && (
            <>
              {data.parent ? (
                <MatchedBlock table={data.parent} kind="parent" />
              ) : (
                <p className="claim-data-empty">No parent-claim matched rows were produced.</p>
              )}
              {data.children.map(child => (
                <MatchedBlock key={child.child_claim_id || child.label} table={child} kind="child" />
              ))}
            </>
          )}
        </div>
        <div className="modal-footer">
          <button className="button-secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
