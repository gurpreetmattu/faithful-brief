"""
Verifier, per specs/writer-verifier.md Sec 5.

verify() is a pure function of a DraftClaim -> Verdict (spec Sec 7): it does not
require a Writer call, and does not care whether the DraftClaim came from a live
Writer or a data/claims.jsonl row. It never imports writer.py and never receives
Writer state -- the only input is the claim itself (spec Sec 1).

KNOWN LIMITATION (spec Sec 12, resolved for v1): the corpus-wide check in
_corpus_entailment() only looks at the 21 papers' abstracts, not full bodies, so it
fits in one call cheaply. A claim entailed only by body text with no trace in any
abstract will read as corpus_entailment="not_found" even though the corpus does, in
fact, support it elsewhere. This under-counts corpus-wide support; it does not
over-count it, so it never turns a real attribution_swap into a false pass.
"""

from __future__ import annotations

import corpus_access
from llm_client import call_llm, get_tool_call
from prompts import UNTRUSTED_SOURCE_CLAUSE, wrap_source
from schemas import DraftClaim, Verdict

_ENTAILMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_entailment",
        "description": "Report whether the cited span asserts the claim.",
        "parameters": {
            "type": "object",
            "properties": {
                "entailed": {
                    "type": "boolean",
                    "description": "true iff the span asserts the claim.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One sentence: why the span does or does not assert the claim.",
                },
            },
            "required": ["entailed", "rationale"],
        },
    },
}

_CORPUS_CHECK_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_corpus_check",
        "description": "Report whether any paper's abstract in the corpus asserts the claim.",
        "parameters": {
            "type": "object",
            "properties": {
                "entailed_elsewhere": {
                    "type": "boolean",
                    "description": "true iff some paper's abstract (any paper_id) asserts the claim.",
                },
                "supporting_paper_id": {
                    "type": ["string", "null"],
                    "description": "paper_id of the supporting abstract, or null if none.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One sentence explaining the finding.",
                },
            },
            "required": ["entailed_elsewhere", "supporting_paper_id", "rationale"],
        },
    },
}


def _cited_entailment(claim: DraftClaim) -> tuple:
    # Worded to match claim-schema.md Sec 6 step 3 exactly: "does this span assert
    # this claim" -- not "is this true in general" -- so the Verifier answers the
    # same question the human labeler answered, not a paraphrase of it.
    system = (
        "You are the Verifier in a faithfulness-checking pipeline. You will be shown "
        "one claim and one span from a paper it is attributed to. Answer ONLY: does "
        "this span assert this claim? Not whether the claim is true in general -- "
        "faithfulness is match-to-source, not truth. Call submit_entailment with your "
        "answer.\n\n" + UNTRUSTED_SOURCE_CLAUSE
    )
    user = (
        f"Claim: {claim.claim_text}\n\n"
        f"Cited span from {claim.cited_paper_id}:\n"
        + wrap_source(claim.cited_paper_id, claim.cited_span)
    )
    response = call_llm(
        role="verifier",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[_ENTAILMENT_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_entailment"}},
    )
    result = get_tool_call(response, "submit_entailment")
    entailed = "entailed" if result["entailed"] else "not_entailed"
    return entailed, result["rationale"]


def _corpus_entailment(claim: DraftClaim) -> tuple:
    abstracts = corpus_access.all_abstracts()
    sources = "\n\n".join(
        wrap_source(pid, text) for pid, text in abstracts.items() if text
    )
    system = (
        "You are the Verifier in a faithfulness-checking pipeline, checking whether "
        "a claim is supported ANYWHERE in a fixed corpus, not just by its cited "
        "paper. You will be shown a claim and every paper's abstract in the corpus. "
        "Call submit_corpus_check with your finding.\n\n" + UNTRUSTED_SOURCE_CLAUSE
    )
    user = f"Claim: {claim.claim_text}\n\nCorpus abstracts:\n{sources}"
    response = call_llm(
        role="verifier",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[_CORPUS_CHECK_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_corpus_check"}},
    )
    result = get_tool_call(response, "submit_corpus_check")
    corpus_entailment = "entailed_elsewhere" if result["entailed_elsewhere"] else "not_found"
    return corpus_entailment, result["rationale"]


def verify(claim: DraftClaim) -> Verdict:
    # Sec 5.0: no citation -- nothing to verify. corpus_entailment still runs as a
    # diagnostic (distinguishes "true but uncited" from a real plausible_addition),
    # but the verdict is block regardless.
    if not claim.cited_span:
        corpus_entailment, corpus_rationale = _corpus_entailment(claim)
        return Verdict(
            claim=claim,
            verdict="block",
            block_reason="no_citation",
            span_verified=None,
            cited_entailment=None,
            corpus_entailment=corpus_entailment,
            verifier_rationale=f"No cited_span given. {corpus_rationale}",
        )

    # Sec 5.1: mechanical, no LLM. Gates whether any LLM call happens at all.
    verified = corpus_access.span_verified(claim.cited_paper_id, claim.cited_span)
    if not verified:
        return Verdict(
            claim=claim,
            verdict="block",
            block_reason="span_not_found",
            span_verified=False,
            cited_entailment=None,
            corpus_entailment=None,
            verifier_rationale=(
                f"cited_span does not appear verbatim in {claim.cited_paper_id}'s "
                "extracted abstract or body text."
            ),
        )

    # Sec 5.2: isolated LLM call.
    cited_entailment, cited_rationale = _cited_entailment(claim)
    if cited_entailment == "entailed":
        return Verdict(
            claim=claim,
            verdict="pass",
            block_reason=None,
            span_verified=True,
            cited_entailment="entailed",
            corpus_entailment=None,
            verifier_rationale=cited_rationale,
        )

    # Sec 5.3: only reached on not_entailed.
    corpus_entailment, corpus_rationale = _corpus_entailment(claim)
    block_reason = (
        "not_entailed_elsewhere" if corpus_entailment == "entailed_elsewhere" else "not_entailed_nowhere"
    )
    return Verdict(
        claim=claim,
        verdict="block",
        block_reason=block_reason,
        span_verified=True,
        cited_entailment="not_entailed",
        corpus_entailment=corpus_entailment,
        verifier_rationale=f"{cited_rationale} {corpus_rationale}",
    )
