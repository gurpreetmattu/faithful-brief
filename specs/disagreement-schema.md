# spec: disagreement schema (real-vs-apparent-conflict ground-truth contract)

Status: DRAFT v0.1
Governs: the hand-labeled real-vs-apparent-conflict set build-order step 7 requires
before any disagreement-detection code is written.

Companion contracts: `specs/corpus-manifest.md` (defines the closed corpus both
papers in a pair must belong to) and `specs/claim-schema.md` (this contract reuses
its binary-label, no-partial, `label_rationale` discipline rather than reinventing
it — the two ground-truth sets are siblings, not strangers).

This contract exists **before** any pair is labeled, and before any detector code
exists (INVARIANT 1's discipline, applied a second time — CLAUDE.md is explicit
that disagreement detection "needs its own labeled real-vs-apparent-conflict set").
If a real pair of papers won't fit this schema cleanly, the schema is wrong — fix
it here first, then label.

---

## 1. Unit: the disagreement candidate

A **pair of spans from two different corpus papers, both bearing on the same
underlying question**, that surface-level appear to conflict.

This is deliberately scoped to **classification only**: given a candidate pair, is
the conflict genuine or apparent? Finding *which* pairs to compare in the first
place — scanning the corpus for topical overlap — is the eventual Detector's
retrieval-style problem, not something this ground-truth set measures. This is the
direct structural twin of claim-schema.md's own scoping: that contract never
measures the Writer's drafting quality, only the Verifier's judgment on a claim it
is handed. Here, a human hands the Detector-under-test a candidate; the set
measures only whether it judges that candidate correctly.

Two papers using different metrics, different datasets, or different scopes can
look contradictory in isolated spans while being fully compatible on closer
reading. A disagreement-surfacing system that cannot tell the two apart is worse
than useless — it either cries wolf constantly or buries the disagreements that
actually matter under noise.

---

## 2. Label space (BINARY — same discipline as claim-schema §2)

`label ∈ { genuine, apparent }`

No third value at the primary label. A "maybe" is a sign the pair needs closer
reading, or is a bad candidate that should be rejected before labeling (§5 step 1)
— not a valid ground-truth outcome. Same reasoning claim-schema §2 gives for
banning `partial`: an ambiguous verdict is a symptom of an under-specified
candidate, not a real third class of finding.

---

## 3. `apparent_reason` (closed taxonomy, populated iff `label == apparent`)

Structurally mirrors claim-schema §3's perturbation taxonomy, but explains the
*why* behind a non-genuine finding — the field that keeps `apparent` from being a
lazy catch-all, the same way `label_rationale` keeps `label` from being
rubber-stamped:

| reason | what explains the surface conflict |
|---|---|
| `different_scope` | different setting/dataset/task — the claims are compatible once scope is accounted for |
| `different_metric` | the two spans are measuring different things entirely |
| `methodological_difference` | different experimental setup produced different numbers (e.g. a reproducibility gap) |
| `not_actually_related` | a candidate-generation miss — the two spans are not really about the same claim at all |

