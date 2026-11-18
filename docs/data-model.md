# Template and mapping data model

## Stable Section 16.3 field keys

| Key | Meaning | Typical type |
|---|---|---|
| `topic_total` | Topic count / overall reporting-period total | `count_ratio` |
| `search_criteria` | Exact MedDRA or other topic retrieval definition | `criteria` |
| `source_spontaneous` | Topic count from spontaneous sources | `count` |
| `source_other_studies` | Topic count from other post-marketing studies/solicited sources | `count` |
| `evaluation` | Interpretation, seriousness/fatality summary and contextual assessment | `narrative` |
| `conclusion` | Safety concern conclusion and action position | `narrative` |
| `data_source` | Internal source/table/reference statement | `source_note` |
| `custom_*` | Client-specific table field | `custom` |

Additional field entries are preserved when a concise unknown row label is found. Some tables omit source rows or use continuation tables. The schema stores original Word table indexes, row/cell/paragraph locators, table style/dimensions and merged-cell layout hints.

## Canonical workbook roles

| Role | Description | Used for |
|---|---|---|
| `case_id` | Case/ICSR identifier; not automatically a patient ID | Numerator and default denominator |
| `event_term` | Event PT or other mapped event label | Exact topic match for explicit PT lists |
| `source_category` | Spontaneous / other-study source | Source count breakdown |
| `initial_flag` | Initial vs follow-up status | Initial-case-only templates |
| `approval_date` | Reporting-interval date field | Period filtering |
| `seriousness` | Seriousness indicator | Reviewer context/extension point |
| `fatal_outcome` | Fatal outcome indicator | Reviewer context/extension point |
| `denominator_case_id` | Optional identifier from separate denominator data | Separate cohort denominator |
| `denominator_initial_flag` | Optional initial/follow-up flag on denominator source | Separate denominator filtering |
| `denominator_approval_date` | Optional reporting date on denominator source | Separate denominator interval filtering |

## Trust boundaries

Column-role hints are hypotheses. A reviewer must confirm all required mapping roles, count unit, time-window definition, event hierarchy and denominator scope. A `case_id` string is not a patient identity unless the source data dictionary explicitly defines it that way. The code never converts HLT/SMQ labels into PT lists without a proper terminology service and reviewed dictionary version.
