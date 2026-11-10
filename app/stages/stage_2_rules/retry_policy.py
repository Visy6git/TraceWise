"""Bounded retry & loop budget configuration for Stage 2 rule engineering."""
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class RetryBudget:
    max_tool_calls: int = 80
    max_turns: int = 30
    max_repair_cycles: int = 2
    max_runtime_seconds: int = 900
    tool_calls: int = 0
    turns: int = 0
    repairs: int = 0
    signatures: list[str] = field(default_factory=list)

    def consume_tool_call(self, signature: str) -> None:
        self.tool_calls += 1
        self.signatures.append(signature)
        if self.tool_calls > self.max_tool_calls:
            raise RuntimeError("Tool-call budget exhausted")
        recent = self.signatures[-8:]
        if any(c >= 4 for c in Counter(recent).values()):
            raise RuntimeError("Repeated tool-call signature detected")

    def consume_repair(self) -> None:
        if self.repairs >= self.max_repair_cycles:
            raise RuntimeError("Repair-cycle budget exhausted")
        self.repairs += 1

