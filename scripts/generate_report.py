"""
Step 8: renders a self-contained HTML report from one run_brief.py result.

render_html() takes the exact dict shape run_brief.py already produces
({"question", "brief", "blocked"}, each item a Verdict.to_dict()) and returns a
complete HTML document -- inline <style>, no external CDN/JS/fonts, so the
file opens correctly straight from disk with no network access.

Sections: a trust receipt (plain numbers on what was checked -- CLAUDE.md's
"the trust is the product" given an actual visual form), the citations that
made it into the brief, the blocked claims (the demo money-shot: the system
catching a bad claim), disagreements -- real detector output (from
data/logs/disagreement_eval_checkpoint.jsonl, produced by
scripts/eval_disagreement.py) shown against the human labels for the fixed
candidate set in data/disagreements.jsonl. This module makes no LLM calls
itself and never generates candidate pairs (that's an unbuilt problem, spec
Sec 1) -- it only renders whatever the detector has already, really, said --
and "beyond the frozen corpus": live arXiv search results
(specs/live-discovery.md), explicitly labeled not verified/not cited so they
can never be mistaken for a real citation the Verifier checked.

Usage: python scripts/generate_report.py <brief.json> [-o out.html]
"""

from __future__ import annotations

import html
import json
import sys
from collections import Counter
from typing import Optional
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DISAGREEMENTS_PATH = REPO_ROOT / "data" / "disagreements.jsonl"
DISAGREEMENT_CHECKPOINT_PATH = REPO_ROOT / "data" / "logs" / "disagreement_eval_checkpoint.jsonl"

