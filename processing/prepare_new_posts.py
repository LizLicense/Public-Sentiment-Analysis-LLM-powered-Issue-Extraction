#!/usr/bin/env python3
"""
Run the posts collected 10 Apr-26 Sep 2026 (data/raw/apr_sep_2026/) through the same pipeline as
the earlier posts, writing only to data/processed/apr_sep_2026/. Internally these rows carry wave=2. No API calls; existing processed files are untouched.

Steps (all local):
  1. combine   data/raw/apr_sep_2026/*.csv (pilot files excluded) -> raw_combined_wave2.csv
  2. clean     processing/preprocess.py                    -> cleaned_posts_wave2.csv
  3. label     processing/telco_labeler.py (brand + VADER) -> posts_labeled_wave2.csv
  4. issues    processing/issue_extraction.py (rules only) -> issues_posts_labeled_wave2.csv

Then, with OPENAI_API_KEY set (you run this; GPT-4o costs ~$0.0004 per unresolved row):
  python processing/issue_extraction.py \\
    --in data/processed/apr_sep_2026/posts_labeled_wave2.csv \\
    --out data/processed/apr_sep_2026/issues_posts_labeled_wave2_gpt4o_hybrid.csv \\
    --summary-out data/processed/apr_sep_2026/issues_summary_wave2_gpt4o_hybrid.json \\
    --checkpoint data/processed/apr_sep_2026/llm_unresolved_gpt4o_checkpoint_wave2.jsonl \\
    --use-llm --llm-unresolved-only --llm-model gpt-4o --resume \\
    --input-cost-per-million 2.50 --output-cost-per-million 10.00

Finally `python processing/prepare_new_posts.py --merge` builds the full clean corpus
(data/processed/corpus_posts.csv).

Usage (from project root):
  python processing/prepare_new_posts.py            # steps 1-4
  python processing/prepare_new_posts.py --merge    # after the GPT-4o hybrid pass
"""

import argparse
import glob
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/apr_sep_2026"
OUT = ROOT / "data/processed/apr_sep_2026"
V1_HYBRID = ROOT / "data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv"
WAVE2_HYBRID = OUT / "issues_posts_labeled_wave2_gpt4o_hybrid.csv"
V2_RAW = OUT / "issues_posts_labeled_v1_plus_wave2_hybrid.csv"
V2_CLEAN = ROOT / "data/processed/corpus_posts.csv"
V2_SUMMARY = ROOT / "data/processed/corpus_summary.json"


def run(cmd):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([sys.executable, *map(str, cmd)], check=True, cwd=ROOT)


def combine() -> Path:
    files = sorted(f for f in glob.glob(str(RAW / "*.csv")) if "pilot" not in Path(f).name)
    if not files:
        raise SystemExit(f"No wave-2 CSVs in {RAW}")
    frames = []
    for f in files:
        df = pd.read_csv(f, low_memory=False)
        if "source" not in df.columns:
            df["source"] = "hwz" if "hwz" in Path(f).name else "reddit"
        # Reddit files name the thread "title"; HWZ files use "thread_title". Fill it here,
        # because preprocess only maps title -> thread_title when the column is absent.
        if "title" in df.columns:
            if "thread_title" not in df.columns:
                df["thread_title"] = df["title"]
            else:
                df["thread_title"] = df["thread_title"].fillna(df["title"])
        df["wave"] = 2
        df["raw_file"] = Path(f).name
        frames.append(df)
        print(f"  + {Path(f).name}: {len(df)} rows")
    combined = pd.concat(frames, ignore_index=True)
    missing = combined["thread_title"].isna() | (combined["thread_title"].astype(str).str.strip() == "")
    if missing.any():
        raise SystemExit(f"{int(missing.sum())} wave-2 rows have no thread title; fix the raw files first.")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "raw_combined_wave2.csv"
    combined.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Combined {len(combined)} rows -> {path.relative_to(ROOT)}")
    return path


def prepare() -> None:
    raw = combine()
    cleaned, labeled = OUT / "cleaned_posts_wave2.csv", OUT / "posts_labeled_wave2.csv"
    run(["processing/preprocess.py", "--in", raw, "--out", cleaned])
    run(["processing/telco_labeler.py", "--in", cleaned, "--out", labeled,
         "--summary-out", OUT / "summary_wave2.json"])
    run(["processing/issue_extraction.py", "--in", labeled,
         "--out", OUT / "issues_posts_labeled_wave2.csv",
         "--summary-out", OUT / "issues_summary_wave2.json"])
    print("\nNext: run the GPT-4o hybrid pass shown in this script's docstring, then --merge.")


def merge() -> None:
    if not WAVE2_HYBRID.exists():
        raise SystemExit(f"Missing {WAVE2_HYBRID.relative_to(ROOT)}: run the GPT-4o hybrid pass first.")
    v1 = pd.read_csv(V1_HYBRID, low_memory=False, encoding="utf-8-sig")
    v1["wave"] = 1
    w2 = pd.read_csv(WAVE2_HYBRID, low_memory=False, encoding="utf-8-sig")
    both = pd.concat([v1, w2], ignore_index=True)
    both.to_csv(V2_RAW, index=False, encoding="utf-8-sig")
    print(f"v1 {len(v1)} + wave2 {len(w2)} rows -> {V2_RAW.relative_to(ROOT)}")
    run(["processing/build_clean_corpus.py", "--in", V2_RAW, "--out", V2_CLEAN, "--summary-out", V2_SUMMARY])
    print("\nNext (API, ~$0.00003 per new post): python models/corpus_llm_sentiment.py "
          f"--in {V2_CLEAN.relative_to(ROOT)} "
          "--out data/processed/corpus_posts_mini_sentiment.csv "
          "--summary-out data/processed/corpus_posts_mini_sentiment_summary.json")
    print("It reuses the existing checkpoint, so only new posts are sent to the API.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Process the Apr-Sep 2026 raw data into data/processed/apr_sep_2026/")
    ap.add_argument("--merge", action="store_true", help="Merge with the earlier posts into data/processed/corpus_posts.csv.")
    args = ap.parse_args()
    merge() if args.merge else prepare()


if __name__ == "__main__":
    main()
