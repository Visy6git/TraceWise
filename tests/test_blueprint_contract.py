from __future__ import annotations

import pytest
from app.schemas.blueprint import SectionReproductionBlueprint


def valid_blueprint() -> dict:
    return {
        "blueprint_id": "bp_test",
        "version": 1,
        "source_learning_run_id": "learning-1",
        "source_stage_1_manifest_hash": "a" * 64,
        "source_stage_2_manifest_hash": "b" * 64,
        "created_at": "2026-11-13T00:00:00Z",
        "section_structure": [{
            "block_id": "s163", "section_number": "16.3", "order": 0,
            "block_type": "heading", "title": "Section 16.3",
        }],
        "datasets": [{"dataset_id": "cases", "purpose": "Case source"}],
        "claims": [{
            "claim_id": "CLM-1", "section_number": "16.3.1",
            "target_locator": {"block_id": "b1"}, "raw_statement": "10 cases",
            "purpose": "Count eligible cases", "entity_definition": "Distinct case", "unit": "cases",
            "dataset_ids": ["cases"],
        }],
    }


def test_valid_blueprint_contract_parses():
    model = SectionReproductionBlueprint.model_validate(valid_blueprint())
    assert model.section_number == "16.3"
    assert model.claims[0].dataset_ids == ["cases"]


def test_blueprint_rejects_unknown_dataset_reference():
    data = valid_blueprint()
    data["claims"][0]["dataset_ids"] = ["not-in-blueprint"]
    with pytest.raises(ValueError, match="unknown datasets"):
        SectionReproductionBlueprint.model_validate(data)


def test_blueprint_rejects_duplicate_claim_ids():
    data = valid_blueprint()
    data["claims"].append(dict(data["claims"][0]))
    with pytest.raises(ValueError, match="unique"):
        SectionReproductionBlueprint.model_validate(data)
