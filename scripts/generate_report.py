"""
Step 8: renders a self-contained HTML report from one run_brief.py result.

render_html() takes the exact dict shape run_brief.py already produces
({"question", "brief", "blocked"}, each item a Verdict.to_dict()) and returns a
complete HTML document -- inline <style>, no external CDN/JS/fonts, so the
file opens correctly straight from disk with no network access.

Sections: a trust receipt (plain numbers on what was checked -- CLAUDE.md's
"the trust is the product" given an actual visual form), the citations that
made it into the brief, the blocked claims (the demo money-shot: the system
catching a bad claim), and disagreements -- which is an HONEST PLACEHOLDER,
not fake data: step 7 has no detector yet, only hand-labeled ground truth in
data/disagreements.jsonl. Never render a sample/fabricated disagreement here.

Usage: python scripts/generate_report.py <brief.json> [-o out.html]
"""

from __future__ import annotations

import html
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DISAGREEMENTS_PATH = REPO_ROOT / "data" / "disagreements.jsonl"

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
"""


def _esc(s) -> str:
    return html.escape(str(s)) if s is not None else ""


def _claim_block(item: dict, blocked: bool) -> str:
    claim = item["claim"]
    paper_id = claim["cited_paper_id"]
    span = claim.get("cited_span")
    arxiv_url = f"https://arxiv.org/abs/{paper_id}"

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
        </div>
        """
    return f"""
    <div class="claim">
      <p class="claim-text">{_esc(claim['claim_text'])}</p>
      <blockquote>{_esc(span)}</blockquote>
      <p class="meta">source: <a href="{arxiv_url}">{_esc(paper_id)}</a></p>
    </div>
    """


def _disagreements_stub() -> str:
    count = 0
    if DISAGREEMENTS_PATH.exists():
        with open(DISAGREEMENTS_PATH, encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
    return f"""
    <div class="stub">
      <strong>Not yet available.</strong> Step 7 (disagreement detection) has no
      detector built yet -- only hand-labeled ground truth exists so far:
      {count} real cross-paper pairs in <code>data/disagreements.jsonl</code>,
      each labeled genuine or apparent per <code>specs/disagreement-schema.md</code>.
      This panel will surface real detected disagreements once that detector exists.
    </div>
    """


def render_html(result: dict) -> str:
    question = result.get("question", "")
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
    {_disagreements_stub()}
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
