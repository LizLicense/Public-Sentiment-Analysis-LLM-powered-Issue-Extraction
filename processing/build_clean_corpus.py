#!/usr/bin/env python3
"""
Build the clean analysis corpus from the hybrid issue file.

Three steps, each reported in the summary JSON:
1. Deduplicate: keep one row per (thread_title, post_text). The scraper collected
   many posts several times across keyword rounds.
2. Drop off-topic threads: keep a thread only if at least --min-telco-share of its
   unique posts name a telco, or its title is about a telco.
3. Weight by thread: report shares three ways (per post, each thread weighted
   equally, at most --cap posts per thread) so one big outage thread cannot
   drive a finding on its own.

Usage (from project root):
  python processing/build_clean_corpus.py
"""

import argparse
import html
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from processing.telco_labeler import detect_telcos

DEFAULT_INPUT = Path("data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv")
DEFAULT_OUTPUT = Path("data/processed/clean_posts_2026-08-21_203752.csv")
DEFAULT_SUMMARY = Path("data/processed/clean_corpus_summary.json")

# Telco words that make a thread title on-topic even when detect_telcos finds no
# brand (e.g. "GOMO user", "CirclesLife charging $70"). Bare "eight" is left to
# detect_telcos, which rejects "eight taxi drivers".
TITLE_TELCO_PATTERN = re.compile(
    r"\b(telcos?|mvnos?|sim[- ]?only|e-?sim|broadband|isps?|roaming|5g|4g|"
    r"mobile (?:plan|data|line)|data plan|fib(?:re|er)|home internet|port(?:ing)? out|"
    r"gomo|circles(?:life|ai)?|myrepublic|vivifi|tpg|maxx|zero1|povo)\b",
    re.IGNORECASE,
)


def text_key(text) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip().lower()


def has_telco(value) -> bool:
    return bool(str(value or "").strip()) and str(value).strip().lower() != "nan"


def title_is_telco(title: str) -> bool:
    return bool(TITLE_TELCO_PATTERN.search(title or "")) or bool(detect_telcos(title or ""))


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["thread_key"] = df["thread_title"].map(text_key)
    df["_text_key"] = df["post_text"].map(text_key)
    df = df[df["_text_key"] != ""]
    copies = df.groupby(["thread_key", "_text_key"])["_text_key"].transform("size")
    df["n_copies"] = copies
    df = df.drop_duplicates(subset=["thread_key", "_text_key"], keep="first")
    return df.drop(columns=["_text_key"]).reset_index(drop=True)


def thread_table(df: pd.DataFrame, min_share: float) -> pd.DataFrame:
    rows = []
    for (source, key), group in df.groupby(["source", "thread_key"]):
        n = len(group)
        named = int(group["telco_label"].map(has_telco).sum())
        title = str(group["thread_title"].iloc[0])
        by_title = title_is_telco(title)
        rows.append({
            "source": source,
            "thread_key": key,
            "thread_title": title,
            "posts": n,
            "posts_naming_telco": named,
            "telco_share": named / n,
            "title_is_telco": by_title,
            "keep": by_title or named / n >= min_share,
        })
    return pd.DataFrame(rows)


def shares(labels: List[str], weights: List[float]) -> Dict[str, float]:
    totals: Dict[str, float] = defaultdict(float)
    for label, weight in zip(labels, weights):
        totals[label] += weight
    total = sum(totals.values()) or 1.0
    return {k: round(100 * v / total, 1) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])}


def cap_per_thread(df: pd.DataFrame, cap: int, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    keep = []
    for _, group in df.groupby("thread_key", sort=True):
        idx = list(group.index)
        keep.extend(idx if len(idx) <= cap else rng.sample(idx, cap))
    return df.loc[sorted(keep)]


def weighted_views(df: pd.DataFrame, cap: int, seed: int) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Issue, sentiment and brand shares under three weightings."""
    capped = cap_per_thread(df, cap, seed)
    thread_size = df.groupby("thread_key")["thread_key"].transform("size")
    views = {
        "per_post": (df, [1.0] * len(df)),
        "thread_equal": (df, list(1.0 / thread_size)),
        f"cap_{cap}_per_thread": (capped, [1.0] * len(capped)),
    }
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for name, (frame, weights) in views.items():
        brand_labels, brand_weights = [], []
        for label, weight in zip(frame["telco_label"], weights):
            parts = [p.strip() for p in str(label or "").split(",") if has_telco(p)]
            for part in parts:
                brand_labels.append(part)
                brand_weights.append(weight / len(parts))
        out[name] = {
            "posts": len(frame),
            "issue_primary": shares(list(frame["issue_primary"].fillna("general_discussion")), weights),
            "sentiment_vader": shares(list(frame["sentiment_label"].fillna("unknown")), weights),
            "brand_share_of_mentions": shares(brand_labels, brand_weights),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate, drop off-topic threads, report thread-weighted shares")
    parser.add_argument("--in", dest="input_path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-out", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--min-telco-share", type=float, default=0.2,
                        help="Keep a thread if at least this share of its unique posts names a telco.")
    parser.add_argument("--cap", type=int, default=5, help="Posts per thread in the capped view.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    raw = pd.read_csv(args.input_path, encoding="utf-8-sig", low_memory=False)
    unique = deduplicate(raw)
    threads = thread_table(unique, args.min_telco_share)
    kept_keys = set(threads.loc[threads["keep"], "thread_key"])
    clean = unique[unique["thread_key"].isin(kept_keys)].copy()
    clean["thread_posts"] = clean.groupby("thread_key")["thread_key"].transform("size")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.out, index=False, encoding="utf-8-sig")

    dropped = threads[~threads["keep"]].sort_values("posts", ascending=False)
    largest = threads[threads["keep"]].sort_values("posts", ascending=False).head(5)
    summary = {
        "input": str(args.input_path),
        "output": str(args.out),
        "min_telco_share": args.min_telco_share,
        "steps": {
            "raw_rows": len(raw),
            "unique_posts": len(unique),
            "threads": len(threads),
            "threads_kept": int(threads["keep"].sum()),
            "threads_dropped_off_topic": int((~threads["keep"]).sum()),
            "posts_in_dropped_threads": int(dropped["posts"].sum()),
            "clean_posts": len(clean),
            "clean_posts_naming_telco": int(clean["telco_label"].map(has_telco).sum()),
        },
        "clean_by_source": {k: int(v) for k, v in clean["source"].value_counts().items()},
        "largest_kept_threads": [
            {"title": r.thread_title, "posts": int(r.posts), "share_of_clean_pct": round(100 * r.posts / len(clean), 1)}
            for r in largest.itertuples()
        ],
        "largest_dropped_threads": [
            {"title": r.thread_title, "posts": int(r.posts), "telco_share": round(r.telco_share, 2)}
            for r in dropped.head(10).itertuples()
        ],
        "raw_rows_view": {
            "issue_primary": shares(list(raw["issue_primary"].fillna("general_discussion")), [1.0] * len(raw)),
            "sentiment_vader": shares(list(raw["sentiment_label"].fillna("unknown")), [1.0] * len(raw)),
        },
        "clean_views": weighted_views(clean, args.cap, args.seed),
    }
    args.summary_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    s = summary["steps"]
    print(f"Raw rows {s['raw_rows']:,} -> unique posts {s['unique_posts']:,} -> clean posts {s['clean_posts']:,}")
    print(f"Threads kept {s['threads_kept']} of {s['threads']} ({s['posts_in_dropped_threads']:,} posts in dropped threads)")
    print(f"Wrote {args.out}")
    print(f"Wrote {args.summary_out}")


if __name__ == "__main__":
    main()
