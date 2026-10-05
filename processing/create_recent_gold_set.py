#!/usr/bin/env python3
"""Blind gold sample of wave-2 posts, to check model accuracy on data the original gold set
never covered (posts after 2026-04-09: newest HWZ thread pages, Reddit via Arctic Shift).

Same rules as processing/create_evaluation_set.py: only posts that name a telco, one copy of
each text, at most --max-per-thread posts per thread, sources in proportion to the eligible
pool, and no model labels, scores, usernames or URLs in the sheet.

Usage (from project root):
  python processing/create_wave2_gold_set.py
Then fill the *_manual columns (see data/evaluation/ANNOTATION_GUIDE.md) and score with:
  python models/llm_evaluation.py --in data/evaluation/wave2_annotator_a.csv \\
      --out-dir data/evaluation/llm_comparison_wave2 --model gpt-4o-mini \\
      --input-cost-per-million 0.15 --output-cost-per-million 0.60
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path

DEFAULT_INPUT = Path("data/processed/clean_posts_v2_mini_sentiment.csv")
DEFAULT_OUTPUT = Path("data/evaluation/wave2_annotator_a.csv")
DEFAULT_METADATA = Path("data/evaluation/wave2_sampling_metadata.json")
FIELDS = [
    "sample_id", "evaluation_set", "source", "thread_title", "post_text",
    "telco_relevance_manual", "telco_targets_manual", "sentiment_manual",
    "issues_manual", "confidence_manual", "notes_manual",
]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser(description="Blind wave-2 gold sample")
    ap.add_argument("--in", dest="input_path", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--metadata-out", type=Path, default=DEFAULT_METADATA)
    ap.add_argument("--size", type=int, default=100)
    ap.add_argument("--max-per-thread", type=int, default=5)
    ap.add_argument("--min-chars", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260926)
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"Refusing to overwrite {args.out}: it may already hold your labels.")

    csv.field_size_limit(10**9)
    with args.input_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if str(r.get("wave", "")).split(".")[0] == "2"]

    seen, eligible = set(), []
    for r in rows:
        text = norm(r.get("post_text", ""))
        if not (r.get("telco_label") or "").strip() or len(text) < args.min_chars or text in seen:
            continue
        seen.add(text)
        eligible.append(r)

    rng = random.Random(args.seed)
    by_source = defaultdict(lambda: defaultdict(list))
    for r in eligible:
        by_source[r["source"]][r["thread_key"]].append(r)
    capped = {}
    for src, threads in by_source.items():
        pool = []
        for posts in threads.values():
            pool.extend(posts if len(posts) <= args.max_per_thread else rng.sample(posts, args.max_per_thread))
        capped[src] = pool
    # Allocate by eligible posts per source (as create_evaluation_set.py does), not by the capped
    # pool: the per-thread cap would otherwise shrink HWZ, whose posts sit in a few long threads.
    eligible_n = {s: sum(len(p) for p in t.values()) for s, t in by_source.items()}
    total = sum(eligible_n.values())
    allocation = {s: round(args.size * n / total) for s, n in eligible_n.items()}
    allocation[max(allocation, key=allocation.get)] += args.size - sum(allocation.values())

    sample = []
    for src in sorted(capped):
        if allocation[src] > len(capped[src]):
            raise SystemExit(f"{src}: need {allocation[src]} posts but only {len(capped[src])} after the thread cap.")
        sample.extend(rng.sample(capped[src], allocation[src]))
    rng.shuffle(sample)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for i, r in enumerate(sample, start=1):
            writer.writerow({
                "sample_id": f"W2-{i:04d}", "evaluation_set": "wave2", "source": r["source"],
                "thread_title": r.get("thread_title", ""), "post_text": r.get("post_text", ""),
                **{f: "" for f in FIELDS[5:]},
            })
    metadata = {
        "input_path": str(args.input_path), "seed": args.seed, "wave2_rows": len(rows),
        "eligible_rows": len(eligible),
        "eligible_by_source": {s: sum(len(p) for p in t.values()) for s, t in by_source.items()},
        "eligible_threads": sum(len(t) for t in by_source.values()),
        "max_rows_per_thread": args.max_per_thread, "size": len(sample), "by_source": allocation,
        "threads_in_sample": len({r["thread_key"] for r in sample}),
        "excluded": "no detected telco, duplicate text, or shorter than --min-chars",
    }
    args.metadata_out.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote {args.out} ({len(sample)} posts: {allocation}, {metadata['threads_in_sample']} threads)")
    print(f"Wrote {args.metadata_out}")


if __name__ == "__main__":
    main()
