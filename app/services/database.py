"""Durable local database repository backed by SQLite with schema auto-migration."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.control_plane.approvals import ApprovalRequest, validate_approval
from app.control_plane.run_state import RunState, validate_transition


class _ClosingConnection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        try:
            return self._conn.__exit__(exc_type, exc_val, exc_tb)
        finally:
            self._conn.close()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._conn, item)


def _dump_json(val: Any, default: Any = None) -> str:
    if val is None:
        return json.dumps(default) if default is not None else "null"
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if hasattr(val, "model_dump"):
        return json.dumps(val.model_dump(mode="json"))
    return json.dumps(val)


class Database:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            url = os.environ.get("DATABASE_URL", "sqlite:///./tracewise-local.db")
            db_path = url[len("sqlite:///") :] if url.startswith("sqlite:///") else "./tracewise-local.db"
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def get_connection(self) -> Any:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return _ClosingConnection(conn)

    def _init_schema(self) -> None:
        with self.get_connection() as conn:
            conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'default',
                run_name TEXT NOT NULL,
                status TEXT NOT NULL,
                active_stage TEXT,
                input_manifest_hash TEXT NOT NULL,
                target_object_id TEXT,
                source_object_ids TEXT,
                product_name TEXT,
                reporting_period_start TEXT,
                reporting_period_end TEXT,
                stage_1_manifest_hash TEXT,
                stage_2_manifest_hash TEXT,
                stage_3_manifest_hash TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                section_id TEXT NOT NULL,
                section_number TEXT NOT NULL,
                section_title TEXT DEFAULT '',
                parent_claim TEXT,
                children_claims TEXT DEFAULT '[]',
                search_criteria TEXT DEFAULT '',
                source_document_mapped TEXT DEFAULT '[]',
                raw_statement TEXT NOT NULL,
                normalized_statement TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                entity_unit TEXT,
                reported_value TEXT,
                unit TEXT,
                numerator TEXT,
                denominator TEXT,
                reporting_period TEXT,
                population TEXT,
                subgroup TEXT,
                target_locator TEXT,
                evidence_hint TEXT,
                derivation TEXT,
                verification_result TEXT,
                status TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, claim_id),
                FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS claim_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                patch TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                claim_id TEXT,
                logical_path TEXT NOT NULL,
                version INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                producer_agent_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS approvals (
                approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                reviewer_role TEXT NOT NULL,
                expected_version INTEGER NOT NULL,
                manifest_hash TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS evaluation_results (
                claim_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                independent_result TEXT,
                report_value TEXT,
                discrepancy_category TEXT,
                reviewer_required INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, claim_id),
                FOREIGN KEY (run_id) REFERENCES runs (run_id) ON DELETE CASCADE
            );
            """
            )
            # Migrate older `claims` tables missing hierarchical columns
            existing_cols = {
                row["name"] for row in conn.execute("PRAGMA table_info(claims)").fetchall()
            }
            migrations = {
                "section_title": "TEXT DEFAULT ''",
                "parent_claim": "TEXT",
                "children_claims": "TEXT DEFAULT '[]'",
                "search_criteria": "TEXT DEFAULT ''",
                "source_document_mapped": "TEXT DEFAULT '[]'",
                "verification_result": "TEXT",
            }
            for col_name, col_def in migrations.items():
                if col_name not in existing_cols:
                    conn.execute(f"ALTER TABLE claims ADD COLUMN {col_name} {col_def}")


default_db = Database()


class RunRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or default_db

    def create_run(
        self,
        run_id: str,
        run_name: str,
        tenant_id: str = "default",
        target_object_id: str | None = None,
        source_object_ids: list[str] | None = None,
        product_name: str | None = None,
        reporting_period_start: str | None = None,
        reporting_period_end: str | None = None,
        input_manifest_hash: str = "00000000000000000000000000000000",
    ) -> dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sources_json = json.dumps(source_object_ids or [])
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, tenant_id, run_name, status, active_stage,
                    input_manifest_hash, target_object_id, source_object_ids,
                    product_name, reporting_period_start, reporting_period_end,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tenant_id,
                    run_name,
                    RunState.READY_FOR_STAGE_1.value,
                    None,
                    input_manifest_hash,
                    target_object_id,
                    sources_json,
                    product_name,
                    reporting_period_start,
                    reporting_period_end,
                    1,
                    now,
                    now,
                ),
            )
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["source_object_ids"] = json.loads(data["source_object_ids"] or "[]")
            return data

    def list_runs(self) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["source_object_ids"] = json.loads(d["source_object_ids"] or "[]")
                out.append(d)
            return out

    def transition(
        self,
        run_id: str,
        expected_version: int,
        new_state: RunState,
        active_stage: str | None = None,
        rework_stage: str | None = None,
    ) -> dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT status, version FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not row:
                raise ValueError(f"Run {run_id} not found")
            current_state = RunState(row["status"])
            current_version = row["version"]
            if current_version != expected_version:
                raise ValueError(
                    f"Concurrency conflict: expected version {expected_version}, got {current_version}"
                )
            validate_transition(current_state, new_state)
            conn.execute(
                """
                UPDATE runs
                SET status = ?, active_stage = ?, version = version + 1, updated_at = ?
                WHERE run_id = ? AND version = ?
                """,
                (new_state.value, active_stage, now, run_id, expected_version),
            )
            conn.execute(
                """
                INSERT INTO audit_events (run_id, actor_type, actor_id, action, object_type, object_id, details, created_at)
                VALUES (?, 'system', 'run_control_plane', 'transition', 'run', ?, ?, ?)
                """,
                (
                    run_id,
                    run_id,
                    json.dumps({"from": current_state.value, "to": new_state.value, "stage": active_stage}),
                    now,
                ),
            )
        return self.get_run(run_id)  # type: ignore[return-value]

    def set_manifest_hash(self, run_id: str, stage: str, manifest_hash: str) -> None:
        col = f"stage_{1 if stage == 'claims' else (2 if stage == 'rules' else 3)}_manifest_hash"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.db.get_connection() as conn:
            conn.execute(f"UPDATE runs SET {col} = ?, updated_at = ? WHERE run_id = ?", (manifest_hash, now, run_id))

    def get_latest_rework_stage(self, run_id: str) -> str | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT stage, decision FROM approvals
                WHERE run_id = ?
                ORDER BY approval_id DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
            if row and row["decision"] == "request_changes":
                return str(row["stage"])
            return None

    def record_approval(
        self,
        run_id: str,
        stage: str,
        reviewer_id: str,
        decision: str,
        expected_version: int,
        expected_manifest_hash: str,
        reviewer_note: str | None = None,
        reviewer_role: str = "reviewer",
    ) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        col_key = f"stage_{1 if stage == 'claims' else (2 if stage == 'rules' else 3)}_manifest_hash"
        current_manifest_hash = run.get(col_key) or ""
        approval_req = ApprovalRequest(
            reviewer_id=reviewer_id,
            decision=decision,
            expected_version=expected_version,
            expected_manifest_hash=expected_manifest_hash,
            current_version=run["version"],
            current_manifest_hash=current_manifest_hash or expected_manifest_hash,
            reviewer_role=reviewer_role,
        )
        validate_approval(approval_req)

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO approvals (run_id, stage, decision, reviewer_id, reviewer_role, expected_version, manifest_hash, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stage,
                    decision,
                    reviewer_id,
                    reviewer_role,
                    expected_version,
                    expected_manifest_hash,
                    reviewer_note,
                    now,
                ),
            )

        if decision == "approve":
            target_map = {
                "claims": RunState.CLAIMS_APPROVED,
                "rules": RunState.RULES_APPROVED,
                "evaluation": RunState.COMPLETE,
            }
            target_state = target_map[stage]
        else:
            target_state = RunState.CHANGES_REQUESTED

        return self.transition(run_id, expected_version, target_state, active_stage=None)


class ClaimRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or default_db

    def delete_claims_for_run(self, run_id: str) -> None:
        with self.db.get_connection() as conn:
            conn.execute("DELETE FROM claims WHERE run_id = ?", (run_id,))

    def save_claim(self, run_id: str, claim_data: dict[str, Any]) -> dict[str, Any]:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        claim_id = claim_data["claim_id"]
        parent_obj = claim_data.get("parent_claim") or {
            "raw_statement": claim_data.get("raw_statement", ""),
            "normalized_statement": claim_data.get("normalized_statement", ""),
            "claim_type": claim_data.get("claim_type", "other"),
            "entity_unit": claim_data.get("entity_unit") or "cases",
            "reported_value": claim_data.get("reported_value"),
            "unit": claim_data.get("unit"),
            "numerator": claim_data.get("numerator"),
            "denominator": claim_data.get("denominator"),
            "target_locator": claim_data.get("target_locator") or {},
        }
        children_obj = claim_data.get("children_claims") or []
        source_mapped = claim_data.get("source_document_mapped") or []

        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    claim_id, run_id, section_id, section_number, section_title,
                    parent_claim, children_claims, search_criteria, source_document_mapped,
                    raw_statement, normalized_statement, claim_type, entity_unit,
                    reported_value, unit, numerator, denominator,
                    reporting_period, population, subgroup, target_locator,
                    evidence_hint, derivation, verification_result, status,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, claim_id) DO UPDATE SET
                    section_title = excluded.section_title,
                    parent_claim = excluded.parent_claim,
                    children_claims = excluded.children_claims,
                    search_criteria = excluded.search_criteria,
                    source_document_mapped = excluded.source_document_mapped,
                    raw_statement = excluded.raw_statement,
                    normalized_statement = excluded.normalized_statement,
                    reported_value = excluded.reported_value,
                    entity_unit = excluded.entity_unit,
                    unit = excluded.unit,
                    evidence_hint = excluded.evidence_hint,
                    derivation = excluded.derivation,
                    verification_result = excluded.verification_result,
                    status = excluded.status,
                    version = claims.version + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    claim_id,
                    run_id,
                    claim_data.get("section_id", ""),
                    claim_data.get("section_number", ""),
                    claim_data.get("section_title", ""),
                    _dump_json(parent_obj, {}),
                    _dump_json(children_obj, []),
                    claim_data.get("search_criteria", ""),
                    _dump_json(source_mapped, []),
                    claim_data.get("raw_statement", ""),
                    claim_data.get("normalized_statement", ""),
                    claim_data.get("claim_type", "other"),
                    claim_data.get("entity_unit"),
                    str(claim_data.get("reported_value")) if claim_data.get("reported_value") is not None else None,
                    claim_data.get("unit"),
                    claim_data.get("numerator"),
                    claim_data.get("denominator"),
                    _dump_json(claim_data.get("reporting_period"), {}),
                    _dump_json(claim_data.get("population"), {}),
                    _dump_json(claim_data.get("subgroup"), None),
                    _dump_json(claim_data.get("target_locator"), {}),
                    _dump_json(claim_data.get("evidence_hint"), {}),
                    _dump_json(claim_data.get("derivation"), None),
                    _dump_json(claim_data.get("verification_result"), None),
                    claim_data.get("status", "draft"),
                    claim_data.get("version", 1),
                    now,
                    now,
                ),
            )
        return self.get_claim(run_id, claim_id)  # type: ignore[return-value]

    def get_claim(self, run_id: str, claim_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM claims WHERE run_id = ? AND claim_id = ?", (run_id, claim_id)
            ).fetchone()
            return self._row_to_claim(row) if row else None

    def list_claims(self, run_id: str, section_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            if section_id:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE run_id = ? AND section_id = ? ORDER BY claim_id",
                    (run_id, section_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM claims WHERE run_id = ? ORDER BY claim_id",
                    (run_id,),
                ).fetchall()
            return [self._row_to_claim(r) for r in rows]

    def update_claim_patch(
        self,
        run_id: str,
        claim_id: str,
        expected_version: int,
        patch: dict[str, Any],
        reviewer_reason: str,
        actor_id: str = "reviewer",
    ) -> dict[str, Any]:
        claim = self.get_claim(run_id, claim_id)
        if not claim:
            raise ValueError(f"Claim {claim_id} not found")
        if claim["version"] != expected_version:
            raise ValueError(
                f"Optimistic concurrency error: expected claim version {expected_version}, got {claim['version']}"
            )

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for k in (
            "raw_statement",
            "normalized_statement",
            "reported_value",
            "entity_unit",
            "unit",
            "search_criteria",
            "source_document_mapped",
            "children_claims",
        ):
            if k in patch and patch[k] is not None:
                claim[k] = patch[k]

        # Keep parent_claim synchronized with patched scalar fields
        parent_claim = claim.get("parent_claim") or {}
        if isinstance(parent_claim, dict):
            for k in ("raw_statement", "normalized_statement", "reported_value", "entity_unit", "unit"):
                if k in patch and patch[k] is not None:
                    parent_claim[k] = patch[k]

        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE claims
                SET raw_statement = ?, normalized_statement = ?, reported_value = ?,
                    entity_unit = ?, unit = ?, search_criteria = ?,
                    source_document_mapped = ?, children_claims = ?, parent_claim = ?,
                    version = version + 1, updated_at = ?
                WHERE run_id = ? AND claim_id = ? AND version = ?
                """,
                (
                    claim.get("raw_statement"),
                    claim.get("normalized_statement"),
                    str(claim.get("reported_value")) if claim.get("reported_value") is not None else None,
                    claim.get("entity_unit"),
                    claim.get("unit"),
                    claim.get("search_criteria", ""),
                    _dump_json(claim.get("source_document_mapped"), []),
                    _dump_json(claim.get("children_claims"), []),
                    _dump_json(parent_claim, {}),
                    now,
                    run_id,
                    claim_id,
                    expected_version,
                ),
            )
            conn.execute(
                """
                INSERT INTO claim_history (run_id, claim_id, version, patch, actor_id, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, claim_id, expected_version + 1, json.dumps(patch), actor_id, reviewer_reason, now),
            )
        return self.get_claim(run_id, claim_id)  # type: ignore[return-value]

    def _row_to_claim(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        json_fields = (
            "parent_claim",
            "children_claims",
            "source_document_mapped",
            "reporting_period",
            "population",
            "subgroup",
            "target_locator",
            "evidence_hint",
            "derivation",
            "verification_result",
        )
        for jf in json_fields:
            raw = d.get(jf)
            if isinstance(raw, str):
                try:
                    d[jf] = json.loads(raw)
                except json.JSONDecodeError:
                    pass
        if d.get("children_claims") is None:
            d["children_claims"] = []
        if d.get("source_document_mapped") is None:
            d["source_document_mapped"] = []
        return d


class ArtifactRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or default_db

    def add_artifact(self, artifact_data: dict[str, Any]) -> dict[str, Any]:
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, run_id, stage, claim_id, logical_path, version,
                    sha256, media_type, size_bytes, producer_agent_id, created_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    version = excluded.version,
                    sha256 = excluded.sha256,
                    size_bytes = excluded.size_bytes,
                    status = excluded.status
                """,
                (
                    artifact_data["artifact_id"],
                    artifact_data["run_id"],
                    artifact_data["stage"],
                    artifact_data.get("claim_id"),
                    artifact_data["logical_path"],
                    artifact_data.get("version", 1),
                    artifact_data["sha256"],
                    artifact_data.get("media_type", "application/json"),
                    artifact_data.get("size_bytes", 0),
                    artifact_data.get("producer_agent_id", "system"),
                    artifact_data.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                    artifact_data.get("status", "ready"),
                ),
            )
        return artifact_data

    def get_artifact(self, run_id: str, artifact_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND artifact_id = ?",
                (run_id, artifact_id),
            ).fetchone()
            return dict(row) if row else None

    def list_artifacts(
        self, run_id: str, stage: str | None = None, claim_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            query = "SELECT * FROM artifacts WHERE run_id = ?"
            params: list[Any] = [run_id]
            if stage:
                query += " AND stage = ?"
                params.append(stage)
            if claim_id:
                query += " AND claim_id = ?"
                params.append(claim_id)
            query += " ORDER BY created_at ASC"
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]


class EvaluationRepository:
    def __init__(self, db: Database | None = None):
        self.db = db or default_db

    def save_evaluation(self, run_id: str, claim_id: str, eval_data: dict[str, Any]) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO evaluation_results (
                    claim_id, run_id, status, independent_result, report_value,
                    discrepancy_category, reviewer_required, payload, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, claim_id) DO UPDATE SET
                    status = excluded.status,
                    independent_result = excluded.independent_result,
                    report_value = excluded.report_value,
                    discrepancy_category = excluded.discrepancy_category,
                    reviewer_required = excluded.reviewer_required,
                    payload = excluded.payload,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    claim_id,
                    run_id,
                    eval_data.get("status", "PLACEHOLDER"),
                    str(eval_data.get("independent_result")) if eval_data.get("independent_result") is not None else None,
                    str(eval_data.get("report_value")) if eval_data.get("report_value") is not None else None,
                    eval_data.get("discrepancy_category"),
                    1 if eval_data.get("reviewer_required") else 0,
                    json.dumps(eval_data),
                    now,
                ),
            )

    def list_evaluations(self, run_id: str) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM evaluation_results WHERE run_id = ?", (run_id,)).fetchall()
            res = []
            for r in rows:
                d = dict(r)
                if d.get("payload"):
                    try:
                        res.append(json.loads(d["payload"]))
                        continue
                    except json.JSONDecodeError:
                        pass
                res.append(d)
            return res


default_run_repo = RunRepository()
default_claim_repo = ClaimRepository()
default_artifact_repo = ArtifactRepository()
default_eval_repo = EvaluationRepository()
