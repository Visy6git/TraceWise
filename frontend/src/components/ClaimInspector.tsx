import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  Code2,
  FileSpreadsheet,
  GitBranch,
  Search,
  Sparkles,
  XCircle,
} from 'lucide-react';
import type { ArtifactItem, Claim, SourceFile } from '../types/domain';

export function ClaimInspector({
  claim,
  sources,
  artifacts,
  onEdit,
  onOpenSource,
  onOpenLocation,
  onOpenArtifact,
}: {
  claim: Claim;
  sources: SourceFile[];
  artifacts: ArtifactItem[];
  onEdit: (claim: Claim) => void;
  onOpenSource: (sourceId: string) => void;
  onOpenLocation: (sectionId: string) => void;
  onOpenArtifact: (artifact: ArtifactItem) => void;
}) {
  const vr = claim.verificationResult;
  const isVerified = claim.status === 'verified' || vr?.verified === true;
  const isDiscrepancy = claim.status === 'discrepancy' || claim.status === 'failed';
  const mappedNames = claim.sourceDocumentMapped?.length ? claim.sourceDocumentMapped : claim.sourceIds;

  const analysisArtifact = artifacts.find(
    a => a.claimId === claim.id && a.name.endsWith('analysis.py'),
  );
  const resultArtifact = artifacts.find(
    a => a.claimId === claim.id && a.name.endsWith('result.json'),
  );

  return (
    <div className="claim-inspector">
      <div className="inspector-top">
        <span>SELECTED CLAIM</span>
        <button className="plain-link" onClick={() => onEdit(claim)}>
          Edit <ArrowUpRight size={12} />
        </button>
      </div>

      <div className="inspector-id">
        <strong>{claim.id}</strong>
        <span>{claim.sectionNumber}</span>
        {isVerified && (
          <span className="verified-badge-inline">
            <CheckCircle2 size={12} /> Verified
          </span>
        )}
        {isDiscrepancy && (
          <span className="discrepancy-badge-inline">
            <AlertTriangle size={12} /> {claim.status === 'failed' ? 'Failed' : 'Discrepancy'}
          </span>
        )}
      </div>

      <p className="inspector-statement">{claim.statement}</p>

      <div className="claim-value-row">
        <div>
          <span>PARENT REPORTED</span>
          <strong>
            {claim.reportedValue} <small>{claim.unit}</small>
          </strong>
        </div>
        <div>
          <span>{vr ? 'STAGE 2 COMPUTED' : 'ENTITY'}</span>
          <strong>
            {vr ? (
              vr.parent_computed_value ?? '—'
            ) : (
              claim.entity
            )}
          </strong>
        </div>
      </div>

      {vr?.discrepancy_summary && !vr.verified && (
        <div className="verification-alert">
          <XCircle size={13} />
          <span>{vr.discrepancy_summary}</span>
        </div>
      )}

      {claim.searchCriteria && (
        <div className="search-criteria-box">
          <div className="lineage-head">
            <span><Search size={12} />SEARCH CRITERIA</span>
          </div>
          <p>{claim.searchCriteria}</p>
        </div>
      )}

      <div className="inspector-divider" />

      <div className="lineage-head">
        <span><GitBranch size={13} />CHILDREN CLAIMS</span>
        <span className="lineage-count">{claim.childrenClaims.length} nested</span>
      </div>

      {claim.childrenClaims.length ? (
        <div className="children-claims-list">
          {claim.childrenClaims.map(child => (
            <div
              key={child.child_claim_id || child.raw_statement}
              className={`child-claim-card ${
                child.verified === true
                  ? 'child-verified'
                  : child.verified === false
                    ? 'child-mismatch'
                    : ''
              }`}
            >
              <div className="child-claim-head">
                <span className="child-rel-tag">{child.relationship}</span>
                {child.verified === true && <CheckCircle2 size={12} className="child-ok-icon" />}
                {child.verified === false && <AlertTriangle size={12} className="child-err-icon" />}
                <strong>
                  {child.reported_value}
                  {child.computed_value != null ? ` -> computed: ${child.computed_value}` : ''}
                </strong>
              </div>
              <p>{child.raw_statement}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty-children-note">No child claims (empty array `[]`).</p>
      )}

      <div className="inspector-divider" />

      <div className="lineage-head">
        <span><GitBranch size={13} />MAPPED SOURCES</span>
        <span className="lineage-count">{mappedNames.length} file(s)</span>
      </div>

      <div className="lineage-chips">
        {mappedNames.map(ref => {
          const matchedSource = sources.find(x => x.id === ref || x.name === ref);
          return (
            <button
              key={ref}
              onClick={() => matchedSource && onOpenSource(matchedSource.id)}
              disabled={!matchedSource}
            >
              <FileSpreadsheet size={12} />
              {matchedSource?.name || ref}
            </button>
          );
        })}
      </div>

      <div className="hint-block">
        <span className="hint-icon"><Sparkles size={12} /></span>
        <div>
          <strong>Evidence hint</strong>
          <p>{claim.hint.text}</p>
        </div>
      </div>

      <div className="hint-markers">
        <span className="observed">● {claim.hint.observed.length} observed</span>
        <span className="inferred">● {claim.hint.inferred.length} inferred</span>
        <span className="unknown">● {claim.hint.unknowns.length} unknown</span>
      </div>

      <div className="inspector-action-stack">
        {(analysisArtifact || resultArtifact) && (
          <div className="inspector-artifact-links">
            {analysisArtifact && (
              <button className="button-secondary" onClick={() => onOpenArtifact(analysisArtifact)}>
                <Code2 size={13} /> View analysis.py
              </button>
            )}
            {resultArtifact && (
              <button className="button-secondary" onClick={() => onOpenArtifact(resultArtifact)}>
                <CheckCircle2 size={13} /> View result.json
              </button>
            )}
          </div>
        )}
        <button className="button-secondary full-width" onClick={() => onOpenLocation(claim.sectionId)}>
          <BookOpen size={14} />Open target location <ArrowUpRight size={13} />
        </button>
      </div>
    </div>
  );
}

