from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _set_paragraph(paragraph, text: str):
    runs=paragraph.runs
    if runs:
        runs[0].text=str(text)
        for run in runs[1:]: run._element.getparent().remove(run._element)
    else:
        paragraph.add_run(str(text))


def set_table_field(table, locator: dict, value: str, doc=None) -> bool:
    try:
        target_table = table
        if doc is not None and locator.get("docx_table_index") is not None:
            t_idx = int(locator["docx_table_index"])
            if 0 <= t_idx < len(doc.tables):
                target_table = doc.tables[t_idx]
        row=target_table.rows[int(locator["row"])]
        cell=row.cells[int(locator.get("cell",0))]
        pi=int(locator.get("paragraph",0))
        if pi>=len(cell.paragraphs): return False
        _set_paragraph(cell.paragraphs[pi],value)
        return True
    except (IndexError,KeyError,ValueError,TypeError):
        return False


def _field(table_schema: dict, key: str) -> dict | None:
    return next((f for f in table_schema.get("fields",[]) if f.get("key")==key),None)


def _breakdown(metrics: dict) -> dict[str,int] | None:
    if not metrics.get("source_breakdown_complete"):
        return None
    result={"Spontaneous":0,"Report from other studies":0}
    for item in metrics.get("source_breakdown",[]):
        group=item.get("classification")
        if group in result: result[group]+=int(item.get("count",0))
    # Do not publish a source split that cannot reconcile to the topic total.
    if sum(result.values()) != int(metrics.get("numerator",-1)):
        return None
    return result


def render_report(base_docx: Path, template_schema: dict, topic_metrics: list[dict], output_path: Path,
                  narratives: dict[str,dict[str,str]] | None = None, source_files: list[str] | None = None) -> dict[str,Any]:
    """Create a copy of the client's DOCX and update only Section 16.3 table cells.

    Existing document and source uploads are never edited. Table paragraph/run styling is
    retained by replacing text in existing paragraphs rather than reconstructing the document.
    """
    narratives=narratives or {}; source_files=source_files or []
    doc=Document(base_docx)
    base_name=template_schema.get("base_document")
    schemas=[t for t in template_schema.get("base_tables",template_schema.get("tables",[])) if t.get("source_file")==base_name]
    by_id={m.get("table_id"):m for m in topic_metrics}
    updated=[]; warnings=[]
    for ts in schemas:
        idx=int(ts["docx_table_index"])
        if idx>=len(doc.tables):
            warnings.append(f"Template table index {idx} not found in base DOCX")
            continue
        table=doc.tables[idx]
        metric=by_id.get(ts["table_id"],{})
        override=narratives.get(ts["table_id"],{})
        if metric.get("status")=="calculated_candidate":
            f=_field(ts,"topic_total")
            if f and f.get("locator"):
                prefix=f.get("value_prefix") or "Post-marketing data – number of initial cases in the reporting interval (per topic/total): "
                if not set_table_field(table,f["locator"],f"{prefix}{metric['numerator']}/{metric['denominator']}",doc=doc):
                    warnings.append(f"Could not place topic count in {ts['topic_heading']}")
            breakdown=_breakdown(metric)
            for key,label in [("source_spontaneous","Spontaneous"),("source_other_studies","Report from other studies")]:
                field=_field(ts,key)
                if field and field.get("locator"):
                    if breakdown is None:
                        value_text=f"[REVIEW REQUIRED: map and reconcile {label.lower()} source categories]"
                        warnings.append(f"{ts['topic_heading']}: source split was not complete/reconciled; {label} count left for review")
                    else:
                        value=breakdown[label]
                        suffix="case" if value==1 else "cases"
                        value_text=f"{value} {suffix}"
                    if not set_table_field(table,field["locator"],value_text,doc=doc):
                        warnings.append(f"Could not place {label} count in {ts['topic_heading']}")
        else:
            warnings.append(f"{ts['topic_heading']}: {metric.get('reason','No calculated candidate available')}")
            # Never let previous-period numeric values survive when a new candidate is unavailable.
            for key,placeholder in [
                ("topic_total","[REVIEW REQUIRED: no approved topic/total count calculated]"),
                ("source_spontaneous","[REVIEW REQUIRED: spontaneous source count not calculated]"),
                ("source_other_studies","[REVIEW REQUIRED: other-study source count not calculated]"),
            ]:
                field=_field(ts,key)
                if field and field.get("locator"):
                    if not set_table_field(table,field["locator"],placeholder,doc=doc):
                        warnings.append(f"Could not clear prior-period {key} for {ts['topic_heading']}")
        for key in ("evaluation","conclusion","data_source"):
            field=_field(ts,key)
            if field and field.get("locator"):
                text=(override.get(key) or "").strip()
                if key=="data_source" and not text:
                    text="Data source: " + "; ".join(source_files) if source_files else "Data source: [review required]"
                elif key in {"evaluation","conclusion"} and not text:
                    text=f"[REVIEW REQUIRED: provide updated {key} text for this reporting interval]"
                # Data source fields may be in a single merged cell: preserve existing prefix if present.
                if key=="data_source" and not text.casefold().startswith("data source"):
                    text="Data source: "+text
                if not set_table_field(table,field["locator"],text,doc=doc):
                    warnings.append(f"Could not update {key} for {ts['topic_heading']}")
        updated.append({"table_id":ts["table_id"],"topic_heading":ts["topic_heading"],"docx_table_index":idx,
                        "metric_status":metric.get("status","not_mapped")})
    output_path.parent.mkdir(parents=True,exist_ok=True)
    doc.save(output_path)
    return {"output_path":str(output_path),"updated_tables":updated,"warnings":warnings,
            "source_docx_unchanged":True,"only_section_16_3_tables_targeted":True}
