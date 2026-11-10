"""Tests for LMStudioStrandsModel tool calling and hierarchical Strands claim tools."""
from __future__ import annotations

import json

import httpx
from strands import Agent

from app.config import get_active_llm_provider, is_live_llm_enabled
from app.services import bedrock, lmstudio
from app.services.lmstudio import (
    LMStudioStrandsModel,
    _clean_thinking_tags,
    invoke_lmstudio,
    normalize_base_url,
)
from app.stages.stage_1_claims.claim_tools import ClaimToolsetContext, create_claim_extraction_tools


def test_normalize_and_thinking_tag_cleanup():
    assert normalize_base_url("http://127.0.0.1:1234") == "http://127.0.0.1:1234/v1"
    assert normalize_base_url("http://127.0.0.1:1234/v1/") == "http://127.0.0.1:1234/v1"
    raw = "<think>\nReasoning...\n</think>\nFinal output"
    assert _clean_thinking_tags(raw) == "Final output"


def test_invoke_lmstudio_and_provider_routing(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json=None, **kwargs):
            assert url.endswith("/chat/completions")
            return FakeResp()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(lmstudio, "LMSTUDIO_ENABLED", True)
    assert invoke_lmstudio("ping") == '{"ok": true}'

    monkeypatch.setattr("app.config.LLM_PROVIDER", "lmstudio")
    monkeypatch.setattr("app.config.LMSTUDIO_ENABLED", True)
    monkeypatch.setattr("app.config.BEDROCK_ENABLED", False)
    assert get_active_llm_provider() == "lmstudio"
    assert is_live_llm_enabled() is True

    monkeypatch.setattr(lmstudio, "invoke_lmstudio", lambda prompt, **kwargs: f"lm:{prompt}")
    assert bedrock.invoke_bedrock("abc") == "lm:abc"


def test_strands_agent_registers_hierarchical_claims_via_tool_call(isolated_env):
    run_repo = isolated_env["run_repo"]
    claim_repo = isolated_env["claim_repo"]
    run = run_repo.create_run(
        run_id="run-strands-1",
        run_name="Strands Tool Test",
        input_manifest_hash="a" * 32,
    )

    ctx = ClaimToolsetContext(
        run_id=run["run_id"],
        target_filename="PBRER.docx",
        sections_by_number={
            "16.3.1.1": {"section_id": "sec_16_3_1_1", "number": "16.3.1.1", "title": "Hepatic events"}
        },
        uploaded_filenames=["01_Hepatic_CSMR.xlsx"],
        per_file_mds={"01_Hepatic_CSMR.xlsx": "# Hepatic CSMR Summary\nSheet `Case Listing`, header_row_index=3"},
    )
    tools = create_claim_extraction_tools(ctx)

    call_seq = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_seq["n"] += 1
        body = json.loads(request.content.decode("utf-8"))
        # Turn 1: intentional invalid call with empty search_criteria to test validation guard
        if call_seq["n"] == 1:
            assert any(t["function"]["name"] == "register_claim_group" for t in body["tools"])
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "tc_bad",
                                        "type": "function",
                                        "function": {
                                            "name": "register_claim_group",
                                            "arguments": json.dumps(
                                                {
                                                    "section_number": "16.3.1.1",
                                                    "parent_statement": "235/500 cases",
                                                    "parent_normalized_statement": "235 cases",
                                                    "parent_claim_type": "distinct_case_count",
                                                    "parent_entity_unit": "Distinct case",
                                                    "parent_reported_value": "235",
                                                    "search_criteria": "",
                                                    "source_document_mapped": ["01_Hepatic_CSMR.xlsx"],
                                                    "hint_text": "Filter hepatic SMQ.",
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        # Turn 2: assert validation error was fed back to Strands, then issue valid hierarchical claim call
        if call_seq["n"] == 2:
            tool_msgs = [m for m in body["messages"] if m.get("role") == "tool"]
            assert any("VALIDATION_ERROR" in m["content"] and "search_criteria" in m["content"] for m in tool_msgs)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "tc_good",
                                        "type": "function",
                                        "function": {
                                            "name": "register_claim_group",
                                            "arguments": json.dumps(
                                                {
                                                    "section_number": "16.3.1.1",
                                                    "parent_statement": "235/500 cases were hepatic adverse events",
                                                    "parent_normalized_statement": "235 interval hepatic cases out of 500 cumulative",
                                                    "parent_claim_type": "distinct_case_count",
                                                    "parent_entity_unit": "Distinct case",
                                                    "parent_reported_value": "235",
                                                    "parent_unit": "cases",
                                                    "parent_numerator": "235",
                                                    "parent_denominator": "500",
                                                    "search_criteria": "MedDRA SMQ Drug related hepatic disorders",
                                                    "source_document_mapped": ["01_Hepatic_CSMR.xlsx"],
                                                    "children_claims": [
                                                        {
                                                            "raw_statement": "15 cases led to fatal outcome",
                                                            "reported_value": "15",
                                                            "relationship": "fatal_subset",
                                                        }
                                                    ],
                                                    "hint_text": "Load Case Listing header row 3, deduplicate Case Number.",
                                                }
                                            ),
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Registered CLM-0001."},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    model = LMStudioStrandsModel(
        model_id="mock-strands",
        base_url="http://mock.local/v1",
        transport=httpx.MockTransport(handler),
    )
    agent = Agent(
        name="TestClaimExtractor",
        system_prompt="Extract claims using register_claim_group.",
        model=model,
        tools=tools,
    )
    agent("Extract Section 16.3.1.1 claims.")

    persisted = claim_repo.list_claims("run-strands-1")
    assert len(persisted) == 1
    c = persisted[0]
    assert c["reported_value"] == "235"
    assert c["search_criteria"] == "MedDRA SMQ Drug related hepatic disorders"
    assert c["source_document_mapped"] == ["01_Hepatic_CSMR.xlsx"]
    assert len(c["children_claims"]) == 1
    assert c["children_claims"][0]["reported_value"] == "15"
    assert c["children_claims"][0]["relationship"] == "fatal_subset"

