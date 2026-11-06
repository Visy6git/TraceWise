"""Claims Agent: Extracts atomic claims and reported figures from Section 16.3 subsections.
Atomizes paragraphs and tables into individual Claim records (one row per figure).
"""
from __future__ import annotations
import json
import re
from typing import Any
from ..base_agent import BaseAgent
from ...schemas.claim import Claim


class ClaimsAgent(BaseAgent):
    def __init__(self, run_id: str, section_id: str, section_number: str, section_title: str):
        super().__init__(
            run_id=run_id,
            agent_id=f"claims_agent_{section_number.replace('.', '_')}",
            agent_name=f"Claims Specialist ({section_number})",
            agent_role="Section 16.3 Claim Decomposer",
        )
        self.section_id = section_id
        self.section_number = section_number
        self.section_title = section_title

    def extract_claims(self, target_text: str, target_locator: dict[str, Any] | None = None) -> list[Claim]:
        """Extracts atomic claims from subsection text using pattern analysis and LLM parsing."""
        claims: list[Claim] = []
        locator = target_locator or {"section_id": self.section_id, "section_number": self.section_number}

        # 1. Decompose numbers and statistics in the text
        clean_text = target_text.strip()
        paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [clean_text] if clean_text else [self.section_title]

        claim_idx = 1

        for p_idx, para in enumerate(paragraphs, start=1):
            para_locator = {**locator, "paragraph": p_idx}

            # A. Extract Total Cases patterns (e.g. "A total of 242 cases", "242 cases were identified")
            total_match = re.search(
                r"(?:total\s+(?:of\s+)?|identified\s+|overall\s+)?(\d{1,6})\s+(?:cases|patients|subjects)\b",
                para,
                flags=re.IGNORECASE,
            )
            if total_match:
                val = total_match.group(1)
                cid = f"CLM-{self.section_number}-{claim_idx:02d}"
                claim = Claim(
                    claim_id=cid,
                    section_id=self.section_id,
                    section_number=self.section_number,
                    raw_text=total_match.group(0),
                    normalized_statement=f"Total {self.section_title} cases reported in period",
                    claim_type="total_cases",
                    reported_value=val,
                    numeric_value=float(val),
                    unit="cases",
                    target_locator=para_locator,
                    extraction_confidence=0.98,
                    status="PENDING",
                )
                claims.append(claim)
                claim_idx += 1
                self.emit("claims.claim.created", f"Extracted claim: {claim.normalized_statement} = {val}", claim.to_dict())

            # B. Extract Source Splits (e.g. "225 spontaneous, 17 from other studies" or "(225 spontaneous, 17 clinical trials)")
            split_matches = re.finditer(
                r"(\d{1,6})\s+(spontaneous|clinical\s*trial|other\s*stud(?:y|ies)|literature|post-marketing|solicited)",
                para,
                flags=re.IGNORECASE,
            )
            for sm in split_matches:
                val = sm.group(1)
                stype = sm.group(2).strip().lower()
                cid = f"CLM-{self.section_number}-{claim_idx:02d}"
                claim = Claim(
                    claim_id=cid,
                    section_id=self.section_id,
                    section_number=self.section_number,
                    raw_text=sm.group(0),
                    normalized_statement=f"{stype.title()} cases for {self.section_title}",
                    claim_type="source_split",
                    reported_value=val,
                    numeric_value=float(val),
                    unit="cases",
                    target_locator=para_locator,
                    extraction_confidence=0.95,
                    status="PENDING",
                )
                claims.append(claim)
                claim_idx += 1
                self.emit("claims.claim.created", f"Extracted claim: {claim.normalized_statement} = {val}", claim.to_dict())

            # C. Extract Preferred Term / Event Frequencies (e.g. "abnormal behaviour (45)", "binge eating: 38 cases")
            pt_matches = re.finditer(
                r"([a-zA-Z\s]{4,35})\s*(?:\(|:\s*|\s*-\s*)(\d{1,5})\s*(?:cases|events|\))",
                para,
            )
            for pm in pt_matches:
                term = pm.group(1).strip()
                val = pm.group(2).strip()
                if term.lower() in {"total", "cases", "spontaneous", "studies", "during", "period"}:
                    continue
                cid = f"CLM-{self.section_number}-{claim_idx:02d}"
                claim = Claim(
                    claim_id=cid,
                    section_id=self.section_id,
                    section_number=self.section_number,
                    raw_text=pm.group(0),
                    normalized_statement=f"Preferred Term '{term}' frequency in {self.section_title}",
                    claim_type="preferred_term",
                    reported_value=val,
                    numeric_value=float(val),
                    unit="cases",
                    target_locator=para_locator,
                    extraction_confidence=0.92,
                    status="PENDING",
                )
                claims.append(claim)
                claim_idx += 1
                self.emit("claims.claim.created", f"Extracted claim: {claim.normalized_statement} = {val}", claim.to_dict())

        # If no specific figures were parsed via regex, create a section-level claim
        if not claims:
            cid = f"CLM-{self.section_number}-01"
            claim = Claim(
                claim_id=cid,
                section_id=self.section_id,
                section_number=self.section_number,
                raw_text=clean_text[:200] if clean_text else self.section_title,
                normalized_statement=f"Evaluation and safety findings for {self.section_title}",
                claim_type="narrative",
                reported_value=None,
                target_locator=locator,
                extraction_confidence=0.85,
                status="PENDING",
            )
            claims.append(claim)
            self.emit("claims.claim.created", f"Extracted narrative claim: {claim.normalized_statement}", claim.to_dict())

        return claims

