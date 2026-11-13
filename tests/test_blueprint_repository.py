"""Unit and integration tests for BlueprintRepository immutability, tenant isolation, and lifecycle."""
from __future__ import annotations

import pytest
from app.services.blueprint_repository import BlueprintRepository


def test_blueprint_immutability(isolated_env):
    repo: BlueprintRepository = isolated_env["blueprint_repo"]
    tenant = "tenant-a"
    bp_id = "bp-001"
    run_id = "run-100"

    manifest_v1 = {
        "blueprint_version": 1,
        "blueprint_id": bp_id,
        "target_document_type": "PBRER_SECTION_16_3",
        "created_from_learning_run_id": run_id,
        "section_key": "16.3",
        "title": "Section 16.3 Benefit-risk evaluation",
        "manifest_sha256": "hash_v1",
        "files": [],
    }

    # Register candidate v1
    repo.register_candidate(
        blueprint_id=bp_id,
        tenant_id=tenant,
        source_learning_run_id=run_id,
        version=1,
        status="candidate_review",
        manifest_hash="hash_v1",
        manifest=manifest_v1,
    )

    # Approve v1
    approved = repo.mark_approved(
        source_learning_run_id=run_id,
        manifest_hash="hash_v1",
        reviewer_id="rev-1",
        tenant_id=tenant,
    )
    assert approved is not None
    assert approved["version"] == 1
    assert approved["status"] == "approved"

    # Attempting to mutate an already approved version must fail
    with pytest.raises(ValueError, match="is approved and cannot be overwritten"):
        repo.register_candidate(
            blueprint_id=bp_id,
            tenant_id=tenant,
            source_learning_run_id=run_id,
            version=1,
            status="candidate_review",
            manifest_hash="hash_v1_tampered",
            manifest=manifest_v1,
        )


def test_blueprint_foreign_keys_and_cascade(isolated_env):
    repo: BlueprintRepository = isolated_env["blueprint_repo"]
    tenant = "tenant-a"
    bp_id = "bp-cascade-01"
    run_id = "run-cascade-01"

    manifest = {
        "blueprint_version": 1,
        "blueprint_id": bp_id,
        "manifest_sha256": "hash_casc",
        "files": [],
    }

    repo.register_candidate(
        blueprint_id=bp_id,
        tenant_id=tenant,
        source_learning_run_id=run_id,
        version=1,
        status="candidate_review",
        manifest_hash="hash_casc",
        manifest=manifest,
    )

    # Verify blueprint exists
    bp = repo.get(tenant, bp_id)
    assert bp is not None
    assert bp["active_version"] == 1

    # Delete parent blueprint
    with repo.db.get_connection() as conn:
        conn.execute("DELETE FROM section_blueprints WHERE tenant_id = ? AND blueprint_id = ?", (tenant, bp_id))

    # Blueprint should no longer exist
    assert repo.get(tenant, bp_id) is None


def test_tenant_isolation(isolated_env):
    repo: BlueprintRepository = isolated_env["blueprint_repo"]
    tenant_1 = "tenant-alpha"
    tenant_2 = "tenant-beta"

    bp_id = "bp-isolated"
    manifest = {"blueprint_id": bp_id, "manifest_sha256": "h1"}

    repo.register_candidate(
        blueprint_id=bp_id,
        tenant_id=tenant_1,
        source_learning_run_id="run-1",
        version=1,
        status="candidate_review",
        manifest_hash="h1",
        manifest=manifest,
    )
    repo.mark_approved(
        source_learning_run_id="run-1",
        manifest_hash="h1",
        reviewer_id="rev-1",
        tenant_id=tenant_1,
    )

    # Tenant 1 can read
    assert repo.get(tenant_1, bp_id) is not None
    assert len(repo.list_approved(tenant_id=tenant_1)) == 1

    # Tenant 2 CANNOT read tenant 1's blueprint
    assert repo.get(tenant_2, bp_id) is None
    assert len(repo.list_approved(tenant_id=tenant_2)) == 0

    # Generation record isolation
    gen_data = {
        "generation_id": "gen-001",
        "tenant_id": tenant_1,
        "run_name": "Gen 2026",
        "blueprint_id": bp_id,
        "blueprint_version": 1,
        "status": "created",
        "reporting_period_start": "2026-01-01",
        "reporting_period_end": "2026-12-31",
        "source_manifest_hash": "src-h1",
        "source_object_ids": ["file1.xlsx"],
    }
    repo.create_generation(gen_data)

    assert repo.get_generation("gen-001", tenant_id=tenant_1) is not None
    assert repo.get_generation("gen-001", tenant_id=tenant_2) is None
    assert len(repo.list_generations(tenant_id=tenant_1)) == 1
    assert len(repo.list_generations(tenant_id=tenant_2)) == 0


def test_generation_lifecycle_and_review(isolated_env):
    repo: BlueprintRepository = isolated_env["blueprint_repo"]
    tenant = "tenant-gamma"
    gen_id = "gen-123"

    gen_data = {
        "generation_id": gen_id,
        "tenant_id": tenant,
        "run_name": "Gen Gamma",
        "blueprint_id": "bp-test",
        "blueprint_version": 1,
        "status": "executing",
        "reporting_period_start": "2026-01-01",
        "reporting_period_end": "2026-12-31",
        "source_manifest_hash": "src-gamma",
        "source_object_ids": ["cases.xlsx"],
    }
    repo.create_generation(gen_data)

    # Update status to output_review
    repo.update_generation(
        generation_id=gen_id,
        tenant_id=tenant,
        status="output_review",
        output_manifest_hash="out-hash-123",
        artifacts_json=[{"artifact_id": "art-1", "path": "section.docx"}],
        compatibility_json={"status": "compatible"},
    )

    gen = repo.get_generation(gen_id, tenant_id=tenant)
    assert gen["status"] == "output_review"
    assert len(gen["artifacts_json"]) == 1
    assert gen["output_manifest_hash"] == "out-hash-123"

    # Review approval
    repo.record_generation_review(
        generation_id=gen_id,
        reviewer_id="clinician-1",
        decision="approve",
        expected_output_manifest_hash="out-hash-123",
        note="All numbers align with source extract",
        tenant_id=tenant,
    )

    reviewed = repo.get_generation(gen_id, tenant_id=tenant)
    assert reviewed["status"] == "complete"
