# spec: scope/decline gate

Status: DRAFT v0.1
Governs: build-order step 9's scope/decline gate — a check run BEFORE the
Writer drafts anything, deciding whether a question is something this system
can competently attempt against its frozen corpus at all.

---

## 1. Why this exists

Today, an out-of-scope question (e.g. "what's new in diffusion models?" against
a 21-paper RAG corpus) still runs the full Writer → Verifier pipeline. The
Writer either finds nothing to cite or cites something irrelevant, the Verifier
correctly blocks it, and the brief comes back with `brief: []` and one or more
blocked claims — **indistinguishable, from the output alone, from a real
in-scope question where the Writer just did a bad job.** That's a silent
failure mode: the honest signal ("this corpus can't answer this") gets lost
inside a normal-looking blocked-claim.

The scope gate makes that signal explicit and immediate: a fast, cheap,
upfront check that a real research question about RAG is at least plausibly
answerable from the frozen corpus, before spending a Writer/Verifier round on
it. It does not replace the Verifier's per-claim faithfulness check — it is a
coarser, question-level triage that runs first.

---

## 2. Label space (BINARY — same discipline as claim-schema §2, disagreement-schema §2)

`label ∈ { in_scope, decline }`

No "maybe." A question that's ambiguous is a labeling-set problem to fix, same
reasoning as the two prior ground-truth contracts in this repo.

---

## 3. What "in scope" means

A question is `in_scope` iff it's a genuine research question about
retrieval-augmented generation (RAG) that at least one paper in the frozen
21-paper corpus (`data/corpus.v1.json`) plausibly bears on — not necessarily
that the corpus fully answers it (that's the Writer/Verifier's job to find
out), only that attempting it is a reasonable use of this system.

`decline` covers two distinct failure shapes, both worth telling the user
about differently:
- **Off-topic**: not about RAG at all (e.g. general ML questions unrelated to
  retrieval, current events, anything outside this project's sub-area per
  CLAUDE.md step 0).
- **Out-of-corpus**: genuinely about RAG, but about a sub-topic, technique, or
  time period this specific frozen 21-paper corpus has no coverage of. This is
  a real, useful distinction from off-topic — it's the seed of step 9's
  separate recency-awareness feature, not the same thing as this gate, but the
  label captures why up front.

---

## 4. Fields

One row (one candidate question):

| field | type | notes |
|---|---|---|
| `question_id` | string | stable unique id |
| `question` | string | verbatim research question |
| `label` | enum | `in_scope` \| `decline` |
| `decline_reason` | enum \| null | `off_topic` \| `out_of_corpus`; null iff `label == in_scope` |
| `label_rationale` | string | one line, labeler's own words |

Serialized as JSONL: `data/scope_gate.jsonl`.

---

## 5. Ground truth (INVARIANT 6)

Same discipline as `data/claims.jsonl` and `data/disagreements.jsonl`: labeled
by the domain-competent human (confirmed RAG, step 0), never by an LLM. Given
the binary is coarser and less ambiguous than claim-faithfulness or
disagreement judgment, candidate questions may be drafted for review, but each
label is a human decision, not a rubber stamp.

---

## 6. Detector

`scope_gate.classify_scope(question: str) -> ScopeVerdict` — a pure function,
same isolation discipline as `verify()` and `disagreement_detector.classify()`
(writer-verifier.md §7). Runs against `corpus_access.all_abstracts()` (already
available, no new corpus access needed) to judge topical fit; makes no
Writer/Verifier call itself and shares no state with either.

`run_brief.py` calls this first. On `decline`, the brief short-circuits: no
Writer call, output clearly states the question was declined and why, instead
of returning an empty/all-blocked brief that looks like an ordinary failure.

---

## 7. Open decisions

- [ ] Whether `decline` should ever be soft (e.g. "low confidence, proceeding
      anyway with a warning") vs. hard-blocking. Starting hard-blocking; revisit
      if real in-scope questions get wrongly declined.
- [ ] Minimum ground-truth count per label — not fixed until real candidates
      exist, same precedent as the other two ground-truth contracts.
