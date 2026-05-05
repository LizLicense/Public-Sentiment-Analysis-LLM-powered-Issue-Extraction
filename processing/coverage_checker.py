#!/usr/bin/env python3
"""
Auto-collect telco samples until each target telco reaches threshold.

Loop per batch:
1) Run enabled scrapers (reddit / hwz / twitter)
2) Rebuild cleaned + labeled datasets
3) Count samples per telco from latest labeled CSV
4) Stop when all requested telcos >= target
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_TELCOS = ["Singtel", "Starhub", "M1", "SIMBA", "Giga", "Eight", "Zym", "redONE"]
DEFAULT_KEYWORDS = "singtel,starhub,m1,giga,eight,simba,circles,zym,redone,mobile plan,sim only"


def run_cmd(args: List[str]) -> int:
    cmd_str = " ".join(args)
    print(f"\n$ {cmd_str}")
    proc = subprocess.run(args, cwd=str(PROJECT_ROOT))
    return proc.returncode


def latest_labeled_csv() -> Path | None:
    files = sorted(PROCESSED_DIR.glob("posts_labeled_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def telco_counts_from_labeled(path: Path) -> Dict[str, int]:
    df = pd.read_csv(path)
    if "telco_label" not in df.columns:
        return {}
    exploded = (
        df["telco_label"]
        .fillna("")
        .astype(str)
        .str.split(",")
        .explode()
        .str.strip()
    )
    exploded = exploded[(exploded != "") & (exploded != "Unknown")]
    vc = exploded.value_counts()
    return {k: int(v) for k, v in vc.items()}


def unmet_targets(counts: Dict[str, int], telcos: List[str], target: int) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in telcos:
        cur = counts.get(t, 0)
        if cur < target:
            out[t] = target - cur
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run scrapers in batches until each telco reaches target sample count."
    )
    ap.add_argument("--target", type=int, default=1000, help="Target samples per telco (default: 1000).")
    ap.add_argument("--telcos", type=str, default=",".join(DEFAULT_TELCOS), help="Comma-separated telcos to track.")
    ap.add_argument("--max-rounds", type=int, default=10, help="Maximum scrape rounds (default: 10).")
    ap.add_argument("--keywords", type=str, default=DEFAULT_KEYWORDS, help="Keywords for reddit/twitter/HWZ title filter.")

    ap.add_argument("--disable-reddit", action="store_true", help="Skip Reddit scraper.")
    ap.add_argument("--disable-hwz", action="store_true", help="Skip HWZ scraper.")
    ap.add_argument("--disable-twitter", action="store_true", help="Skip Twitter scraper.")

    ap.add_argument("--reddit-subreddits", type=str, default="singapore,asksingapore", help="Subreddits for reddit scraper.")
    ap.add_argument("--reddit-limit", type=int, default=1200, help="Max posts per subreddit per round.")
    ap.add_argument("--reddit-max-comments", type=int, default=800, help="Max comments per post per round.")

    ap.add_argument("--hwz-forum-pages", type=int, default=25, help="HWZ forum listing pages per round.")
    ap.add_argument("--hwz-max-threads", type=int, default=250, help="HWZ matched threads per round.")
    ap.add_argument("--hwz-max-thread-pages", type=int, default=12, help="HWZ pages per thread per round.")

    ap.add_argument("--twitter-max-tweets", type=int, default=1000, help="Max tweets per round.")
    ap.add_argument("--twitter-bearer-token", type=str, default="", help="Optional token override for twitter scraper.")

    ap.add_argument("--skip-preprocess", action="store_true", help="Skip preprocess; label latest raw file directly.")
    args = ap.parse_args()

    telcos = [t.strip() for t in args.telcos.split(",") if t.strip()]
    if not telcos:
        print("Error: --telcos cannot be empty.")
        sys.exit(1)
    if args.disable_reddit and args.disable_hwz and args.disable_twitter:
        print("Error: all sources disabled. Enable at least one scraper.")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    py = sys.executable

    print("=== Coverage Checker ===")
    print(f"Target per telco: {args.target}")
    print(f"Tracked telcos:   {telcos}")
    print(f"Max rounds:       {args.max_rounds}")

    for round_i in range(1, args.max_rounds + 1):
        print(f"\n========== Round {round_i}/{args.max_rounds} ==========")

        if not args.disable_reddit:
            rc = run_cmd(
                [
                    py,
                    "scrapers/reddit_scraper.py",
                    "--subreddits",
                    args.reddit_subreddits,
                    "--keywords",
                    args.keywords,
                    "--limit",
                    str(args.reddit_limit),
                    "--max-comments-per-post",
                    str(args.reddit_max_comments),
                    "--out",
                    f"data/raw/reddit_posts_round{round_i}",
                ]
            )
            if rc != 0:
                print("Warning: Reddit scraper failed this round.")

        if not args.disable_hwz:
            rc = run_cmd(
                [
                    py,
                    "scrapers/hwz_forum_scraper.py",
                    "--keywords",
                    args.keywords,
                    "--forum-pages",
                    str(args.hwz_forum_pages),
                    "--max-threads",
                    str(args.hwz_max_threads),
                    "--max-thread-pages",
                    str(args.hwz_max_thread_pages),
                    "--out",
                    f"data/raw/hwz_posts_round{round_i}",
                ]
            )
            if rc != 0:
                print("Warning: HWZ scraper failed this round.")

        if not args.disable_twitter:
            cmd = [
                py,
                "scrapers/twitter_scraper.py",
                "--keywords",
                args.keywords,
                "--max-tweets",
                str(args.twitter_max_tweets),
                "--out",
                f"data/raw/twitter_posts_round{round_i}",
            ]
            if args.twitter_bearer_token.strip():
                cmd.extend(["--bearer-token", args.twitter_bearer_token.strip()])
            rc = run_cmd(cmd)
            if rc != 0:
                print("Warning: Twitter scraper failed this round.")

        if args.skip_preprocess:
            rc = run_cmd([py, "processing/telco_labeler.py"])
        else:
            rc = run_cmd([py, "processing/preprocess.py", "--out", "data/processed/cleaned_posts.csv"])
            if rc == 0:
                rc = run_cmd([py, "processing/telco_labeler.py", "--in", "data/processed/cleaned_posts.csv"])
        if rc != 0:
            print("Error: labeling step failed; stopping.")
            sys.exit(2)

        labeled = latest_labeled_csv()
        if not labeled:
            print("Error: no posts_labeled_*.csv found after labeling; stopping.")
            sys.exit(2)

        counts = telco_counts_from_labeled(labeled)
        gaps = unmet_targets(counts, telcos, args.target)
        print(f"\nLatest labeled file: {labeled.name}")
        print("Current counts:")
        for t in telcos:
            print(f"  {t}: {counts.get(t, 0)}")

        if not gaps:
            print("\nSUCCESS: all tracked telcos reached target.")
            return

        print("\nStill below target:")
        for t, miss in gaps.items():
            print(f"  {t}: need {miss} more")

    print("\nStopped: reached max rounds before all telcos met target.")
    sys.exit(3)


if __name__ == "__main__":
    main()
