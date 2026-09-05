# spec: claim schema (ground-truth data contract)

Status: DRAFT v0.1
Governs: the hand-labeled ground-truth claim set (build-order step 3) and, downstream,
what the Verifier is scored against (step 5).

This contract exists **before** any claim is labeled. Do not label against a mental model;
label against this file. If a real claim won't fit the schema cleanly, the schema is wrong —
fix it here first, then relabel.

---

## 1. Unit: the atomic claim

An atomic claim is **one verifiable assertion** — a single subject, predicate, and
value/relationship. If a sentence can be half-true, it is not atomic; split it.

- Atomic:    "STAIR achieves Recall@1 of 82.6% on SearchTome."
- NOT atomic: "STAIR beats BM25, DPR, and Mistral." → three claims, one per baseline.

Rationale: atomicity and binary labeling reinforce each other. A compound claim forces a
"partial" label, and partial labels turn precision/recall into mush. Keep claims splittable
until each is cleanly true or cleanly false against a single span.

---

## 2. Label space (ground truth is BINARY)

`label ∈ { supported, unsupported }`

No `partial` in ground truth. Partial is a symptom of a non-atomic claim — rewrite it.
(The *system's* judge may later emit yes/no/partial; how a system "partial" scores against
binary ground truth is a scoring decision deferred to the eval-harness spec. Not here.)

Target distribution: **majority `supported`** (~60/40 supported:unsupported or thereabouts).
If most claims are unsupported, a Verifier that blocks everything scores high recall for free.
The set must make blind-block a losing strategy.

---

## 3. Perturbation taxonomy (closed set)

`perturbation_type` is null for supported claims; for unsupported claims it is exactly one of:

| type                | what it corrupts                                              | in-place? |
|---------------------|--------------------------------------------------------------|-----------|
| `magnitude_change`  | a number/quantity (82.6% → 85.6%)                            | yes       |
| `entity_swap`       | a named thing (iTransformer → PatchTST; dataset, method)     | yes       |
| `scope_broadening`  | quantifier/qualifier ("most settings" → "all settings")      | yes       |
| `causal_inversion`  | direction/purpose of a relationship (find-more → filter-out) | yes       |
| `attribution_swap`  | which paper a (true) claim belongs to                        | no*       |
| `plausible_addition`| a fluent claim NO paper makes                                | no*       |

*The first four edit a true claim in place — same cited paper, corrupted content.
The last two are structural (see §5) and are the ones a naive checker misses, so they
must be represented, not skipped.

Report recall **per type**. A single aggregate number hides the `causal_inversion` /
`plausible_addition` weakness, which is exactly where a real Verifier fails.

---

## 4. Fields

Each row (one claim):

| field             | type              | notes |
|-------------------|-------------------|-------|
| `claim_id`        | string            | stable unique id, e.g. `stair-03` |
| `claim_text`      | string            | the atomic assertion as it would appear in a brief |
| `cited_paper_id`  | string            | arXiv id the claim is **attributed to** (the paper the Verifier checks against) |
| `cited_span`      | string \| null    | verbatim span from `cited_paper_id` the claim is checked against; **null only for `plausible_addition`** |
| `label`           | enum              | `supported` \| `unsupported` |
| `perturbation_type`| enum \| null     | null iff `supported` |
| `derived_from`    | string \| null    | `claim_id` of the true claim this was perturbed from (null for originals & `plausible_addition`) |
| `label_rationale` | string            | one line: WHY this label. Forces the labeler to justify; catches rubber-stamping. |

Serialized as JSONL, one object per line. `specs/` holds this contract; the data lives
elsewhere (e.g. `data/claims.jsonl`) and is corpus-pinned.

---

## 5. Why `cited_span` is checked, not "best matching span"

The Verifier must check the claim against **the span in the cited paper**, not against the
best-matching span anywhere in the corpus. This is the design point that makes two failure
modes visible instead of silently repaired:

- **`attribution_swap`**: `cited_paper_id` is the WRONG paper. `cited_span` is a real span
  from that wrong paper that does NOT entail the claim (the claim is true of *another* paper).
  A checker that searches the whole corpus for support will "find" it elsewhere and wrongly
  pass it. Checking the cited span exposes the misattribution.
- **`plausible_addition`**: `cited_span` is null — nothing supports it anywhere. A corpus-wide
  search may surface a loosely-related span and pass it. Cited-span checking has nothing to
  latch onto, correctly.

Design consequence for the Verifier (step 4): run two checks and report both —
(a) does the cited span entail the claim, and (b) does anything in the corpus entail it.
The gap between (a) and (b) is the misattribution signal, and it's a metric almost nobody has.

---

## 6. Labeling procedure (per claim)

1. Read `claim_text`.
2. Open `cited_paper_id`, locate the span it rests on.
3. Ask ONLY: does this span assert this claim? (Not "is this true in general" — faithfulness
   is match-to-source, not truth. An abstract that overclaims is still the source of record.)
4. Set `label`, fill `cited_span` (paste verbatim), write `label_rationale`.
5. For unsupported rows, set `perturbation_type` and `derived_from`.

---

## Open decisions (resolve before step 3)

- [ ] Confirm supported:unsupported ratio target (proposed ~60:40).
- [ ] Fix per-type minimum counts so each `perturbation_type` has enough rows for a
      meaningful per-type recall (a type with 2 rows yields a noise metric).
- [ ] Decide whether abstract-only spans are acceptable for v1 `cited_span`, or whether
      `causal_inversion`/`attribution_swap` rows require a body-section span. (Ties to the
      known "abstracts overclaim" limitation.)
