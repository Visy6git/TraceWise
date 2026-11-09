# UI component extraction boundary

`App.tsx` currently contains the complete interactive prototype and colocated view components so the starter can be explored immediately. During the next frontend pass, extract the named components without changing the UX/API contract:

- `Shell/TopBar`, `Shell/LeftRail`, `Shell/WorkspaceFooter`
- `Run/StageRail`, `Run/StageControl`, `Run/MetricStrip`
- `Document/SectionTree`, `Document/ReportViewer`
- `Activity/Timeline`, `Activity/AgentCards`, `Activity/ToolActivity`
- `Claims/ClaimRegister`, `Claims/ClaimInspector`, `Claims/ClaimEditor`, `Claims/LineageView`
- `Sources/SourceInventory`, `Sources/SourceDrawer`, `Sources/UploadModal`
- `Artifacts/ArtifactExplorer`, `Review/ReviewGateModal`

All controls should remain keyboard accessible, expose labels, and use the AG-UI state projection rather than creating an independent ad hoc event model.
