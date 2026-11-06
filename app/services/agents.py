"""Backward-compatible shim for app.services.agents.
Delegates to the modular agent architecture in app.agents.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from queue import Queue
from typing import Any

from ..agents.orchestrator.agent import MultiAgentOrchestrator, SectionMapping
from ..agents.explorer.agent import ExplorerAgent
from ..agents.claims.agent import ClaimsAgent
from ..agents.evidence.agent import EvidenceDiscoveryAgent
from ..agents.rule_engineer.agent import RuleEngineerAgent
from ..agents.validator.agent import ValidatorAgent
from ..services.bedrock import is_bedrock_available, converse_sonnet, DEFAULT_SONNET_MODEL_ID


@dataclass
class A2AMessage:
    message_id: str
    sender: str
    recipient: str
    intent: str
    payload: dict[str, Any]


__all__ = [
    "MultiAgentOrchestrator",
    "SectionMapping",
    "A2AMessage",
    "ExplorerAgent",
    "ClaimsAgent",
    "EvidenceDiscoveryAgent",
    "RuleEngineerAgent",
    "ValidatorAgent",
    "is_bedrock_available",
    "converse_sonnet",
]
