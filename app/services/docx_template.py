from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table
from docx.oxml.ns import qn


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def norm(text: str) -> str:
    return clean(text).casefold().strip(" :–-\t")


def paragraph_text(p_element, doc) -> str:
    return clean(Paragraph(p_element, doc).text)


def is_section_heading(text: str, needle: str) -> bool:
    return norm(text) == norm(needle)


def classify_field(label: str) -> tuple[str, str, str]:
    n = norm(label)
    if "post-marketing data" in n or "number of initial cases" in n:
        return "topic_total", "count_ratio", "Topic count divided by overall count in the reporting interval"
    if "search criteria" in n:
        return "search_criteria", "criteria", "MedDRA PT/HLT/SMQ or other search definition used to select the topic"
    if "spontaneous" in n:
        return "source_spontaneous", "count", "Number of topic cases from spontaneous reporting sources"
    if "report from other studies" in n or "other studies" in n or "solicited" in n:
        return "source_other_studies", "count", "Number of topic cases from other post-marketing study/solicited sources"
    if "evaluation" in n:
        return "evaluation", "narrative", "Evaluation narrative, including seriousness/fatality and interpretation"
    if "conclusion" in n:
        return "conclusion", "narrative", "Conclusion and proposed safety/regulatory position"
    if "data source" in n:
        return "data_source", "source_note", "Source-of-data statement and references to internal tables"
    return "custom_" + re.sub(r"[^a-z0-9]+", "_", n).strip("_")[:40], "custom", "Client-specific table field"


def _physical_cell_paragraphs(cell) -> list[str]:
    return [clean(p.text) for p in cell.paragraphs]


def _find_value_paragraph(table, row_index: int, cell_index: int, preferred: int = 0) -> tuple[int, int, int] | None:
    try:
        cell = table.rows[row_index].cells[cell_index]
        if len(cell.paragraphs) > preferred:
            return row_index, cell_index, preferred
    except Exception:
        pass
    return None


