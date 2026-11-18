from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import asyncio, json, re, shutil
from typing import Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app import db
from app.services.pause_controller import PauseController
from app.services.llm_client import llm_status_info
from app.services.orchestrator import run_template_learning, run_source_exploration, run_mapping_stage, generate_docx

app=FastAPI(title="PBRER Section 16.3 Table Workbench",version="1.0.0")
app.mount("/static",StaticFiles(directory="app/static"),name="static")
db.init_db()
db.mark_interrupted_runs()
RUNS:dict[str,dict[str,Any]]={}


def utcnow(): return datetime.now(timezone.utc).isoformat()

def tenant_slug(value:str)->str:
    v=re.sub(r"[^A-Za-z0-9_-]","-",(value or "").strip()).strip("-")[:64]
    if not v: raise HTTPException(422,"A tenant must be selected")
    return v

def safe_filename(value:str)->str:
    return re.sub(r"[^A-Za-z0-9._ -]","_",Path(value or "upload").name)[:150] or "upload"

def workspace_path(rel:str)->Path:
    p=(settings.workspace_root/rel).resolve()
    root=settings.workspace_root.resolve()
    if p!=root and root not in p.parents: raise HTTPException(400,"Invalid workspace path")
    return p

def ensure_tenant(tenant_id:str):
    if not any(t["tenant_id"]==tenant_id for t in db.list_tenants()):
        raise HTTPException(404,"Tenant does not exist. Create it in the workspace selector first.")

def emit(run_id:str,event_type:str,**payload):
    run=RUNS.get(run_id)
    if not run:return
    event={"type":event_type,**payload}
    run.setdefault("events",[]).append(event)
    # Keep event history durable so a page refresh/server restart can replay completed runs.
    try: db.update_run(run_id,events=run["events"])
    except Exception: pass

def progress_for(run_id:str):
    def cb(agent:str,message:str,details:dict):
        emit(run_id,"CUSTOM",name="agent.activity",value={"agent":agent,"message":message,"details":details,"timestamp":utcnow()})
    return cb

def agui_for(run_id:str):
    def cb(event_type:str,payload:dict[str,Any]):
        emit(run_id,event_type,**payload)
    return cb

def save_upload(upload:UploadFile,destination:Path,allowed:set[str])->Path:
    name=safe_filename(upload.filename or "upload")
    suffix=Path(name).suffix.lower()
    if suffix not in allowed: raise HTTPException(415,f"Unsupported file type for {name}; allowed: {', '.join(sorted(allowed))}")
    candidate=destination/name
    if candidate.exists(): candidate=destination/f"{uuid4().hex[:8]}_{name}"
    data=upload.file.read()
    if len(data)>settings.max_upload_mb*1024*1024: raise HTTPException(413,f"File {name} exceeds {settings.max_upload_mb} MB")
    candidate.write_bytes(data)
    return candidate

async def event_stream(run_id:str):
    sent=0
    while True:
        run=RUNS.get(run_id)
        persisted=None if run else db.get_run(run_id)
        if not run and not persisted: break
        events=run.get("events",[]) if run else persisted.get("events",[])
        status=run.get("status") if run else persisted.get("status")
        while sent<len(events):
            yield f"data: {json.dumps(events[sent],ensure_ascii=False)}\n\n"
            sent+=1
        if status in {"completed","failed"} and sent>=len(events):break
        await asyncio.sleep(.3)

@app.get("/",response_class=HTMLResponse)
async def index():
    return Path("app/static/index.html").read_text(encoding="utf-8")

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        **llm_status_info(),
        "note": "Tenant selector is workspace organization only; this local POC has no authentication/authorization.",
    }

@app.get("/api/tenants")
async def list_tenants(): return {"tenants":db.list_tenants()}

class TenantCreate(BaseModel):
    tenant_id:str
    display_name:str

