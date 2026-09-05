# CLAUDE.md

Steering file for every Claude Code session in this repo. Read before acting.
If a request conflicts with an INVARIANT below, stop and say so — do not comply silently.

---

## What this is

A research agent that reads recent arXiv papers on **RAG** and produces a structured brief in which:
- every claim traces to a specific source span,
- claims no source supports are **detected and blocked** before output, and
- genuine cross-paper disagreements are surfaced, not blended away.

The writing is the commodity. **The trust is the product.** Build effort belongs in
verification and disagreement detection, never in making prose prettier.

The single sentence this project exists to earn:
> "I deliberately fed the system unfaithful claims and measured what fraction it caught —
> precision/recall, broken down by perturbation type."

---

## INVARIANTS (non-negotiable)

1. **Eval-first.** No Writer/Verifier/agent code is written before the hand-labeled
   ground-truth claim set exists and is committed. The eval measures the agents;
   if agents come first, they get built to pass a loose eval — circular and worthless.

2. **Real papers only.** The corpus is real arXiv papers. No synthetic/fabricated source
   text, ever. A system that grades data fabricated to be gradable proves nothing.

3. **Contract before data, contract before code.** Schemas/specs land in `specs/` and are
   committed before the data or code they govern is written.

4. **Corpus is frozen and versioned.** The paper set is fixed and version-pinned from its
   first commit. Eval numbers are only comparable against a stable corpus.

5. **Writer and Verifier are separate.** The separation IS the faithfulness mechanism
   (an adversarial checker that does not share the writer's state), not a style choice.
   One agent that writes and checks its own work is a model grading its own homework.

6. **Ground truth is human.** Faithfulness labels are hand-produced by the domain-competent
   human (RAG, confirmed). An LLM may assist drafting claims for review, but LLM-produced
   labels never serve as ground truth — that collapses the anchor the whole eval depends on.

---

## Working standard

- Bar is **shipped, not demoed.** Happy-path-only is disqualifying. Documented failure modes,
  real P50/P95 latency + cost-per-brief, evals gating merges in CI, ADRs recording rejected
  alternatives, and a demo whose money-shot is the system **catching a bad claim**.
- **Every component must earn its place.** If something is decorative here, cut it — say so.
- **Spec-driven.** Contracts/schemas before implementation.
- Paper text is **untrusted input** — prompt-injection defense is a design concern from the
  moment the Writer ingests paper text, not a later bolt-on.

---

## Build order (mark position as we go)

- [x] 0. Confirm sub-area — **DONE: RAG confirmed** (labeler competence verified 3/3, incl. a flipped-meaning perturbation).
- [x] 1. **Claim schema** in `specs/` — DONE (`specs/claim-schema.md`, plus `specs/corpus-manifest.md` for the corpus contract).
- [x] 2. Pull + freeze 15–20 real RAG papers (abstracts + HTML where available) — DONE:
      21 papers frozen in `data/corpus.v1.json` (18 in-window cs.CL/cs.IR 2024-09–2026-08,
      3 verified anchors), fetched via `scripts/fetch_corpus.py`. All 21 have `arxiv_native`
      HTML; abstract+HTML hashes verified against cache.
- [ ] 3. Hand-build ground-truth claim set against the schema ← **CURRENT** (IN PROGRESS:
      15/~40-50 claims confirmed in `data/claims.jsonl` — 9 supported, 6 unsupported, one per
      `perturbation_type`. Every row was reviewed claim-by-claim against its `cited_span` by
      the domain-competent human reviewer per INVARIANT 6; none were LLM-labeled. Still open:
      claim-schema.md's own per-type minimum-count and body-vs-abstract-span decisions, and
      scaling this batch up to the full target ratio.)
- [ ] 4. Writer + Verifier (measured against the set from line one)
- [ ] 5. Prove it — precision/recall on injected perturbations, per type
- [ ] 6. Evals into CI (gate merges) — only after step 5 numbers are locally stable
- [ ] 7. Disagreement detection (needs its own labeled real-vs-apparent-conflict set)
- [ ] 8. UI surfacing citations, disagreements, blocked-claims panel, trust receipt
- [ ] 9. Stretch: retrieval-as-agent (+ arXiv MCP), recency-awareness, scope/decline gate

## Not yet (premature — do not scaffold before the step that needs it)

Docker, LLM gateway, caching, CI, hooks, subagents, MCP. Each wraps a working system that
does not exist yet. **Subagent note:** the Verifier is the natural isolated-context subagent
(adversarial separation maps onto context separation) — build it when the agents are real,
not before.
