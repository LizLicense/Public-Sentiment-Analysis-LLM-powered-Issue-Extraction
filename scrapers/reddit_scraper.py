#!/usr/bin/env python3
"""
Reddit scraper using the public JSON API (no API keys required).
Fetches posts from subreddits, optionally filtered by keywords, and saves to CSV + JSONL.
"""

import argparse
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from tqdm import tqdm

DEFAULT_KEYWORDS = ["singtel", "starhub", "m1", "gomo", "eight","simba","circles","mobile plan",  "sim only", "sim-only"]
# DEFAULT_KEYWORDS = ["starhub","5G"]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) RedditScraper/1.0 "
    "(Research; +https://github.com/example/reddit-scraper)"
)

BASE_URL = "https://api.reddit.com"


@dataclass(frozen=True)
class RedditPost:
    subreddit: str
    post_id: str
    title: str
    url: str
    author: str
    created_utc: float
    selftext: str
    score: int
    num_comments: int
    permalink: str


def clean_text(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n\s+", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _normalize_for_match(s: str) -> str:
    """Normalize string for case-insensitive matching (ignore case)."""
    return (s or "").strip().lower()


def keyword_match(text: str, keywords: List[str]) -> bool:
    """Return True if any keyword appears in text. Matching ignores case."""
    if not text or not keywords:
        return True
    t = _normalize_for_match(text)
    return any(_normalize_for_match(k) in t for k in keywords if k)


def telcos_mentioned(text: str, telcos: List[str]) -> str:
    """Return comma-separated telco names found in text. Matching ignores case."""
    if not text or not telcos:
        return ""
    t = _normalize_for_match(text)
    found = [name for name in telcos if name and _normalize_for_match(name) in t]
    return ",".join(found) if found else ""


def utc_to_comment_time(utc: Optional[float]) -> str:
    """Format Unix UTC timestamp as 'YYYY-MM-DD HH:MM:SS UTC'."""
    if utc is None or (isinstance(utc, (int, float)) and utc <= 0):
        return ""
    try:
        return datetime.utcfromtimestamp(float(utc)).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OSError, ValueError):
        return ""


def polite_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def fetch_json(
    session: requests.Session,
    url: str,
    params: Optional[Dict] = None,
    timeout: int = 30,
    retries: int = 3,
) -> Dict:
    last_err = None
    for _ in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            # 429 = rate limit; 403 = blocked User-Agent
            if r.status_code == 429:
                polite_sleep(60, 120)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            polite_sleep(2.0, 4.0)
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def subreddit_listing_url(subreddit: str, sort: str, limit: int, after: Optional[str]) -> str:
    sub = subreddit.strip().lstrip("/r/")
    path = f"/r/{sub}/{sort}.json"
    url = urljoin(BASE_URL, path)
    params = {"limit": min(limit, 100), "raw_json": 1}
    if after:
        params["after"] = after
    return url, params


def parse_listing(data: Dict, subreddit: str) -> List[RedditPost]:
    posts: List[RedditPost] = []
    children = (data.get("data") or {}).get("children") or []
    for c in children:
        d = c.get("data") or {}
        post_id = d.get("id") or ""
        if not post_id:
            continue
        title = clean_text(d.get("title") or "")
        selftext = clean_text(d.get("selftext") or "")
        author = str(d.get("author") or "[deleted]")
        created = float(d.get("created_utc") or 0)
        score = int(d.get("score") or 0)
        num_comments = int(d.get("num_comments") or 0)
        permalink = d.get("permalink") or ""
        full_url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        link_url = d.get("url") or full_url
        posts.append(
            RedditPost(
                subreddit=subreddit,
                post_id=post_id,
                title=title,
                url=link_url,
                author=author,
                created_utc=created,
                selftext=selftext,
                score=score,
                num_comments=num_comments,
                permalink=full_url,
            )
        )
    return posts


def get_after(data: Dict) -> Optional[str]:
    return (data.get("data") or {}).get("after")