@app.post("/api/tenants")
async def add_tenant(payload:TenantCreate):
    tid=tenant_slug(payload.tenant_id)
    try: db.create_tenant(tid,payload.display_name.strip() or tid)
    except Exception: raise HTTPException(409,"Tenant ID already exists")
    return {"tenant_id":tid,"display_name":payload.display_name}

# -------------------------- TEMPLATE GENERATOR --------------------------
@app.post("/api/template-runs")
async def create_template_run(
    tenant_id: str = Form(...),
    run_name: str = Form(...),
    template_type: str = Form("generic"),
    files: list[UploadFile] = File(...),
):
    tid=tenant_slug(tenant_id); ensure_tenant(tid)
    norm_type = (template_type or "generic").strip().lower()
    if norm_type not in {"generic", "product"}:
        raise HTTPException(422, "template_type must be 'generic' or 'product'")
    if not files:raise HTTPException(400,"Upload at least one DOCX reference document")
    if len(files)>settings.max_docx_files:raise HTTPException(413,f"Maximum {settings.max_docx_files} DOCX files per template run")
    rid=db.next_run_id(workspace_path(tid)); rel=Path(tid)/"template_runs"/rid
    input_dir=workspace_path(str(rel/"input")); work_dir=workspace_path(str(rel/"work"))
    input_dir.mkdir(parents=True,exist_ok=True);work_dir.mkdir(parents=True,exist_ok=True)
    saved=[]
    try:
        for f in files:saved.append(save_upload(f,input_dir,{".docx"}))
    except Exception:
        shutil.rmtree(input_dir.parent,ignore_errors=True);raise
    if sum(p.stat().st_size for p in saved)>settings.max_upload_mb*1024*1024:
        shutil.rmtree(input_dir.parent,ignore_errors=True);raise HTTPException(413,"Combined upload exceeds configured size limit")
    run={"run_id":rid,"tenant_id":tid,"run_type":"template","name":run_name.strip() or "Section 16.3 template",
         "template_type":norm_type,"status":"queued","events":[],"input_dir":input_dir,"work_dir":work_dir,"files":saved,
         "input_dir_rel":str(rel/"input"),"work_dir_rel":str(rel/"work"),"created_at":utcnow(),
         "pause_controller":PauseController()}
    RUNS[rid]=run;db.save_run(run)
    asyncio.create_task(_template_task(rid))
    return {"run_id":rid,"status":"queued","template_type":norm_type}

async def _template_task(run_id:str):
    run=RUNS[run_id];run["status"]="running";db.update_run(run_id,status="running")
    emit(run_id,"RUN_STARTED",threadId=run_id,runId=run_id,timestamp=utcnow())
    try:
        pc: PauseController | None = run.get("pause_controller")
        pause_check = pc.wait_if_paused if pc else None
        # Flexible invocation supporting mocks with varying signatures
        import inspect
        sig = inspect.signature(run_template_learning)
        kwargs = {}
        if "template_type" in sig.parameters:
            kwargs["template_type"] = run.get("template_type", "generic")
        if "pause_check" in sig.parameters:
            kwargs["pause_check"] = pause_check
        out=await asyncio.to_thread(
            run_template_learning,
            run_id,
            run["tenant_id"],
            run["name"],
            run["files"],
            run["work_dir"],
            progress_for(run_id),
            agui_for(run_id),
            **kwargs,
        )
        template_id=db.next_template_id()
        base_rel=str(Path(out["base_docx_path"]).resolve().relative_to(settings.workspace_root.resolve()))
        template_type=out["schema"].get("template_type",run.get("template_type","generic"))
        template={"template_id":template_id,"tenant_id":run["tenant_id"],"name":run["name"],"status":"draft",
                  "template_type":template_type,"schema":out["schema"],"master_md":out["master_md"],"base_docx_rel":base_rel,
                  "source_docs":[p.name for p in run["files"]],"created_at":utcnow()}
        db.create_template(template)
        run["result"]={"template_id":template_id,"template":template,"schema":out["schema"],"master_md":out["master_md"],"template_type":template_type}
        run["status"]="completed";db.update_run(run_id,status="completed",result=run["result"],template_id=template_id)
        emit(run_id,"CUSTOM",name="template.ready",value={"template_id":template_id,"table_count":len(out["schema"].get("base_tables",[])),"status":"draft","template_type":template_type},timestamp=utcnow())
        emit(run_id,"RUN_FINISHED",threadId=run_id,runId=run_id,timestamp=utcnow())
    except Exception as exc:
        run["status"]="failed";run["error"]=str(exc);db.update_run(run_id,status="failed",error=str(exc))
        emit(run_id,"RUN_ERROR",threadId=run_id,runId=run_id,message=str(exc),code="TEMPLATE_FAILED",timestamp=utcnow())

