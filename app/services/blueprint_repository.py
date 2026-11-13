"""Persistence for tenant-scoped reusable blueprints and separate generation runs.

The existing TraceWise DB adapter is SQLite in the current repository. This class
uses its connection manager and creates additive tables. Production should carry
these DDLs into the project's migration system when PostgreSQL/Aurora is enabled.
"""
from __future__ import annotations

import json
import time
from typing import Any

from app.services.database import default_db


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class BlueprintRepository:
    def __init__(self, db=default_db) -> None:
        self.db = db
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS section_blueprints (
              blueprint_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              source_learning_run_id TEXT NOT NULL,
              active_version INTEGER NOT NULL,
              status TEXT NOT NULL,
              active_manifest_hash TEXT NOT NULL,
              manifest_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (tenant_id, blueprint_id)
            );
            CREATE TABLE IF NOT EXISTS section_blueprint_versions (
              blueprint_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              status TEXT NOT NULL,
              manifest_hash TEXT NOT NULL,
              manifest_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              approved_at TEXT,
              approved_by TEXT,
              PRIMARY KEY (tenant_id, blueprint_id, version),
              FOREIGN KEY (tenant_id, blueprint_id)
                REFERENCES section_blueprints(tenant_id, blueprint_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_bp_versions_approved
              ON section_blueprint_versions(tenant_id, status);
            CREATE INDEX IF NOT EXISTS idx_bp_learning_run
              ON section_blueprints(source_learning_run_id);

            CREATE TABLE IF NOT EXISTS generation_runs (
              generation_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              run_name TEXT NOT NULL,
              blueprint_id TEXT NOT NULL,
              blueprint_version INTEGER NOT NULL,
              status TEXT NOT NULL,
              reporting_period_start TEXT NOT NULL,
              reporting_period_end TEXT NOT NULL,
              as_of_date TEXT,
              source_manifest_hash TEXT NOT NULL,
              source_object_ids TEXT NOT NULL,
              compatibility_json TEXT,
              output_manifest_hash TEXT,
              artifacts_json TEXT NOT NULL DEFAULT '[]',
              error_summary TEXT,
              version INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gen_runs_tenant
              ON generation_runs(tenant_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS generation_reviews (
              review_id INTEGER PRIMARY KEY AUTOINCREMENT,
              generation_id TEXT NOT NULL,
              reviewer_id TEXT NOT NULL,
              decision TEXT NOT NULL,
              expected_output_manifest_hash TEXT NOT NULL,
              note TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (generation_id) REFERENCES generation_runs(generation_id) ON DELETE CASCADE
            );
            """)

    def register_candidate(
        self,
        *,
        blueprint_id: str,
        tenant_id: str,
        source_learning_run_id: str,
        version: int,
        status: str,
        manifest_hash: str,
        manifest: dict[str, Any],
    ) -> None:
        """Register a candidate blueprint version. Approved versions are strictly immutable."""
        now = _now()
        manifest_json = json.dumps(manifest, sort_keys=True)
        with self.db.get_connection() as conn:
            # Check version immutability: approved versions cannot be overwritten
            existing = conn.execute(
                "SELECT status FROM section_blueprint_versions WHERE tenant_id=? AND blueprint_id=? AND version=?",
                (tenant_id, blueprint_id, version),
            ).fetchone()
            if existing and existing["status"] == "approved":
                raise ValueError(
                    f"Immutable version conflict: Blueprint {blueprint_id} version v{version} is approved and cannot be overwritten."
                )

            conn.execute("""
              INSERT INTO section_blueprints (
                blueprint_id, tenant_id, source_learning_run_id, active_version,
                status, active_manifest_hash, manifest_json, created_at, updated_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(tenant_id, blueprint_id) DO UPDATE SET
                active_version=excluded.active_version, status=excluded.status,
                active_manifest_hash=excluded.active_manifest_hash,
                manifest_json=excluded.manifest_json, updated_at=excluded.updated_at
            """, (
                blueprint_id, tenant_id, source_learning_run_id, version, status,
                manifest_hash, manifest_json, now, now,
            ))

            conn.execute("""
              INSERT INTO section_blueprint_versions (
                blueprint_id, tenant_id, version, status, manifest_hash,
                manifest_json, created_at, approved_at, approved_by
              ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
              ON CONFLICT(tenant_id, blueprint_id, version) DO UPDATE SET
                status=excluded.status, manifest_hash=excluded.manifest_hash,
                manifest_json=excluded.manifest_json, created_at=excluded.created_at
            """, (blueprint_id, tenant_id, version, status, manifest_hash, manifest_json, now))

    def mark_approved(
        self,
        *,
        source_learning_run_id: str,
        manifest_hash: str,
        reviewer_id: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a specific candidate blueprint version as approved."""
        now = _now()
        with self.db.get_connection() as conn:
            query = "SELECT * FROM section_blueprints WHERE source_learning_run_id=? AND active_manifest_hash=?"
            params: list[Any] = [source_learning_run_id, manifest_hash]
            if tenant_id:
                query += " AND tenant_id=?"
                params.append(tenant_id)
            query += " ORDER BY created_at DESC LIMIT 1"
            row = conn.execute(query, params).fetchone()
            if not row:
                return None
            conn.execute("""
              UPDATE section_blueprints SET status='approved', updated_at=?
              WHERE tenant_id=? AND blueprint_id=? AND active_manifest_hash=?
            """, (now, row["tenant_id"], row["blueprint_id"], manifest_hash))
            conn.execute("""
              UPDATE section_blueprint_versions SET status='approved', approved_at=?, approved_by=?
              WHERE tenant_id=? AND blueprint_id=? AND version=? AND manifest_hash=?
            """, (now, reviewer_id, row["tenant_id"], row["blueprint_id"], row["active_version"], manifest_hash))
        return self.get(row["tenant_id"], row["blueprint_id"], row["active_version"])

    def get(self, tenant_id: str, blueprint_id: str, version: int | None = None) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            if version is None:
                row = conn.execute("""
                  SELECT b.*, v.version, v.manifest_hash, v.manifest_json,
                         v.status AS version_status, v.approved_at, v.approved_by
                  FROM section_blueprints b
                  JOIN section_blueprint_versions v
                    ON b.tenant_id=v.tenant_id AND b.blueprint_id=v.blueprint_id
                    AND b.active_version=v.version
                  WHERE b.tenant_id=? AND b.blueprint_id=?
                """, (tenant_id, blueprint_id)).fetchone()
            else:
                row = conn.execute("""
                  SELECT b.*, v.version, v.manifest_hash, v.manifest_json,
                         v.status AS version_status, v.approved_at, v.approved_by
                  FROM section_blueprints b
                  JOIN section_blueprint_versions v
                    ON b.tenant_id=v.tenant_id AND b.blueprint_id=v.blueprint_id
                  WHERE b.tenant_id=? AND b.blueprint_id=? AND v.version=?
                """, (tenant_id, blueprint_id, version)).fetchone()
        return self._decode(row) if row else None

    def get_for_learning_run(self, source_learning_run_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            query = """
              SELECT b.*, v.version, v.manifest_hash, v.manifest_json,
                     v.status AS version_status, v.approved_at, v.approved_by
              FROM section_blueprints b
              JOIN section_blueprint_versions v
                ON b.tenant_id=v.tenant_id AND b.blueprint_id=v.blueprint_id
                AND b.active_version=v.version
              WHERE b.source_learning_run_id=?
            """
            params: list[Any] = [source_learning_run_id]
            if tenant_id:
                query += " AND b.tenant_id=?"
                params.append(tenant_id)
            query += " ORDER BY b.updated_at DESC LIMIT 1"
            row = conn.execute(query, params).fetchone()
        return self._decode(row) if row else None

    def list_approved(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        """List all approved blueprint versions available to the generator."""
        with self.db.get_connection() as conn:
            rows = conn.execute("""
              SELECT b.blueprint_id, b.tenant_id, b.source_learning_run_id,
                     b.created_at, b.updated_at, v.version, v.manifest_hash,
                     v.manifest_json, v.status AS version_status, v.approved_at, v.approved_by
              FROM section_blueprint_versions v
              JOIN section_blueprints b
                ON b.tenant_id=v.tenant_id AND b.blueprint_id=v.blueprint_id
              WHERE v.tenant_id=? AND v.status='approved'
              ORDER BY v.approved_at DESC, v.version DESC
            """, (tenant_id,)).fetchall()
        return [self._decode(row) for row in rows]

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        item = dict(row)
        raw = item.pop("manifest_json", "{}")
        item["manifest"] = json.loads(raw) if raw else {}
        return item

    def create_generation(self, data: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        tenant = data.get("tenant_id", "default")
        with self.db.get_connection() as conn:
            conn.execute("""
              INSERT INTO generation_runs (
                generation_id, tenant_id, run_name, blueprint_id, blueprint_version,
                status, reporting_period_start, reporting_period_end, as_of_date,
                source_manifest_hash, source_object_ids, artifacts_json, created_at, updated_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
            """, (
                data["generation_id"], tenant, data["run_name"],
                data["blueprint_id"], data["blueprint_version"], data.get("status", "created"),
                data["reporting_period_start"], data["reporting_period_end"], data.get("as_of_date"),
                data["source_manifest_hash"], json.dumps(data.get("source_object_ids", [])), now, now,
            ))
        result = self.get_generation(data["generation_id"], tenant_id=tenant)
        if not result:
            raise RuntimeError(f"Failed to create generation run {data['generation_id']}")
        return result

    def get_generation(self, generation_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            if tenant_id:
                row = conn.execute(
                    "SELECT * FROM generation_runs WHERE generation_id=? AND tenant_id=?",
                    (generation_id, tenant_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM generation_runs WHERE generation_id=?",
                    (generation_id,),
                ).fetchone()
        return self._decode_generation(row) if row else None

    def list_generations(self, tenant_id: str = "default", blueprint_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            if blueprint_id:
                rows = conn.execute(
                    "SELECT * FROM generation_runs WHERE tenant_id=? AND blueprint_id=? ORDER BY created_at DESC",
                    (tenant_id, blueprint_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM generation_runs WHERE tenant_id=? ORDER BY created_at DESC",
                    (tenant_id,),
                ).fetchall()
        return [self._decode_generation(row) for row in rows]

    def update_generation(
        self,
        generation_id: str,
        tenant_id: str | None = None,
        **patch: Any,
    ) -> dict[str, Any] | None:
        allowed = {"status", "compatibility_json", "output_manifest_hash", "artifacts_json", "error_summary"}
        if not patch or set(patch) - allowed:
            raise ValueError(f"Unsupported generation fields: {set(patch) - allowed}")
        assignments = [f"{key}=?" for key in patch] + ["updated_at=?", "version=version+1"]
        values = [
            json.dumps(value) if key.endswith("_json") and not isinstance(value, str) else value
            for key, value in patch.items()
        ]
        values.extend([_now(), generation_id])
        query = f"UPDATE generation_runs SET {', '.join(assignments)} WHERE generation_id=?"
        if tenant_id:
            query += " AND tenant_id=?"
            values.append(tenant_id)
        with self.db.get_connection() as conn:
            conn.execute(query, values)
        return self.get_generation(generation_id, tenant_id=tenant_id)

    def record_generation_review(
        self,
        generation_id: str,
        reviewer_id: str,
        decision: str,
        expected_output_manifest_hash: str,
        note: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        if decision not in {"approve", "request_changes"}:
            raise ValueError("decision must be approve or request_changes")
        item = self.get_generation(generation_id, tenant_id=tenant_id)
        if not item:
            return None
        if item.get("output_manifest_hash") != expected_output_manifest_hash:
            raise ValueError("Output manifest changed; refresh before reviewing")
        if item.get("status") != "output_review":
            raise ValueError(f"Generation is not awaiting output review: {item.get('status')}")
        next_status = "complete" if decision == "approve" else "output_review"
        with self.db.get_connection() as conn:
            conn.execute("""
              INSERT INTO generation_reviews (
                generation_id, reviewer_id, decision, expected_output_manifest_hash, note, created_at
              ) VALUES (?, ?, ?, ?, ?, ?)
            """, (generation_id, reviewer_id, decision, expected_output_manifest_hash, note, _now()))
            query = "UPDATE generation_runs SET status=?, updated_at=?, version=version+1 WHERE generation_id=?"
            params: list[Any] = [next_status, _now(), generation_id]
            if tenant_id:
                query += " AND tenant_id=?"
                params.append(tenant_id)
            conn.execute(query, params)
        return self.get_generation(generation_id, tenant_id=tenant_id)

    @staticmethod
    def _decode_generation(row: Any) -> dict[str, Any]:
        item = dict(row)
        for key in ("source_object_ids", "compatibility_json", "artifacts_json"):
            raw = item.get(key)
            if raw:
                try:
                    item[key] = json.loads(raw)
                except json.JSONDecodeError:
                    item[key] = [] if key != "compatibility_json" else None
            elif key in ("source_object_ids", "artifacts_json"):
                item[key] = []
        return item


default_blueprint_repo = BlueprintRepository()
