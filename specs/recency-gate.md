# spec: recency-awareness

Status: DRAFT v0.1
Governs: build-order step 9's recency-awareness sub-item.

Companion: `specs/corpus-manifest.md` §5, which already earmarked this —
`submitted_at` vs `version_date` are kept as separate fields specifically
because "pinning v4 of a 2020 paper gives content from 2021 for a paper whose
ideas are from 2020. Recency-awareness (step 9) needs the former; content
provenance needs the latter." This spec is that promise, kept.

---

## 1. Why this is mechanical, not an LLM judgment call

Unlike the Verifier, the Disagreement Detector, or the scope gate, every fact
this needs is already a plain date sitting in `data/corpus.v1.json`:
`frozen_at`, `selection_criteria.date_window`, and per-paper `submitted_at` /
`version_date`. Comparing dates and matching a few keyword patterns needs no
model call, no ground truth, and no eval — the same reasoning
`check_claims_integrity.py` already applies to mechanical span verification
(CLAUDE.md's "every component must earn its place": an LLM call here would be
decorative, not load-bearing). This intentionally has no `data/*.jsonl` ground
truth file and no `eval_*.py` script, unlike step 7/9's other gates.

---

## 2. Three distinct notices, not one blended signal

**2.1 Corpus staleness** (question-independent): how long ago was the corpus
frozen, relative to now? Computed once per run: `days_since_freeze = today -
frozen_at`. Flagged `stale=true` past `STALENESS_THRESHOLD_DAYS` (90 — RAG is a
fast-moving sub-area; a quarter is long enough that real relevant work has
likely appeared outside the frozen 21 papers). This is a judgment call, not a
measured threshold — documented as such, adjustable if it proves too noisy or
too quiet in practice.

**2.2 Question recency-sensitivity** (per-question): does the question's own
wording ask for currency the frozen corpus cannot promise — "latest",
"newest", "most recent", "current state of the art", "this year", or an
explicit year later than `date_window.to`'s year? A heuristic keyword/regex
match, not exhaustive — false negatives (missing a recency-sensitive phrasing)
are the acceptable failure direction here, since this is an advisory notice,
not a blocking gate (contrast the scope gate, which does block).

**2.3 Per-citation idea age** (per cited paper): when a specific cited paper's
`submitted_at` predates its `version_date` by more than
`IDEA_AGE_THRESHOLD_DAYS` (90), the ideas being cited may be materially older
than the pinned version's date suggests — corpus-manifest §5's own example
(2020 ideas, 2021-dated v4 content).

---

## 3. Behavior: advisory, never blocking

Unlike the scope gate (§9's other sub-item, which declines and skips the
Writer entirely), recency notices never stop a brief from running — they are
attached to the output alongside the claims, so the user sees them without the
system refusing to help. `run_brief.py`'s result JSON gains a `recency` object
(corpus staleness + question signal) and each brief/blocked item's citation
gains an optional idea-age note. `generate_report.py` renders a banner when
either signal is set, and an inline note per citation when applicable.

---

## 4. Open decisions

- [ ] Thresholds (90 days for both staleness and idea-age) are first-guess
      defaults, not tuned against any data — there's nothing to tune them
      against, since this is mechanical. Revisit if they prove noisy.
- [ ] Whether question-recency-sensitivity should ever escalate to something
      the scope gate considers (e.g. an `out_of_corpus`-flavored decline) is
      explicitly NOT decided here — kept separate per CLAUDE.md's own step 9
      framing of these as distinct sub-items.