_STYLE = """
:root {
  --bg: #f7f7f5; --card: #ffffff; --text: #1c1c1c; --muted: #6b6b6b;
  --border: #e3e2de; --accent: #2f6f4f; --accent-bg: #eaf4ee;
  --warn: #a13a2e; --warn-bg: #fbecea; --stub-bg: #f1f1ee;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17181a; --card: #1f2023; --text: #e8e8e6; --muted: #9a9a95;
    --border: #34353a; --accent: #6fcf9a; --accent-bg: #16261e;
    --warn: #e0796a; --warn-bg: #2c1b18; --stub-bg: #232427;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.5;
}
.wrap { max-width: 760px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
.question { color: var(--muted); font-size: 1rem; margin: 0 0 28px; }
.card {
  background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px 22px; margin-bottom: 20px;
}
.receipt-stats { display: flex; flex-wrap: wrap; gap: 20px; margin-top: 12px; }
.stat { min-width: 110px; }
.stat .n { font-size: 1.6rem; font-weight: 700; }
.stat .label { color: var(--muted); font-size: 0.8rem; }
.stat.pass .n { color: var(--accent); }
.stat.block .n { color: var(--warn); }
.receipt-note { color: var(--muted); font-size: 0.85rem; margin-top: 14px; }
section h2 {
  font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: var(--muted); margin: 32px 0 12px;
}
.claim { border-bottom: 1px solid var(--border); padding: 14px 0; }
.claim:last-child { border-bottom: none; }
.claim-text { font-weight: 600; margin: 0 0 6px; }
.claim blockquote {
  margin: 8px 0 6px; padding: 8px 12px; border-left: 3px solid var(--border);
  color: var(--muted); font-size: 0.92rem; font-style: italic;
}
.claim .meta { font-size: 0.8rem; color: var(--muted); }
.claim .meta a { color: var(--accent); text-decoration: none; }
.claim.blocked { }
.claim.blocked .reason {
  display: inline-block; font-size: 0.75rem; font-weight: 600;
  color: var(--warn); background: var(--warn-bg); border-radius: 4px;
  padding: 2px 8px; margin-bottom: 8px;
}
.claim.blocked .rationale { font-size: 0.9rem; }
.blocked-card { border-color: var(--warn); }
.empty { color: var(--muted); font-style: italic; font-size: 0.9rem; }
.stub {
  background: var(--stub-bg); border: 1px dashed var(--border);
  border-radius: 10px; padding: 18px 22px; color: var(--muted); font-size: 0.9rem;
}
.stub strong { color: var(--text); }
.caveat {
  background: var(--stub-bg); border: 1px dashed var(--border);
  border-radius: 8px; padding: 12px 16px; color: var(--muted); font-size: 0.85rem;
  margin-bottom: 16px;
}
.caveat strong { color: var(--text); }
.disagreement { border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin-bottom: 14px; }
.disagreement .topic { font-weight: 600; margin: 0 0 10px; }
.disagreement .spans { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.disagreement .span-row { font-size: 0.88rem; }
.disagreement .span-row .who { color: var(--muted); font-size: 0.78rem; }
.disagreement .verdicts { display: flex; flex-wrap: wrap; gap: 10px; font-size: 0.82rem; }
.pill {
  display: inline-block; border-radius: 4px; padding: 2px 9px; font-weight: 600;
}
.pill.human { background: var(--stub-bg); color: var(--text); border: 1px solid var(--border); }
.pill.match { background: var(--accent-bg); color: var(--accent); }
.pill.mismatch { background: var(--warn-bg); color: var(--warn); }
.disagreement .rationale { font-size: 0.85rem; color: var(--muted); margin-top: 8px; }
.idea-age { font-size: 0.78rem; color: var(--muted); font-style: italic; margin-top: 6px; }
.recency-banner {
  background: var(--stub-bg); border: 1px dashed var(--border); border-radius: 8px;
  padding: 10px 16px; color: var(--muted); font-size: 0.85rem; margin-bottom: 20px;
}
.discovery-note { font-size: 0.85rem; color: var(--muted); margin-bottom: 14px; }
.discovery-item { padding: 10px 0; border-bottom: 1px solid var(--border); }
.discovery-item:last-child { border-bottom: none; }
.discovery-item .title { font-weight: 600; margin: 0 0 4px; }
.discovery-item .title a { color: var(--text); text-decoration: none; }
.discovery-item .title a:hover { color: var(--accent); }
.discovery-item .snippet { font-size: 0.85rem; color: var(--muted); }
"""


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _claim_block(item: dict, blocked: bool) -> str:
    claim = item["claim"]
    paper_id = claim["cited_paper_id"]
    span = claim.get("cited_span")
    arxiv_url = f"https://arxiv.org/abs/{paper_id}"
    idea_note = item.get("idea_age_note")
    idea_note_html = f'<p class="idea-age">{_esc(idea_note)}</p>' if idea_note else ""

    if blocked:
        reason = item.get("block_reason") or "unknown"
        rationale = item.get("verifier_rationale") or ""
        span_html = (
            f"<blockquote>{_esc(span)}</blockquote>" if span else "<p class='empty'>No cited span given.</p>"
        )
        return f"""
        <div class="claim blocked">
          <span class="reason">{_esc(reason)}</span>
          <p class="claim-text">{_esc(claim['claim_text'])}</p>
          {span_html}
          <p class="meta">cited to <a href="{arxiv_url}">{_esc(paper_id)}</a></p>
          <p class="rationale">{_esc(rationale)}</p>
          {idea_note_html}
        </div>
        """
    return f"""
    <div class="claim">
      <p class="claim-text">{_esc(claim['claim_text'])}</p>
      <blockquote>{_esc(span)}</blockquote>
      <p class="meta">source: <a href="{arxiv_url}">{_esc(paper_id)}</a></p>
      {idea_note_html}
    </div>
    """


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _disagreement_row(pair: dict, detector: dict | None) -> str:
    human_pill = f'<span class="pill human">human: {_esc(pair["label"])}</span>'

    if detector is None:
        detector_pill = '<span class="pill human">detector: not run</span>'
        rationale_html = ""
    else:
        got_label = detector["label"]
        match = got_label == pair["label"]
        cls = "match" if match else "mismatch"
        detector_pill = f'<span class="pill {cls}">detector: {_esc(got_label)}</span>'
        rationale_html = f'<p class="rationale">{_esc(detector.get("rationale", ""))}</p>'

    reason_bits = []
    if pair.get("apparent_reason"):
        reason_bits.append(f'<span class="pill human">human reason: {_esc(pair["apparent_reason"])}</span>')
    if detector is not None and detector.get("apparent_reason"):
        reason_bits.append(f'<span class="pill human">detector reason: {_esc(detector["apparent_reason"])}</span>')

    return f"""
    <div class="disagreement">
      <p class="topic">{_esc(pair['topic'])}</p>
      <div class="spans">
        <div class="span-row"><span class="who">{_esc(pair['paper_a_id'])}:</span> &ldquo;{_esc(pair['span_a'])}&rdquo;</div>
        <div class="span-row"><span class="who">{_esc(pair['paper_b_id'])}:</span> &ldquo;{_esc(pair['span_b'])}&rdquo;</div>
      </div>
      <div class="verdicts">{human_pill}{detector_pill}{''.join(reason_bits)}</div>
      {rationale_html}
    </div>
    """


def _disagreements_panel() -> str:
    pairs = _load_jsonl(DISAGREEMENTS_PATH)
    if not pairs:
        return '<div class="stub"><strong>No ground-truth pairs found.</strong></div>'

    detector_by_id = {r["pair_id"]: r for r in _load_jsonl(DISAGREEMENT_CHECKPOINT_PATH)}
    has_genuine = any(p["label"] == "genuine" for p in pairs)

    caveat = f"""
    <div class="caveat">
      <strong>What this panel is, honestly:</strong> {len(pairs)} hand-labeled
      candidate pairs from <code>data/disagreements.jsonl</code>
      (<code>specs/disagreement-schema.md</code>) -- a fixed set, not pairs
      generated from the question above. Finding candidate pairs is a separate,
      unbuilt problem (spec &sect;1); this only shows what
      <code>scripts/disagreement_detector.py</code> says about pairs a human
      already identified. Detector verdicts below come from
      <code>data/logs/disagreement_eval_checkpoint.jsonl</code>
      ({"present" if detector_by_id else "not found -- run scripts/eval_disagreement.py first"}).
      {"" if has_genuine else (
          "<br><strong>No `genuine` example exists in this set</strong> -- every row "
          "is `apparent`, so the detector's recall on a real genuine disagreement is "
          "unmeasured. A detector that always answered \"apparent\" would look just "
          "as good here."
      )}
    </div>
    """

    rows_html = "\n".join(_disagreement_row(p, detector_by_id.get(p["pair_id"])) for p in pairs)
    return caveat + rows_html