def _extract_table(table: Table, table_index: int, source_file: str, topic_heading: str) -> dict[str, Any] | None:
    rows_out=[]
    # Work with logical python-docx cells/paragraphs, which exposes the text in vertical merges.
    for ri, row in enumerate(table.rows):
        cells=[]
        # Row may repeat merged grid cells; de-duplicate by underlying XML cell identity.
        seen=set()
        for ci, cell in enumerate(row.cells):
            key=id(cell._tc)
            if key in seen:
                continue
            seen.add(key)
            paras=_physical_cell_paragraphs(cell)
            cells.append({"cell_index": ci, "paragraphs": paras, "text": clean(" ".join(p for p in paras if p))})
        rows_out.append(cells)

    all_text=" ".join(c["text"] for r in rows_out for c in r)
    low_all=all_text.casefold()
    has_summary=any(k in low_all for k in ["post-marketing data", "search criteria", "spontaneous", "report from other studies"])
    has_narrative_continuation=("evaluation" in low_all and ("conclusion" in low_all or "data source" in low_all))
    if not (has_summary or has_narrative_continuation):
        return None

    fields=[]
    # The first row commonly spans the full table and contains topic/total ratio.
    first_text = rows_out[0][0]["text"] if rows_out and rows_out[0] else ""
    if first_text and ("post-marketing data" in norm(first_text) or "number of initial cases" in norm(first_text)):
        key, ftype, hint = classify_field(first_text)
        ratio = re.search(r"(?:\b|:)(\d[\d, ]*)\s*/\s*(\d[\d, ]*)\s*$", first_text)
        prefix = first_text[:ratio.start()] if ratio else first_text
        fields.append({"key":key,"label":"Post-marketing data – topic / total initial cases","type":ftype,"required":True,
                       "source_intent":hint,"example":first_text,"value_prefix":prefix,"example_ratio":ratio.groups() if ratio else None,
                       "locator":{"row":0,"cell":0,"paragraph":0}})

    # Parse labels and values. The Sifrol document uses a vertically merged value cell
    # for spontaneous / other studies / evaluation in one of its topic tables.
    for ri, row in enumerate(table.rows):
        if not row.cells:
            continue
        left = row.cells[0]
        for pi, p in enumerate(left.paragraphs):
            label=clean(p.text)
            if not label:
                continue
            key, ftype, hint = classify_field(label)
            if key.startswith("custom_"):
                continue
            if key == "topic_total":
                continue
            # Locate the matching value paragraph in the right cell. For vertical merges,
            # the logical merged cell includes paragraphs originating in the following row.
            value_cell = row.cells[1] if len(row.cells)>1 else None
            value_pi = 0
            value = ""
            if value_cell is not None:
                if key == "source_other_studies" and len(value_cell.paragraphs)>1:
                    value_pi=1
                elif key == "evaluation" and len(value_cell.paragraphs)>2:
                    value_pi=3 if len(value_cell.paragraphs)>3 else len(value_cell.paragraphs)-1
                else:
                    value_pi=min(pi, len(value_cell.paragraphs)-1) if value_cell.paragraphs else 0
                if value_cell.paragraphs:
                    value=clean(value_cell.paragraphs[value_pi].text)
            # Source labels may occur in split paragraphs. Keep one field per key.
            if any(f["key"]==key for f in fields):
                continue
            field_label="Data source" if key=="data_source" else (label.split(":",1)[0] if key=="data_source" else label.rstrip(":"))
            fields.append({"key":key,"label":field_label,"type":ftype,"required":key in {"search_criteria","source_spontaneous","evaluation","conclusion"},
                           "source_intent":hint,"example":value,"locator":{"row":ri,"cell":1,"paragraph":value_pi},
                           "label_locator":{"row":ri,"cell":0,"paragraph":pi}})

    # Preserve unknown, client-specific labels as editable schema fields.
    known_labels={"search criteria","spontaneous","report from other studies","evaluation","evaluation (cont’d)","conclusion","data source"}
    for ri,row in enumerate(table.rows):
        if not row.cells: continue
        label=clean(row.cells[0].text)
        if not label: continue
        n=norm(label)
        if n in known_labels or any(token in n for token in ["post-marketing data","search criteria","spontaneous","other studies","evaluation","conclusion","data source"]): continue
        # Avoid storing the sample's long narrative as a generic data point.
        if len(label)<90 and not any(f["label"].casefold()==label.casefold() for f in fields):
            key,ftype,hint=classify_field(label)
            fields.append({"key":key,"label":label,"type":ftype,"required":False,"source_intent":hint,
                           "example":"","locator":{"row":ri,"cell":1,"paragraph":0}})

    # MedDRA criterion type and searchable terms are kept separately for mapping.
    search_text=""
    for f in fields:
        if f["key"]=="search_criteria":
            search_text=f.get("example","")
    criterion_type="manual"
    terms=[]
    m=re.search(r"\b(MedDRA\s+(?:PTs?|HLTs?|SMQs?))\s*(.*)$",search_text,re.I)
    if m:
        criterion_type=m.group(1)
        tail=m.group(2).strip()
        if "PT" in criterion_type.upper():
            terms=[clean(x).strip("'‘’\";.") for x in re.split(r";|\band\b",tail,flags=re.I) if clean(x).strip("'‘’\";.")]
        else:
            # HLT/SMQ definitions may need a MedDRA hierarchy/query expansion and are not
            # treated as exact PT matching by the deterministic mapper.
            terms=[tail] if tail else []

    style = table.style.name if table.style else ""
    col_widths=[]
    try:
        col_widths=[int(c.get(qn('w:w'))) for c in table._tbl.tblGrid.gridCol_lst]
    except Exception:
        pass
    row_layout=[]
    for ri,row in enumerate(table.rows):
        cells=[];seen=set()
        for ci,cell in enumerate(row.cells):
            xml_id=id(cell._tc)
            if xml_id in seen: continue
            seen.add(xml_id)
            tc_pr=cell._tc.tcPr
            span=1;vmerge=None
            try:
                if tc_pr is not None and tc_pr.gridSpan is not None: span=int(tc_pr.gridSpan.val)
                if tc_pr is not None and tc_pr.vMerge is not None: vmerge=tc_pr.vMerge.val or "continue"
            except Exception: pass
            cell_text=clean(" ".join(p.text for p in cell.paragraphs))
            cells.append({"cell_index":ci,"grid_span":span,"vertical_merge":vmerge,
                          "paragraph_count":len(cell.paragraphs),"text_example":cell_text[:220]})
        row_layout.append({"row_index":ri,"cells":cells})
    try: autofit=bool(table.autofit)
    except Exception: autofit=None
    return {
        "table_id":f"{Path(source_file).stem}-table-{table_index}","source_file":source_file,"docx_table_index":table_index,
        "topic_heading":topic_heading or f"Section 16.3 table {table_index}","table_style":style,"column_count":len(table.columns),
        "column_widths_dxa":col_widths,"row_count":len(table.rows),"autofit":autofit,"row_layout":row_layout,"fields":fields,
        "criterion_type":criterion_type,"criterion_terms":terms,"search_criteria_example":search_text,
        "requires_initial_only":bool(re.search(r"\binitial\s+cases?\b", first_text, re.I)),
        "requires_reporting_interval":bool(re.search(r"\breporting interval\b", first_text, re.I)),
        "structure_notes":["Original row order and paragraph/cell locators are retained for styled DOCX rendering.",
                           "A table may use merged cells; logical fields are extracted from paragraph-level content."],
    }


