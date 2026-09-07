"""
Run the Disagreement Detector standalone against every row in
data/disagreements.jsonl and report accuracy, per specs/disagreement-schema.md
and the same "bypass, don't fabricate" discipline eval_verifier.py uses for the
Verifier (writer-verifier.md Sec 7): each row's paper_a_id/paper_b_id/topic/
span_a/span_b is fed straight into classify() exactly as a live candidate would
be, no detector-under-test involved in producing the row itself.

READ THIS BEFORE TRUSTING THE NUMBER THIS PRINTS: every row in
data/disagreements.jsonl today is labeled `apparent` -- four independent search
passes across the corpus found zero `genuine` examples (CLAUDE.md step 7).
100% accuracy on this eval set is therefore NOT evidence the detector can catch
a real genuine contradiction -- a detector hardcoded to always return "apparent"
would also score 100% here. This script deliberately prints that caveat with
every run rather than only in a comment nobody reads at run time.

Checkpointed at data/logs/disagreement_eval_checkpoint.jsonl, same rationale
and mechanism as eval_verifier.py's checkpoint (shared free-tier provider
quotas have been observed to run out mid-run; --reset clears it).

Usage: python scripts/eval_disagreement.py [path/to/disagreements.jsonl] [--reset]
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

from disagreement_detector import classify
from schemas import DisagreementCandidate

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "data" / "disagreements.jsonl"
CHECKPOINT_PATH = REPO_ROOT / "data" / "logs" / "disagreement_eval_checkpoint.jsonl"


def load_rows(path: Path) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_checkpoint() -> dict:
    if not CHECKPOINT_PATH.exists():
        return {}
    done = {}
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                done[rec["pair_id"]] = rec
    return done


def append_checkpoint(rec: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    args = [a for a in sys.argv[1:] if a != "--reset"]
    reset = "--reset" in sys.argv
    path = Path(args[0]) if args else DEFAULT_PATH
    rows = load_rows(path)
    print(f"Loaded {len(rows)} ground-truth disagreement pairs from {path}", file=sys.stderr)

    label_counts = Counter(r["label"] for r in rows)
    if not label_counts.get("genuine"):
        print(
            "\nWARNING: 0 'genuine' rows in this eval set -- see this script's "
            "module docstring. Any accuracy number below only measures apparent-"
            "case discrimination.\n",
            file=sys.stderr,
        )

    if reset and CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
        print("--reset: cleared existing checkpoint", file=sys.stderr)

    checkpoint = load_checkpoint()
    if checkpoint:
        print(f"Resuming: {len(checkpoint)} pairs already checkpointed at {CHECKPOINT_PATH}", file=sys.stderr)
        print("Waiting 65s for any residual rate-limit window from a prior run to clear...", file=sys.stderr)
        time.sleep(65)

    correct_label = 0
    correct_reason = 0  # of the apparent rows, how many also got apparent_reason right
    apparent_rows = 0
    mismatches = []

    for i, row in enumerate(rows, 1):
        cached = checkpoint.get(row["pair_id"])
        if cached is not None:
            got_label = cached["label"]
            got_reason = cached["apparent_reason"]
            print(f"[{i}/{len(rows)}] {row['pair_id']} ... (checkpointed)", file=sys.stderr)
        else:
            candidate = DisagreementCandidate(
                paper_a_id=row["paper_a_id"],
                paper_b_id=row["paper_b_id"],
                topic=row["topic"],
                span_a=row["span_a"],
                span_b=row["span_b"],
            )
            print(f"[{i}/{len(rows)}] {row['pair_id']} ...", file=sys.stderr, flush=True)
            result = classify(candidate)
            got_label = result.label
            got_reason = result.apparent_reason
            append_checkpoint(
                {
                    "pair_id": row["pair_id"],
                    "label": got_label,
                    "apparent_reason": got_reason,
                    "rationale": result.rationale,
                }
            )

        label_ok = got_label == row["label"]
        if label_ok:
            correct_label += 1

        reason_ok = None
        if row["label"] == "apparent":
            apparent_rows += 1
            reason_ok = label_ok and got_reason == row["apparent_reason"]
            if reason_ok:
                correct_reason += 1

        if not label_ok or reason_ok is False:
            mismatches.append((row["pair_id"], row["label"], got_label, row.get("apparent_reason"), got_reason))

        print(
            f"    label={row['label']:9s} -> got={got_label:9s}"
            + (f"  reason={row.get('apparent_reason')} -> got={got_reason}" if row["label"] == "apparent" else ""),
            file=sys.stderr,
        )

    label_accuracy = correct_label / len(rows) if rows else float("nan")
    reason_accuracy = correct_reason / apparent_rows if apparent_rows else float("nan")

    print("\n=== Overall ===")
    print(f"n={len(rows)}  label_accuracy={label_accuracy:.3f}")
    print(f"apparent_reason_accuracy (of {apparent_rows} apparent rows) = {reason_accuracy:.3f}")

    print(
        "\nNOTE: no 'genuine' rows exist in this eval set -- label_accuracy above "
        "does not measure whether this detector can recognize a real genuine "
        "disagreement. See this script's and disagreement_detector.py's module "
        "docstrings, and CLAUDE.md step 7."
    )

    if mismatches:
        print("\n=== Mismatches ===")
        for pair_id, exp_label, got_label, exp_reason, got_reason in mismatches:
            print(f"  {pair_id}  label: expected={exp_label} got={got_label}  reason: expected={exp_reason} got={got_reason}")
    else:
        print("\nNo mismatches -- every verdict matched its ground-truth label (apparent-only).")

    # Unlike eval_verifier.py, this does NOT set a CI exit-code gate on any
    # threshold. With zero genuine examples, a numeric gate here would create
    # false confidence -- CLAUDE.md's own working standard bars "demoed, not
    # shipped," and gating on an incomplete eval set is exactly that dressed up
    # as rigor. This always exits 0; a human reads the printed numbers.
    sys.exit(0)


if __name__ == "__main__":
    main()
