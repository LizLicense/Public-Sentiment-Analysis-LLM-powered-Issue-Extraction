#!/usr/bin/env python3
"""
Create a small labeled-sample template for manual annotation.

Samples N rows from a cleaned or labeled CSV, adds empty columns for manual labels,
and saves a template CSV. You then open it in Excel/Sheets, fill in
sentiment_label_manual and issue_manual, and save as e.g. labeled_sample.csv
for model evaluation.
"""

import argparse
import random
from pathlib import Path

import pandas as pd
import re

PROCESSED_DIR = Path("data/processed")
TEMPLATE_NAME = "labeled_sample_template.csv"
INSTRUCTIONS_NAME = "labeled_sample_INSTRUCTIONS.txt"


def _draft_sentiment_from_text(df: pd.DataFrame) -> pd.Series:
    """Fallback draft sentiment labels from post_text using VADER if available, else neutral."""
    if "post_text" not in df.columns and "selftext" in df.columns:
        df = df.copy()
        df["post_text"] = df["selftext"]
    text_series = df.get("post_text", pd.Series([""] * len(df), index=df.index)).fillna("").astype(str)
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
        labels = []
        for t in text_series:
            s = analyzer.polarity_scores(t)["compound"]
            if s >= 0.05:
                labels.append("happy")
            elif s <= -0.05:
                labels.append("not_happy")
            else:
                labels.append("neutral")
        return pd.Series(labels, index=df.index)
    except Exception:
        return pd.Series(["neutral"] * len(df), index=df.index)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sample rows and create a template CSV for manual sentiment + issue labeling."
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        type=str,
        default=None,
        help="Input CSV (default: data/processed/cleaned_posts.csv or latest in data/processed/).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(PROCESSED_DIR / TEMPLATE_NAME),
        help="Output template CSV path.",
    )
    parser.add_argument(
        "-n",
        "--num-samples",
        type=int,
        default=150,
        help="Number of rows to sample (default: 150).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling (default: 42).",
    )
    parser.add_argument(
        "--prefill-from-model",
        action="store_true",
        help="Prefill sentiment_label_manual from existing sentiment_label/llm_sentiment_label (recommended to speed up manual review).",
    )
    parser.add_argument(
        "--instructions",
        action="store_true",
        default=True,
        help="Write a short INSTRUCTIONS file next to the template (default: True).",
    )
    parser.add_argument(
        "--no-instructions",
        action="store_true",
        help="Do not write INSTRUCTIONS file.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path) if args.input_path else None
    if input_path is None or not input_path.exists():
        # Prefer latest labeled output, then cleaned_posts, then any recent CSV
        labeled = sorted(PROCESSED_DIR.glob("posts_labeled_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if labeled:
            input_path = labeled[0]
        else:
            cleaned = PROCESSED_DIR / "cleaned_posts.csv"
            if cleaned.exists():
                input_path = cleaned
            else:
                csvs = sorted(
                    PROCESSED_DIR.glob("*.csv"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                csvs = [c for c in csvs if "summary" not in c.name.lower()]
                if not csvs:
                    print(f"Error: No input CSV found. Run preprocess.py first (or pass --in path).")
                    return
                input_path = csvs[0]
        print(f"Using: {input_path}")

    df = pd.read_csv(input_path)
    if df.empty:
        print("Input CSV is empty.")
        return

    n = min(args.num_samples, len(df))
    if n < len(df):
        random.seed(args.seed)
        indices = random.sample(range(len(df)), n)
        df = df.iloc[indices].copy()
    else:
        print(f"Requested {args.num_samples}, only {len(df)} rows available; using all.")

    # Add manual label columns (optionally prefill from model outputs)
    if args.prefill_from_model:
        if "llm_sentiment_label" in df.columns:
            df["sentiment_label_manual"] = df["llm_sentiment_label"].fillna("").astype(str)
        elif "sentiment_label" in df.columns:
            df["sentiment_label_manual"] = df["sentiment_label"].fillna("").astype(str)
        else:
            df["sentiment_label_manual"] = ""
        # If still empty (e.g. source has NaN sentiment), draft from text
        empty_mask = df["sentiment_label_manual"].fillna("").astype(str).str.strip() == ""
        if empty_mask.any():
            fallback = _draft_sentiment_from_text(df)
            df.loc[empty_mask, "sentiment_label_manual"] = fallback.loc[empty_mask]
            print(f"Prefill fallback applied for {int(empty_mask.sum())} rows (VADER draft or neutral).")
    else:
        df["sentiment_label_manual"] = ""
    df["issue_manual"] = ""
    df["notes"] = ""

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Saved template with {len(df)} rows: {out_path}")

    write_instructions = args.instructions and not args.no_instructions
    if write_instructions:
        instr_path = out_path.parent / INSTRUCTIONS_NAME
        with open(instr_path, "w", encoding="utf-8") as f:
            f.write("Manual labeling instructions\n")
            f.write("=" * 40 + "\n\n")
            f.write("1. Open the CSV in Excel or Google Sheets.\n")
            f.write("2. For each row, fill in:\n")
            f.write("   - sentiment_label_manual: one of  happy | not_happy | neutral\n")
            f.write("   - issue_manual: e.g. pricing, network, customer_service, porting, roaming, other (or comma-separated)\n")
            f.write("   - notes: optional\n")
            f.write("3. Save as labeled_sample.csv (or another name) for use in evaluation.\n")
            f.write("Tip: run with --prefill-from-model to start from model labels and correct them manually.\n")
        print(f"Saved instructions: {instr_path}")


if __name__ == "__main__":
    main()
