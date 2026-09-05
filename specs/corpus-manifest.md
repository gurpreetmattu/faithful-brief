# spec: corpus manifest (frozen corpus data contract)

Status: DRAFT v0.1
Governs: the frozen paper set (build-order step 2) and the **corpus boundary** that every
later step depends on — what the Verifier may check against, and what counts as
"in the corpus" at all.

This contract exists **before** any paper is fetched. Do not pull first and describe after;
a corpus assembled and then documented is a corpus selected by convenience. If a real paper
won't fit this schema cleanly, the schema is wrong — fix it here first, then fetch.

Companion contract: `specs/claim-schema.md` (§6 below defines how the two join).

---

## 1. Why this file exists

An arXiv ID without a version suffix (`2005.11401`) is a **mutable pointer** — it resolves
to whatever the latest version is today. Pinning `2005.11401v4` fixes the paper. But fixing
the paper does not fix the *bytes*: arXiv re-renders HTML as its toolchain moves.

So there are two distinct things to pin, and conflating them is the mistake this spec
avoids:

- **identity** — which paper, which version → the versioned `paper_id`
- **content** — the actual text a `cited_span` was taken from → the content hash

INVARIANT 4 says eval numbers are only comparable against a stable corpus. A precision
number reported against "the RAG corpus" is meaningless unless "the RAG corpus" names an
exact byte-set. This file makes corpus drift **loud and diagnosable** rather than silent.

---

## 2. Storage layout

| what | where | committed? |
|---|---|---|
| this contract | `specs/corpus-manifest.md` | yes |
| the manifest | `data/corpus.v1.json` | yes |
| fetched bodies | `data/cache/<paper_id>/` | **no — gitignored** |

**The manifest is the corpus.** The cache is a reconstructible artifact whose integrity the
manifest asserts.

Bodies are not committed. arXiv's default license
(`http://arxiv.org/licenses/nonexclusive-distrib/1.0/`) grants distribution rights to
arXiv, not blanket redistribution rights to us — and the license varies per paper (§3,
`license`). Hash-pinning gets reproducibility without redistribution, and it has the useful
side effect of making the hash **load-bearing**: if bodies were committed, git would pin the
bytes and the hash field would be decorative. Per CLAUDE.md, decorative components get cut.

`data/` does not exist yet and is not created by this contract. It is created in step 2.

---

## 3. Corpus-level fields

`data/corpus.v1.json` is a single JSON object:

| field | type | notes |
|---|---|---|
| `corpus_version` | string | `v1`. Matches the filename. Never reused after freeze. |
| `frozen_at` | ISO date | the date the freeze was declared |
| `paper_count` | int | MUST equal `len(papers)`; a redundant field that exists to catch truncation |
| `selection_criteria` | object | see §4 |
| `corpus_hash` | string | `sha256:<hex>`, computed per §5 |
| `papers` | array | see §5 |

---

## 4. Selection criteria

```json
"selection_criteria": {
  "arxiv_categories": ["cs.CL", "cs.IR"],
  "date_window": { "from": "2024-01-01", "to": "2026-08-31" },
  "query": "<the exact arXiv API query string used>",
  "queried_at": "<ISO datetime the search was run>",
  "inclusion_rules": ["<explicit, e.g. 'must present quantitative results'>"],
  "exclusion_rules": ["<explicit, e.g. 'surveys excluded — no own results to cite'>"]
}
```

`queried_at` is recorded because arXiv search results change as papers are submitted.
Without it the *paper set* is reproducible but the *search that produced it* is not, and a
reader cannot tell whether a paper was excluded deliberately or simply did not exist yet.

Per-paper, `selection_note` (§5) records why that specific paper survived the filter. This
is the deliberate analogue of `label_rationale` in claim-schema §4: that field catches
rubber-stamping, this one catches convenience-sampling. Both force a human to state a reason
that a reviewer can disagree with.

---

## 5. Per-paper fields

Each element of `papers`:

