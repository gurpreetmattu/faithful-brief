"""
Fetch and freeze the corpus per specs/corpus-manifest.md.

Pulls metadata (arXiv Atom + OAI-PMH arXivRaw), abstract text, and HTML body for a
fixed paper list, caches raw bytes under data/cache/ (gitignored), computes the two
hashes the manifest spec defines (sha256_raw, sha256_content), and writes
data/corpus.v1.json.

Re-running this script is the drift check described in spec section 6.4: it recomputes
hashes from a fresh fetch and will disagree with an existing corpus.v1.json if upstream
content changed. It does not overwrite an existing corpus.v1.json; see spec section 6.5.
"""

import hashlib
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "cache"
MANIFEST_PATH = REPO_ROOT / "data" / "corpus.v1.json"

ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

IN_WINDOW_IDS = [
    "2409.01666",   # In Defense of RAG in the Era of Long-Context Language Models
    "2411.06805",   # AssistRAG
    "2502.01113",   # GFM-RAG: Graph Foundation Model for Retrieval Augmented Generation
    "2502.01549",   # VideoRAG: RAG with Extreme Long-Context Videos
    "2502.11371",   # RAG vs. GraphRAG: A Systematic Evaluation and Key Insights
    "2503.14649",   # RAGO: Systematic Performance Optimization for RAG Serving
    "2504.12560",   # CDF-RAG: Causal Dynamic Feedback for Adaptive RAG
    "2505.17503",   # CReSt: Benchmark for RAG with Complex Reasoning
    "2506.21931",   # ARAG: Agentic RAG for Personalized Recommendation
    "2507.17399",   # Millions of GeAR-s: Extending GraphRAG to Millions of Documents
    "2508.15253",   # Conflict-Aware Soft Prompting for RAG
    "2601.16503",   # MRAG: Benchmarking RAG for Bio-medicine
    "2602.18734",   # Rethinking RAG as a Cooperative Decision-Making Problem
    "2603.09891",   # Overview of the TREC 2025 RAG Track
    "2604.19899",   # A Reproducibility Study of Metacognitive RAG
    "2605.14192",   # Why Retrieval-Augmented Generation Fails: A Graph Perspective
    "2607.01852",   # Evaluating Chunking Strategies for RAG on Academic Texts
    "2607.24767",   # The Effect of Text Chunk Size on RAG Performance
]

ANCHOR_IDS = {
    # selection_notes verified post-fetch by grepping cached in-window bodies for
    # citations (see corpus.v1.json for the final, evidence-backed note text).
    "2005.11401": "Foundational RAG paper. Verified: cited by name (Lewis et al., 2020) in 13/18 in-window papers cached in this corpus.",
    "2310.11511": "Self-RAG. Verified: cited by name/ID in >=7 in-window papers (e.g. 2503.14649, 2508.15253, 2602.18734, 2605.14192), contrasted as an adaptive-retrieval baseline.",
    "2404.16130": "GraphRAG. Verified: cited by ID in >=5 in-window papers (2502.01113, 2502.01549, 2502.11371, 2503.14649, 2507.17399); directly contested by 2502.11371 (RAG vs. GraphRAG: A Systematic Evaluation).",
}

UA = {"User-Agent": "faithful-brief-corpus-fetch/0.1 (research; contact via repo)"}


def http_get(url, retries=3, delay=3):
    last_err = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(delay)
    raise last_err


def fetch_atom(paper_id_bare):
    url = f"https://export.arxiv.org/api/query?id_list={paper_id_bare}"
    xml_bytes = http_get(url)
    root = ET.fromstring(xml_bytes)
    entry = root.find("a:entry", ATOM_NS)
    if entry is None:
        raise RuntimeError(f"no Atom entry for {paper_id_bare}")
    id_url = entry.find("a:id", ATOM_NS).text
    versioned_id = id_url.rsplit("/abs/", 1)[-1]
    title = " ".join(entry.find("a:title", ATOM_NS).text.split())
    authors = [a.find("a:name", ATOM_NS).text for a in entry.findall("a:author", ATOM_NS)]
    categories = [c.get("term") for c in entry.findall("a:category", ATOM_NS)]
    primary = entry.find("arxiv:primary_category", ATOM_NS)
    primary_category = primary.get("term") if primary is not None else categories[0]
    summary = entry.find("a:summary", ATOM_NS).text.strip()
    published = entry.find("a:published", ATOM_NS).text[:10]
    return {
        "paper_id": versioned_id,
        "title": title,
        "authors": authors,
        "categories": categories,
        "primary_category": primary_category,
        "abstract_text": summary,
        "submitted_at": published,  # overwritten with true v1 date from OAI-PMH below
    }


