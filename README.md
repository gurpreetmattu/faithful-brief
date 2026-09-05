# faithful-brief

A research agent that reads recent arXiv papers on **RAG** and produces a structured brief
in which every claim traces to a specific source span, claims no source supports are detected
and **blocked** before they reach the output, and genuine cross-paper disagreements are
surfaced rather than blended away.

The summary itself is the commodity — anyone can wrap an LLM around a stack of papers. The
value here is that faithfulness is **provable**: the system is deliberately fed unfaithful
claims and its catch rate is measured — precision and recall, broken down by perturbation
type. The writing is the commodity; the trust is the product.

## Status

Spec baseline. See `CLAUDE.md` for invariants and build order, and `specs/` for contracts.
No agent code exists yet by design — the hand-labeled ground-truth eval set is built before
the agents it measures (invariant 1).

## Scope

The system runs on any AI topic; faithfulness is rigorously evaluated on **RAG specifically**,
because that is where ground truth can be personally verified. The methodology is
domain-independent — proving it required narrowing to a domain of competent judgment.

Sources are arXiv-only, by design. Known limitations are owned in `LIMITATIONS.md` (added
once the core is measured), not hidden.
