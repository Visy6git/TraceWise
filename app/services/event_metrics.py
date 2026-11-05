from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re
from openpyxl import load_workbook


def norm(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()

@dataclass
class EventMetricRule:
    metric_name: str
    sheet_name: str
    case_column: str
    event_column: str
    event_terms: tuple[str, ...]
    initial_only: bool = False
    initial_flag_column: str = 'Derived-Initial-Follow-up-Flag'
    required_nonempty_columns: tuple[str, ...] = ()
    date_column: str | None = None
    start_date_yyyymmdd: str | None = None
    end_date_yyyymmdd: str | None = None
    include_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
    exclude_values: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def validate(self):
        if not self.event_terms: raise ValueError('At least one event term is required')
        if bool(self.start_date_yyyymmdd) != bool(self.end_date_yyyymmdd): raise ValueError('Both date bounds are required')
        if bool(self.date_column) != bool(self.start_date_yyyymmdd): raise ValueError('date_column and both date bounds must be supplied together')
        if self.start_date_yyyymmdd:
            if not re.fullmatch(r'\d{8}',self.start_date_yyyymmdd) or not re.fullmatch(r'\d{8}',self.end_date_yyyymmdd or ''): raise ValueError('Dates must use YYYYMMDD')
            if self.start_date_yyyymmdd > self.end_date_yyyymmdd: raise ValueError('Start date must not exceed end date')
        for mapping in (self.include_values,self.exclude_values):
            for col,vals in mapping.items():
                if not col.strip() or not vals: raise ValueError('Value filters require column and values')


def calculate_case_event_metric(path: Path, rule: EventMetricRule) -> dict[str, Any]:
    rule.validate()
    if path.suffix.lower() != '.xlsx': raise ValueError('Metric calculation currently supports .xlsx only')
    wb=load_workbook(path,read_only=True,data_only=True)
    if rule.sheet_name not in wb.sheetnames: raise ValueError(f'Sheet not found: {rule.sheet_name}')
    ws=wb[rule.sheet_name]
    required={norm(x) for x in [rule.case_column,rule.event_column,*rule.required_nonempty_columns,*rule.include_values.keys(),*rule.exclude_values.keys()]}
    if rule.date_column: required.add(norm(rule.date_column))
    if rule.initial_only: required.add(norm(rule.initial_flag_column))
    header_row=None; headers=[]
    for i,row in enumerate(ws.iter_rows(min_row=1,max_row=min(ws.max_row or 1,60),values_only=True),1):
        vals=[str(v).strip() if v is not None else '' for v in row]
        if required.issubset({norm(v) for v in vals}): header_row=i; headers=vals; break
    if header_row is None: wb.close(); raise ValueError(f'Could not find header row containing: {sorted(required)}')
    hmap={norm(v):i for i,v in enumerate(headers) if v}
    ci,ei=hmap[norm(rule.case_column)],hmap[norm(rule.event_column)]
    ri=[hmap[norm(c)] for c in rule.required_nonempty_columns]
    di=hmap[norm(rule.date_column)] if rule.date_column else None
    ii=hmap[norm(rule.initial_flag_column)] if rule.initial_only else None
    inc={hmap[norm(c)]:{norm(v) for v in vals} for c,vals in rule.include_values.items()}
    exc={hmap[norm(c)]:{norm(v) for v in vals} for c,vals in rule.exclude_values.items()}
    max_col=max([ci,ei,*ri,*inc.keys(),*exc.keys(),di or 0,ii or 0])+1
    cases=set(); matched=set(); evidence=[]; scanned=0; matched_rows=0; terms={norm(x) for x in rule.event_terms}
    for row_no,row in enumerate(ws.iter_rows(min_row=header_row+1,max_col=max_col,values_only=True),header_row+1):
        cid=str(row[ci] or '').strip() if ci<len(row) else ''
        if not cid: continue
        scanned+=1
        if any(idx>=len(row) or not str(row[idx] or '').strip() for idx in ri): continue
        if ii is not None and norm(row[ii] if ii<len(row) else '')!='initial': continue
        if di is not None:
            dv=str(row[di] or '').strip() if di<len(row) else ''
            if not dv.isdigit() or not rule.start_date_yyyymmdd<=dv<=rule.end_date_yyyymmdd: continue
        if any(idx>=len(row) or norm(row[idx]) not in vals for idx,vals in inc.items()): continue
        if any(idx<len(row) and norm(row[idx]) in vals for idx,vals in exc.items()): continue
        cases.add(cid)
        event=str(row[ei] or '').strip() if ei<len(row) else ''
        if norm(event) in terms:
            matched.add(cid); matched_rows+=1
            if len(evidence)<1000:
                evidence.append({'case_id':cid,'event':event,'excel_row':row_no,'case_cell':f'{ws.cell(row_no,ci+1).coordinate}','event_cell':f'{ws.cell(row_no,ei+1).coordinate}'})
    wb.close()
    denominator=len(cases); numerator=len(matched)
    return {'metric_name':rule.metric_name,'numerator_distinct_cases':numerator,'denominator_distinct_cases':denominator,'percentage':round(numerator/denominator*100,4) if denominator else None,'matched_case_ids':sorted(matched),'matched_event_rows_count':matched_rows,'evidence':evidence,'evidence_truncated':matched_rows>len(evidence),'rule':{'sheet_name':rule.sheet_name,'case_column':rule.case_column,'event_column':rule.event_column,'event_terms':list(rule.event_terms),'initial_only':rule.initial_only,'required_nonempty_columns':list(rule.required_nonempty_columns),'date_column':rule.date_column,'start_date_yyyymmdd':rule.start_date_yyyymmdd,'end_date_yyyymmdd':rule.end_date_yyyymmdd,'include_values':rule.include_values,'exclude_values':rule.exclude_values},'limitations':['Exact case-insensitive event-term matching only; no synonym or MedDRA hierarchy expansion.','Distinct case IDs are counted; patient-level deduplication is not inferred.','Evidence is capped at 1,000 matched rows.']}
