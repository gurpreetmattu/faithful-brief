"""
Run the Verifier standalone against every row in data/claims.jsonl and report
precision/recall per perturbation_type, per specs/writer-verifier.md Sec 7 and the
sentence CLAUDE.md opens with: "I deliberately fed the system unfaithful claims and
measured what fraction it caught -- precision/recall, broken down by perturbation
type."

This bypasses the Writer entirely (Sec 7: verify() is a pure function of a
DraftClaim, not a Writer output) -- each row's claim_text/cited_paper_id/cited_span
is fed straight into verify() exactly as a live draft claim would be.

Positive class = "unsupported" (the thing the Verifier exists to catch):
  TP: label=unsupported, verdict=block   (caught a bad claim)
  FN: label=unsupported, verdict=pass    (missed a bad claim -- the dangerous case)
  FP: label=supported,   verdict=block   (wrongly blocked a good claim)
  TN: label=supported,   verdict=pass    (correctly passed a good claim)

Checkpointed at data/logs/eval_checkpoint.jsonl: each evaluated claim_id's result is
appended as it completes, and a re-run skips claim_ids already checkpointed. This
matters in practice, not just in theory -- both free-tier providers this project
currently runs against (Groq: shared daily quota; Hugging Face: shared monthly
credits) have been observed to run out mid-eval, and re-spending already-exhausted
budget to redo already-correct results would be wasteful. Pass --reset to ignore
the checkpoint and re-evaluate everything from scratch.

Usage: python scripts/eval_verifier.py [path/to/claims.jsonl] [--reset]
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from schemas import DraftClaim
from verifier import verify

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLAIMS_PATH = REPO_ROOT / "data" / "claims.jsonl"
CHECKPOINT_PATH = REPO_ROOT / "data" / "logs" / "eval_checkpoint.jsonl"


def load_claims(path: Path) -> list:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_checkpoint() -> dict:
    """claim_id -> checkpointed result dict, or {} if no checkpoint exists yet."""
    if not CHECKPOINT_PATH.exists():
        return {}
    done = {}
    with open(CHECKPOINT_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rec = json.loads(line)
                done[rec["claim_id"]] = rec
    return done


def append_checkpoint(rec: dict) -> None:
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    args = [a for a in sys.argv[1:] if a != "--reset"]
    reset = "--reset" in sys.argv
    path = Path(args[0]) if args else DEFAULT_CLAIMS_PATH
    rows = load_claims(path)
    print(f"Loaded {len(rows)} ground-truth claims from {path}", file=sys.stderr)

    if reset and CHECKPOINT_PATH.exists():
        CHECKPOINT_PATH.unlink()
        print("--reset: cleared existing checkpoint", file=sys.stderr)

    checkpoint = load_checkpoint()
    if checkpoint:
        print(f"Resuming: {len(checkpoint)} claims already checkpointed at {CHECKPOINT_PATH}", file=sys.stderr)
        # A resumed run's self-imposed Groq pacer (llm_client._wait_for_groq_budget)
        # starts with an empty in-memory history -- it has no way to know the
        # previous process's last calls, seconds ago, may still be inside Groq's
        # real 60s window. Replaying checkpointed rows costs nothing and takes no
        # time, so without this wait the very first *new* call fires immediately
        # into a window Groq's server still considers full. A fixed cool-down here
        # is cheap insurance against repeating that exact failure on every resume.
        print("Waiting 65s for any residual rate-limit window from a prior run to clear...", file=sys.stderr)
        time.sleep(65)

    tp = fp = fn = tn = 0
    per_type = defaultdict(lambda: {"tp": 0, "fn": 0})
    mismatches = []

    for i, row in enumerate(rows, 1):
        cached = checkpoint.get(row["claim_id"])
        if cached is not None:
            verdict_str = cached["verdict"]
            block_reason = cached["block_reason"]
            print(f"[{i}/{len(rows)}] {row['claim_id']} ... (checkpointed)", file=sys.stderr)
        else:
            claim = DraftClaim(
                claim_text=row["claim_text"],
                cited_paper_id=row["cited_paper_id"],
                cited_span=row["cited_span"],
            )
            print(f"[{i}/{len(rows)}] {row['claim_id']} ...", file=sys.stderr, flush=True)
            result = verify(claim)
            verdict_str = result.verdict
            block_reason = result.block_reason
            append_checkpoint(
                {
                    "claim_id": row["claim_id"],
                    "verdict": verdict_str,
                    "block_reason": block_reason,
                    "cited_entailment": result.cited_entailment,
                    "corpus_entailment": result.corpus_entailment,
                }
            )

        expected_unsupported = row["label"] == "unsupported"
        predicted_block = verdict_str == "block"

        if expected_unsupported and predicted_block:
            tp += 1
            outcome = "TP"
        elif expected_unsupported and not predicted_block:
            fn += 1
            outcome = "FN"
        elif not expected_unsupported and predicted_block:
            fp += 1
            outcome = "FP"
        else:
            tn += 1
            outcome = "TN"

        if expected_unsupported:
            ptype = row.get("perturbation_type") or "unknown"
            if predicted_block:
                per_type[ptype]["tp"] += 1
            else:
                per_type[ptype]["fn"] += 1

        if outcome in ("FP", "FN"):
            mismatches.append((row["claim_id"], outcome, row["label"], verdict_str, block_reason))

        print(f"    label={row['label']:12s} verdict={verdict_str:6s} -> {outcome}", file=sys.stderr)

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else float("nan")
    accuracy = (tp + tn) / len(rows) if rows else float("nan")

    print("\n=== Overall ===")
    print(f"n={len(rows)}  TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"accuracy={accuracy:.3f}  precision={precision:.3f}  recall={recall:.3f}  f1={f1:.3f}")

    print("\n=== Recall by perturbation_type ===")
    for ptype in sorted(per_type):
        stats = per_type[ptype]
        n = stats["tp"] + stats["fn"]
        r = stats["tp"] / n if n else float("nan")
        print(f"  {ptype:20s} caught={stats['tp']}/{n}  recall={r:.3f}")

    if mismatches:
        print("\n=== Mismatches (worth reading individually) ===")
        for claim_id, outcome, label, got_verdict, block_reason in mismatches:
            print(f"  {outcome}  {claim_id:12s} label={label:12s} verdict={got_verdict}  block_reason={block_reason}")
    else:
        print("\nNo mismatches -- every verdict matched its ground-truth label.")

    # CI gate (step 6, tier 2): recall is the number this project cannot tolerate
    # regressing -- a drop means a real unfaithful claim slipped through. Precision
    # is reported above but never gates: we've directly observed real run-to-run
    # LLM variance on this exact eval (the same claim flipping between FN and TP
    # across two runs earlier in this project's history), so a strict precision
    # bar would make CI flaky for reasons unrelated to a real regression.
    if recall < 1.0:
        print(f"\nFAILED: recall {recall:.3f} < 1.000 -- a real unfaithful claim was missed.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
