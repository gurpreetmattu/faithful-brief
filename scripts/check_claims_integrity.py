"""
Tier 1 of build-order step 6's CI gate (CLAUDE.md): a fast, free, deterministic
check with no LLM calls, run on every push/PR.

Validates data/claims.jsonl against specs/claim-schema.md Sec 4's field contract,
and mechanically re-verifies every non-null cited_span against the frozen corpus
using the exact same corpus_access.span_verified() the live Verifier uses (spec
Sec 5.1) -- one source of truth for "does this span really exist," not a second
mechanism that could quietly drift from it.

This is the ad hoc check run by hand several times earlier in this project's
history, made permanent. Exit 0 on a clean pass, exit 1 with every violation
listed on any failure.

Usage: python scripts/check_claims_integrity.py [path/to/claims.jsonl]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import corpus_access

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLAIMS_PATH = REPO_ROOT / "data" / "claims.jsonl"

REQUIRED_FIELDS = {
    "claim_id",
    "claim_text",
    "cited_paper_id",
    "span_artifact",
    "cited_span",
    "label",
    "perturbation_type",
    "derived_from",
    "label_rationale",
}
VALID_LABELS = {"supported", "unsupported"}
VALID_PERTURBATION_TYPES = {
    "magnitude_change",
    "entity_swap",
    "scope_broadening",
    "causal_inversion",
    "attribution_swap",
    "plausible_addition",
}
VALID_SPAN_ARTIFACTS = {"abstract", "html"}


def check_row(row: dict, line_no: int) -> list:
    """Returns a list of violation strings for one row (empty if clean)."""
    violations = []
    claim_id = row.get("claim_id", f"<line {line_no}, no claim_id>")

    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        violations.append(f"{claim_id}: missing fields {sorted(missing)}")
        return violations  # can't check anything else meaningfully

    label = row["label"]
    if label not in VALID_LABELS:
        violations.append(f"{claim_id}: label {label!r} not in {VALID_LABELS}")

    ptype = row["perturbation_type"]
    if label == "supported" and ptype is not None:
        violations.append(f"{claim_id}: label=supported but perturbation_type={ptype!r} (must be null)")
    elif label == "unsupported":
        if ptype not in VALID_PERTURBATION_TYPES:
            violations.append(f"{claim_id}: perturbation_type {ptype!r} not in {VALID_PERTURBATION_TYPES}")

    span = row["cited_span"]
    artifact = row["span_artifact"]
    if span is None:
        if ptype != "plausible_addition":
            violations.append(
                f"{claim_id}: cited_span is null but perturbation_type={ptype!r} "
                "(spec Sec 4: null only for plausible_addition)"
            )
        if artifact is not None:
            violations.append(f"{claim_id}: cited_span is null but span_artifact={artifact!r} (should be null too)")
    else:
        if artifact not in VALID_SPAN_ARTIFACTS:
            violations.append(f"{claim_id}: span_artifact {artifact!r} not in {VALID_SPAN_ARTIFACTS}")
        paper_id = row["cited_paper_id"]
        if paper_id not in corpus_access.paper_ids():
            violations.append(f"{claim_id}: cited_paper_id {paper_id!r} is not in the frozen corpus")
        elif not corpus_access.span_verified(paper_id, span):
            violations.append(
                f"{claim_id}: cited_span does not appear verbatim in {paper_id}'s "
                "extracted abstract or body text"
            )

    if not row["label_rationale"].strip():
        violations.append(f"{claim_id}: label_rationale is empty")

    return violations


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CLAIMS_PATH
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if line:
                rows.append((line_no, json.loads(line)))

    print(f"Checking {len(rows)} rows in {path} ...")
    all_violations = []
    for line_no, row in rows:
        all_violations.extend(check_row(row, line_no))

    if all_violations:
        print(f"\nFAILED: {len(all_violations)} integrity violation(s):")
        for v in all_violations:
            print(f"  - {v}")
        sys.exit(1)

    print(f"OK: all {len(rows)} rows pass schema and verbatim-span checks.")
    sys.exit(0)


if __name__ == "__main__":
    main()