def fetch_subreddit_posts(
    session: requests.Session,
    subreddit: str,
    sort: str,
    limit: int,
    keywords: List[str],
    sleep_min: float,
    sleep_max: float,
) -> List[RedditPost]:
    posts: List[RedditPost] = []
    after: Optional[str] = None
    per_request = min(300, limit)

    while len(posts) < limit:
        url, params = subreddit_listing_url(subreddit, sort, per_request, after)
        data = fetch_json(session, url, params=params)
        batch = parse_listing(data, subreddit)

        for p in batch:
            if len(posts) >= limit:
                break
            if keywords and not keyword_match(p.title + " " + p.selftext, keywords):
                continue
            posts.append(p)

        after = get_after(data)
        if not after or not batch:
            break
        polite_sleep(sleep_min, sleep_max)

    return posts


def fetch_comments(
    session: requests.Session,
    subreddit: str,
    post_id: str,
    permalink: str,
    max_comments: int,
    sleep_min: float,
    sleep_max: float,
) -> List[Dict]:
    """Fetch top-level comments for a post. Permalink like /r/sub/comments/id/title/."""
    path = permalink.rstrip("/") + ".json"
    if not path.startswith("http"):
        path = f"https://www.reddit.com{path}" if path.startswith("/") else f"https://www.reddit.com/{path}"
    try:
        data = fetch_json(session, path)
    except Exception:
        return []
    polite_sleep(sleep_min, sleep_max)

    comments: List[Dict] = []
    if not isinstance(data, list) or len(data) < 2:
        return comments
    comment_listing = data[1].get("data", {}).get("children", [])

    for c in comment_listing:
        if len(comments) >= max_comments:
            break
        d = c.get("data") or {}
        if d.get("kind") == "more":
            continue
        body = clean_text(d.get("body") or "")
        if len(body) < 5:
            continue
        comments.append({
            "comment_id": d.get("id"),
            "author": str(d.get("author") or "[deleted]"),
            "created_utc": float(d.get("created_utc") or 0),
            "body": body,
            "score": int(d.get("score") or 0),
        })
    return comments


def scrape_reddit(
    subreddits: List[str],
    keywords: List[str],
    telco_keywords: List[str],
    sort: str,
    limit_per_sub: int,
    include_comments: bool,
    max_comments_per_post: int,
    sleep_min: float,
    sleep_max: float,
    session: Optional[requests.Session] = None,
) -> List[Dict]:
    if session is None:
        session = make_session()

    all_posts: List[RedditPost] = []
    for sub in subreddits:
        batch = fetch_subreddit_posts(
            session, sub, sort, limit_per_sub, keywords, sleep_min, sleep_max
        )
        all_posts.extend(batch)
        polite_sleep(sleep_min, sleep_max)

    scraped_at = datetime.utcnow().isoformat()
    rows: List[Dict] = []

    for p in tqdm(all_posts, desc="Processing posts"):
        post_text_combined = (p.title or "") + " " + (p.selftext or "")
        telco = telcos_mentioned(post_text_combined, telco_keywords)
        comment_time = utc_to_comment_time(p.created_utc)

        row: Dict = {
            "source": "reddit",
            "subreddit": p.subreddit,
            "post_id": p.post_id,
            "title": p.title,
            "url": p.url,
            "permalink": p.permalink,
            "author": p.author,
            "created_utc": p.created_utc,
            "comment_time": comment_time,
            "telco_mentioned": telco,
            "score": p.score,
            "num_comments": p.num_comments,
            "post_text": p.selftext,
            "scraped_at_utc": scraped_at,
        }
        rows.append(row)

        if include_comments and max_comments_per_post > 0 and p.num_comments > 0:
            comments = fetch_comments(
                session,
                p.subreddit,
                p.post_id,
                p.permalink,
                max_comments_per_post,
                sleep_min,
                sleep_max,
            )
            for c in comments:
                comment_text_combined = (p.title or "") + " " + (c["body"] or "")
                ct = telcos_mentioned(comment_text_combined, telco_keywords)
                ct_time = utc_to_comment_time(c["created_utc"])
                rows.append({
                    "source": "reddit",
                    "subreddit": p.subreddit,
                    "post_id": p.post_id,
                    "title": p.title,
                    "url": p.url,
                    "permalink": p.permalink,
                    "author": c["author"],
                    "created_utc": c["created_utc"],
                    "comment_time": ct_time,
                    "telco_mentioned": ct,
                    "score": c["score"],
                    "num_comments": None,
                    "post_text": c["body"],
                    "scraped_at_utc": scraped_at,
                    "comment_id": c["comment_id"],
                })

    return rows