| field | type | notes |
|---|---|---|
| `paper_id` | string | arXiv ID **with mandatory version suffix**, e.g. `2005.11401v4`. A bare ID is invalid — see §1. |
| `title` | string | as fetched |
| `authors` | string[] | as fetched |
| `primary_category` | string | e.g. `cs.CL` |
| `categories` | string[] | all cross-lists |
| `submitted_at` | ISO date | date of **v1** — the paper's real age |
| `version_date` | ISO date | date of **this pinned version** — what the content corresponds to |
| `license` | string | license URI (§7) |
| `html_source` | enum | `arxiv_native` \| `ar5iv` \| `none` (§8) |
| `html_url` | string \| null | resolved URL; null iff `html_source == "none"` |
| `artifacts` | object | `{ abstract: <artifact>, html: <artifact> \| null }` |
| `selection_note` | string | one line: why this paper is in the frozen set |
| `known_drift` | object \| null | null unless §6 drift has been triaged; see §6 |

**Admissibility (INVARIANT 2).** Every entry MUST correspond to a real arXiv paper that
resolves at its pinned version. Synthetic, fabricated, or hand-written "papers" are
inadmissible, and so is hand-editing cached body text. The manifest is the gate INVARIANT 2
is enforced at: an entry whose `paper_id` does not resolve, or whose cached bytes do not
hash to what upstream serves, is not a corpus entry.

`authors` is kept for a non-obvious consumer: disagreement detection (step 7) needs to know
when two "independent" papers share an author group, because that is corroboration of a
weaker kind and blending it away is exactly the failure that step exists to prevent.

`submitted_at` and `version_date` are both kept and are genuinely different: pinning v4 of a
2020 paper gives content from 2021 for a paper whose ideas are from 2020. Recency-awareness
(step 9) needs the former; content provenance needs the latter.

### 5.1 Artifact object

| field | type | notes |
|---|---|---|
| `path` | string | relative to repo root, under `data/cache/` |
| `source_url` | string | exact URL fetched |
| `fetched_at` | ISO datetime | |
| `bytes` | int | raw byte length |
| `sha256_raw` | string | `sha256:<hex>` over raw fetched bytes |
| `sha256_content` | string | `sha256:<hex>` over normalized extracted text (§6) |
| `generator` | string \| null | renderer version string, HTML only (§6); null for abstracts |

---

## 6. Hashing and drift

The hash is the mechanism the whole freeze rests on, so its definition is exact.

### 6.1 Two hashes, because there are two kinds of change

Empirically, arXiv-served HTML embeds volatile boilerplate — a dated stylesheet reference
(`arxiv-html-papers-20260823.css`) and a LaTeXML generator version comment. Both change
without the paper changing. A single raw-byte hash would therefore fire constantly on
benign re-renders, and **a hash that cries wolf gets ignored** — which would quietly defeat
the only drift defense we have.

So each artifact carries two:

- **`sha256_raw`** — sha256 over the raw bytes exactly as fetched, no normalization.
  This is exact provenance: it answers "are these the same bytes I saw?"
- **`sha256_content`** — sha256 over the extracted content text. This is what
  `cited_span` validity actually depends on: it answers "did the *paper* change?"

### 6.2 Content extraction (normative)

`sha256_content` is computed over UTF-8 bytes of text derived as follows.

**HTML artifacts:**
1. Take the main article content only — drop `<head>`, `<script>`, `<style>`, `<nav>`,
   and arXiv page chrome outside the paper body.
2. Extract text content; drop all attributes and tags.
3. Collapse each run of whitespace to a single space; normalize newlines to `\n`; strip
   leading/trailing whitespace per line and on the whole document.

**Abstract artifacts:** the extracted abstract text only — never the API response envelope,
which carries volatile response metadata that would trip false drift. Newlines normalized
to `\n`, trailing whitespace stripped.

The normalization set above is **closed**. Anything it does not list is not normalized.
Every additional normalization is content the hash stops protecting, so widening this list
is a spec change, not an implementation detail.

### 6.3 `corpus_hash`

sha256 over the newline-joined, lexicographically sorted list of
`<paper_id> <artifact_kind> <sha256_content>` lines.

Content hashes, not raw — so `corpus_hash` identifies *the corpus as text*, which is the
thing eval numbers are actually a function of. Sorting makes it order-independent;
`corpus_hash` is excluded from its own computation. One value pins the entire corpus, and
it is the value an eval report cites.

### 6.4 The verify procedure

Contract only — the script is written in step 2, not authorized here.