def fetch_oai(paper_id_bare):
    url = (
        "https://oaipmh.arxiv.org/oai?verb=GetRecord"
        f"&identifier=oai:arXiv.org:{paper_id_bare}&metadataPrefix=arXivRaw"
    )
    xml_bytes = http_get(url)
    text = xml_bytes.decode("utf-8", errors="replace")
    license_m = re.search(r"<license>([^<]*)</license>", text)
    license_url = license_m.group(1).strip() if license_m else None
    versions = re.findall(
        r'<version version="(v\d+)"[^>]*>.*?<date>([^<]+)</date>', text, re.S
    )
    version_dates = {}
    for v, d in versions:
        dt = datetime.strptime(d.strip(), "%a, %d %b %Y %H:%M:%S %Z")
        version_dates[v] = dt.date().isoformat()
    return license_url, version_dates


ARTICLE_RE = re.compile(r"<article[^>]*>(.*)</article>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
GEN_RE = re.compile(r"Generated by (LaTeXML[^)]*\))", re.I)


def extract_content_text(raw_html_text):
    m = ARTICLE_RE.search(raw_html_text)
    if not m:
        return None
    inner = m.group(1)
    inner = re.sub(r"<script.*?</script>", " ", inner, flags=re.S | re.I)
    inner = re.sub(r"<style.*?</style>", " ", inner, flags=re.S | re.I)
    text = TAG_RE.sub(" ", inner)
    text = html.unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln != "")
    return text.strip()


