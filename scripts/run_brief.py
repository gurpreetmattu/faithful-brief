"""
CLI: python scripts/run_brief.py "<research question>" [--html out.html]

Runs the step 9 scope gate first (specs/scope-gate.md): a question the gate
declines short-circuits here -- no Writer/Verifier call at all -- and the
result carries declined=true plus why, instead of silently running the full
pipeline down to an empty/all-blocked brief that looks like an ordinary
failure. Otherwise, runs the Writer to draft claims, then the Verifier over
each one independently (spec Sec 7), and prints the assembled brief (pass
claims, spec Sec 6) and the blocked-claims log (block claims) as JSON to
stdout -- always, unchanged from before. --html is additive: also render the
step 8 report (generate_report.py) directly, so asking a question and getting
a viewable report is one command instead of a JSON-then-convert two-step.

NOTE on the rendered report's disagreements panel: it reads
data/logs/disagreement_eval_checkpoint.jsonl, which this command does NOT
produce -- that file only exists after running
`python scripts/eval_disagreement.py`. Without it, the panel says so plainly
rather than rendering nothing silently; it never depends on the question asked
here, since disagreement candidates are a fixed hand-labeled set, not derived
from a live brief (disagreement-schema.md Sec 1).
"""

from __future__ import annotations

import json
import sys

from generate_report import render_html
from scope_gate import classify_scope
from verifier import verify
from writer import draft_brief


def main():
    html_path = None
    argv = sys.argv[1:]
    if "--html" in argv:
        idx = argv.index("--html")
        html_path = argv[idx + 1]
        argv = argv[:idx] + argv[idx + 2:]

    if len(argv) != 1:
        print("usage: python scripts/run_brief.py \"<research question>\" [--html out.html]", file=sys.stderr)
        sys.exit(1)
    question = argv[0]

    scope = classify_scope(question)
    if scope.label == "decline":
        result = {
            "question": question,
            "declined": True,
            "decline_reason": scope.decline_reason,
            "scope_rationale": scope.rationale,
            "brief": [],
            "blocked": [],
        }
        print(json.dumps(result, indent=2, ensure_ascii=True))
        print(
            f"Declined ({scope.decline_reason}) -- no Writer/Verifier call made. {scope.rationale}",
            file=sys.stderr,
        )
        if html_path:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(render_html(result))
            print(f"wrote {html_path}", file=sys.stderr)
        return

    draft_claims = draft_brief(question)

    brief = []
    blocked = []
    for claim in draft_claims:
        result = verify(claim)
        if result.verdict == "pass":
            brief.append(result.to_dict())
        else:
            blocked.append(result.to_dict())

    result = {"question": question, "brief": brief, "blocked": blocked}
    # ensure_ascii=True: paper-derived text can contain arbitrary Unicode (e.g.
    # non-breaking hyphens), and this console's default stdout encoding
    # (cp1252 on Windows) can't represent it directly. \uXXXX-escaped JSON is
    # still valid JSON -- json.loads() decodes it transparently -- so this is
    # the portable choice, not a workaround that loses information.
    print(json.dumps(result, indent=2, ensure_ascii=True))

    if html_path:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(render_html(result))
        print(f"wrote {html_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
