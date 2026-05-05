#!/usr/bin/env python3
"""
Twitter / X scraper using the Twitter API v2 (recent search).
Fetches tweets matching keywords, normalizes to same schema as Reddit/HWZ for processing.
Requires a Bearer Token (Twitter Developer Portal). Free tier: last 7 days, limited requests.
"""

import argparse
import json
import os
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import requests
from tqdm import tqdm

DEFAULT_KEYWORDS = ["singtel", "starhub", "m1", "gomo", "eight", "simba", "circles", "mobile plan", "sim only"]

# WARNING: Hard-coding tokens is insecure. Do not commit real tokens to git.
# Get a token at https://developer.twitter.com/en/portal/dashboard
# Option A: set here (keep private)
TWITTER_BEARER_TOKEN_HARDCODED = "AAAAAAAAAAAAAAAAAAAAAM9h8AEAAAAAtiqKz6KDyIubxy3Yb8Q2acAPlZc%3DoTOZk78i1MClV7rymQwxChyNIuRnRR0WiXldgy6HnLdSIAcfWg"  # e.g. "AAAAAAAAAAAAAAAAAAAAA..."
# Option B: env var
TWITTER_BEARER_TOKEN = TWITTER_BEARER_TOKEN_HARDCODED or os.getenv("TWITTER_BEARER_TOKEN", "").strip()

BASE_URL = "https://api.twitter.com/2"


def clean_text(s: str) -> str:
    if not s or not isinstance(s, str):
        return ""
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n\s+", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _normalize_for_match(s: str) -> str:
    return (s or "").strip().lower()


def keyword_match(text: str, keywords: List[str]) -> bool:
    if not text or not keywords:
        return True
    t = _normalize_for_match(text)
    return any(_normalize_for_match(k) in t for k in keywords if k)


def polite_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def make_session(bearer_token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "User-Agent": "TwitterScraper/1.0 (Research)",
    })
    return s


def fetch_search_recent(
    session: requests.Session,
    query: str,
    max_results: int = 100,
    next_token: Optional[str] = None,
    timeout: int = 30,
) -> Dict:
    """Twitter API v2 GET tweets/search/recent. Returns JSON with data, includes, meta."""
    url = f"{BASE_URL}/tweets/search/recent"
    params = {
        "query": query,
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,public_metrics,author_id",
        "expansions": "author_id",
        "user.fields": "username",
    }
    if next_token:
        params["next_token"] = next_token

    r = session.get(url, params=params, timeout=timeout)
    if r.status_code == 429:
        raise RuntimeError("Rate limited (429). Wait and retry.")
    if r.status_code != 200:
        try:
            err = r.json()
            msg = err.get("detail") or err.get("title") or r.text or r.reason
        except Exception:
            msg = r.text or r.reason
        raise RuntimeError(f"Twitter API {r.status_code}: {msg}")
    return r.json()


def build_query(keywords: List[str], extra: str = "") -> str:
    """Build a search query: (kw1 OR kw2 OR ...) lang:en, optional extra."""
    if not keywords:
        return "lang:en" + (" " + extra if extra else "")
    quoted = [f'"{k}"' if " " in k else k for k in keywords[:20]]
    q = " OR ".join(quoted)
    out = f"({q}) lang:en"
    if extra:
        out += " " + extra
    return out


