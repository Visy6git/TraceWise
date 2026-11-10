# TraceWise UI Components

Extracted workspace components backing `src/App.tsx`:

- `ArtifactViewerModal.tsx`: Modal inspector for generated `.py`, `.md`, `master_source_summary.md`, and `result.json` artifacts.
- `ClaimInspector.tsx`: Hierarchical claim viewer showing parent claim, nested children claims (`verified`/`mismatch`/`empty`), search criteria, mapped sources, evidence hints, and verification result shortcuts.
- `SourceDrawer.tsx`: Slide-out source file inspector displaying SHA-256 integrity, Stage 1 per-file Markdown summary, and linked claim pills.
- `Modals.tsx`: Stage review gate (`ReviewModal`), versioned `ClaimEditor`, and runtime-aware `UploadModal`.
