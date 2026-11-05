from pathlib import Path
from typing import Any
import csv


def extract_file(path: Path) -> dict[str, Any]:
    ext = path.suffix.lower()
    if ext in {'.xlsx', '.xlsm', '.xltx', '.xltm', '.xls'}:
        return extract_excel(path)
    if ext == '.csv':
        with path.open('r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        return {'kind': 'csv', 'columns': rows[0] if rows else [], 'row_count': max(0, len(rows)-1), 'preview': rows[1:101]}
    if ext == '.docx':
        from docx import Document
        doc = Document(path)
        paragraphs = [{'paragraph': i+1, 'text': p.text} for i,p in enumerate(doc.paragraphs) if p.text.strip()]
        tables=[]
        for ti, table in enumerate(doc.tables, 1):
            tables.append({'table': ti, 'rows': [[c.text for c in r.cells] for r in table.rows]})
        return {'kind':'docx','paragraphs':paragraphs,'tables':tables}
    if ext == '.pdf':
        from pypdf import PdfReader
        reader=PdfReader(str(path))
        return {'kind':'pdf','pages':[{'page':i+1,'text':page.extract_text() or ''} for i,page in enumerate(reader.pages)]}
    if ext == '.doc':
        raise ValueError('Legacy .doc is not supported; convert it to .docx')
    raise ValueError(f'Unsupported file type: {ext}')


def extract_excel(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == '.xls':
        import pandas as pd
        book = pd.ExcelFile(path)
        sheets=[]
        for name in book.sheet_names:
            raw=pd.read_excel(path,sheet_name=name,header=None,nrows=50,dtype=str).fillna('')
            header_idx=next((i for i,row in raw.iterrows() if any(str(v).strip().casefold() in {'case number','case id','patient id','event pt','event pt (primary path)'} for v in row.tolist())), None)
            if header_idx is None:
                sheets.append({'sheet':name,'header_row':None,'columns':[],'row_count':0,'preview':[]}); continue
            df=pd.read_excel(path,sheet_name=name,header=header_idx,dtype=str).fillna('')
            preview=df.head(100).to_dict(orient='records')
            for j,record in enumerate(preview): record['__source_excel_row__']=int(header_idx)+2+j
            sheets.append({'sheet':name,'header_row':int(header_idx)+1,'columns':[str(c) for c in df.columns],'row_count':len(df),'preview':preview})
        return {'kind':'excel','sheets':sheets}
    from openpyxl import load_workbook
    wb=load_workbook(path,read_only=True,data_only=True)
    sheets=[]
    for ws in wb.worksheets:
        scan=list(ws.iter_rows(min_row=1,max_row=min(ws.max_row or 1,50),values_only=True))
        header_idx=None
        for i,row in enumerate(scan):
            values=[str(v).strip() for v in row if v is not None]
            if any(v.casefold() in {'case number','case id','patient id','event pt','event pt (primary path)'} for v in values):
                header_idx=i; break
        if header_idx is None:
            header_idx=next((i for i,row in enumerate(scan) if sum(v is not None and str(v).strip() for v in row)>=2),None)
        if header_idx is None:
            sheets.append({'sheet':ws.title,'header_row':None,'columns':[],'row_count':0,'preview':[]}); continue
        columns=[str(v).strip() if v is not None else f'column_{j+1}' for j,v in enumerate(scan[header_idx])]
        row_count=0; preview=[]
        for excel_row,row in enumerate(ws.iter_rows(min_row=header_idx+2,max_col=len(columns),values_only=True),header_idx+2):
            if not row or not any(v is not None and str(v).strip() for v in row): continue
            row_count+=1
            if len(preview)<100:
                rec={columns[j]:(str(row[j]) if j<len(row) and row[j] is not None else '') for j in range(len(columns))}
                rec['__source_excel_row__']=excel_row; preview.append(rec)
        sheets.append({'sheet':ws.title,'header_row':header_idx+1,'columns':columns,'row_count':row_count,'preview':preview})
    wb.close()
    return {'kind':'excel','sheets':sheets}
