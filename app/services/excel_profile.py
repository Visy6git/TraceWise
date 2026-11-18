from __future__ import annotations
from pathlib import Path
from typing import Any
import re
from collections import Counter
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import pandas as pd

KNOWN_HEADERS={
    "case_id":["case number","case #","case id","icsr number","safety report id"],
    "event_term":["event pt","event pt (primary path)","preferred term","meddra pt","event preferred term","reaction pt"],
    "source_category":["derived-primary-source","primary source","primary source category","reporting source","source category","source"],
    "initial_flag":["derived-initial-follow-up-flag","initial/follow-up flag","case type","report type","initial follow-up"],
    "approval_date":["derived-initial-approval-date-(yyyymmdd)","initial approval date","approval date","case receipt date","receipt date","date of receipt"],
    "seriousness":["seriousness","serious case","case seriousness","serious/non-serious"],
    "fatal_outcome":["fatal","death","fatal outcome","fatality"],
}


def norm(x: Any) -> str:
    return re.sub(r"[^a-z0-9]+"," ",str(x or "").casefold()).strip()


def role_for_header(header: str) -> str | None:
    h=norm(header)
    for role,aliases in KNOWN_HEADERS.items():
        if any(norm(a)==h or norm(a) in h or h in norm(a) for a in aliases):
            return role
    return None


def infer_type(values: list[Any]) -> str:
    vals=[v for v in values if v is not None and str(v).strip()]
    if not vals:return "empty"
    # YYYYMMDD exports are frequently stored as numeric cells; infer dates by value shape.
    compact_dates=[]
    for value in vals[:200]:
        text=str(value).strip()
        if re.fullmatch(r"\d{8}(?:\.0)?",text):
            try:
                from datetime import datetime
                datetime.strptime(text.split('.')[0],"%Y%m%d")
                compact_dates.append(True)
            except ValueError: compact_dates.append(False)
        else: compact_dates.append(False)
    if compact_dates and sum(compact_dates)/len(compact_dates)>.8:return "date_yyyymmdd"
    dates=sum(1 for v in vals if hasattr(v,"year") and hasattr(v,"month"))
    numeric=0; integers=0
    for v in vals:
        try:
            float(str(v).replace(",","")); numeric+=1
            if float(str(v).replace(",","" )).is_integer(): integers+=1
        except Exception: pass
    if dates/len(vals)>.6:return "date"
    if numeric/len(vals)>.8:return "integer" if integers==numeric else "numeric"
    uniq={str(v).strip() for v in vals}
    if len(uniq)<=max(30,int(len(vals)*.2)):return "categorical"
    return "text"


def find_header(ws, max_scan=40):
    best=None
    for row_no,row in enumerate(ws.iter_rows(min_row=1,max_row=min(max_scan,ws.max_row or max_scan),values_only=True),1):
        vals=[str(v).strip() if v is not None else "" for v in row]
        nonempty=[v for v in vals if v]
        if len(nonempty)<2: continue
        roles=sum(role_for_header(v) is not None for v in nonempty)
        score=roles*10+len(nonempty)
        if best is None or score>best[0]: best=(score,row_no,vals)
        if roles>=2:return row_no,vals
    if best and len([v for v in best[2] if v])>=2:return best[1],best[2]
    return None,[]


def _profile_dataframe_sheet(sheet_name: str, raw: pd.DataFrame, header_row: int, sample_limit: int) -> dict[str, Any]:
    headers=[str(v).strip() if v is not None and str(v).strip() else f"Unnamed column {i+1}" for i,v in enumerate(raw.iloc[header_row-1].tolist())]
    data=raw.iloc[header_row:].copy()
    data.columns=headers
    columns=[]; sample_rows=[]
    for _,row in data.head(sample_limit).iterrows():
        sample_rows.append({c:(str(row[c])[:80] if pd.notna(row[c]) else "") for c in headers})
    for i,header in enumerate(headers):
        values=data.iloc[:,i].tolist()
        nonempty=[v for v in values if pd.notna(v) and str(v).strip()]
        columns.append({"column":header,"excel_column":get_column_letter(i+1),"index":i,
            "inferred_type":infer_type(nonempty[:500]),"non_empty_count":len(nonempty),
            "unique_estimate":len({str(v) for v in nonempty[:10000]}),"semantic_role":role_for_header(header),
            "sample_values":[str(v)[:80] for v in nonempty[:3]]})
    return {"sheet":sheet_name,"header_row":header_row,"row_count":int(len(data)),"columns":columns,
            "sample_rows":sample_rows,"max_column":len(headers)}


