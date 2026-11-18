from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


def test_template_history_fork_approval_and_tenant_scoping(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(settings, "workspace_root", workspace)
    monkeypatch.setattr(settings, "database_path", workspace / "workbench.sqlite3")
    workspace.mkdir()
    db.init_db()
    db.create_tenant("tenant-alpha", "Tenant Alpha")
    now = datetime.now(timezone.utc).isoformat()
    template_id = "template-original"
    schema = {"base_tables": [{"table_id": "t1", "fields": []}]}
    db.create_template({
        "template_id": template_id, "tenant_id": "tenant-alpha", "name": "Alpha 16.3",
        "status": "approved", "schema": schema, "master_md": "# Master",
        "base_docx_rel": "tenant-alpha/base.docx", "source_docs": ["base.docx"], "created_at": now,
    })

    with TestClient(app) as client:
        assert client.get("/api/templates?tenant_id=tenant-alpha").status_code == 200
        assert client.get(f"/api/templates/{template_id}?tenant_id=tenant-other").status_code == 404
        patch = client.patch(f"/api/templates/{template_id}?tenant_id=tenant-alpha", json={"name": "mutated"})
        assert patch.status_code == 409  # approved version is immutable
        fork = client.post(f"/api/templates/{template_id}/fork?tenant_id=tenant-alpha",
                           data={"name": "Alpha 16.3 draft"})
        assert fork.status_code == 200
        forked = fork.json()
        assert forked["status"] == "draft"
        assert forked["template_id"] != template_id
        edit = client.patch(f"/api/templates/{forked['template_id']}?tenant_id=tenant-alpha",
                            json={"name": "Alpha revised", "master_md": "# Revised"})
        assert edit.status_code == 200
        assert edit.json()["name"] == "Alpha revised"
        assert db.get_template(template_id)["name"] == "Alpha 16.3"
        deleted = client.delete(f"/api/templates/{forked['template_id']}?tenant_id=tenant-alpha")
        assert deleted.status_code == 200
        listed = client.get("/api/templates?tenant_id=tenant-alpha").json()["templates"]
        assert [x["template_id"] for x in listed] == [template_id]