**Not yet defined:** a `genuine`-side sub-taxonomy (e.g. "direct numeric
contradiction" vs. "opposite qualitative conclusion"). Flagged as an open decision
(§8) — real genuine examples don't exist yet to design a taxonomy against, the
same discipline claim-schema used for its own open decisions.

---

## 4. Fields

Each row (one candidate pair):

| field | type | notes |
|---|---|---|
| `pair_id` | string | stable unique id |
| `paper_a_id` | string | MUST be in `data/corpus.v1.json` (§7) |
| `paper_b_id` | string | MUST be in `data/corpus.v1.json` (§7); different paper from `paper_a_id` |
| `topic` | string | one-line statement of the shared question both spans bear on — this is what ties an otherwise-unrelated pair of quotes together into a candidate at all |
| `span_a` | string | verbatim span from `paper_a_id` stating its position |
| `span_a_artifact` | enum | `abstract` \| `html` — which artifact `span_a` came from (claim-schema's `span_artifact`, applied per-side) |
| `span_b` | string | verbatim span from `paper_b_id` stating its position |
| `span_b_artifact` | enum | `abstract` \| `html` |
| `label` | enum | `genuine` \| `apparent` |
| `apparent_reason` | enum \| null | one of §3's four values; null iff `label == genuine` |
| `label_rationale` | string | one line, in the labeler's own words: why this label. Forces justification; catches rubber-stamping (claim-schema §4's same rationale). |

**Canonical pair order:** `paper_a_id` and `paper_b_id` are stored lexicographically
sorted by `paper_id`, so `(A, B)` and `(B, A)` can never be logged as two distinct
candidate rows for the same underlying pair.

Serialized as JSONL, one object per line, analogous to `data/claims.jsonl` — likely
`data/disagreements.jsonl` once labeling starts (not created by this contract).

---

## 5. Labeling procedure (per candidate)

1. Scan the frozen corpus for two papers bearing on the same underlying question —
   a title/abstract skim is enough to propose a candidate. (This step is not
   measured by this ground-truth set, per §1 — a bad candidate is simply rejected
   here, not force-labeled.)
2. Pull one verbatim span from each paper that states its position on that
   question.
3. Ask ONLY: reading both spans **in full context** (not in isolation), do they
   actually contradict each other? This is the structural twin of claim-schema
   §6's "faithfulness is match-to-source, not truth" — apparent-conflict-checking
   is full-context reading, not isolated-quote reading. A span that sounds like a
   flat contradiction out of context is exactly the case §3's taxonomy exists to
   catch.
4. Set `label`. If `apparent`, set `apparent_reason`. Always set
   `label_rationale`.

---

## 6. Worked examples

Both real, pulled from and verified against the frozen corpus's cached abstracts
(not fabricated, per INVARIANT 2's spirit even in a spec) — verified verbatim as
of 2026-09-07.

**Example 1 — `apparent` / `different_scope`:**

```json
{
  "pair_id": "graphrag-scope-01",
  "paper_a_id": "2404.16130v2",
  "paper_b_id": "2502.11371v3",
  "topic": "Does GraphRAG outperform conventional RAG?",
  "span_a": "For a class of global sensemaking questions over datasets in the 1 million token range, we show that GraphRAG leads to substantial improvements over a conventional RAG baseline for both the comprehensiveness and diversity of generated answers.",
  "span_a_artifact": "abstract",
  "span_b": "Our results highlight the distinct strengths of RAG and GraphRAG across different tasks and evaluation perspectives.",
  "span_b_artifact": "abstract",
  "label": "apparent",
  "apparent_reason": "different_scope",
  "label_rationale": "2404.16130 scopes its improvement claim specifically to global sensemaking questions over million-token datasets; 2502.11371's broader benchmark finding that each approach has task-dependent strengths does not contradict that narrower claim -- it explains why a single blanket 'GraphRAG wins' or 'RAG wins' framing would be wrong, not that either paper is incorrect."
}
```

**Example 2 — `apparent` / `methodological_difference`, and the open question it
surfaces (§8):**

`2604.19899v1` (a reproducibility study) reports "lower absolute scores than
reported" versus the original MetaRAG paper, attributed to "closed-source LLM
updates, missing implementation details, and unreleased prompts" — a clean
methodological-difference case. It is **not reduced to a full row here**: its
natural comparison point is the *original* MetaRAG paper, which is not itself in
the frozen 21-paper corpus. Left as a worked *observation*, not a worked *row*,
until §8's admissibility question is resolved — silently inventing a `paper_b_id`
for a paper outside the corpus boundary would violate §7 before this contract even
finishes being written.

---

## 7. Corpus boundary & untrusted input

Both `paper_a_id` and `paper_b_id` MUST resolve to a `paper_id` in
`data/corpus.v1.json` — the same closed-boundary discipline as
claim-schema/corpus-manifest §9. A pair citing a paper outside the frozen corpus
is not a valid row under this contract (see §8 for whether that boundary should
ever flex, and how).

Paper text remains untrusted input per CLAUDE.md's standing design concern —
nothing in this contract weakens that; it is inherited unchanged from
corpus-manifest §10.

---

## 8. Open decisions

- [ ] **Target `genuine`:`apparent` ratio.** Likely **apparent-majority** is
      correct here — the mirror image of claim-schema's supported-majority
      target, for the mirror-image reason: genuine contradictions under truly
      identical conditions are the rare, hard-to-find case, and a Detector that
      always answers "apparent" would win by default on a genuine-majority set,
      exactly the blind-strategy failure claim-schema §2 guards against in the
      other direction. Not fixed numerically until real candidates exist.
- [ ] **Per-`apparent_reason` minimum count**, once real data exists. Precedent:
      claim-schema's per-type floor of 3 was set only after real counts existed
      in `data/claims.jsonl`, not guessed in advance.
- [ ] **Whether a paper outside the frozen corpus is ever admissible as one side
      of a pair** (Example 2 above is the live case: the original MetaRAG paper).
      Silently allowing it would break §7's closed boundary; silently forbidding
      it would throw away a real, clean example. The likely shape of a fix is an
      anchor-like admission rule (corpus-manifest §4's anchor mechanism is the
      closest precedent: a capped, justified exception, not a blanket carve-out) —
      but that is a corpus-manifest change, not something to decide inside this
      file.
- [ ] **A `genuine`-side sub-taxonomy** (§3), deferred until a real genuine
      example is found during labeling — the same "don't design a taxonomy against
      examples that don't exist yet" discipline claim-schema followed.
