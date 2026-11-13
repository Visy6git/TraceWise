# Section 16.3 Reproduction Blueprint contract

## What the blueprint represents

The blueprint is a versioned, machine-readable and human-reviewable specification of how the complete Section 16.3 is constructed. It joins five models:

1. **Document model:** headings, paragraphs, tables, order, row/column definitions, exact target locators and presentation constraints.
2. **Claim model:** claim purpose, exact assertion, entity/denominator/unit semantics, reporting period, population, subgroup, numerator/denominator, dependencies and target binding.
3. **Source model:** logical datasets and fields, physical mapping evidence, expected grain, keys, join contracts, version history and known limitations.
4. **Retrieval/transformation model:** reporting-period semantics, as-of date, latest-record precedence, filters, deduplication, joins, calculations, rounding and derivations.
5. **Rendering model:** narrative templates, claim substitutions, tables, row order, null/zero behaviour, precision, footnotes and cross references.

A prose summary is not enough. The blueprint must be executable and must include tests.

## Core files in a blueprint version

```text
blueprint.json
section_model.json
claim_catalog.json
source_contracts.json
retrieval_policies.json
transformation_graph.json
narrative_templates.json
render_spec.json
schema_drift_policy.json
reproduce_section.py
tests/test_reproduction_contract.py
requirements.lock
README.md
blueprint_validation.json
blueprint_manifest.json
```

Every file is immutable inside a version folder. The manifest records relative path, media type, byte size and SHA-256. The DB registry points to the immutable version. Human approval is attached to the exact manifest hash; an updated file means a new version and new approval.

## Claim-to-output traceability

For each claim, the blueprint must explain and record:

- claim ID and Stage 1 version;
- section, paragraph/table/cell locator and original statement;
- purpose and rationale epistemic state (`observed`, `inferred`, `unknown`);
- entity (case, event, patient, subject, report, person-time, etc.) and unit;
- population/subgroup and period boundaries;
- logical source dataset(s) and fields;
- Stage 2 rule/evidence/provenance artifact references;
- explicit filter definitions and epistemic status;
- joins with key, expected cardinality and duplicate-expansion checks;
- record version/latest selection and tie-breaking policy;
- deduplication and aggregation semantics;
- numerator and denominator logic, if any;
- derivation dependencies and rounding;
- render binding and formatting;
- unresolved questions and reviewer decisions.

No prior target report number is a generation input. Old report values are useful while learning and reconciling Stage 2; they must not be copied into the annual runtime or used as an optimization target.

## Source contract: logical identity beats physical filename

A source contract describes a logical dataset with multiple possible physical locations. Physical filenames and worksheet names are useful candidates but not the contract's identity. Stable identity comes from a set of observed logical fields, field semantics, data types, expected grain, candidate keys and relationship tests.

Example (illustrative only):

```json
{
  "dataset_id": "individual_case_safety_reports",
  "purpose": "Source of eligible individual safety reports",
  "fields": [
    {
      "logical_name": "case_id",
      "meaning": "Stable case identifier at the case grain",
      "physical_name": "Case Number",
      "aliases": ["Case ID"],
      "data_type": "string",
      "required": true,
      "mapping_state": "observed",
      "evidence_refs": ["stage_2_rules/claims/CLM-001/provenance.json"]
    },
    {
      "logical_name": "receipt_date",
      "meaning": "Approved source-system date used for reporting-period eligibility",
      "physical_name": "Initial Receipt Date",
      "aliases": [],
      "data_type": "date",
      "required": true,
      "mapping_state": "observed",
      "evidence_refs": ["stage_2_rules/claims/CLM-001/rule_spec.json"]
    }
  ],
  "entity_key": ["case_id"],
  "expected_grain": "one row per source case version",
  "source_version_policy": {
    "version_field": "case_version",
    "selection_rule": "Must be explicitly established from Stage 2 evidence",
    "tie_breaker": "Must be explicitly established from Stage 2 evidence"
  }
}
```

This JSON is only an example of the contract shape, not a prescription for PV filters or date semantics. Stage 3 must derive actual field names and semantics from the specific approved artifacts.

## “Latest records” must be explicit

Do not use a generic `MAX(updated_at)` heuristic. Model separately:

- record version number or version sequence;
- effective date;
- initial receipt date;
- follow-up receipt date;
- last-modified/extract timestamp;
- source-system “current record” flag, if present;
- as-of cut-off;
- tie-break rule;
- whether superseded versions remain in the extract;
- whether the input is a point-in-time extract or a mutable current-state export.

If the prior Stage 1/2 artifacts do not establish which date/field selects the record, that is a blocker or `unknown` requiring human investigation. It is not an invitation to guess.

## Schema drift classification

- **Safe / informational:** extra unused columns; file rename where all required logical fields, types, keys, sheet grain and relationships are proven equivalent.
- **Review required:** physical column rename that maps to an existing logical field; sheet rename; header offset change; changed types/date formats; changed row count/cardinality; multiple candidate sheets; optional field absent; new source file.
- **Blocking:** required field unavailable; entity key changed; case/event/patient grain changed; join semantics/cardinality changed; source version or effective-date semantics changed; filter/population definition changed; a new claim or output block appears; latest-record precedence unknown.

A mapping candidate from the harness is a proposal. It becomes usable only after evidence tests and reviewer approval, generally through a new blueprint version. It cannot silently patch an approved version.

## Executable contract

The deterministic entrypoint interface is:

```text
python reproduce_section.py \
  --blueprint blueprint.json \
  --generation-context generation_context.json \
  --source-dir <read-only source snapshot> \
  --output-dir <generation workspace>
```

Required output files:

- `section_16_3.docx` — complete Section 16.3 in the approved structure;
- `result.json` — claim-level and section-level computed values and status;
- `lineage.json` — dataset/sheet/field/filter/join/aggregation references and source snapshot hash (avoid raw personal rows);
- `exceptions.json` — missing/ambiguous mappings, data-quality exceptions, unavailable source coverage and warnings.

The entrypoint must be deterministic for the same source snapshot, blueprint, parameters and pinned environment. Model calls are not part of routine calculation. A later model may assist with exceptions, but it cannot autonomously alter the computation method in the current run.
