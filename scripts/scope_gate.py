"""
Scope/decline gate, per specs/scope-gate.md.

classify_scope() is a pure function of a question string -> ScopeVerdict, same
isolation discipline as verify() and disagreement_detector.classify()
(writer-verifier.md Sec 7): no Writer/Verifier state, no side effects, callable
standalone against data/scope_gate.jsonl without running a brief.

Runs against corpus_access.all_abstracts() -- already-available corpus access,
no new fetch/cache mechanism -- to judge topical fit against the frozen 21
papers before a Writer call is ever made. This is a coarse, question-level
triage, not a per-claim faithfulness check; it exists so an out-of-scope
question gets an honest "this corpus can't answer that" instead of silently
running the full pipeline down to an empty/all-blocked brief that looks like
an ordinary failure (spec Sec 1).
"""

from __future__ import annotations

import corpus_access
from llm_client import call_llm, get_tool_call
from prompts import UNTRUSTED_SOURCE_CLAUSE, wrap_source
from schemas import DECLINE_REASONS, ScopeVerdict

_SCOPE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_scope_verdict",
        "description": "Decide whether a research question is in scope for this frozen RAG-paper corpus.",
        "parameters": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": ["in_scope", "decline"],
                    "description": (
                        "in_scope iff this is a genuine RAG research question that at least "
                        "one corpus paper plausibly bears on (not that the corpus fully "
                        "answers it -- only that attempting it is reasonable)."
                    ),
                },
                "decline_reason": {
                    "type": ["string", "null"],
                    "description": (
                        "Required iff label == decline, else null. off_topic: not about "
                        "RAG at all. out_of_corpus: a genuine RAG question, but no corpus "
                        "paper covers that sub-topic/technique."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": "One sentence explaining the verdict.",
                },
            },
            "required": ["label", "decline_reason", "rationale"],
        },
    },
}


def classify_scope(question: str) -> ScopeVerdict:
    abstracts = corpus_access.all_abstracts()
    sources = "\n\n".join(wrap_source(pid, text) for pid, text in abstracts.items() if text)

    system = (
        "You are the scope/decline gate in a RAG-paper research-brief pipeline, "
        "per specs/scope-gate.md. You are shown a research question and every "
        "paper's abstract in a FROZEN, FIXED 21-paper corpus about "
        "retrieval-augmented generation (RAG). Decide ONLY: is this question a "
        "genuine RAG research question that at least one corpus paper plausibly "
        "bears on? label=in_scope if so (even if no single paper fully answers "
        "it -- that's a separate downstream check). label=decline otherwise, "
        "with decline_reason=off_topic if the question isn't about RAG at all, "
        "or decline_reason=out_of_corpus if it's a genuine RAG question this "
        "specific corpus has no real coverage of. Call submit_scope_verdict.\n\n"
        + UNTRUSTED_SOURCE_CLAUSE
    )
    user = f"Question: {question}\n\nCorpus abstracts:\n{sources}"

    response = call_llm(
        role="scope_gate",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[_SCOPE_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_scope_verdict"}},
    )
    result = get_tool_call(response, "submit_scope_verdict")

    label = result["label"]
    decline_reason = result.get("decline_reason")
    rationale = result.get("rationale", "")

    if label == "in_scope":
        decline_reason = None
    elif decline_reason not in DECLINE_REASONS:
        raise ValueError(
            f"Gate returned decline but decline_reason={decline_reason!r} is not "
            f"in {DECLINE_REASONS}. Rationale given: {rationale!r}"
        )

    return ScopeVerdict(question=question, label=label, decline_reason=decline_reason, rationale=rationale)
