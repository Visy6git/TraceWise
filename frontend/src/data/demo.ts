import type { RunSnapshot } from '../types/domain';

export const demoRun: RunSnapshot = {
  runId: 'TW-26-1109-042',
  name: 'PBRER · Example product',
  product: 'Example product / active substance',
  period: '01 Jan 2025 — 31 Dec 2025',
  status: 'Stage 1 · In review',
  createdAt: '09 Nov 2026 · 09:42',
  targetDocument: 'PBRER_Example_Product_v4.docx',
  activeStage: 'claims',
  sources: [
    { id: 'src-csmr', name: 'CSMR_2025.xlsx', kind: 'xlsx', sizeLabel: '8.4 MB', rows: 42816, sheets: 6, status: 'indexed', hash: 'a93c…8e21', usedBy: 8, sourceNote: 'Case and event extracts; export filters require reviewer confirmation.' },
    { id: 'src-case', name: 'Case_listing_Q4.xlsx', kind: 'xlsx', sizeLabel: '3.1 MB', rows: 12642, sheets: 3, status: 'indexed', hash: 'bc42…117a', usedBy: 5, sourceNote: 'Case-level records; candidate link key available.' },
    { id: 'src-exp', name: 'Exposure_summary.xlsx', kind: 'xlsx', sizeLabel: '940 KB', rows: 124, sheets: 2, status: 'warning', hash: 'c14d…98f0', usedBy: 2, sourceNote: 'Preamble row detected; population definition not explicit.' },
    { id: 'src-signal', name: 'Signal_tracker.xlsx', kind: 'xlsx', sizeLabel: '2.2 MB', rows: 1860, sheets: 4, status: 'indexed', hash: '09be…82cc', usedBy: 3 },
    { id: 'src-method', name: 'Data_cut_methodology.pdf', kind: 'pdf', sizeLabel: '1.6 MB', status: 'indexed', usedBy: 4 },
    { id: 'src-dictionary', name: 'Data_dictionary.docx', kind: 'docx', sizeLabel: '380 KB', status: 'indexed', usedBy: 6 },
  ],
  sections: [
    { id: 's16', number: '16', title: 'Integrated benefit-risk analysis', level: 0, children: [
      { id: 's163', number: '16.3', title: 'Benefit-risk evaluation', level: 1, selected: true, children: [
        { id: 's1631', number: '16.3.1', title: 'Important identified risks', level: 2, claims: 4, children: [
          { id: 's16311', number: '16.3.1.1', title: 'Hepatic events', level: 3, claims: 2 },
          { id: 's16312', number: '16.3.1.2', title: 'Serious skin reactions', level: 3, claims: 2 },
        ] },
        { id: 's1632', number: '16.3.2', title: 'Important potential risks', level: 2, claims: 3, children: [
          { id: 's16321', number: '16.3.2.1', title: 'Cardiovascular events', level: 3, claims: 2 },
          { id: 's16322', number: '16.3.2.2', title: 'Use in pregnancy', level: 3, claims: 1 },
        ] },
        { id: 's1633', number: '16.3.3', title: 'Missing information', level: 2, claims: 2, children: [
          { id: 's16331', number: '16.3.3.1', title: 'Long-term exposure', level: 3, claims: 2 },
        ] },
      ] },
      { id: 's17', number: '17', title: 'Conclusions and actions', level: 1, children: [] },
    ] },
  ],
  claims: [
    { id: 'CLM-001', sectionId: 's16311', sectionNumber: '16.3.1.1', sectionTitle: 'Hepatic events', statement: 'A total of 184 cases with hepatic events were identified during the reporting interval.', reportedValue: '184', unit: 'cases', entity: 'Distinct case', status: 'hinted', period: '2025 reporting interval', hint: { text: 'Start with the CSMR case/event extracts. Confirm hepatic event coding, reporting-period date field, and case-level deduplication after event joins.', observed: ['Report states reporting interval is 2025', 'CSMR workbook contains case and event tabs'], inferred: ['Hepatic event grouping may require MedDRA PT / SMQ mapping'], unknowns: ['Whether follow-up versions are collapsed to latest case version', 'Which date field drives interval inclusion'] }, sourceIds: ['src-csmr', 'src-method', 'src-dictionary'], artifacts: ['source_knowledge.md'], locator: 'PBRER · p. 118 · paragraph 6' },
    { id: 'CLM-002', sectionId: 's16311', sectionNumber: '16.3.1.1', sectionTitle: 'Hepatic events', statement: 'Of these, 39 cases were classified as serious.', reportedValue: '39', unit: 'cases', entity: 'Distinct serious case', status: 'hinted', period: '2025 reporting interval', hint: { text: 'Use the same hepatic event cohort as CLM-001, then verify the seriousness definition and whether seriousness is case-level or event-level.', observed: ['Claim is nested under the hepatic-event subsection'], inferred: ['Seriousness likely comes from case seriousness criteria'], unknowns: ['Which seriousness field and aggregation rule is authoritative'] }, sourceIds: ['src-csmr', 'src-dictionary'], artifacts: ['source_knowledge.md'], locator: 'PBRER · p. 118 · paragraph 7' },
    { id: 'CLM-003', sectionId: 's16312', sectionNumber: '16.3.1.2', sectionTitle: 'Serious skin reactions', statement: 'Twenty-seven unique cases met the serious skin reaction definition.', reportedValue: '27', unit: 'cases', entity: 'Distinct case', status: 'hinted', period: '2025 reporting interval', hint: { text: 'Inspect case and event listings together. Locate the approved serious skin reaction term set and test join cardinality before counting distinct cases.', observed: ['The target sentence specifies unique cases'], inferred: ['A curated term set may be documented in Signal Tracker'], unknowns: ['Approved term-list version and effective date'] }, sourceIds: ['src-case', 'src-signal', 'src-dictionary'], artifacts: ['source_knowledge.md'], locator: 'PBRER · p. 121 · table 16-8' },
    { id: 'CLM-004', sectionId: 's16321', sectionNumber: '16.3.2.1', sectionTitle: 'Cardiovascular events', statement: 'The reporting period included 62 events of special interest.', reportedValue: '62', unit: 'events', entity: 'Event', status: 'hinted', period: '2025 reporting interval', hint: { text: 'Investigate event-level data and the report’s event-of-special-interest definition. Preserve event identity separately from case identity.', observed: ['Target text explicitly says events'], inferred: ['Signal tracker may reference the event definition'], unknowns: ['Whether multiple qualifying events per case are counted independently'] }, sourceIds: ['src-csmr', 'src-signal'], artifacts: ['source_knowledge.md'], locator: 'PBRER · p. 126 · paragraph 3' },
    { id: 'CLM-005', sectionId: 's16331', sectionNumber: '16.3.3.1', sectionTitle: 'Long-term exposure', statement: 'Cumulative exposure exceeded 12,400 patient-years.', reportedValue: '12,400', unit: 'patient-years', entity: 'Exposure', status: 'hinted', period: 'Cumulative through 31 Dec 2025', hint: { text: 'Review exposure summary preamble, population basis, cut-off date and patient-time calculation method. Reconcile worksheet totals with the methodology PDF.', observed: ['Target specifies patient-years and cumulative cut-off'], inferred: ['Exposure workbook likely contains derived totals'], unknowns: ['Whether exposure is observed or modelled and which cohorts are included'] }, sourceIds: ['src-exp', 'src-method'], artifacts: ['source_knowledge.md'], locator: 'PBRER · p. 133 · table 16-14' },
  ],
  stages: [
    { id: 'claims', number: '01', title: 'Claims & sources', subtitle: 'Understand the report. Map evidence.', status: 'review', progress: 100, agents: 3, subagents: 2, artifacts: 4 },
    { id: 'rules', number: '02', title: 'Rules & evidence', subtitle: 'Investigate. Code. Reproduce.', status: 'locked', progress: 0, agents: 0, subagents: 0, artifacts: 0 },
    { id: 'evaluation', number: '03', title: 'Independent evaluation', subtitle: 'Rerun. Verify. Reconcile.', status: 'locked', progress: 0, agents: 0, subagents: 0, artifacts: 0 },
  ],
  agents: [
    { id: 'agt-claims', name: 'Claims Orchestrator', role: 'Stage 1 · primary', stage: 'claims', status: 'done', currentTask: 'Claim register drafted · awaiting reviewer', elapsed: '02:48', children: 2 },
    { id: 'agt-source', name: 'Source Intelligence', role: 'Stage 1 · specialist', stage: 'claims', status: 'done', currentTask: 'Profiled 6 files · 19 worksheets', elapsed: '01:56', children: 0 },
    { id: 'agt-atom', name: 'Claim Atomizer', role: 'Stage 1 · specialist', stage: 'claims', status: 'done', currentTask: 'Created 5 atomic claims', elapsed: '00:52', children: 0 },
  ],
  activity: [
    { id: 'ev1', stage: 'claims', time: '09:42:08', title: 'Run initialized', detail: 'Target report and 6 source documents added to immutable input snapshot.', kind: 'system', status: 'done' },
    { id: 'ev2', stage: 'claims', time: '09:42:14', title: 'Claims Orchestrator started', detail: 'Fresh Stage 1 context · read access to all input documents.', kind: 'agent', agent: 'Claims Orchestrator', status: 'done' },
    { id: 'ev3', stage: 'claims', time: '09:42:25', title: 'Document structure extracted', detail: 'Full report scanned · 18 top-level sections · Section 16.3 found.', kind: 'tool', agent: 'Document tools', source: 'PBRER_Example_Product_v4.docx', status: 'done' },
    { id: 'ev4', stage: 'claims', time: '09:43:02', title: 'Source survey completed', detail: '6 source files · 19 worksheets · 57,442 rows profiled.', kind: 'tool', agent: 'Source Intelligence', source: '6 uploaded sources', status: 'done' },
    { id: 'ev5', stage: 'claims', time: '09:43:41', title: 'Knowledge artifacts written', detail: 'Schema profiles, relationship map and reviewer summary generated.', kind: 'artifact', artifact: 'source_knowledge.md', status: 'done' },
    { id: 'ev6', stage: 'claims', time: '09:44:12', title: 'Leaf claims atomized', detail: '5 quantitative claims · 1 derived relationship candidate · 2 ambiguities flagged.', kind: 'success', agent: 'Claim Atomizer', status: 'done' },
    { id: 'ev7', stage: 'claims', time: '09:44:56', title: 'Stage 1 ready for review', detail: 'Claim register validated · evidence hints attached · reviewer approval required.', kind: 'gate', status: 'warning' },
  ],
  artifacts: [
    { id: 'art1', name: 'source_knowledge.md', type: 'Source overview', stage: 'claims', size: '18 KB', version: 'v1', status: 'ready', updated: '09:44' },
    { id: 'art2', name: 'source_knowledge.json', type: 'Canonical source model', stage: 'claims', size: '42 KB', version: 'v1', status: 'ready', updated: '09:44' },
    { id: 'art3', name: 'knowledge_graph.json', type: 'Dataset relationships', stage: 'claims', size: '12 KB', version: 'v1', status: 'ready', updated: '09:44' },
    { id: 'art4', name: 'claims_register.v001.json', type: 'Claim registry', stage: 'claims', size: '9 KB', version: 'v1', status: 'review', updated: '09:45' },
  ],
};
