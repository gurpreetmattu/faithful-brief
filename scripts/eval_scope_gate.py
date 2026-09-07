"""
Run the scope gate standalone against every row in data/scope_gate.jsonl and
report accuracy, per specs/scope-gate.md. Same bypass discipline as
eval_verifier.py and eval_disagreement.py: each row's question is fed straight
into classify_scope(), no live brief involved.

Positive class = "decline" (the thing this gate exists to catch):
  TP: label=decline,  verdict=decline   (correctly declined)
  FN: label=decline,  verdict=in_scope  (should have declined but didn't -- lets
      an unanswerable question run the full pipeline anyway)
  FP: label=in_scope, verdict=decline   (wrongly declined a real question --
      the more costly direction for a research tool: it refuses to help)
  TN: label=in_scope, verdict=in_scope  (correctly proceeded)

Checkpointed at data/logs/scope_gate_eval_checkpoint.jsonl (--reset to clear).

Usage: python scripts/eval_scope_gate.py [path/to/scope_gate.jsonl] [--reset]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from scope_gate import classify_scope

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "data" / "scope_gate.jsonl"
CHECKPOINT_PATH = REPO_ROOT / "data" / "logs" / "scope_gate_eval_checkpoint.jsonl"


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
                done[rec["question_id"]] = rec
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
    print(f"Loaded {len(rows)} ground-truth scope questions from {path}", file=sys.stderr)

    if reset and CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
        print("--reset: cleared existing checkpoint", file=sys.stderr)

    checkpoint = load_checkpoint()
    if checkpoint:
        print(f"Resuming: {len(checkpoint)} questions already checkpointed at {CHECKPOINT_PATH}", file=sys.stderr)
        print("Waiting 65s for any residual rate-limit window from a prior run to clear...", file=sys.stderr)
        time.sleep(65)

    tp = fp = fn = tn = 0
    mismatches = []

    for i, row in enumerate(rows, 1):
        cached = checkpoint.get(row["question_id"])
        if cached is not None:
            got_label = cached["label"]
            got_reason = cached["decline_reason"]
            print(f"[{i}/{len(rows)}] {row['question_id']} ... (checkpointed)", file=sys.stderr)
        else:
            print(f"[{i}/{len(rows)}] {row['question_id']} ...", file=sys.stderr, flush=True)
            result = classify_scope(row["question"])
            got_label = result.label
            got_reason = result.decline_reason
            append_checkpoint(
                {
                    "question_id": row["question_id"],
                    "label": got_label,
                    "decline_reason": got_reason,
                    "rationale": result.rationale,
                }
            )

        expected_decline = row["label"] == "decline"
        predicted_decline = got_label == "decline"

        if expected_decline and predicted_decline:
            tp += 1
            outcome = "TP"
        elif expected_decline and not predicted_decline:
            fn += 1
            outcome = "FN"
        elif not expected_decline and predicted_decline:
            fp += 1
            outcome = "FP"
        else:
            tn += 1
            outcome = "TN"

        if outcome in ("FP", "FN"):
            mismatches.append((row["question_id"], outcome, row["label"], got_label, row.get("decline_reason"), got_reason))

        print(f"    label={row['label']:9s} -> got={got_label:9s} -> {outcome}", file=sys.stderr)

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    accuracy = (tp + tn) / len(rows) if rows else float("nan")

    print("\n=== Overall ===")
    print(f"n={len(rows)}  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"accuracy={accuracy:.3f}  precision={precision:.3f}  recall={recall:.3f}")
    print(
        "\nNote on which error matters more: FP (wrongly declining a real "
        "question) blocks a user from getting help at all; FN (failing to "
        "decline) just means an out-of-scope question runs the full pipeline "
        "and likely comes back all-blocked anyway -- annoying, not harmful. "
        "This is the opposite priority from the Verifier's recall-first gate."
    )

    if mismatches:
        print("\n=== Mismatches ===")
        for qid, outcome, exp_label, got_label, exp_reason, got_reason in mismatches:
            print(f"  {outcome}  {qid}  label: expected={exp_label} got={got_label}  reason: expected={exp_reason} got={got_reason}")
    else:
        print("\nNo mismatches -- every verdict matched its ground-truth label.")

    sys.exit(0)


if __name__ == "__main__":
    main()
