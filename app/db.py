from __future__ import annotations
import json
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from app.config import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    con = sqlite3.connect(settings.database_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS tenants (
          tenant_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS templates (
          template_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL,
          schema_json TEXT NOT NULL,
          master_md TEXT NOT NULL,
          base_docx_rel TEXT NOT NULL,
          source_docs_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          approved_at TEXT,
          deleted_at TEXT,
          FOREIGN KEY(tenant_id) REFERENCES tenants(tenant_id)
        );
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          run_type TEXT NOT NULL,
          name TEXT NOT NULL,
          status TEXT NOT NULL,
          input_dir_rel TEXT NOT NULL,
          work_dir_rel TEXT NOT NULL,
          result_json TEXT NOT NULL DEFAULT '{}',
          events_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          template_id TEXT,
          error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_templates_tenant ON templates(tenant_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_runs_tenant ON runs(tenant_id, run_type, created_at);
        """)
        # Migrate an existing local POC database created before event persistence.
        columns={r[1] for r in con.execute("PRAGMA table_info(runs)").fetchall()}
        if "events_json" not in columns:
            con.execute("ALTER TABLE runs ADD COLUMN events_json TEXT NOT NULL DEFAULT '[]'")
        con.execute("INSERT OR IGNORE INTO tenants(tenant_id,display_name,created_at) VALUES(?,?,?)",
                    ("demo-tenant", "Demo tenant", now_iso()))


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def list_tenants():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM tenants ORDER BY display_name").fetchall()]


def create_tenant(tenant_id: str, display_name: str):
    with connect() as con:
        con.execute("INSERT INTO tenants VALUES(?,?,?)", (tenant_id, display_name, now_iso()))


def mark_interrupted_runs():
    """Mark in-process jobs as interrupted after a server restart; do not pretend they resumed."""
    with connect() as con:
        con.execute("UPDATE runs SET status='failed',error=?,updated_at=? WHERE status IN ('queued','running','paused')",
                    ("Local server restarted before this run completed. Start a new run to resume processing.",now_iso()))


def next_run_id(tenant_dir: Path | None = None) -> str:
    """Return the next readable sequential run ID (run_1, run_2, ...)."""
    max_num = 0
    with connect() as con:
        rows = con.execute("SELECT run_id FROM runs").fetchall()
    for r in rows:
        m = re.fullmatch(r"run_(\d+)", str(r[0] or ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    if tenant_dir and tenant_dir.exists():
        for sub in ("template_runs", "generator_runs"):
            d = tenant_dir / sub
            if d.is_dir():
                for child in d.iterdir():
                    m = re.fullmatch(r"run_(\d+)", child.name)
                    if m:
                        max_num = max(max_num, int(m.group(1)))
    return f"run_{max_num + 1}"


def next_template_id() -> str:
    """Return the next readable sequential template ID (template_1, template_2, ...)."""
    max_num = 0
    with connect() as con:
        rows = con.execute("SELECT template_id FROM templates").fetchall()
    for r in rows:
        m = re.fullmatch(r"template_(\d+)", str(r[0] or ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"template_{max_num + 1}"


def save_run(run: dict):
    with connect() as con:
        con.execute("""INSERT OR REPLACE INTO runs
          (run_id,tenant_id,run_type,name,status,input_dir_rel,work_dir_rel,result_json,events_json,created_at,updated_at,template_id,error)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (run["run_id"],run["tenant_id"],run["run_type"],run["name"],run["status"],run["input_dir_rel"],
           run["work_dir_rel"],json_dump(run.get("result",{})),json_dump(run.get("events",[])),
           run.get("created_at",now_iso()),now_iso(),run.get("template_id"),run.get("error")))


def update_run(run_id: str, **fields):
    allowed = {"status", "result", "events", "error", "template_id", "name"}
    sets=[]; vals=[]
    for key,value in fields.items():
        if key not in allowed: continue
        dbkey = {"result":"result_json","events":"events_json"}.get(key,key)
        sets.append(f"{dbkey}=?")
        vals.append(json_dump(value) if key in {"result","events"} else value)
    if not sets: return
    sets.append("updated_at=?"); vals.append(now_iso()); vals.append(run_id)
    with connect() as con:
        con.execute(f"UPDATE runs SET {','.join(sets)} WHERE run_id=?", vals)


def get_run(run_id: str):
    with connect() as con:
        row=con.execute("SELECT * FROM runs WHERE run_id=?",(run_id,)).fetchone()
    if not row:return None
    item=dict(row)
    item["result"] = json.loads(item.pop("result_json") or "{}")
    item["events"] = json.loads(item.pop("events_json", "[]") or "[]")
    return item


def create_template(template: dict):
    with connect() as con:
        con.execute("""INSERT INTO templates
          (template_id,tenant_id,name,status,schema_json,master_md,base_docx_rel,source_docs_json,created_at,updated_at,approved_at,deleted_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL)""",
          (template["template_id"],template["tenant_id"],template["name"],template["status"],
           json_dump(template["schema"]),template["master_md"],template["base_docx_rel"],
           json_dump(template["source_docs"]),template["created_at"],template["created_at"],None))


def list_templates(tenant_id: str, include_deleted: bool = False):
    query="SELECT * FROM templates WHERE tenant_id=?"
    args=[tenant_id]
    if not include_deleted: query += " AND deleted_at IS NULL"
    query += " ORDER BY created_at DESC"
    with connect() as con: rows=con.execute(query,args).fetchall()
    return [_template_from_row(r) for r in rows]


def _template_from_row(row):
    item=dict(row)
    item["schema"]=json.loads(item.pop("schema_json"))
    item["source_docs"]=json.loads(item.pop("source_docs_json"))
    item["source_doc_count"]=len(item["source_docs"])
    return item


def get_template(template_id: str):
    with connect() as con: row=con.execute("SELECT * FROM templates WHERE template_id=?",(template_id,)).fetchone()
    return _template_from_row(row) if row else None


def fork_template(template_id: str, new_template_id: str, new_name: str):
    source=get_template(template_id)
    if not source or source["status"]=="deleted":
        raise ValueError("Template not found")
    clone={"template_id":new_template_id,"tenant_id":source["tenant_id"],"name":new_name,
           "status":"draft","schema":source["schema"],"master_md":source["master_md"],
           "base_docx_rel":source["base_docx_rel"],"source_docs":source["source_docs"],"created_at":now_iso()}
    create_template(clone)
    return get_template(new_template_id)


def update_template(template_id: str, **fields):
    allowed={"name","schema","master_md","status","approved_at"}
    sets=[]; vals=[]
    for key,value in fields.items():
        if key not in allowed: continue
        dbkey={"schema":"schema_json"}.get(key,key)
        sets.append(f"{dbkey}=?"); vals.append(json_dump(value) if key=="schema" else value)
    if not sets:return
    sets.append("updated_at=?"); vals.append(now_iso()); vals.append(template_id)
    with connect() as con: con.execute(f"UPDATE templates SET {','.join(sets)} WHERE template_id=?",vals)


def soft_delete_template(template_id: str):
    with connect() as con:
        con.execute("UPDATE templates SET status='deleted',deleted_at=?,updated_at=? WHERE template_id=?",
                    (now_iso(),now_iso(),template_id))