def extract_section_tables(path: Path) -> dict[str, Any]:
    doc=Document(path)
    in_section=False
    seen_section=False
    current_heading=""
    table_index=0
    tables=[]
    section_intro=[]
    for child in doc.element.body.iterchildren():
        if child.tag==qn("w:p"):
            txt=paragraph_text(child,doc)
            n=norm(txt)
            style=Paragraph(child,doc).style.name if Paragraph(child,doc).style else ""
            heading_text=re.sub(r"^16\.3\s+","",n)
            if heading_text=="evaluation of risks and new information" and ("2nd level" in style.lower() or "heading 1" in style.lower()):
                in_section=True; seen_section=True; current_heading=txt; continue
            stop_text=re.sub(r"^16\.4\s+","",n)
            if in_section and stop_text in {"important identified risks","important potential risks","characterisation of risks","characterization of risks"} and ("3rd level" in style.lower() or "heading" in style.lower()):
                in_section=False
            if in_section and txt:
                # The document's topic heading is a numbered/outline paragraph followed by table.
                if any(k in style.lower() for k in ["3rd level","4th level","heading 3","heading 2"]):
                    current_heading=txt
                if "event level" in n and txt not in section_intro:
                    section_intro.append(txt)
        elif child.tag==qn("w:tbl"):
            if in_section:
                table_obj=next((t for t in doc.tables if t._tbl is child),None)
                if table_obj is not None:
                    parsed=_extract_table(table_obj,table_index,path.name,current_heading)
                    if parsed:
                        parsed["section"]="16.3"
                        tables.append(parsed)
            table_index+=1
    if not seen_section:
        # Fallback for docs whose headings carry numbering but use a different label.
        # Only structurally strong candidates are included, with an explicit warning.
        for idx,table_obj in enumerate(doc.tables):
            parsed=_extract_table(table_obj,idx,path.name,"")
            if parsed:
                parsed["section"]="inferred-16.3"
                tables.append(parsed)
    return {
        "filename":path.name,"paragraph_count":len(doc.paragraphs),"table_count":len(doc.tables),
        "section_16_3_found":seen_section,"section_intro":section_intro,"tables":tables,
        "styles":sorted({t["table_style"] for t in tables if t.get("table_style")}),
        "warning":None if seen_section else "Section 16.3 heading was not confidently found; structural table fallback was used.",
    }


def consolidate_template(doc_profiles: list[dict[str, Any]], template_name: str, tenant_id: str) -> tuple[dict[str, Any], str]:
    all_tables=[]
    for profile in doc_profiles:
        tables=profile["tables"]
        previous_topic=None
        for table in tables:
            has_header=any(f.get("key")=="topic_total" for f in table.get("fields",[]))
            if not has_header and previous_topic:
                table["continuation_of_previous"]=True
                table["parent_topic_table_id"]=previous_topic["table_id"]
            else:
                table["continuation_of_previous"]=False
            if has_header:
                previous_topic=table
            all_tables.append(table)
    fields_by_key: dict[str,list[dict[str,Any]]]={}
    for table in all_tables:
        for field in table["fields"]:
            fields_by_key.setdefault(field["key"],[]).append(field)
    common_fields=[]
    for key,values in fields_by_key.items():
        first=values[0]
        common_fields.append({"key":key,"label":first["label"],"type":first["type"],
                              "occurrences":len(values),"documents":sorted({t["source_file"] for t in all_tables}),
                              "required":any(v.get("required") for v in values),"source_intent":first["source_intent"]})
    schema={
        "template_version":"1.0","template_name":template_name,"tenant_id":tenant_id,"target_section":"16.3",
        "focus":"table-centric","base_document":doc_profiles[0]["filename"] if doc_profiles else None,
        "document_profiles":doc_profiles,"tables":all_tables,"common_fields":common_fields,
        "reporting_interval_required":any(t.get("requires_reporting_interval") for t in all_tables),
        "review_policy":{"status":"draft","require_approval_before_generator":True,
                         "never_infer_unseen_numbers":True,"preserve_original_docx_as_read_only":True,
                         "require_explicit_count_unit":True,"preserve_client_table_variations":True},
    }
    md=build_master_md(schema)
    return schema,md


