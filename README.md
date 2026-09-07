# faithful-brief

A research agent that reads recent arXiv papers on **RAG** and produces a structured brief
in which every claim traces to a specific source span, claims no source supports are detected
and **blocked** before they reach the output, and cross-paper disagreements are classified as
genuine or apparent rather than blended away.

The writing is the commodity — anyone can wrap an LLM around a stack of papers. The value
here is that faithfulness is **provable**: the system is deliberately fed unfaithful claims
and its catch rate is measured — precision and recall, broken down by perturbation type.
The writing is the commodity; the trust is the product.

## Proof, not a demo

Every number below comes from a real run against real, hand-labeled ground truth — none of
it is a projection or a cherry-picked example.

| Component | Result |
|---|---|
| **Verifier** (faithfulness check) | n=44, accuracy=0.955, precision=0.909, **recall=1.000** — caught every injected unfaithful claim, across all 6 perturbation types |
| **Scope gate** (decline out-of-scope questions) | n=10, accuracy=0.900, precision=1.000, recall=0.800 |
| **Disagreement detector** (genuine vs. apparent) | n=5, first real run: label accuracy 0.6–0.8 (run-to-run LLM variance observed); **0 `genuine` examples exist in the ground-truth set** after 4 independent search passes across the corpus — recall on a real genuine disagreement is honestly unmeasured, not silently assumed |

The Verifier's recall gates CI (`.github/workflows/verifier-eval.yml`) — a regression below
1.000 fails the build. See `CLAUDE.md` for full numbers, methodology, and every real bug
found along the way.

## What it does

- **Writer** drafts claims from the frozen corpus, each with a citation.
- **Verifier** — a *separate* agent sharing no state with the Writer — independently checks
  every claim against its cited span, then the whole corpus, and blocks anything unsupported.
  This separation (not a shared self-check) is the actual faithfulness mechanism.
- **Disagreement detector** classifies candidate cross-paper conflicts as genuine or apparent
  (and why), so a surface-level contradiction isn't mistaken for a real one.
- **Scope gate** declines questions the frozen corpus can't competently address, before
  spending a single Writer/Verifier call.
- **Recency-awareness** flags when the corpus is stale relative to today, or when a question
  asks for currency the corpus can't promise — mechanical (date comparisons), no LLM call.
- **Live discovery** surfaces real, live arXiv papers beyond the frozen corpus as a
  "you may also want to read" list — titles/links only, **never cited, never verified, never
  added to the corpus**.

## Usage

```
python scripts/run_brief.py "How does GraphRAG compare to conventional RAG?" --html out.html
```

Prints the assembled brief (JSON) to stdout and, with `--html`, renders a self-contained
report — trust receipt, citations, blocked claims, disagreements, live discovery — that
opens straight from disk, no server required.

Run any component's eval standalone against its ground truth:

```
python scripts/eval_verifier.py        # 44 hand-labeled claims
python scripts/eval_disagreement.py    # 5 hand-labeled disagreement pairs
python scripts/eval_scope_gate.py      # 10 hand-labeled scope questions
```

Requires at least one of `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `HF_TOKEN`
in `.env` (see `.env.example`) — see `scripts/llm_client.py` for the fallback order.

## Corpus

21 real arXiv RAG papers, frozen and hash-pinned (`data/corpus.v1.json` + `data/cache/`),
spanning a 2024-09–2026-08 window plus 3 justified pre-window anchors. No paper is ever
fetched live at brief time — the corpus is fixed so eval numbers stay comparable run to run.
See `specs/corpus-manifest.md`.

## Architecture

Every component that makes a judgment call is proven against hand-labeled, human-produced
ground truth before it's trusted — an LLM never labels its own eval set. Contracts live in
`specs/` and are written before the code or data they govern. Full invariants, build order,
and the honest status of every step (including real bugs found and fixed) are in
`CLAUDE.md` — the steering file for this repo, kept current rather than aspirational.

## Known limitations

- The disagreement detector has never been evaluated against a real `genuine` contradiction
  — one may simply not exist in this 21-paper corpus, or it hasn't been found yet.
- The Verifier's corpus-wide entailment check only searches abstracts, not full paper bodies
  (a cost tradeoff — see `scripts/verifier.py`).
- The corpus is RAG-specific by construction: the pipeline architecture (Writer/Verifier
  separation, span verification, disagreement classification) is domain-general, but this
  instance is built and proven only against RAG — the corpus, eval set, and labeler's domain
  competence are all RAG-specific, and swapping domains means re-freezing a new corpus.
- Live discovery's arXiv relevance ranking isn't independently tuned or evaluated (no ground
  truth applies — see `specs/live-discovery.md` for why).