For each artifact: recompute both hashes from the cached file and emit one status:

| condition | status | meaning |
|---|---|---|
| both hashes match | `ok` | |
| file absent | `missing` | cache needs refetch |
| raw differs, content matches | `rerender` | benign — arXiv re-rendered, paper unchanged |
| content differs | `drifted` | **corpus is not what evals were run against** |

Exit non-zero on `drifted` or `missing`. `rerender` is reported, not fatal — that
distinction is the entire reason for two hashes.

This spec does **not** authorize a CI gate. CI is on CLAUDE.md's not-yet list until step 6.

### 6.5 The re-freeze rule

**A hash is never edited in place.** Not once, not "just to make verify pass."

Silently updating a hash leaves the version label `v1` intact while changing what `v1`
means, retroactively invalidating every number ever reported against it — the precise
failure INVARIANT 4 exists to prevent. Two sanctioned responses to `drifted`:

- **(a)** The cached bytes remain canon. Record `known_drift`:
  `{ "detected_at": <date>, "field": "html.sha256_content", "upstream_sha256": "...", "note": "..." }`
  The manifest now openly says upstream and local disagree, and which one the evals used.
- **(b)** Mint `data/corpus.v2.json` and re-run evals against it. `corpus.v1.json` is left
  byte-identical on disk. Old numbers stay attached to v1; new numbers to v2.

`rerender` is recorded in `known_drift` too, at the same cost and without invalidating
anything — it is provenance, not alarm.

---

## 7. License

Recorded per paper because it varies, and because it is the field that makes the
don't-commit-bodies decision (§2) auditable rather than assumed. A CC-BY paper is one we
*could* commit; a default-licensed one is not. Recording it per paper keeps that distinction
visible instead of applying the most restrictive rule blindly to everything.

**Source note:** `license` is **not** available from the arXiv Atom API. It comes from the
OAI-PMH interface (`arXivRaw` metadata format), which also supplies a dated entry for
*every* version — necessary because Atom's `updated` reports only the latest version's date
and cannot date a pinned older version. Step 2 must query both endpoints; a fetcher built
against the Atom API alone cannot populate `license` or a non-latest `version_date`.

---

## 8. HTML availability

`html_source` is a tri-state, not a boolean:

| value | meaning |
|---|---|
| `arxiv_native` | rendered by arXiv from LaTeX source (`arxiv.org/html/<id>`) |
| `ar5iv` | rendered by ar5iv — a separately-generated rendering |
| `none` | no HTML exists; PDF-only submission with no LaTeX source |

A boolean would hide that two papers' bodies came from different rendering pipelines — a
confound that lands directly on `cited_span` quality in step 3, where a labeler pastes
verbatim spans out of whichever rendering they happen to be reading.

**Detection rule.** `arxiv.org/html/<id>` returns HTTP **200 for every ID**, including ones
with no HTML. Status code is not a signal. Detection MUST be content-based: a genuine
rendering carries the LaTeXML generator comment and the paper's own `<title>`. Record that
generator string in the artifact's `generator` field — it is what later distinguishes a
`rerender` from real drift (§6.4).

**Expected distribution.** arXiv has back-rendered its LaTeX corpus; native HTML was
observed even for a 1999 paper. `arxiv_native` should be near-universal, and `ar5iv` may
never be exercised. It stays in the enum because a fallback that is unrepresentable when
needed is worse than one that goes unused — but if step 2 finishes with zero `ar5iv` rows,
say so and consider cutting the value.

---

## 9. Join to the claim schema

This section is normative for `specs/claim-schema.md`.

1. **`cited_paper_id` MUST match a manifest `paper_id` exactly, version suffix included.**
   A claim citing `2005.11401` rather than `2005.11401v4` is invalid — it cites a mutable
   pointer, so its `cited_span` cannot be checked against a fixed text.

2. **Every `cited_span` MUST appear verbatim in a named artifact** of that pinned paper
   version, after the §6.2 content normalization. This is checkable mechanically, and step 3
   should check it — a span that is not literally present is a transcription error, and one
   silently-wrong span is a permanently mislabeled ground-truth row.