def _sanitize_for_filename(s: str) -> str:
    """Replace characters that are invalid in filenames."""
    return re.sub(r'[^\w\-]', '_', (s or "").strip())


def build_output_prefix(base: str, keywords: List[str]) -> str:
    """Build output prefix with base, keywords, and timestamp."""
    kw_part = "_".join(_sanitize_for_filename(k)[:20] for k in keywords[:8] if k) if keywords else "all"
    if len(kw_part) > 60:
        kw_part = kw_part[:60].rstrip("_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{kw_part}_{ts}"


def save_outputs(rows: List[Dict], out_prefix: str) -> None:
    df = pd.DataFrame(rows)
    csv_path = f"{out_prefix}.csv"
    jsonl_path = f"{out_prefix}.jsonl"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Saved: {csv_path}")
    print(f"Saved: {jsonl_path}")
    print(f"Rows:  {len(rows)}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reddit scraper (public JSON API). Fetches posts from subreddits."
    )
    ap.add_argument(
        "--subreddits",
        type=str,
        default="singapore",
        help="Comma-separated subreddit names (e.g. singapore,asksingapore).",
    )
    ap.add_argument(
        "--keywords",
        type=str,
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated keywords; only include posts matching any. Empty = no filter.",
    )
    ap.add_argument(
        "--telco-keywords",
        type=str,
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated telco names for 'telco_mentioned' column (default: same as --keywords).",
    )
    ap.add_argument(
        "--sort",
        type=str,
        choices=["new", "hot", "top", "rising"],
        default="new",
        help="Listing sort.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=300,
        help="Max posts per subreddit.",
    )
    ap.add_argument(
        "--no-comments",
        action="store_true",
        help="Don't fetch comments (default: fetch comments).",
    )
    ap.add_argument(
        "--max-comments-per-post",
        type=int,
        default=500,
        help="Max comments to fetch per post (default: 500).",
    )
    ap.add_argument("--sleep-min", type=float, default=2.0, help="Min seconds between requests.")
    ap.add_argument("--sleep-max", type=float, default=4.0, help="Max seconds between requests.")
    ap.add_argument("--out", type=str, default="data/raw/reddit_posts", help="Output prefix (CSV + JSONL). Writes to data/raw/ by default.")
    args = ap.parse_args()

    subreddits = [s.strip().lstrip("/r/") for s in args.subreddits.split(",") if s.strip()]
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    if not subreddits:
        print("Provide at least one subreddit via --subreddits.")
        return

    print(f"Subreddits: {subreddits}")
    print(f"Keywords:   {keywords or '(none)'}")
    print(f"Sort:       {args.sort}")
    print(f"Limit:      {args.limit} per subreddit")

    telco_keywords = [k.strip() for k in args.telco_keywords.split(",") if k.strip()] or list(DEFAULT_KEYWORDS)

    session = make_session()
    rows = scrape_reddit(
        subreddits=subreddits,
        keywords=keywords,
        telco_keywords=telco_keywords,
        sort=args.sort,
        limit_per_sub=args.limit,
        include_comments=not args.no_comments,
        max_comments_per_post=args.max_comments_per_post,
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
        session=session,
    )

    if not rows:
        print("No posts collected.")
        return

    out_prefix = build_output_prefix(args.out, keywords)
    save_outputs(rows, out_prefix)


if __name__ == "__main__":
    main()
