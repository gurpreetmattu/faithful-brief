"""
Live discovery, per specs/live-discovery.md.

search_live() is discovery-only (spec Sec 1): it queries live arXiv and
returns real search results beyond the frozen 21-paper corpus, as a plain
title/link list. It NEVER touches data/corpus.v1.json or data/cache/, is
NEVER imported by writer.py or verifier.py, and a result from here can never
become a cited_paper_id in a brief -- there is no code path where that could
happen. Mechanical filtering only (paper_id set-membership against the frozen
corpus), no judgment call -- see spec Sec 2 for why this needs no ground
truth or eval, unlike verify()/classify_scope()/classify().
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import corpus_access

ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
UA = {"User-Agent": "faithful-brief-live-discovery/0.1 (research; contact via repo)"}
SEARCH_URL = "https://export.arxiv.org/api/query"


@dataclass
class LiveResult:
    paper_id: str
    title: str
    abstract_snippet: str
    arxiv_url: str

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "abstract_snippet": self.abstract_snippet,
            "arxiv_url": self.arxiv_url,
        }


def _http_get(url: str, retries: int = 2, delay: float = 2.0) -> bytes:
    last_err = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(delay)
    raise last_err


def _bare_id(versioned_id: str) -> str:
    # "2404.16130v2" -> "2404.16130"; arXiv search results may not carry the
    # exact version the frozen corpus pinned, so dedup on the bare id.
    return versioned_id.rsplit("v", 1)[0] if "v" in versioned_id.rsplit("/", 1)[-1] else versioned_id


def search_live(question: str, max_results: int = 5) -> list:
    """
    Real arXiv search, scoped to cs.CL/cs.IR (corpus-manifest.md's own
    categories), filtered to exclude anything already in the frozen corpus.
    Returns [] on any network failure rather than raising -- discovery is a
    nice-to-have addendum, not something a brief should fail over.
    """
    frozen_bare_ids = {_bare_id(pid) for pid in corpus_access.paper_ids()}

    query = f'({question}) AND (cat:cs.CL OR cat:cs.IR)'
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results + len(frozen_bare_ids),  # headroom to filter frozen hits
        "sortBy": "relevance",
    }
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"

    try:
        xml_bytes = _http_get(url)
        root = ET.fromstring(xml_bytes)
    except Exception:  # noqa: BLE001
        return []

    results = []
    for entry in root.findall("a:entry", ATOM_NS):
        id_url = entry.find("a:id", ATOM_NS).text
        versioned_id = id_url.rsplit("/abs/", 1)[-1]
        if _bare_id(versioned_id) in frozen_bare_ids:
            continue
        title = " ".join(entry.find("a:title", ATOM_NS).text.split())
        summary = " ".join(entry.find("a:summary", ATOM_NS).text.split())
        snippet = summary[:200] + ("..." if len(summary) > 200 else "")
        results.append(
            LiveResult(
                paper_id=versioned_id,
                title=title,
                abstract_snippet=snippet,
                arxiv_url=f"https://arxiv.org/abs/{versioned_id}",
            )
        )
        if len(results) >= max_results:
            break

    return results