def scrape_twitter(
    bearer_token: str,
    keywords: List[str],
    max_tweets: int,
    sleep_min: float,
    sleep_max: float,
) -> List[Dict]:
    if not bearer_token:
        raise ValueError("TWITTER_BEARER_TOKEN (env or in script) is required.")

    session = make_session(bearer_token)
    query = build_query(keywords)
    scraped_at = datetime.utcnow().isoformat()
    rows: List[Dict] = []
    next_token: Optional[str] = None
    per_request = min(100, max_tweets)

    with tqdm(total=max_tweets, desc="Fetching tweets", unit="tweet") as pbar:
        while len(rows) < max_tweets:
            try:
                data = fetch_search_recent(
                    session,
                    query,
                    max_results=per_request,
                    next_token=next_token,
                )
            except RuntimeError as e:
                err_msg = str(e)
                if "429" in err_msg:
                    polite_sleep(60, 120)
                    continue
                print(f"Request error: {err_msg}")
                if "403" in err_msg:
                    print("403 Forbidden: Check that your Twitter app has 'Search Tweets' access at https://developer.twitter.com/en/portal/dashboard (Products). Free tier may not include search.")
                break
            except Exception as e:
                print(f"Request error: {e}")
                break

            tweets = data.get("data") or []
            users = {}
            for u in (data.get("includes") or {}).get("users") or []:
                users[u["id"]] = u.get("username") or u.get("id")

            for t in tweets:
                if len(rows) >= max_tweets:
                    break
                text = clean_text(t.get("text") or "")
                if keywords and not keyword_match(text, keywords):
                    continue
                author_id = t.get("author_id")
                username = users.get(author_id, author_id or "unknown")
                created = t.get("created_at") or ""
                tweet_id = t.get("id") or ""
                url = f"https://twitter.com/i/status/{tweet_id}" if tweet_id else ""
                metrics = t.get("public_metrics") or {}
                row = {
                    "source": "twitter",
                    "tweet_id": tweet_id,
                    "thread_title": "",  # tweets have no thread; labeler can use post_text only
                    "title": "",
                    "post_text": text,
                    "selftext": text,
                    "timestamp": created,
                    "created_utc": created,
                    "author": username,
                    "url": url,
                    "like_count": metrics.get("like_count"),
                    "retweet_count": metrics.get("retweet_count"),
                    "reply_count": metrics.get("reply_count"),
                    "scraped_at_utc": scraped_at,
                }
                rows.append(row)
                pbar.update(1)

            next_token = (data.get("meta") or {}).get("next_token")
            if not next_token or not tweets:
                break
            polite_sleep(sleep_min, sleep_max)

    return rows


def _sanitize_for_filename(s: str) -> str:
    return re.sub(r"[^\w\-]", "_", (s or "").strip())


def build_output_prefix(base: str, keywords: List[str]) -> str:
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
    parser = argparse.ArgumentParser(
        description="Twitter/X scraper (API v2 recent search). Requires TWITTER_BEARER_TOKEN."
    )
    parser.add_argument(
        "--keywords",
        type=str,
        default=",".join(DEFAULT_KEYWORDS),
        help="Comma-separated keywords; tweets matching any are kept. Empty = no filter.",
    )
    parser.add_argument(
        "--max-tweets",
        type=int,
        default=500,
        help="Max tweets to fetch (default: 500). API may cap per request.",
    )
    parser.add_argument("--sleep-min", type=float, default=1.0, help="Min seconds between requests.")
    parser.add_argument("--sleep-max", type=float, default=2.5, help="Max seconds between requests.")
    parser.add_argument(
        "--out",
        type=str,
        default="data/raw/twitter_posts",
        help="Output prefix (CSV + JSONL). Writes to data/raw/ by default.",
    )
    parser.add_argument(
        "--bearer-token",
        type=str,
        default=TWITTER_BEARER_TOKEN,
        help="Bearer token (default: TWITTER_BEARER_TOKEN env or script value).",
    )
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    token = (args.bearer_token or "").strip()

    if not token:
        print("Error: No Twitter Bearer Token.")
        print("Set TWITTER_BEARER_TOKEN in the environment or pass --bearer-token.")
        print("Get a token at: https://developer.twitter.com/en/portal/dashboard")
        return

    print(f"Keywords:   {keywords or '(none)'}")
    print(f"Max tweets: {args.max_tweets}")

    rows = scrape_twitter(
        bearer_token=token,
        keywords=keywords,
        max_tweets=args.max_tweets,
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
    )

    if not rows:
        print("No tweets collected.")
        return

    out_prefix = build_output_prefix(args.out, keywords)
    save_outputs(rows, out_prefix)


if __name__ == "__main__":
    main()
