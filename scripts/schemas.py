"""
Data shapes shared by writer.py, verifier.py, and run_brief.py, per
specs/writer-verifier.md Sec 4, Sec 5, Sec 9.

DraftClaim's fields are a strict subset of a data/claims.jsonl row (claim_text,
cited_paper_id, cited_span) -- that overlap is what makes a live Writer output and a
ground-truth row interchangeable inputs to verify() (spec Sec 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class DraftClaim:
    claim_text: str
    cited_paper_id: str
    cited_span: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "DraftClaim":
        return DraftClaim(
            claim_text=d["claim_text"],
            cited_paper_id=d["cited_paper_id"],
            cited_span=d.get("cited_span"),
        )


# spec Sec 5's verdict table, closed set.
BLOCK_REASONS = {
    "no_citation",
    "span_not_found",
    "not_entailed_elsewhere",
    "not_entailed_nowhere",
}


@dataclass
class Verdict:
    claim: DraftClaim
    verdict: str  # "pass" | "block"
    block_reason: Optional[str] = None  # one of BLOCK_REASONS, or None iff verdict == pass
    span_verified: Optional[bool] = None  # None iff cited_span was null (Sec 5.0 skips it)
    cited_entailment: Optional[str] = None  # "entailed" | "not_entailed" | None (not reached)
    corpus_entailment: Optional[str] = None  # "entailed_elsewhere" | "not_found" | None (not run)
    verifier_rationale: str = ""

    def __post_init__(self):
        if self.verdict not in ("pass", "block"):
            raise ValueError(f"verdict must be 'pass' or 'block', got {self.verdict!r}")
        if self.verdict == "pass" and self.block_reason is not None:
            raise ValueError("a pass verdict must not carry a block_reason")
        if self.verdict == "block" and self.block_reason not in BLOCK_REASONS:
            raise ValueError(f"block verdict needs a block_reason in {BLOCK_REASONS}, got {self.block_reason!r}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claim"] = self.claim.to_dict()
        return d


# disagreement-schema.md Sec 3's closed taxonomy.
APPARENT_REASONS = {
    "different_scope",
    "different_metric",
    "methodological_difference",
    "not_actually_related",
}


@dataclass
class DisagreementCandidate:
    """
    One row of disagreement-schema.md Sec 4: a pair of spans from two different
    corpus papers, both bearing on the same underlying question. Candidate
    generation (finding which pairs to compare) is out of scope per spec Sec 1 --
    this is just the classification unit, human-identified today.
    """

    paper_a_id: str
    paper_b_id: str
    topic: str
    span_a: str
    span_b: str

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "DisagreementCandidate":
        return DisagreementCandidate(
            paper_a_id=d["paper_a_id"],
            paper_b_id=d["paper_b_id"],
            topic=d["topic"],
            span_a=d["span_a"],
            span_b=d["span_b"],
        )


@dataclass
class DisagreementVerdict:
    candidate: DisagreementCandidate
    label: str  # "genuine" | "apparent"
    apparent_reason: Optional[str] = None  # one of APPARENT_REASONS, or None iff label == genuine
    rationale: str = ""

    def __post_init__(self):
        if self.label not in ("genuine", "apparent"):
            raise ValueError(f"label must be 'genuine' or 'apparent', got {self.label!r}")
        if self.label == "genuine" and self.apparent_reason is not None:
            raise ValueError("a genuine label must not carry an apparent_reason")
        if self.label == "apparent" and self.apparent_reason not in APPARENT_REASONS:
            raise ValueError(
                f"apparent label needs apparent_reason in {APPARENT_REASONS}, got {self.apparent_reason!r}"
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["candidate"] = self.candidate.to_dict()
        return d


@dataclass
class CallLog:
    role: str  # "writer" | "verifier"
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    timestamp: str  # ISO datetime

    def to_dict(self) -> dict:
        return asdict(self)
