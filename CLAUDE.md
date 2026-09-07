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
- [x] 3. Hand-build ground-truth claim set against the schema — DONE: 44 claims confirmed in
      `data/claims.jsonl` — 24 supported, 20 unsupported (~55/45), every `perturbation_type`
      at or above the resolved floor of 3 (entity_swap 4, scope_broadening 4,
      magnitude_change 3, causal_inversion 3, attribution_swap 3, plausible_addition 3),
      20/21 corpus papers used. Every row was reviewed claim-by-claim against its
      `cited_span` by the domain-competent human reviewer per INVARIANT 6; none were
      LLM-labeled. All 42 non-null `cited_span`s mechanically re-verified verbatim against
      the frozen corpus cache (the 2 null-span rows are deliberate: `plausible_addition`
      claims with zero support anywhere in the source, confirmed by the human reviewer).
      `claim-schema.md`'s per-type minimum-count and body-vs-abstract-span decisions are
      resolved (see its "Resolved decisions" section). Known open wrinkle, not blocking:
      arXiv's abstract API field sometimes preserves raw LaTeX escapes (e.g. "5.0\%",
      "$\\text{GeAR}$") not present in the rendered page — worked around per-claim by
      pasting the verbatim cached text, not fixed at the source.
- [ ] 4. Writer + Verifier (measured against the set from line one) ← **CURRENT**:
      contract in `specs/writer-verifier.md`; code written in `scripts/` (`writer.py`,
      `verifier.py`, `corpus_access.py`, `schemas.py`, `prompts.py`, `llm_client.py`,
      `run_brief.py`). Two providers wired (Groq primary, Hugging Face fallback on
      rate-limit or generation failure — Groq's free tier is tight enough that a real
      run needs it); `call_log.jsonl` + optional Langfuse tracing per Sec 9.
      Live-verified: `verify()` run standalone against 5 real `data/claims.jsonl` rows
      (bypassing the Writer, per Sec 7) — every verdict matched the human label. One
      full `run_brief.py` brief run end-to-end and correctly BLOCKED a real bad claim
      (cited span didn't support the claim text, even though the same paper's
      abstract elsewhere did — `not_entailed_elsewhere`). Not yet done: this was one
      brief with one drafted claim (small-model + tight-budget output was thin);
      step 5's actual precision/recall run against all 44 ground-truth claims hasn't
      been done.
- [x] 5. Prove it — precision/recall on injected perturbations, per type — DONE:
      full run of `scripts/eval_verifier.py` against all 44 rows in
      `data/claims.jsonl`, `verify()` called directly (bypassing the Writer, per
      writer-verifier.md Sec 7). **n=44, TP=20, FP=2, FN=0, TN=22 — accuracy 0.955,
      precision 0.909, recall 1.000, f1 0.952. Recall is 100% in every one of the
      six `perturbation_type`s** (attribution_swap 3/3, causal_inversion 3/3,
      entity_swap 4/4, magnitude_change 3/3, plausible_addition 3/3,
      scope_broadening 4/4) — the Verifier missed zero unfaithful claims. The 2 FPs
      (`claim-16`, `claim-33`) are both cases where the cited span cleanly supports
      the claim and the Verifier wrongly blocked it anyway — a real miss, not a
      labeling ambiguity, and a defensible failure direction for a faithfulness
      checker (over-cautious rather than permissive).
      Getting here required real infrastructure work, not just running a script:
      Groq's free tier (8000 tok/min + 200,000 tok/day) turned out to be a
      per-*organization* pool shared across all 13 `GROQ_API_KEY_N` values (same
      org ID in every response — confirmed live, including a side-by-side
      rate-limit-header dump across all 13 keys), so key rotation bought nothing;
      Hugging Face's monthly free credit ran out mid-eval and didn't reliably
      recover; added Gemini and OpenRouter as genuinely independent-quota
      fallbacks (`llm_client.py`, four providers in order: groq → gemini →
      openrouter → huggingface) plus a self-imposed per-minute pacer for Groq and
      a `data/logs/eval_checkpoint.jsonl` checkpoint so repeated interruptions
      (rate limits, and separately the host machine repeatedly running low on
      memory) never re-spent budget on already-evaluated claims.
