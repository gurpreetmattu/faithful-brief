"""
Disagreement Detector, per specs/disagreement-schema.md.

classify() is a pure function of a DisagreementCandidate -> DisagreementVerdict,
mirroring verifier.verify()'s Sec 7 discipline: it takes a candidate pair someone
has already identified (finding candidate pairs is explicitly NOT this detector's
job -- disagreement-schema.md Sec 1 scopes that to an eventual retrieval-style
problem) and classifies it: genuine or apparent, and if apparent, why.

KNOWN LIMITATION -- read before trusting eval_disagreement.py's numbers:
data/disagreements.jsonl has 5 hand-labeled rows, ALL `apparent`. Four
independent search passes across the 21-paper corpus (keyword grep, full
related-work reading, metric/scope-targeted hunting, benchmark/baseline-table
cross-referencing) found zero genuine examples -- see CLAUDE.md step 7. This
detector's recall on genuine disagreements is therefore UNMEASURED, not just
untested-but-probably-fine. A detector that always predicts "apparent" would
score perfectly against today's eval set; that is exactly the blind-strategy
failure disagreement-schema.md Sec 8 warns about, made concrete rather than
theoretical. Do not cite eval_disagreement.py's accuracy as evidence this
detector correctly identifies real contradictions -- it is only evidence it
correctly identifies apparent ones.
"""

from __future__ import annotations

from llm_client import call_llm, get_tool_call
from prompts import UNTRUSTED_SOURCE_CLAUSE, wrap_source
from schemas import APPARENT_REASONS, DisagreementCandidate, DisagreementVerdict

_CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_disagreement_verdict",
        "description": "Classify whether two spans from different papers genuinely contradict each other.",
        "parameters": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "enum": ["genuine", "apparent"],
                    "description": "genuine iff the spans actually contradict each other under the same conditions.",
                },
                "apparent_reason": {
                    "type": ["string", "null"],
                    "description": (
                        "Required iff label == apparent, else null. One of: "
                        "different_scope (different setting/dataset/task), "
                        "different_metric (measuring different things), "
                        "methodological_difference (different experimental setup produced "
                        "different numbers), not_actually_related (not really the same claim)."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": "One sentence: why this label, in light of both spans read in full context.",
                },
            },
            "required": ["label", "apparent_reason", "rationale"],
        },
    },
}


def classify(candidate: DisagreementCandidate) -> DisagreementVerdict:
    # Worded to match disagreement-schema.md Sec 5 step 3 exactly: read both
    # spans in full context, not in isolation -- the same "don't judge from an
    # isolated quote" discipline claim-schema.md Sec 6 applies to the Verifier.
    system = (
        "You are the Disagreement Detector in a research-brief pipeline, per "
        "specs/disagreement-schema.md. You are given a candidate pair: two spans "
        "from two different papers that surface-level appear to conflict on the "
        "same underlying question. The candidate has already been identified for "
        "you -- do not judge whether it's a good candidate, only classify it.\n\n"
        "Read both spans IN FULL CONTEXT (the surrounding text is included below), "
        "not as isolated quotes. Decide ONLY: do these spans actually contradict "
        "each other under the same conditions (genuine), or does the surface "
        "conflict dissolve once scope, metric, or method is accounted for, or is "
        "the pair not really about the same claim at all (apparent)? If apparent, "
        "you must also pick the single best-fitting apparent_reason from the "
        "closed set described in the tool schema -- do not invent a new reason. "
        "Call submit_disagreement_verdict with your answer.\n\n" + UNTRUSTED_SOURCE_CLAUSE
    )
    user = (
        f"Shared topic: {candidate.topic}\n\n"
        f"Span A, from {candidate.paper_a_id}:\n"
        + wrap_source(candidate.paper_a_id, candidate.span_a)
        + f"\n\nSpan B, from {candidate.paper_b_id}:\n"
        + wrap_source(candidate.paper_b_id, candidate.span_b)
    )
    response = call_llm(
        role="disagreement_detector",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=[_CLASSIFY_TOOL],
        tool_choice={"type": "function", "function": {"name": "submit_disagreement_verdict"}},
    )
    result = get_tool_call(response, "submit_disagreement_verdict")

    label = result["label"]
    apparent_reason = result.get("apparent_reason")
    rationale = result.get("rationale", "")

    if label == "genuine":
        # Defensive: force null regardless of what the model returned alongside
        # a genuine label, so a stray non-null value can never violate the
        # DisagreementVerdict invariant that genuine carries no apparent_reason.
        apparent_reason = None
    elif apparent_reason not in APPARENT_REASONS:
        # The model drifted outside the closed taxonomy despite the schema
        # constraint (e.g. a close-but-wrong string). Fail loudly rather than
        # silently coercing to a guessed reason -- disagreement-schema.md Sec 3
        # is explicit that apparent_reason must never be a lazy catch-all.
        raise ValueError(
            f"Detector returned apparent but apparent_reason={apparent_reason!r} "
            f"is not in the closed taxonomy {APPARENT_REASONS}. Rationale given: {rationale!r}"
        )

    return DisagreementVerdict(
        candidate=candidate,
        label=label,
        apparent_reason=apparent_reason,
        rationale=rationale,
    )