@app.post("/api/template-runs/{run_id}/pause")
async def pause_template_run(run_id: str):
    run = RUNS.get(run_id)
    if not run or run.get("run_type") != "template":
        raise HTTPException(404, "Active template run not found")
    if run["status"] != "running":
        raise HTTPException(409, f"Run is currently in '{run['status']}' state")
    pc: PauseController | None = run.get("pause_controller")
    if not pc:
        raise HTTPException(409, "Pause controller not available for this run")
    pc.pause()
    run["status"] = "paused"
    db.update_run(run_id, status="paused")
    emit(run_id, "CUSTOM", name="run.paused", value={"run_id": run_id, "run_type": "template", "status": "paused"}, timestamp=utcnow())
    return {"run_id": run_id, "status": "paused"}

@app.post("/api/template-runs/{run_id}/resume")
async def resume_template_run(run_id: str):
    run = RUNS.get(run_id)
    if not run or run.get("run_type") != "template":
        raise HTTPException(404, "Active template run not found")
    if run["status"] != "paused":
        raise HTTPException(409, f"Run is currently in '{run['status']}' state")
    pc: PauseController | None = run.get("pause_controller")
    if not pc:
        raise HTTPException(409, "Pause controller not available for this run")
    run["status"] = "running"
    db.update_run(run_id, status="running")
    pc.resume()
    emit(run_id, "CUSTOM", name="run.resumed", value={"run_id": run_id, "run_type": "template", "status": "running"}, timestamp=utcnow())
    return {"run_id": run_id, "status": "running"}

@app.get("/api/template-runs/{run_id}")
async def get_template_run(run_id:str):
    run=RUNS.get(run_id)
    if run:return {"run_id":run_id,"status":run["status"],"is_paused":run["status"]=="paused","result":run.get("result",{}),"error":run.get("error")}
    saved=db.get_run(run_id)
    if not saved or saved["run_type"]!="template":raise HTTPException(404,"Template run not found")
    return {"run_id":run_id,"status":saved["status"],"is_paused":saved["status"]=="paused","result":saved["result"],"error":saved.get("error")}