def build_master_md(schema: dict[str,Any]) -> str:
    fields=schema.get("common_fields",[])
    names={f["key"] for f in fields}
    lines=[f"# {schema.get('template_name','Section 16.3')} — Master Template Notes", "",
           "> Scope: Section 16.3 only. These notes describe structural patterns observed in the uploaded DOCX references; they are not a regulatory standard or a substitute for reviewer approval.", "",
           "## Observed table architecture", "",
           "- The primary unit is a topic-specific table/block under Section 16.3.",
           "- The recurring top row states the number of initial cases in the reporting interval as a topic/total ratio.",
           "- A search-criteria row records the retrieval definition. Observed criterion families include MedDRA PTs, HLTs and SMQs; these are not interchangeable.",
           "- Source breakdown rows commonly distinguish `Spontaneous` from `Report from other studies` (wording and presence vary).",
           "- Narrative rows commonly include `Evaluation` and `Conclusion`; some tables continue an evaluation in a separate continuation table.",
           "- A data-source row records internal table names, report references or other source descriptions.", "",
           "## Table layout patterns", "",
           f"- {len(schema.get('tables',[]))} table blocks were detected across {len(schema.get('document_profiles',[]))} DOCX reference(s).",
           f"- Observed Word table styles: {', '.join(sorted({t.get('table_style','(none)') for t in schema.get('tables',[])})) or 'not recorded'}.",
           "- Each table schema stores row/cell positions, paragraph locations, column widths, merged-cell hints and continuation relationships so the renderer can work against the original DOCX rather than inventing a new layout.", "",
           "## Common fields observed", ""]
    for f in fields:
        lines.append(f"- `{f['key']}` — **{f['label']}** ({f['type']}); observed in {f['occurrences']} table(s). {f['source_intent']}")
    lines += ["", "## Data interpretation guardrails", "",
              "- Retain the client's exact search-criteria type and wording. A PT list can be matched exactly only when the source event column is at PT level and the approved rule says exact match.",
              "- HLT and SMQ criteria require the correct MedDRA version and a reviewed hierarchy/query expansion. Do not treat the text label as an exact PT list.",
              "- Preserve the count unit exactly as specified by the report (case, event, patient, subject, or record). Do not silently deduplicate case IDs or count event rows without approval.",
              "- Keep reporting interval, DLP, product scope, primary-source inclusion/exclusion, initial/follow-up status and denominator definition explicit.",
              "- A PBRER reference observed in the uploaded sample states that Section 16.3 data are presented at event level and that one ICSR may contain multiple records for a topic. Confirm whether that principle applies to each client's table before choosing a count method.",
              "- Seriousness/fatality statements and evaluation/conclusion narratives are not derivable from column names alone. Map them to explicit source columns or require reviewer-authored text.",
              "- The template stores examples as reference material only. Previous-period numbers and narratives must not be silently carried into a new reporting interval.",
              "- Every mapped value must retain source workbook, worksheet, column, row/cell evidence and the rule used.", "",
              "## Observed table variations", ""]
    for table in schema.get("tables",[]):
        labels="; ".join(f["label"] for f in table["fields"])
        suffix=" (continuation of preceding topic table)" if table.get("continuation_of_previous") else ""
        lines.append(f"- **{table['topic_heading']}** — {table['source_file']}, DOCX table index {table['docx_table_index']}; style `{table.get('table_style') or 'unspecified'}`; fields: {labels}.{suffix}")
    lines += ["", "## Fields requiring client configuration", "",
              "- Reporting-period dates and whether the start/end dates are inclusive.",
              "- Count mode and unit (for example, initial cases versus event records).",
              "- Source-category mapping and rules for excluding clinical-trial or non-applicable records.",
              "- Exact MedDRA version, search term hierarchy and any SMQ scope (narrow/broad).",
              "- Serious/fatal counting level and evaluation/conclusion text for the new interval.",
              "- Data-source citation format expected by the client.", "",
              "## Template inventory", "",
              f"- Reference DOCX files: {len(schema.get('document_profiles',[]))}",
              f"- Candidate Section 16.3 tables: {len(schema.get('tables',[]))}",
              f"- Distinct field keys: {len(fields)}", "",
              "## Approval status", "",
              "This template is a draft until a user reviews the extracted table structures, labels, field types, examples and master notes, then explicitly approves it.", ""]
    return "\n".join(lines)