def profile_xlsx(path: Path, sample_limit: int=8) -> dict[str,Any]:
    """Profile XLSX and legacy XLS workbooks; values are sampled locally only."""
    suffix=path.suffix.lower()
    if suffix==".xls":
        book=pd.ExcelFile(path,engine="xlrd")
        sheets=[]
        for name in book.sheet_names:
            raw=pd.read_excel(path,sheet_name=name,header=None,dtype=object,engine="xlrd",nrows=40)
            header_idx=None; best_score=-1
            for i,row in raw.iterrows():
                vals=[str(v).strip() if pd.notna(v) else "" for v in row.tolist()]
                roles=sum(role_for_header(v) is not None for v in vals if v)
                nonempty=sum(bool(v) for v in vals)
                score=roles*10+nonempty
                if score>best_score and nonempty>=2: best_score=score; header_idx=int(i)
                if roles>=2: header_idx=int(i); break
            if header_idx is None:
                sheets.append({"sheet":name,"header_row":None,"row_count":0,"columns":[],"warning":"No clear header row found in first 40 rows."})
                continue
            full=pd.read_excel(path,sheet_name=name,header=header_idx,dtype=object,engine="xlrd")
            # Rebuild a raw-like dataframe so XLS and XLSX share one Markdown schema.
            combined=pd.concat([pd.DataFrame([full.columns.tolist()],columns=range(len(full.columns))),full.reset_index(drop=True)],ignore_index=True)
            sheet=_profile_dataframe_sheet(name,combined,1,sample_limit)
            sheet["header_row"]=header_idx+1
            # Adjust sample absolute row evidence to workbook row numbers.
            for row in sheet["sample_rows"]: row["__source_excel_row__"]="(sample; see source workbook)"
            sheets.append(sheet)
        return {"filename":path.name,"kind":"xls","sheets":sheets}
    if suffix!=".xlsx":
        raise ValueError("Only .xlsx and .xls Excel workbooks are supported")
    wb=load_workbook(path,read_only=True,data_only=True)
    sheets=[]
    try:
        for ws in wb.worksheets:
            header_row,headers=find_header(ws)
            if not header_row:
                sheets.append({"sheet":ws.title,"header_row":None,"row_count":0,"columns":[],"warning":"No clear header row found in first 40 rows."})
                continue
            headers=[(h or f"Unnamed column {i+1}") for i,h in enumerate(headers)]
            max_col=max((i+1 for i,h in enumerate(headers) if h),default=1)
            values_by_col=[[] for _ in range(max_col)]
            nonempty=[0]*max_col; row_count=0
            column_uniques=[set() for _ in range(max_col)]
            sample_rows=[]
            for row_no,row in enumerate(ws.iter_rows(min_row=header_row+1,max_col=max_col,values_only=True),header_row+1):
                if not row or not any(v is not None and str(v).strip() for v in row): continue
                row_count+=1
                if len(sample_rows)<sample_limit:
                    sample={headers[i]:str(row[i])[:80] if i<len(row) and row[i] is not None else "" for i in range(max_col)}
                    sample["__source_excel_row__"]=row_no
                    sample_rows.append(sample)
                for i in range(max_col):
                    val=row[i] if i<len(row) else None
                    if val is not None and str(val).strip():
                        nonempty[i]+=1
                        if len(values_by_col[i])<500: values_by_col[i].append(val)
                        if len(column_uniques[i])<10000: column_uniques[i].add(str(val))
            columns=[]
            for i,header in enumerate(headers):
                if not header.strip(): continue
                columns.append({"column":header,"excel_column":get_column_letter(i+1),"index":i,
                    "inferred_type":infer_type(values_by_col[i]),"non_empty_count":nonempty[i],
                    "unique_estimate":len(column_uniques[i]),"semantic_role":role_for_header(header),
                    "sample_values":[str(v)[:80] for v in values_by_col[i][:3]]})
            sheets.append({"sheet":ws.title,"header_row":header_row,"row_count":row_count,
                           "columns":columns,"sample_rows":sample_rows,"max_column":max_col})
    finally: wb.close()
    return {"filename":path.name,"kind":"xlsx","sheets":sheets}


def profile_to_markdown(profile: dict[str,Any]) -> str:
    lines=[f"# Source profile — {profile['filename']}","",f"- File type: `{profile['kind']}`",f"- Sheets: {len(profile['sheets'])}",""]
    for sheet in profile["sheets"]:
        lines += [f"## Sheet: {sheet['sheet']}","",f"- Detected header row: {sheet.get('header_row')}",f"- Data rows: {sheet.get('row_count',0)}",""]
        if not sheet.get("columns"):
            lines += [f"> {sheet.get('warning','No columns detected')}",""]; continue
        lines += ["| Excel column | Field name | Inferred type | Non-empty | Unique estimate | Semantic role |", "|---|---|---:|---:|---:|---|"]
        for c in sheet["columns"]:
            lines.append(f"| {c['excel_column']} | `{c['column']}` | {c['inferred_type']} | {c['non_empty_count']} | {c['unique_estimate']} | {c.get('semantic_role') or 'unclassified'} |")
        lines += ["","### Sample values (for local reviewer inspection only)",""]
        for c in sheet["columns"]:
            if c["sample_values"]: lines.append(f"- `{c['column']}`: {', '.join('`'+v+'`' for v in c['sample_values'])}")
        lines.append("")
    lines += ["## Interpretation notes","","- Column roles are heuristic candidates, not approved mappings.","- Samples are a small local preview; do not treat them as proof of population completeness.","- The original workbook is retained unchanged in the run input directory.",""]
    return "\n".join(lines)


def build_master_summary(profiles: list[dict[str,Any]]) -> str:
    lines=["# Generator Stage 1 — Master Source Summary","","This file inventories all uploaded workbooks and their detected sheet schemas. It does not calculate report values or approve column mappings.",""]
    for p in profiles:
        lines += [f"## {p['filename']}",""]
        for s in p["sheets"]:
            lines.append(f"- **{s['sheet']}** — {s.get('row_count',0)} rows; header row {s.get('header_row') or 'not detected'}.")
            for c in s.get("columns",[]):
                lines.append(f"  - `{c['column']}` ({c['inferred_type']}, {c['non_empty_count']} non-empty, {c.get('semantic_role') or 'role unknown'}).")
        lines.append("")
    lines += ["## Candidate canonical roles","","The mapper searches for the following roles: case identifier, event term/MedDRA PT, primary source category, initial/follow-up status, initial approval/receipt date, seriousness, and fatal outcome.","","## Mapping safeguards","","- Role selection is a proposal; a reviewer must confirm the selected workbook/sheet/column.","- No sample row values are sent to Bedrock by this POC. The LLM receives field names and type metadata only.","- If the source uses different field names, the user can select a candidate manually; the workbook is never modified.",""]
    return "\n".join(lines)
