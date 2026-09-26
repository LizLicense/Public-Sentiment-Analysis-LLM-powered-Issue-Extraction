#!/usr/bin/env python3
"""
Preprocessing script: raw scraped data → one cleaned dataset for modeling and dashboard.

- Normalizes column names (post_text, thread_title/title) across HWZ and Reddit.
- Drops noise: too-short text, placeholder messages (e.g. "Please log in to view").
- Optional: filter to English-only (requires langdetect).
- Writes a single CSV to data/processed/ for use by the labeler, models, and dashboard.
"""

import argparse
import re
from pathlib import Path

import pandas as pd

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")

# Placeholder / noise patterns: drop rows where post_text is only this
NOISE_PATTERNS = [
    r"please\s+log\s+in",
    r"verify\s+your\s+age\s+to\s+view",
    r"login\s+and\s+verify",
    r"\[deleted\]",
    r"\[removed\]",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE) if NOISE_PATTERNS else None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure post_text and thread_title exist (for Reddit: selftext → post_text, title → thread_title)."""
    if "post_text" not in df.columns and "selftext" in df.columns:
        df = df.copy()
        df["post_text"] = df["selftext"]
    if "thread_title" not in df.columns and "title" in df.columns:
        df = df.copy()
        df["thread_title"] = df["title"]
    if "source" not in df.columns:
        df = df.copy()
        # Infer source for HWZ-like rows (thread_url exists) else unknown.
        if "thread_url" in df.columns:
            df["source"] = "hwz"
        else:
            df["source"] = "unknown"
    return df


def is_noise(text: str) -> bool:
    """True if text looks like a placeholder or non-content."""
    if not text or not isinstance(text, str):
        return True
    t = text.strip()
    if len(t) < 10:
        return True
    if NOISE_RE and NOISE_RE.search(t) and len(t) < 200:
        return True
    return False


def clean_text_cell(s: str) -> str:
    """Normalize whitespace in a single cell."""
    if not isinstance(s, str):
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n\s+", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def filter_english(df: pd.DataFrame, text_col: str = "post_text") -> pd.DataFrame:
    """Keep only rows where text_col is detected as English. Requires langdetect."""
    try:
        import langdetect
    except ImportError:
        print("Warning: langdetect not installed. Skipping language filter. pip install langdetect")
        return df
    def is_en(t):
        try:
            return langdetect.detect(str(t)[:500]) == "en"
        except Exception:
            return False
    mask = df[text_col].fillna("").apply(is_en)
    return df.loc[mask].copy()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess raw scraped CSVs into one cleaned dataset."
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        type=str,
        default=None,
        help="Input CSV (default: combine all CSVs in data/raw/).",
    )
    parser.add_argument(
        "--combine-all",
        action="store_true",
        default=True,
        help="Combine all CSV files in data/raw/ when --in is not provided (default: True).",
    )
    parser.add_argument(
        "--no-combine-all",
        action="store_true",
        help="If set, use only the latest CSV in data/raw/ when --in is not provided.",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(PROCESSED_DIR / "cleaned_posts.csv"),
        help="Output cleaned CSV path.",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=20,
        help="Drop rows where post_text has fewer than this many characters (default: 20).",
    )
    parser.add_argument(
        "--require-english",
        action="store_true",
        help="Drop rows where post_text is not detected as English (requires langdetect).",
    )
    parser.add_argument(
        "--no-drop-noise",
        action="store_true",
        help="Do not drop placeholder/noise rows (e.g. 'Please log in').",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path) if args.input_path else None
    combine_all = args.combine_all and not args.no_combine_all
    if input_path is None or not input_path.exists():
        if not RAW_DIR.exists():
            print(f"Error: {RAW_DIR} not found. Run scrapers first.")
            return
        csvs = sorted(RAW_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        csvs = [c for c in csvs if "labeled" not in c.name.lower() and "summary" not in c.name.lower()]
        if not csvs:
            csvs = list(RAW_DIR.glob("*.csv"))
        if not csvs:
            print(f"Error: No CSV found in {RAW_DIR}. Run scrapers first.")
            return
        if combine_all:
            print(f"Combining {len(csvs)} raw CSV files from {RAW_DIR} ...")
            frames = []
            for p in csvs:
                try:
                    part = pd.read_csv(p)
                    part = normalize_columns(part)
                    # Infer source from filename when unknown
                    if "source" in part.columns:
                        if "reddit" in p.name.lower():
                            part.loc[part["source"].fillna("").astype(str).str.strip() == "", "source"] = "reddit"
                        elif "hwz" in p.name.lower():
                            part.loc[part["source"].fillna("").astype(str).str.strip() == "", "source"] = "hwz"
                    frames.append(part)
                    print(f"  + {p.name}: {len(part)} rows")
                except Exception as e:
                    print(f"  ! Skip {p.name}: {e}")
            if not frames:
                print("Error: no valid CSV could be loaded from data/raw.")
                return
            df = pd.concat(frames, ignore_index=True)
            print(f"Combined rows before cleaning: {len(df)}")
        else:
            input_path = csvs[0]
            print(f"Using latest raw CSV: {input_path}")
            df = pd.read_csv(input_path)
    else:
        df = pd.read_csv(input_path)

    if df.empty:
        print("Input CSV is empty.")
        return

    # Normalize columns
    df = normalize_columns(df)
    if "post_text" not in df.columns:
        print("Error: No post_text or selftext column found.")
        return

    # Clean text cells
    df["post_text"] = df["post_text"].fillna("").astype(str).apply(clean_text_cell)
    if "thread_title" in df.columns:
        df["thread_title"] = df["thread_title"].fillna("").astype(str).apply(clean_text_cell)

    # Drop too short
    before = len(df)
    df = df[df["post_text"].str.len() >= args.min_length].copy()
    dropped_short = before - len(df)

    # Drop noise (placeholders)
    if not args.no_drop_noise:
        mask = ~df["post_text"].apply(is_noise)
        dropped_noise = (~mask).sum()
        df = df.loc[mask].copy()
    else:
        dropped_noise = 0

    # Optional English-only
    if args.require_english:
        before_lang = len(df)
        df = filter_english(df, "post_text")
        dropped_lang = before_lang - len(df)
        print(f"Dropped {dropped_lang} non-English rows.")
    else:
        dropped_lang = 0

    # Write
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"Dropped {dropped_short} short rows, {dropped_noise} noise rows.")
    print(f"Remaining: {len(df)} rows.")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