def _normalize_for_match(s):
    # Strip LaTeX math/command syntax ($...$, \command, {}) before reducing to
    # bare alnum, so a title like "$\text{GeAR}$-s" and its rendered form
    # "GeAR-s" collapse to the same comparable string.
    s = re.sub(r"\$", "", s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    s = re.sub(r"[{}]", "", s)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def check_native_html(paper_id_versioned, expected_title):
    url = f"https://arxiv.org/html/{paper_id_versioned}"
    try:
        raw = http_get(url)
    except Exception:  # noqa: BLE001
        return None, None, None
    raw_text = raw.decode("utf-8", errors="replace")
    gen_m = GEN_RE.search(raw_text)
    if not gen_m:
        return None, None, None
    # The page <title> tag is not a reliable signal: LaTeXML mis-renders it for
    # papers with math markup in the title, or a non-\title{} source layout
    # (observed on real, correctly-rendered papers in this corpus). The article
    # body is rendered correctly even when the head <title> is not, so match
    # against the extracted body text instead.
    content_text = extract_content_text(raw_text)
    if not content_text or len(content_text) < 2000:
        return None, None, None
    haystack = _normalize_for_match(content_text[:3000])
    # Try the full title, and (for "Acronym: Descriptive Subtitle" titles) the
    # part after the first colon — a stylized acronym heading is sometimes
    # rendered outside the running text LaTeXML captures, while the subtitle
    # always appears in it.
    candidates = [expected_title]
    if ":" in expected_title:
        candidates.append(expected_title.split(":", 1)[1])
    if not any(_normalize_for_match(c)[:40] in haystack for c in candidates if _normalize_for_match(c)):
        return None, None, None
    return raw, url, gen_m.group(1).strip()


def sha256_hex(data_bytes):
    return "sha256:" + hashlib.sha256(data_bytes).hexdigest()


def normalize_abstract(text):
    # spec section 6.2: newlines normalized to \n, trailing whitespace stripped.
    # No internal-whitespace collapsing (that rule is HTML-only) and no per-line
    # stripping beyond trailing whitespace, so original wrapping is preserved.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    return "\n".join(lines).strip()


def build_paper_entry(bare_id, is_anchor, selection_note):
    print(f"fetching {bare_id} ...", file=sys.stderr)
    meta = fetch_atom(bare_id)
    versioned_id = meta["paper_id"]
    license_url, version_dates = fetch_oai(bare_id)
    version_suffix = versioned_id.rsplit("v", 1)[-1]
    version_key = f"v{version_suffix}"
    submitted_at = version_dates.get("v1", meta["submitted_at"])
    version_date = version_dates.get(version_key, meta["submitted_at"])

    paper_dir = CACHE_DIR / versioned_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    abstract_raw = normalize_abstract(meta["abstract_text"]).encode("utf-8")
    abstract_path = paper_dir / "abstract.txt"
    abstract_path.write_bytes(abstract_raw)
    abstract_artifact = {
        "path": str(abstract_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "source_url": f"https://export.arxiv.org/api/query?id_list={bare_id}",
        "fetched_at": now_iso,
        "bytes": len(abstract_raw),
        "sha256_raw": sha256_hex(abstract_raw),
        "sha256_content": sha256_hex(abstract_raw),
        "generator": None,
    }

    raw_html, html_url, generator = check_native_html(versioned_id, meta["title"])
    if raw_html is not None:
        html_source = "arxiv_native"
        html_path = paper_dir / "body.html"
        html_path.write_bytes(raw_html)
        content_text = extract_content_text(raw_html.decode("utf-8", errors="replace"))
        content_bytes = content_text.encode("utf-8")
        html_artifact = {
            "path": str(html_path.relative_to(REPO_ROOT)).replace("\\", "/"),
            "source_url": html_url,
            "fetched_at": now_iso,
            "bytes": len(raw_html),
            "sha256_raw": sha256_hex(raw_html),
            "sha256_content": sha256_hex(content_bytes),
            "generator": generator,
        }
    else:
        html_source = "none"
        html_url = None
        html_artifact = None

    entry = {
        "paper_id": versioned_id,
        "title": meta["title"],
        "authors": meta["authors"],
        "primary_category": meta["primary_category"],
        "categories": meta["categories"],
        "submitted_at": submitted_at,
        "version_date": version_date,
        "license": license_url,
        "html_source": html_source,
        "html_url": html_url,
        "artifacts": {"abstract": abstract_artifact, "html": html_artifact},
        "selection_note": selection_note,
        "is_anchor": is_anchor,
        "known_drift": None,
    }
    return entry


def main():
    if MANIFEST_PATH.exists():
        print(f"{MANIFEST_PATH} already exists; refusing to overwrite (spec section 6.5).", file=sys.stderr)
        sys.exit(1)

    papers = []
    for bare_id, note in ANCHOR_IDS.items():
        papers.append(build_paper_entry(bare_id, True, note))
    for bare_id in IN_WINDOW_IDS:
        note = f"In-window RAG paper (cs.CL/cs.IR, within selection_criteria.date_window); presents its own quantitative results."
        papers.append(build_paper_entry(bare_id, False, note))

    hash_lines = []
    for p in papers:
        hash_lines.append(f"{p['paper_id']} abstract {p['artifacts']['abstract']['sha256_content']}")
        if p["artifacts"]["html"]:
            hash_lines.append(f"{p['paper_id']} html {p['artifacts']['html']['sha256_content']}")
    hash_lines.sort()
    corpus_hash = sha256_hex("\n".join(hash_lines).encode("utf-8"))

    manifest = {
        "corpus_version": "v1",
        "frozen_at": datetime.now(timezone.utc).date().isoformat(),
        "paper_count": len(papers),
        "selection_criteria": {
            "arxiv_categories": ["cs.CL", "cs.IR"],
            "date_window": {"from": "2024-09-01", "to": "2026-08-31"},
            "query": '(cat:cs.CL OR cat:cs.IR) AND abs:"retrieval-augmented generation" '
                     'AND submittedDate:[20240901000000 TO 20260831235959]',
            "queried_at": "2026-09-06T00:00:00Z",
            "inclusion_rules": [
                "presents quantitative results the paper itself owns",
                "substantive method, benchmark, or empirical-evaluation contribution to RAG",
            ],
            "exclusion_rules": ["surveys and systematic mapping studies — no own results to cite"],
            "max_anchors": 3,
            "anchor_rule": "pre-window papers admissible only as anchors; each requires selection_note naming >=2 in-window papers that cite or contest it",
        },
        "corpus_hash": corpus_hash,
        "papers": papers,
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {MANIFEST_PATH} with {len(papers)} papers", file=sys.stderr)


if __name__ == "__main__":
    main()
