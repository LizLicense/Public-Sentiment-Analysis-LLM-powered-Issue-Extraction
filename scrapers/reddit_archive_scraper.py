#!/usr/bin/env python3
"""
Reddit posts and comments from the Arctic Shift research archive (no Reddit API key).

Reddit blocks unauthenticated API access from many networks and now gates new API apps.
Arctic Shift (https://arctic-shift.photon-reddit.com) archives public Reddit data for
research. This script lists every post in each subreddit for a date range, keeps telco
posts with the same strict brand filter as scrapers/reddit_scraper.py, then fetches all
of their comments, including replies.

Output uses the same columns as reddit_scraper.py, so preprocess.py and the rest of the
pipeline work unchanged. Cite Arctic Shift as the source; the archive can miss content
that was deleted before it was captured.

Usage (from project root):
  python scrapers/reddit_archive_scraper.py --subreddits singapore,askSingapore \\
      --since 2026-04-10 --out data/raw/apr_sep_2026/reddit_archive

Progress is checkpointed next to --out, so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reddit_scraper import (  # noqa: E402  same filters and formatting as the live scraper
    DEFAULT_KEYWORDS,
    clean_text,
    strict_telco_match,
    telcos_mentioned,
    utc_to_comment_time,
)

API = "https://arctic-shift.photon-reddit.com/api"
USER_AGENT = "sg-telco-capstone research scraper (github.com/LizLicense)"
MIN_BODY = 5
DROPPED_BODIES = {"[deleted]", "[removed]"}


def polite_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def get_json(session: requests.Session, path: str, params: Dict, sleep: tuple, retries: int = 6) -> List[Dict]:
    """GET an Arctic Shift endpoint; back off on rate limits and server timeouts."""
    wait = 10.0
    for attempt in range(1, retries + 1):
        try:
            r = session.get(f"{API}{path}", params=params, timeout=90)
            body = r.json() if r.content else {}
            if r.status_code == 200 and body.get("error") is None:
                polite_sleep(*sleep)
                return body.get("data") or []
            reason = body.get("error") or f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
        print(f"    retry {attempt}/{retries} in {wait:.0f}s ({reason})", flush=True)
        time.sleep(wait)
        wait = min(wait * 2, 300)
    raise RuntimeError(f"Arctic Shift {path} failed after {retries} attempts: {reason}")


def iter_posts(session, subreddit: str, after: int, before: int, sleep) -> Iterator[Dict]:
    """All posts in a subreddit between two epoch seconds, oldest first."""
    seen: set = set()
    cursor = after
    while True:
        batch = get_json(session, "/posts/search",
                         {"subreddit": subreddit, "after": cursor, "before": before, "limit": 100, "sort": "asc"},
                         sleep)
        fresh = [p for p in batch if p["id"] not in seen]
        for p in fresh:
            seen.add(p["id"])
            yield p
        if len(batch) < 100 or not fresh:
            return
        cursor = int(batch[-1]["created_utc"])


def fetch_comments(session, post_id: str, sleep) -> List[Dict]:
    """All archived comments on one post, including replies."""
    out: Dict[str, Dict] = {}
    cursor = 0
    while True:
        params = {"link_id": post_id, "limit": 100, "sort": "asc"}
        if cursor:
            params["after"] = cursor
        batch = get_json(session, "/comments/search", params, sleep)
        fresh = [c for c in batch if c["id"] not in out]
        for c in fresh:
            out[c["id"]] = c
        if len(batch) < 100 or not fresh:
            return list(out.values())
        cursor = int(batch[-1]["created_utc"])


def post_row(p: Dict, telco_keywords: List[str], scraped_at: str) -> Dict:
    text = clean_text(p.get("selftext") or "")
    return {
        "source": "reddit",
        "subreddit": p.get("subreddit"),
        "post_id": p["id"],
        "title": p.get("title"),
        "url": p.get("url"),
        "permalink": "https://www.reddit.com" + (p.get("permalink") or ""),
        "author": str(p.get("author") or "[deleted]"),
        "created_utc": float(p.get("created_utc") or 0),
        "comment_time": utc_to_comment_time(p.get("created_utc")),
        "telco_mentioned": telcos_mentioned(f"{p.get('title') or ''} {text}", telco_keywords),
        "score": p.get("score"),
        "num_comments": p.get("num_comments"),
        "post_text": text,
        "scraped_at_utc": scraped_at,
        "archive_source": "arctic-shift",
    }


def comment_row(p: Dict, c: Dict, telco_keywords: List[str], scraped_at: str) -> Optional[Dict]:
    body = clean_text(c.get("body") or "")
    if len(body) < MIN_BODY or body in DROPPED_BODIES:
        return None
    return {
        **post_row(p, telco_keywords, scraped_at),
        "author": str(c.get("author") or "[deleted]"),
        "created_utc": float(c.get("created_utc") or 0),
        "comment_time": utc_to_comment_time(c.get("created_utc")),
        "telco_mentioned": telcos_mentioned(f"{p.get('title') or ''} {body}", telco_keywords),
        "score": c.get("score"),
        "num_comments": None,
        "post_text": body,
        "comment_id": c["id"],
        "parent_id": c.get("parent_id"),
    }


def to_epoch(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def main() -> None:
    ap = argparse.ArgumentParser(description="Reddit telco posts + comments from the Arctic Shift archive")
    ap.add_argument("--subreddits", default="singapore,askSingapore")
    ap.add_argument("--since", required=True, help="First day to include, YYYY-MM-DD (UTC).")
    ap.add_argument("--until", default="", help="Last day to include, YYYY-MM-DD (UTC). Default: now.")
    ap.add_argument("--max-comments-per-post", type=int, default=2000)
    ap.add_argument("--max-posts", type=int, default=0, help="Stop after this many telco posts (pilot).")
    ap.add_argument("--sleep-min", type=float, default=1.5)
    ap.add_argument("--sleep-max", type=float, default=3.0)
    ap.add_argument("--out", required=True, help="Output prefix; a timestamp is appended.")
    args = ap.parse_args()

    subreddits = [s.strip() for s in args.subreddits.split(",") if s.strip()]
    after = to_epoch(args.since)
    before = to_epoch(args.until) + 86400 if args.until else int(time.time())
    sleep = (args.sleep_min, args.sleep_max)
    telco_keywords = list(DEFAULT_KEYWORDS)

    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.out).name
    checkpoint = out_dir / f"_{stem}_{args.since}_checkpoint.jsonl"
    done: Dict[str, List[Dict]] = {}
    if checkpoint.exists():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[item["post"]["id"]] = item
        print(f"Resuming: {len(done)} telco posts already in {checkpoint.name}")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    scraped_at = datetime.now(timezone.utc).isoformat()
    kept = len(done)

    for sub in subreddits:
        scanned = matched = 0
        print(f"r/{sub}: listing posts {args.since} → {datetime.fromtimestamp(before, timezone.utc).date()}", flush=True)
        for p in iter_posts(session, sub, after, before, sleep):
            scanned += 1
            if scanned % 500 == 0:
                print(f"  scanned {scanned}, telco {matched}, up to {datetime.fromtimestamp(p['created_utc'], timezone.utc).date()}", flush=True)
            if not strict_telco_match(f"{p.get('title') or ''} {p.get('selftext') or ''}"):
                continue
            matched += 1
            if p["id"] in done:
                continue
            comments = fetch_comments(session, p["id"], sleep) if p.get("num_comments") else []
            item = {"post": p, "comments": comments[: args.max_comments_per_post]}
            with checkpoint.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            done[p["id"]] = item
            kept += 1
            if args.max_posts and kept >= args.max_posts:
                break
        print(f"r/{sub}: scanned {scanned} posts, {matched} telco posts", flush=True)
        if args.max_posts and kept >= args.max_posts:
            break

    rows: List[Dict] = []
    for item in done.values():
        rows.append(post_row(item["post"], telco_keywords, scraped_at))
        rows.extend(r for r in (comment_row(item["post"], c, telco_keywords, scraped_at) for c in item["comments"]) if r)

    prefix = f"{args.out}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    for path in (f"{prefix}.csv", f"{prefix}.jsonl"):
        if os.path.exists(path):
            raise SystemExit(f"Refusing to overwrite existing file: {path}")
    pd.DataFrame(rows).to_csv(f"{prefix}.csv", index=False, encoding="utf-8-sig")
    with open(f"{prefix}.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Saved: {prefix}.csv ({len(rows)} rows: {len(done)} posts + {len(rows) - len(done)} comments)")


if __name__ == "__main__":
    main()