- [x] 6. Evals into CI (gate merges) — DONE: tiered design implemented, pushed,
      and live-gating. `.github/workflows/fast-checks.yml` (every push/PR, no
      LLM calls: schema validation + mechanical `cited_span` re-verification
      via `scripts/check_claims_integrity.py`, always gates) and
      `.github/workflows/verifier-eval.yml` (only on changes touching
      Writer/Verifier code, specs/, or the ground-truth data, plus manual
      dispatch: the real 44-claim live eval, gates on recall only —
      `scripts/eval_verifier.py` exits 1 iff recall < 1.000, per the run-to-run
      LLM variance observed this session; precision is reported, not
      blocking). Repo is at `github.com/gurpreetmattu/faithful-brief`
      (**public** — GitHub only enforces branch protection on private repos on
      paid org plans, discovered live when the free-tier warning appeared;
      going public was the honest fix given the project's own thesis is
      showing real eval numbers, not a workaround). `fast-checks` confirmed
      green on a real push; a real CI failure was caught and fixed along the
      way (`data/cache/` was gitignored, so a clean CI checkout had no
      artifacts for `check_claims_integrity.py`'s span re-verification to
      check against — it only ever passed locally because the cache already
      existed on disk; fixed by committing `data/cache/`, since
      `corpus.v1.json`'s `sha256_content` hashes were always meant to pin
      those exact files per INVARIANT 4). All 4 Actions secrets
      (`GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `HF_TOKEN`)
      added and rotated (original values were briefly pasted into this
      session's chat, so all 4 were revoked/regenerated at their providers
      before being re-added — not the same keys the eval numbers above were
      produced with, but the same providers/models). Branch protection on
      `master` requires `fast-checks`.
- [ ] 7. Disagreement detection (needs its own labeled real-vs-apparent-conflict set)
      ← **CURRENT**: contract in `specs/disagreement-schema.md`. Labeling in
      `data/disagreements.jsonl`: **5/? pairs confirmed, all `apparent`** —
      every one of §3's four `apparent_reason` values now has a real example:
      `pair-01`/`pair-02` (`2404.16130v2` GraphRAG vs `2502.11371v3` RAG-vs-
      GraphRAG): different_scope, methodological_difference. `pair-03`
      (`2310.11511v1` Self-RAG vs `2508.15253v2` CARE): different_scope.
      `pair-04` (`2404.16130v2` vs `2605.14192v1` "Why RAG Fails"): a deliberate
      not_actually_related negative example (both mention "graph," but one means
      a knowledge graph and the other a mechanistic-interpretability attribution
      graph). `pair-05` (`2310.11511v1` Self-RAG vs `2601.16503v2` MRAG):
      different_metric (factuality/citations vs. readability).
      **No `genuine` example found across three separate search passes**
      (keyword search; full intro/related-work reading by hand on CoRAG,
      CDF-RAG, CReSt, MRAG, "In Defense of RAG"; targeted metric/scope hunting).
      Treating this as a real, honest finding rather than a gap to force-fill —
      the spec expected genuine same-condition contradictions to be rare, and
      they may simply not exist in this 21-paper corpus. §3's genuine-side
      taxonomy and §8's ratio/per-reason-minimum decisions stay open until one
      turns up (or a deliberate decision is made to proceed without one). Paused
      at explicit user request, not finished. No detector code yet.
- [ ] 8. UI surfacing citations, disagreements, blocked-claims panel, trust receipt
      ← **CURRENT**: `scripts/generate_report.py` renders a self-contained
      static HTML report from a `run_brief.py` result (no server/framework --
      matches the project's dependency-light style). Three of four panels are
      real: trust receipt (drafted/verified/blocked counts, per-`block_reason`
      breakdown), citations (linked to arXiv, span shown verbatim), and blocked
      claims (the demo money-shot — a real caught claim, verified end-to-end
      against genuine Verifier output, not a fabricated fixture). Disagreements
      is an honest "not yet available" placeholder — step 7 has no detector
      yet — not fake data standing in for a feature that doesn't exist.
      `run_brief.py --html out.html` renders the report directly in one
      command. Also fixed two real bugs surfaced while testing this end-to-end:
      `_wait_for_groq_budget` crashed on an empty history when a single call's
      own estimated size exceeded the whole per-minute budget; `run_brief.py`'s
      stdout JSON crashed on Unicode paper text under this console's cp1252
      default (now `ensure_ascii=True`). Not yet done: disagreements panel
      needs step 7's detector.
- [ ] 9. Stretch: retrieval-as-agent (+ arXiv MCP), recency-awareness, scope/decline gate

## Not yet (premature — do not scaffold before the step that needs it)

Docker, LLM gateway, caching, CI, hooks, subagents, MCP. Each wraps a working system that
does not exist yet. **Subagent note:** the Verifier is the natural isolated-context subagent
(adversarial separation maps onto context separation) — build it when the agents are real,
not before.
