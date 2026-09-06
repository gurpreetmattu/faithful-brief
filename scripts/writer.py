"""
Writer, per specs/writer-verifier.md Sec 4.

draft_brief() takes one user question, gives the model all 21 corpus abstracts plus
a get_paper_body tool, and loops on tool calls until the model submits its draft
claims via a submit_draft_claims tool call. Output is a list of DraftClaim -- the
same shape as a data/claims.jsonl row minus the label fields (spec Sec 4) -- with no
verification performed here. Verification is entirely verifier.py's job (Sec 1: the
Writer and Verifier share no state, and that includes the Writer never grading its
own claims).
"""

from __future__ import annotations

import json

import corpus_access
from llm_client import call_llm
from prompts import UNTRUSTED_SOURCE_CLAUSE, wrap_source
from schemas import DraftClaim

_GET_PAPER_BODY_TOOL = {
    "type": "function",
    "function": {
        "name": "get_paper_body",
        "description": (
            "Fetch the full extracted body text of one paper from the frozen corpus, "
            "by its exact paper_id (including version suffix, e.g. '2005.11401v4'). "
            "Use this before citing a span you haven't already seen in the abstract."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "paper_id": {
                    "type": "string",
                    "description": "Exact corpus paper_id, version suffix included.",
                }
            },
            "required": ["paper_id"],
        },
    },
}

_SUBMIT_CLAIMS_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_draft_claims",
        "description": "Submit the final list of draft claims for the brief.",
        "parameters": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_text": {
                                "type": "string",
                                "description": "One atomic assertion -- single subject, predicate, value/relationship.",
                            },
                            "cited_paper_id": {
                                "type": "string",
                                "description": "Exact corpus paper_id the claim is attributed to.",
                            },
                            "cited_span": {
                                "type": "string",
                                "description": "Verbatim span from cited_paper_id's abstract or body that supports the claim.",
                            },
                        },
                        "required": ["claim_text", "cited_paper_id", "cited_span"],
                    },
                }
            },
            "required": ["claims"],
        },
    },
}

_SYSTEM = (
    "You are the Writer in a faithfulness-checking research brief pipeline. You "
    "will answer one research question using ONLY the papers in the frozen corpus "
    "below. For every claim you make:\n"
    "- claim_text must be one atomic assertion (a single subject, predicate, and "
    "value/relationship -- if it could be half-true, split it into separate claims).\n"
    "- cited_paper_id must be one of the corpus paper_ids shown to you, exactly as "
    "given (version suffix included).\n"
    "- cited_span must be copied VERBATIM from that paper's abstract or body -- "
    "never paraphrased, never invented. If you have not seen the exact wording in "
    "context, call get_paper_body to read the paper's full text before citing a "
    "span from it.\n"
    "Call get_paper_body as many times as you need, then call submit_draft_claims "
    "exactly once with your final list.\n\n" + UNTRUSTED_SOURCE_CLAUSE
)


def _abstracts_block() -> str:
    return "\n\n".join(
        wrap_source(pid, text) for pid, text in corpus_access.all_abstracts().items() if text
    )


def draft_brief(question: str, max_tool_rounds: int = 6) -> list:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"Research question: {question}\n\n"
                f"Corpus abstracts (paper_ids you may cite):\n{_abstracts_block()}"
            ),
        },
    ]
    tools = [_GET_PAPER_BODY_TOOL, _SUBMIT_CLAIMS_TOOL]

    for _ in range(max_tool_rounds):
        response = call_llm(role="writer", messages=messages, tools=tools, tool_choice="auto")
        message = response["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []

        submit = next(
            (c for c in tool_calls if c["function"]["name"] == "submit_draft_claims"), None
        )
        if submit is not None:
            claims = json.loads(submit["function"]["arguments"])["claims"]
            return [DraftClaim.from_dict(c) for c in claims]

        if not tool_calls:
            # Model stopped without submitting -- nudge it once rather than looping forever.
            messages.append({"role": "assistant", "content": message.get("content") or ""})
            messages.append(
                {
                    "role": "user",
                    "content": "Please call submit_draft_claims now with your final list of claims.",
                }
            )
            continue

        messages.append(
            {"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls}
        )
        for call in tool_calls:
            if call["function"]["name"] == "get_paper_body":
                args = json.loads(call["function"]["arguments"])
                result = corpus_access.get_paper_body(args["paper_id"])
            else:
                result = f"ERROR: unknown tool '{call['function']['name']}'"
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": result}
            )

    raise RuntimeError(
        f"Writer did not submit draft claims within {max_tool_rounds} tool-call rounds."
    )
