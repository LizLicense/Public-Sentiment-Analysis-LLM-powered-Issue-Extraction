#!/usr/bin/env python3
"""Label the clean corpus with GPT-4o-mini sentiment, using the evaluated setup.

Reuses the prompt, batching, retries and parsing from models/llm_evaluation.py, so
corpus labels come from the same configuration that scored sentiment macro F1
0.631 on the 295 representative gold posts. Only sentiment is used downstream;
the issue labels the joint prompt also returns are kept for reference, because
the hybrid rules + GPT-4o issue labels already beat all-post LLM issues.

Usage (from project root):
  export OPENAI_API_KEY="..."
  python models/corpus_llm_sentiment.py --dry-run     # plan + cost estimate, no API calls
  python models/corpus_llm_sentiment.py               # run (resumable; rerun to continue)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from models.llm_evaluation import (
    OpenAI,
    append_checkpoint,
    batches,
    call_batch,
    cost_summary,
    load_checkpoint,
)

DEFAULT_INPUT = Path("data/processed/clean_posts_2026-08-21_203752.csv")
DEFAULT_OUTPUT = Path("data/processed/clean_posts_2026-08-21_203752_mini_sentiment.csv")
DEFAULT_CHECKPOINT = Path("data/processed/clean_posts_mini_sentiment_checkpoint.jsonl")
DEFAULT_SUMMARY = Path("data/processed/clean_posts_mini_sentiment_summary.json")

# Measured on the representative evaluation run: 38,464 tokens for 295 posts.
TOKENS_PER_POST = 38_464 / 295


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GPT-4o-mini sentiment on the clean corpus")
    parser.add_argument("--in", dest="input_path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--summary-out", type=Path, default=DEFAULT_SUMMARY)
    # Same defaults as models/llm_evaluation.py; change them and the gold-set score no longer applies.
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL", ""))
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-text-chars", type=int, default=2000)
    parser.add_argument("--max-output-tokens", type=int, default=1600)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=2.0)
    parser.add_argument("--input-cost-per-million", type=float, default=0.15)
    parser.add_argument("--output-cost-per-million", type=float, default=0.60)
    parser.add_argument("--limit", type=int, default=0, help="Optional post limit for a pilot.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and cost estimate only.")
    return parser.parse_args()


def read_posts(path: Path, limit: int) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for i, row in enumerate(rows):
        # Stable per-post ID, so a rebuilt corpus reuses the checkpoint instead of re-billing.
        row["sample_id"] = row.get("post_key") or f"CP-{i:05d}"
    return (rows[:limit] if limit else rows), fields


def main() -> None:
    args = parse_args()
    rows, fields = read_posts(args.input_path, args.limit)
    n_batches = (len(rows) + args.batch_size - 1) // args.batch_size
    done = load_checkpoint(args.checkpoint)
    pending = [r for r in rows if r["sample_id"] not in done or done[r["sample_id"]].get("error")]
    est_tokens = TOKENS_PER_POST * len(pending)
    est_cost = est_tokens / 1_000_000 * (0.8 * args.input_cost_per_million + 0.2 * args.output_cost_per_million)

    print(f"Posts: {len(rows):,} in {n_batches} batches of {args.batch_size}; already done: {len(rows) - len(pending):,}")
    print(f"Model: {args.model}  |  estimated ~{est_tokens:,.0f} tokens, ~${est_cost:.2f}")
    if args.dry_run:
        print("Dry run: no API calls made.")
        return

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")
    if OpenAI is None:
        raise SystemExit("The openai package is not installed. Run: venv/bin/python -m pip install openai")
    client = OpenAI(api_key=api_key, base_url=args.base_url or None)
    call_args = SimpleNamespace(
        model=args.model,
        max_text_chars=args.max_text_chars,
        max_output_tokens=args.max_output_tokens,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
    )

    started = time.perf_counter()
    total = (len(pending) + args.batch_size - 1) // args.batch_size
    for number, batch in enumerate(batches(pending, args.batch_size), start=1):
        output, meta = call_batch(client, batch, call_args)
        append_checkpoint(args.checkpoint, output)
        status = f"error: {meta['error']}" if meta["error"] else f"{meta['returned_model']} ok"
        print(f"[{number}/{total}] {status}", flush=True)
    elapsed = time.perf_counter() - started

    done = load_checkpoint(args.checkpoint)
    failed = [r["sample_id"] for r in rows if r["sample_id"] not in done or done[r["sample_id"]].get("error")]
    for row in rows:
        item = done.get(row["sample_id"], {})
        row["llm_sentiment"] = "" if item.get("error") else item.get("llm_sentiment", "")
        row["llm_issues_reference"] = ",".join(item.get("llm_issues", []) or [])
        row["llm_returned_model"] = item.get("returned_model", "")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields + ["sample_id", "llm_sentiment", "llm_issues_reference", "llm_returned_model"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    # Token counts are stored per batch on every row of that batch; count each batch once.
    batch_usage = {}
    for item in done.values():
        if not item.get("error"):
            batch_usage[item.get("request_id")] = (item.get("input_tokens", 0), item.get("output_tokens", 0))
    input_tokens = sum(i for i, _ in batch_usage.values())
    output_tokens = sum(o for _, o in batch_usage.values())
    summary = {
        "input": str(args.input_path),
        "output": str(args.out),
        "requested_model": args.model,
        "returned_models": dict(Counter(r["llm_returned_model"] for r in rows if r["llm_returned_model"])),
        "posts": len(rows),
        "labelled": len(rows) - len(failed),
        "failed_sample_ids": failed,
        "elapsed_seconds_this_run": round(elapsed, 1),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost_summary(input_tokens, output_tokens, args.input_cost_per_million, args.output_cost_per_million),
        "sentiment_counts": dict(Counter(r["llm_sentiment"] for r in rows if r["llm_sentiment"])),
    }
    args.summary_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Labelled {summary['labelled']:,}/{len(rows):,} posts; failed {len(failed)}")
    print(f"Tokens {input_tokens:,} in / {output_tokens:,} out; cost ${summary['cost']['estimated_total_cost']:.4f}")
    print(f"Wrote {args.out}")
    if failed:
        print("Some batches failed. Rerun the same command to retry only those posts.")


if __name__ == "__main__":
    main()