def _live_discovery_html(live_discovery: Optional[list]) -> str:
    note = (
        '<p class="discovery-note"><strong>Beyond the frozen corpus</strong> -- '
        "live arXiv search results, NOT verified and NOT cited in this brief "
        "(specs/live-discovery.md). For your own follow-up reading only.</p>"
    )
    if not live_discovery:
        return note + "<p class='empty'>No live results found (or none beyond the frozen corpus).</p>"
    items = "\n".join(
        f"""
        <div class="discovery-item">
          <p class="title"><a href="{_esc(r['arxiv_url'])}">{_esc(r['title'])}</a></p>
          <p class="snippet">{_esc(r['abstract_snippet'])}</p>
        </div>
        """
        for r in live_discovery
    )
    return note + items


def _recency_banner(recency: Optional[dict]) -> str:
    if not recency or not (recency.get("corpus_stale") or recency.get("question_recency_sensitive")):
        return ""
    return f'<div class="recency-banner">{_esc(recency.get("note", ""))}</div>'


def _declined_html(question: str, result: dict) -> str:
    # Step 9's scope gate short-circuited before any Writer/Verifier call --
    # render that plainly instead of falling through to the normal report,
    # which would otherwise show an honest-looking but misleading 0/0/0 trust
    # receipt (indistinguishable from "we tried and found nothing").
    reason = result.get("decline_reason") or "unknown"
    rationale = result.get("scope_rationale") or ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Faithful Brief Report</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
  <h1>Faithful Brief</h1>
  <p class="question">{_esc(question)}</p>
  {_recency_banner(result.get("recency"))}
  <div class="card">
    <span class="reason">declined: {_esc(reason)}</span>
    <p style="margin-top:10px;">This question was declined by the scope gate
    (<code>specs/scope-gate.md</code>) before any Writer or Verifier call was
    made -- no brief was attempted.</p>
    <p class="receipt-note">{_esc(rationale)}</p>
  </div>

  <section>
    <h2>Beyond the frozen corpus</h2>
    {_live_discovery_html(result.get("live_discovery"))}
  </section>
</div>
</body>
</html>
"""


def render_html(result: dict) -> str:
    question = result.get("question", "")
    if result.get("declined"):
        return _declined_html(question, result)
    brief = result.get("brief", [])
    blocked = result.get("blocked", [])
    total = len(brief) + len(blocked)
    reason_counts = Counter(item.get("block_reason") or "unknown" for item in blocked)
    reason_line = ", ".join(f"{k}: {v}" for k, v in sorted(reason_counts.items())) if blocked else "none"

    citations_html = (
        "\n".join(_claim_block(item, blocked=False) for item in brief)
        if brief
        else "<p class='empty'>No claims passed verification for this brief.</p>"
    )
    blocked_html = (
        "\n".join(_claim_block(item, blocked=True) for item in blocked)
        if blocked
        else "<p class='empty'>Nothing was blocked -- every drafted claim was verified.</p>"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Faithful Brief Report</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
  <h1>Faithful Brief</h1>
  <p class="question">{_esc(question)}</p>
  {_recency_banner(result.get("recency"))}

  <div class="card">
    <div class="receipt-stats">
      <div class="stat"><div class="n">{total}</div><div class="label">claims drafted</div></div>
      <div class="stat pass"><div class="n">{len(brief)}</div><div class="label">verified &amp; included</div></div>
      <div class="stat block"><div class="n">{len(blocked)}</div><div class="label">blocked</div></div>
    </div>
    <p class="receipt-note">
      Blocked by reason: {_esc(reason_line)}.
      Every claim above traces to a verbatim span checked against the frozen,
      hash-pinned corpus (<code>data/corpus.v1.json</code>) -- nothing in this
      brief is unverified.
    </p>
  </div>

  <section>
    <h2>Citations</h2>
    {citations_html}
  </section>

  <section>
    <h2>Blocked claims</h2>
    <div class="card blocked-card">
      {blocked_html}
    </div>
  </section>

  <section>
    <h2>Disagreements</h2>
    {_disagreements_panel()}
  </section>

  <section>
    <h2>Beyond the frozen corpus</h2>
    {_live_discovery_html(result.get("live_discovery"))}
  </section>
</div>
</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print("usage: python scripts/generate_report.py <brief.json> [-o out.html]", file=sys.stderr)
        sys.exit(1)
    in_path = Path(sys.argv[1])
    if "-o" in sys.argv:
        out_path = Path(sys.argv[sys.argv.index("-o") + 1])
    else:
        out_path = in_path.with_suffix(".html")

    result = json.loads(in_path.read_text(encoding="utf-8"))
    out_path.write_text(render_html(result), encoding="utf-8")
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
