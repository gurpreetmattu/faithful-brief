"""
Read-only access to the frozen corpus (data/corpus.v1.json + data/cache/), per
specs/writer-verifier.md Sec 3.

Both writer.py and verifier.py go through this module rather than touching the
corpus files directly, so there is exactly one place that (a) reuses
fetch_corpus.extract_content_text -- the same extractor that produced sha256_content,
required so a real span never fails verification on a formatting mismatch -- and
(b) can never issue a live arXiv fetch (the corpus is frozen; re-fetching at brief
time would let it drift under a running system).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fetch_corpus import extract_content_text

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "corpus.v1.json"


@lru_cache(maxsize=1)
def _load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _papers_by_id() -> dict:
    return {p["paper_id"]: p for p in _load_manifest()["papers"]}


def paper_ids() -> list:
    """All paper_ids in the frozen corpus -- the corpus boundary (corpus-manifest Sec 9.3)."""
    return list(_papers_by_id().keys())


def _read_artifact_text(paper_id: str, artifact_kind: str) -> Optional[str]:
    paper = _papers_by_id().get(paper_id)
    if paper is None:
        return None
    artifact = paper["artifacts"].get(artifact_kind)
    if artifact is None:
        return None
    raw_path = REPO_ROOT / artifact["path"]
    if not raw_path.exists():
        return None
    raw_bytes = raw_path.read_bytes()
    if artifact_kind == "abstract":
        return raw_bytes.decode("utf-8")
    return extract_content_text(raw_bytes.decode("utf-8", errors="replace"))


@lru_cache(maxsize=64)
def get_abstract(paper_id: str) -> Optional[str]:
    return _read_artifact_text(paper_id, "abstract")


# KNOWN LIMITATION, discovered empirically (2026-09-06): a full extracted body can run
# to ~70,000 characters. Feeding that back into a multi-turn tool-calling conversation
# means the *next* request carries the whole prior context plus the full body -- on
# this account's Groq tier (8000 tokens/minute, shared across all provisioned keys --
# they're one organization, not independent budgets), one such turn alone requested
# ~36,000 tokens and reliably failed regardless of retries or waiting. This cap keeps
# the Writer's tool result -- and therefore the next turn's whole request -- bounded.
# It does NOT affect verify()'s mechanical span_verified() check (spec Sec 5.1), which
# reads the untruncated cached text directly via _read_artifact_text(), never through
# this function -- so a real citation to text beyond the cap still verifies correctly.
_WRITER_BODY_CHAR_CAP = 2500


@lru_cache(maxsize=64)
def get_paper_body(paper_id: str) -> str:
    """
    Extracted body text for one paper, for the Writer's get_paper_body tool (spec
    Sec 3/Sec 12), truncated to _WRITER_BODY_CHAR_CAP characters (see note above).
    Returns an explicit error string rather than raising or returning None -- this
    is a tool result the model reads, and an invalid citation attempt (bad
    paper_id, or html_source == "none") is exactly the kind of thing a live Writer
    can produce and needs to see plainly.
    """
    if paper_id not in _papers_by_id():
        return f"ERROR: '{paper_id}' is not in the frozen corpus (data/corpus.v1.json)."
    paper = _papers_by_id()[paper_id]
    if paper["html_source"] == "none":
        abstract = get_abstract(paper_id) or ""
        return (
            f"ERROR: '{paper_id}' has no HTML body (html_source: none). "
            f"Only its abstract is available:\n\n{abstract}"
        )
    body = _read_artifact_text(paper_id, "html")
    if body is None:
        return f"ERROR: cached body for '{paper_id}' is missing or unreadable."
    if len(body) > _WRITER_BODY_CHAR_CAP:
        body = (
            body[:_WRITER_BODY_CHAR_CAP]
            + f"\n\n[TRUNCATED: showing the first {_WRITER_BODY_CHAR_CAP} of "
            f"{len(body)} characters. Cite only text that appears above this line.]"
        )
    return body


def all_abstracts() -> dict:
    """paper_id -> abstract text, for the Writer's inline context and the Verifier's
    corpus-wide entailment check (spec Sec 5.3)."""
    return {pid: get_abstract(pid) for pid in paper_ids()}


def span_verified(paper_id: str, cited_span: str) -> bool:
    """
    Mechanical check (spec Sec 5.1): does cited_span appear verbatim in paper_id's
    extracted abstract or body text? No LLM call -- this is the cheapest check in
    the Sec 5 pipeline and gates whether the LLM checks run at all.
    """
    if paper_id not in _papers_by_id():
        return False
    abstract = get_abstract(paper_id) or ""
    if cited_span in abstract:
        return True
    paper = _papers_by_id()[paper_id]
    if paper["html_source"] != "none":
        body = _read_artifact_text(paper_id, "html") or ""
        if cited_span in body:
            return True
    return False
