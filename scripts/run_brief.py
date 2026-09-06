"""
CLI: python scripts/run_brief.py "<research question>"

Runs the Writer to draft claims, then the Verifier over each one independently
(spec Sec 7), and prints the assembled brief (pass claims, spec Sec 6) and the
blocked-claims log (block claims) as JSON to stdout.

No file persistence here by design -- a durable brief format is step 8's UI concern,
not this CLI's.
"""

from __future__ import annotations

import json
import sys

from verifier import verify
from writer import draft_brief


def main():
    if len(sys.argv) != 2:
        print("usage: python scripts/run_brief.py \"<research question>\"", file=sys.stderr)
        sys.exit(1)
    question = sys.argv[1]

    draft_claims = draft_brief(question)

    brief = []
    blocked = []
    for claim in draft_claims:
        result = verify(claim)
        if result.verdict == "pass":
            brief.append(result.to_dict())
        else:
            blocked.append(result.to_dict())

    print(json.dumps({"question": question, "brief": brief, "blocked": blocked}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
