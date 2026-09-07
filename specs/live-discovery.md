# spec: live discovery (retrieval-as-agent, discovery-only)

Status: DRAFT v0.1
Governs: build-order step 9's "retrieval-as-agent (+ arXiv MCP)" sub-item.

---

## 1. Scope, deliberately narrow

This is **discovery only**: given a research question, search live arXiv for
papers beyond the frozen 21-paper corpus and surface them as a plain
title/link list. That is the entire feature.

**What this NEVER does** (each maps to a specific invariant it would
otherwise threaten):

- Never modifies `data/corpus.v1.json` or `data/cache/` — the corpus stays
  frozen and versioned exactly as `corpus-manifest.md` defines it
  (INVARIANT 4). A live search result is not "added to the corpus"; it isn't
  persisted anywhere beyond one run's output.
- Never reaches the Writer or the Verifier. `writer.py` and `verifier.py`
  import nothing from this module and this module imports neither of them.
  A live-fetched paper can never become a `cited_paper_id` in a brief or
  blocked claim — there is no code path where that could happen.
- Never fabricates results. Every row returned is a real arXiv API response
  (INVARIANT 2) — titles, ids, and abstract snippets exactly as arXiv serves
  them, not summarized or rewritten.

Why discovery-only over a full live-citation path (the alternative
considered): letting live papers actually be cited would require a second,
parallel span-verification path alongside `corpus_access.py`, real-time
untrusted-input handling for content that was never audited the way the
frozen 21 were, and no ground truth to eval it against — a substantially
bigger, riskier feature for a "Stretch" line, and it would blur the exact
trust story (`INVARIANT 4`: a fixed, versioned, audited corpus) that is this
project's core thesis. Discovery-only gets real user value (surfacing papers
worth a human's own follow-up) at zero risk to that story.

---

## 2. Why no ground truth / eval (INVARIANT 1 doesn't apply here)

INVARIANT 1 bars *agent* code — code making a judgment call — before ground
truth exists. This module makes no judgment call: it queries arXiv's search
API and returns what comes back, filtered only by "is this paper_id already
in the frozen corpus" (a mechanical set-membership check against
`corpus_access.paper_ids()`, not a relevance judgment). There is nothing to
grade a human-labeled set against. Same reasoning `recency.py` used for
skipping ground truth/eval — mechanical, not a classifier.

---

## 3. Behavior

`search_live(question: str, max_results: int = 5) -> list[LiveResult]`:

1. Calls arXiv's search API (`export.arxiv.org/api/query`, the same host
   `fetch_corpus.py` already uses for the frozen corpus, reusing its
   `http_get` retry/User-Agent convention rather than reimplementing it) with
   the question as a free-text query, scoped to `cat:cs.CL OR cat:cs.IR`
   (same categories as `corpus-manifest.md`'s own selection criteria, so
   results stay on-topic for this project's sub-area).
2. Drops any result whose bare paper_id is already in
   `corpus_access.paper_ids()` (stripped of version suffix) — this is
   specifically about surfacing what's *beyond* the frozen corpus, not
   re-listing what a brief could already cite.
3. Returns up to `max_results` rows: `paper_id`, `title`, `abstract_snippet`
   (first ~200 chars), `arxiv_url`. No `cited_span`, no `label` — this is not
   a claim schema row and must never be confused with one downstream.

Runs on a real network call — no live-corpus test can be part of CI's
`fast-checks` (no LLM key needed, but a real network dependency doesn't
belong in a job that's supposed to be free/deterministic/offline). Not wired
into `verifier-eval.yml` either, since there's nothing to eval.

---

## 4. Integration with run_brief.py / generate_report.py

`run_brief.py` calls `search_live()` after producing the normal brief (or
after a scope-gate decline — discovery can still be useful even when the
frozen corpus can't answer directly) and attaches the result as a
`live_discovery` list, clearly separate from `brief`/`blocked`.
`generate_report.py` renders it as its own section, explicitly labeled
"beyond the frozen corpus — not verified, not cited" so it can never be
mistaken for a citation the Verifier actually checked.

---

## 5. Open decisions

- [ ] Whether `search_live` should ever be skipped for cost/latency reasons
      (e.g. only run it when the scope gate declined, since that's when a
      user most needs pointers elsewhere). Currently always runs.
- [ ] No retry/backoff tuning done against arXiv's real rate limits under
      load — first-guess `http_get` reuse from `fetch_corpus.py`, not
      independently hardened.