@app.get("/api/template-runs/{run_id}/events")
async def template_events(run_id:str):
    saved=db.get_run(run_id)
    if run_id not in RUNS and (not saved or saved["run_type"]!="template"):
        raise HTTPException(404,"Template run events not found")
    return StreamingResponse(event_stream(run_id),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.get("/api/templates")
async def templates(tenant_id:str):
    tid=tenant_slug(tenant_id);ensure_tenant(tid)
    items=db.list_templates(tid)
    return {
        "templates": [
            {k: v for k, v in t.items() if k not in {"schema", "master_md", "base_docx_rel", "source_docs"}}
            | {
                "template_type": t["schema"].get("template_type", "generic"),
                "table_count": len(t["schema"].get("base_tables", [])),
                "source_doc_count": t.get("source_doc_count", len(t.get("source_docs", []))),
            }
            for t in items
        ]
    }

@app.get("/api/templates/{template_id}")
async def template_detail(template_id:str,tenant_id:str):
    t=db.get_template(template_id)
    if not t or t.get("status")=="deleted":raise HTTPException(404,"Template not found")
    if t["tenant_id"]!=tenant_slug(tenant_id):raise HTTPException(404,"Template not found for this tenant")
    t["template_type"] = t.get("schema", {}).get("template_type", "generic")
    return t

class TemplateUpdate(BaseModel):
    name:str|None=None
    schema_data:dict|None=Field(default=None,alias="schema")
    master_md:str|None=None

@app.patch("/api/templates/{template_id}")
async def edit_template(template_id:str,tenant_id:str,payload:TemplateUpdate):
    t=db.get_template(template_id)
    if not t or t["tenant_id"]!=tenant_slug(tenant_id) or t.get("status")=="deleted":raise HTTPException(404,"Template not found")
    if t["status"]=="approved":
        # Edits to approved templates fork a new draft rather than silently changing a live version.
        raise HTTPException(409,"Approved templates are immutable. Duplicate/relearn into a new draft to edit this version.")
    fields={k:v for k,v in payload.model_dump(by_alias=True,exclude_unset=True).items() if v is not None}
    if "name" in fields:fields["name"]=fields["name"].strip() or t["name"]
    db.update_template(template_id,**fields)
    return await template_detail(template_id,tenant_id)

@app.post("/api/templates/{template_id}/approve")
async def approve_template(template_id:str,tenant_id:str):
    t=db.get_template(template_id)
    if not t or t["tenant_id"]!=tenant_slug(tenant_id) or t.get("status")=="deleted":raise HTTPException(404,"Template not found")
    if not t["schema"].get("base_tables"):raise HTTPException(409,"No Section 16.3 tables were detected; edit/re-upload the reference documents before approval")
    db.update_template(template_id,status="approved",approved_at=utcnow())
    return {"template_id":template_id,"status":"approved","template_type":t.get("schema",{}).get("template_type","generic")}

@app.delete("/api/templates/{template_id}")
async def delete_template(template_id:str,tenant_id:str):
    t=db.get_template(template_id)
    if not t or t["tenant_id"]!=tenant_slug(tenant_id) or t.get("status")=="deleted":raise HTTPException(404,"Template not found")
    db.soft_delete_template(template_id)
    return {"template_id":template_id,"status":"deleted"}

@app.post("/api/templates/{template_id}/fork")
async def fork_template(template_id:str,tenant_id:str,name:str=Form("")):
    tid=tenant_slug(tenant_id);t=db.get_template(template_id)
    if not t or t["tenant_id"]!=tid or t.get("status")=="deleted":raise HTTPException(404,"Template not found")
    fork_id=db.next_template_id();fork_name=(name.strip() or f"{t['name']} — editable draft")
    clone=db.fork_template(template_id,fork_id,fork_name)
    return clone

@app.get("/api/templates/{template_id}/master.md")
async def download_master(template_id:str,tenant_id:str):
    t=db.get_template(template_id)
    if not t or t["tenant_id"]!=tenant_slug(tenant_id) or t.get("status")=="deleted":raise HTTPException(404,"Template not found")
    filename=f"{safe_filename(t['name']).replace(' ','_')}_master.md"
    return PlainTextResponse(t["master_md"],media_type="text/markdown",headers={"Content-Disposition":f'attachment; filename="{filename}"'})

# ------------------------------- GENERATOR -------------------------------
@app.post("/api/generator-runs")
async def create_generator_run(tenant_id:str=Form(...),run_name:str=Form(...),template_id:str=Form(...),
                               period_start:str=Form(""),period_end:str=Form(""),files:list[UploadFile]=File(...)):
    tid=tenant_slug(tenant_id);ensure_tenant(tid)
    t=db.get_template(template_id)
    if not t or t["tenant_id"]!=tid or t["status"]!="approved":
        raise HTTPException(409,"Choose an approved template belonging to this tenant")
    if not files:raise HTTPException(400,"Upload at least one Excel source workbook")
    if len(files)>settings.max_excel_files:raise HTTPException(413,f"Maximum {settings.max_excel_files} workbooks per run")
    if bool(period_start)!=bool(period_end):raise HTTPException(422,"Provide both reporting interval start and end dates, or leave both blank")
    if period_start and period_end and period_start>period_end:raise HTTPException(422,"Reporting interval start must be before end")
    if t["schema"].get("reporting_interval_required") and not (period_start and period_end):
        raise HTTPException(422,"This template explicitly requires a reporting interval. Provide both start and end dates.")
    rid=db.next_run_id(workspace_path(tid));rel=Path(tid)/"generator_runs"/rid
    input_dir=workspace_path(str(rel/"input"));work_dir=workspace_path(str(rel/"work"))
    input_dir.mkdir(parents=True,exist_ok=True);work_dir.mkdir(parents=True,exist_ok=True)
    saved=[]
    try:
        for f in files:saved.append(save_upload(f,input_dir,{".xlsx",".xls"}))
    except Exception:
        shutil.rmtree(input_dir.parent,ignore_errors=True);raise
    if sum(p.stat().st_size for p in saved)>settings.max_upload_mb*1024*1024:
        shutil.rmtree(input_dir.parent,ignore_errors=True);raise HTTPException(413,"Combined upload exceeds configured size limit")
    base_path=workspace_path(t["base_docx_rel"])
    run={"run_id":rid,"tenant_id":tid,"run_type":"generator","name":run_name.strip() or "Section 16.3 generation",
         "status":"queued","events":[],"input_dir":input_dir,"work_dir":work_dir,"files":saved,
         "source_filenames":[p.name for p in saved],"input_dir_rel":str(rel/"input"),"work_dir_rel":str(rel/"work"),
         "template_id":template_id,"template":t["schema"],"base_docx_path":str(base_path),
         "period_start":period_start or None,"period_end":period_end or None,"created_at":utcnow(),
         "pause_controller":PauseController()}
    RUNS[rid]=run;db.save_run(run)
    asyncio.create_task(_generator_task(rid))
    return {"run_id":rid,"status":"queued"}

async def _generator_task(run_id:str):
    run=RUNS[run_id];run["status"]="running";db.update_run(run_id,status="running")
    emit(run_id,"RUN_STARTED",threadId=run_id,runId=run_id,timestamp=utcnow())
    try:
        pc: PauseController | None = run.get("pause_controller")
        pause_check = pc.wait_if_paused if pc else None
        emit(run_id,"STEP_STARTED",stepName="source_exploration",stepId="source_exploration",timestamp=utcnow())
        profiles=await asyncio.to_thread(
            run_source_exploration,
            run_id,
            run["files"],
            run["work_dir"],
            progress_for(run_id),
            agui_for(run_id),
            pause_check,
        )
        emit(run_id,"STEP_FINISHED",stepName="source_exploration",stepId="source_exploration",timestamp=utcnow())
        emit(run_id,"STEP_STARTED",stepName="mapping",stepId="mapping",timestamp=utcnow())
        mapping_result=await asyncio.to_thread(
            run_mapping_stage,
            run["template"],
            profiles,
            run["input_dir"],
            run["period_start"],
            run["period_end"],
            progress_for(run_id),
            pause_check,
        )
        artifacts=sorted(p.name for p in run["work_dir"].iterdir() if p.is_file() and p.suffix.lower() in {".md",".py"})
        result={"template_id":run["template_id"],"template_name":run["template"].get("template_name"),
                "profiles":profiles,"source_mapping":mapping_result,"period_start":run["period_start"],"period_end":run["period_end"],
                "artifacts":artifacts,"requires_mapping_approval":True}
        (run["work_dir"]/"mapping_proposals.json").write_text(json.dumps(mapping_result,indent=2,ensure_ascii=False),encoding="utf-8")
        run["result"]=result;run["status"]="completed";db.update_run(run_id,status="completed",result=result)
        emit(run_id,"STEP_FINISHED",stepName="mapping",stepId="mapping",timestamp=utcnow())
        emit(run_id,"CUSTOM",name="mapping.ready",value={"mapping_roles":list(mapping_result["column_mapping"].keys()),"tables":len(mapping_result["topic_metrics"]),"artifacts":result["artifacts"]},timestamp=utcnow())
        emit(run_id,"RUN_FINISHED",threadId=run_id,runId=run_id,timestamp=utcnow())
    except Exception as exc:
        run["status"]="failed";run["error"]=str(exc);db.update_run(run_id,status="failed",error=str(exc))
        emit(run_id,"RUN_ERROR",threadId=run_id,runId=run_id,message=str(exc),code="GENERATOR_FAILED",timestamp=utcnow())

@app.post("/api/generator-runs/{run_id}/pause")
async def pause_generator_run(run_id: str):
    run = RUNS.get(run_id)
    if not run or run.get("run_type") != "generator":
        raise HTTPException(404, "Active generator run not found")
    if run["status"] != "running":
        raise HTTPException(409, f"Run is currently in '{run['status']}' state")
    pc: PauseController | None = run.get("pause_controller")
    if not pc:
        raise HTTPException(409, "Pause controller not available for this run")
    pc.pause()
    run["status"] = "paused"
    db.update_run(run_id, status="paused")
    emit(run_id, "CUSTOM", name="run.paused", value={"run_id": run_id, "run_type": "generator", "status": "paused"}, timestamp=utcnow())
    return {"run_id": run_id, "status": "paused"}

@app.post("/api/generator-runs/{run_id}/resume")
async def resume_generator_run(run_id: str):
    run = RUNS.get(run_id)
    if not run or run.get("run_type") != "generator":
        raise HTTPException(404, "Active generator run not found")
    if run["status"] != "paused":
        raise HTTPException(409, f"Run is currently in '{run['status']}' state")
    pc: PauseController | None = run.get("pause_controller")
    if not pc:
        raise HTTPException(409, "Pause controller not available for this run")
    run["status"] = "running"
    db.update_run(run_id, status="running")
    pc.resume()
    emit(run_id, "CUSTOM", name="run.resumed", value={"run_id": run_id, "run_type": "generator", "status": "running"}, timestamp=utcnow())
    return {"run_id": run_id, "status": "running"}

@app.get("/api/generator-runs/{run_id}")
async def get_generator_run(run_id:str):
    run=RUNS.get(run_id)
    if run:return {"run_id":run_id,"status":run["status"],"is_paused":run["status"]=="paused","result":run.get("result",{}),"error":run.get("error")}
    saved=db.get_run(run_id)
    if not saved or saved["run_type"]!="generator":raise HTTPException(404,"Generator run not found")
    return {"run_id":run_id,"status":saved["status"],"is_paused":saved["status"]=="paused","result":saved["result"],"error":saved.get("error")}

@app.get("/api/generator-runs/{run_id}/events")
async def generator_events(run_id:str):
    saved=db.get_run(run_id)
    if run_id not in RUNS and (not saved or saved["run_type"]!="generator"):
        raise HTTPException(404,"Generator run events not found")
    return StreamingResponse(event_stream(run_id),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

def load_generator_runtime(run_id:str) -> dict | None:
    runtime=RUNS.get(run_id)
    if runtime:return runtime
    saved=db.get_run(run_id)
    if not saved or saved["run_type"]!="generator":return None
    template=db.get_template(saved.get("template_id")) if saved.get("template_id") else None
    if not template or template.get("status")=="deleted":return None
    input_dir=workspace_path(saved["input_dir_rel"])
    work_dir=workspace_path(saved["work_dir_rel"])
    if not input_dir.exists() or not work_dir.exists():return None
    runtime={"run_id":run_id,"tenant_id":saved["tenant_id"],"run_type":"generator","name":saved["name"],
        "status":saved["status"],"events":saved.get("events",[]),"result":saved.get("result",{}),
        "input_dir":input_dir,"work_dir":work_dir,"input_dir_rel":saved["input_dir_rel"],
        "work_dir_rel":saved["work_dir_rel"],"template_id":saved["template_id"],"template":template["schema"],
        "base_docx_path":str(workspace_path(template["base_docx_rel"])),
        "source_filenames":sorted(p.name for p in input_dir.iterdir() if p.is_file()),
        "period_start":saved.get("result",{}).get("period_start"),"period_end":saved.get("result",{}).get("period_end")}
    RUNS[run_id]=runtime
    return runtime


class GenerateRequest(BaseModel):
    approved:bool=False
    count_mode:str|None=None
    column_mapping:dict[str,dict|None]=Field(default_factory=dict)
    narratives:dict[str,dict[str,str]]=Field(default_factory=dict)

@app.post("/api/generator-runs/{run_id}/generate")
async def generate_output(run_id:str,payload:GenerateRequest):
    run=load_generator_runtime(run_id)
    if not run:raise HTTPException(404,"Generator run not found")
    if run.get("status")!="completed":raise HTTPException(409,"Generator exploration/mapping stage is not complete")
    if not payload.approved:raise HTTPException(409,"Mapping approval is required before generating the report")
    if payload.count_mode not in {"distinct_case","event_rows"}:raise HTTPException(422,"Unsupported count mode")
    original=run["result"]["source_mapping"]["column_mapping"]
    mapping=original.copy()
    all_cols=run["result"]["source_mapping"]["all_columns"]
    for role,entry in payload.column_mapping.items():
        if role not in original:raise HTTPException(422,f"Unknown mapping role: {role}")
        if entry is None: mapping[role]=None;continue
        valid=next((c for c in all_cols if c["source_file"]==entry.get("source_file") and c["sheet"]==entry.get("sheet") and c["column"]==entry.get("column")),None)
        if not valid:raise HTTPException(422,f"Mapping for {role} does not reference a detected column in this run")
        mapping[role]={**valid,"confidence":"reviewer_selected","rationale":"Selected/approved by reviewer."}
    emit(run_id,"STEP_STARTED",stepName="deterministic_calculation_and_docx_render",stepId="report_generation")
    out_path=run["work_dir"]/f"{safe_filename(run['name']).replace(' ','_')}_Section_16_3.docx"
    try:
        generated=await asyncio.to_thread(generate_docx,run["template"],run,mapping,run["period_start"],run["period_end"],payload.count_mode,payload.narratives,out_path)
    except Exception as exc:raise HTTPException(500,f"Report generation failed: {exc}") from exc
    result={"output_filename":out_path.name,"output_url":f"/api/generator-runs/{run_id}/artifact/{out_path.name}",
            "metrics":generated["metrics"],"render":generated["render"],"count_mode":payload.count_mode,
            "approved":True,"review_notes":["Evaluation/conclusion narratives must be reviewed; blank inputs are rendered as explicit review placeholders.",
            "Only the base DOCX's Section 16.3 table cells were targeted; other document content is retained."]}
    run["generation_result"]=result;run["result"]["generation_result"]=result
    db.update_run(run_id,result=run["result"])
    emit(run_id,"CUSTOM",name="report.generated",value={"filename":out_path.name,"updated_tables":len(generated["render"]["updated_tables"]),"warnings":generated["render"]["warnings"]})
    emit(run_id,"STEP_FINISHED",stepName="deterministic_calculation_and_docx_render",stepId="report_generation")
    return result

@app.get("/api/generator-runs/{run_id}/artifact/{filename}")
async def download_artifact(run_id:str,filename:str):
    run=load_generator_runtime(run_id)
    if not run:raise HTTPException(404,"Run workspace not found")
    safe=Path(filename).name;path=run["work_dir"]/safe
    if not path.is_file():raise HTTPException(404,"Artifact not found")
    return FileResponse(path,filename=safe)

@app.get("/api/generator-runs/{run_id}/files")
async def generator_artifacts(run_id:str):
    run=load_generator_runtime(run_id)
    if not run:raise HTTPException(404,"Run not found")
    return {"files":[{"name":p.name,"size":p.stat().st_size} for p in run["work_dir"].glob("*") if p.is_file()]}