3. **The corpus boundary is closed: `papers` is the whole corpus.** Claim-schema §5 asks the
   Verifier to report "(b) does anything in the corpus entail it" — that check has no meaning
   without a defined boundary. `papers` is it. Anything outside is out of corpus, and
   `plausible_addition` claims are unsupported *with respect to this set*, which is the only
   claim an eval can honestly make.

### 9.1 Proposed amendment to claim-schema (not applied here)

Claim-schema §4 defines `cited_span` but not **which artifact** it came from. Now that the
manifest names artifacts (`abstract`, `html`), that ambiguity is closable and worth closing:
a `span_artifact` field on each claim row.

It matters because claim-schema's own third open decision — whether `causal_inversion` /
`attribution_swap` rows require a body span rather than an abstract span — cannot be
*enforced* or even *measured* without recording which artifact each span came from.

Flagged, not applied. Editing claim-schema is a separate, deliberate change.

---

## 10. Untrusted input

Fetched paper text is untrusted input (CLAUDE.md). This manifest records **provenance and
integrity only**: that bytes came from a named URL and have not changed since.

It makes no claim that the content is safe to feed to a model unescaped. A verified hash
means "this is the same text," not "this text contains no injection." Injection defense
belongs to the Writer at step 4 and is not weakened or discharged by anything here.

---

## 11. Worked example

Metadata below is real (verified against the arXiv Atom and OAI-PMH APIs on 2026-09-06).
**Hashes, paths, and `fetched_at` are illustrative placeholders** — the cache does not exist
until step 2, and no real hash is claimed here.

```json
{
  "corpus_version": "v1",
  "frozen_at": "2026-09-06",
  "paper_count": 1,
  "selection_criteria": {
    "arxiv_categories": ["cs.CL", "cs.IR"],
    "date_window": { "from": "2024-01-01", "to": "2026-08-31" },
    "query": "<exact query string>",
    "queried_at": "2026-09-06T00:00:00Z",
    "inclusion_rules": ["presents quantitative results the paper itself owns"],
    "exclusion_rules": ["surveys — no own results to cite"]
  },
  "corpus_hash": "sha256:<illustrative>",
  "papers": [
    {
      "paper_id": "2005.11401v4",
      "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
      "authors": ["Patrick Lewis", "et al."],
      "primary_category": "cs.CL",
      "categories": ["cs.CL", "cs.LG"],
      "submitted_at": "2020-05-22",
      "version_date": "2021-04-12",
      "license": "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",
      "html_source": "arxiv_native",
      "html_url": "https://arxiv.org/html/2005.11401v4",
      "artifacts": {
        "abstract": {
          "path": "data/cache/2005.11401v4/abstract.txt",
          "source_url": "https://export.arxiv.org/api/query?id_list=2005.11401v4",
          "fetched_at": "<illustrative>",
          "bytes": 0,
          "sha256_raw": "sha256:<illustrative>",
          "sha256_content": "sha256:<illustrative>",
          "generator": null
        },
        "html": {
          "path": "data/cache/2005.11401v4/body.html",
          "source_url": "https://arxiv.org/html/2005.11401v4",
          "fetched_at": "<illustrative>",
          "bytes": 244097,
          "sha256_raw": "sha256:<illustrative>",
          "sha256_content": "sha256:<illustrative>",
          "generator": "LaTeXML oxide (version 0.7.6)"
        }
      },
      "selection_note": "Foundational RAG paper; needed as an anchor the later papers argue with.",
      "known_drift": null
    }
  ]
}
```

Note: this example is a pre-2024 paper included against the stated `date_window` — exactly
the kind of exception `selection_note` exists to make visible rather than invisible. Whether
to actually grant it is an open decision below.

---

## Open decisions (resolve before fetching)

- [ ] Final `paper_count` (15–20) and category filter — `cs.CL` only, or `+cs.IR`?
- [ ] Date window for "recent."
- [ ] Are pre-window foundational papers admissible as anchors (as in §11), or does the
      window hold strictly? Affects whether disagreement detection (step 7) has anything
      old enough to disagree *with*.
- [ ] Whether an `ar5iv`-sourced body is eligible for body-level `cited_span`s
      (couples to claim-schema's third open decision, and to §9.1's `span_artifact`).
- [ ] Whether `abstract` alone is a sufficient artifact for any paper where
      `html_source == "none"`, or whether such papers are excluded from the corpus outright.
