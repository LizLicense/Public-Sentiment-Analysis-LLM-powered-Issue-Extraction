#!/usr/bin/env python3
"""
Reddit scraper using the public JSON API (no API keys required).
Fetches posts from subreddits, optionally filtered by keywords, and saves to CSV + JSONL.

Two modes:
  listing  (default) reads /new, /hot, /top or /rising. Reddit caps a listing at ~1,000
           posts, so on a busy subreddit /new only reaches back a few days.
  search   runs one subreddit search per query (sorted by new, past year), which reaches
           months back. Combine with --since and --strict-match, e.g.

  python scrapers/reddit_scraper.py --mode search --subreddits singapore,askSingapore \
      --since 2026-04-10 --strict-match --out data/raw/reddit_wave2

Authentication: Reddit now blocks unauthenticated JSON requests from many networks
(HTTP 403 "Blocked"). Create a "script" app at https://www.reddit.com/prefs/apps and set
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
(e.g. "script:sg-telco-capstone:v1.0 (by /u/yourname)"). The scraper then uses
application-only OAuth against oauth.reddit.com (read-only, public data).
"""

import argparse
import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from tqdm import tqdm

DEFAULT_KEYWORDS = ["singtel", "starhub", "m1", "gomo", "eight","simba","circles","mobile plan",  "sim only", "sim-only"]

# Search mode: one Reddit search per query. Multi-word queries match all words.
DEFAULT_SEARCH_QUERIES = [
    "singtel", "starhub", "m1 telco", "m1 mobile", "simba", "giga mobile", "gomo", "circles.life",
    "eight telecom", "zym", "redone", "myrepublic mobile", "vivifi", "heya", "zero1",
    "sim only", "mobile plan", "roaming", "port number", "5g", "mvno", "telco",
]

# Brand terms for --strict-match. Ambiguous names (a number, an Apple chip, a common
# word) count only with a telco word nearby, as in processing/telco_labeler.py.
STRICT_BRANDS = [
    "singtel", "starhub", "m1", "simba", "giga", "gomo", "circles", "circles.life", "eight",
    "zym", "redone", "myrepublic", "vivifi", "heya", "zero1", "tpg",
]
AMBIGUOUS_BRANDS = {"m1", "giga", "simba", "circles", "eight", "heya", "zero1"}
TELCO_TOPIC_TERMS = [
    "sim only", "sim-only", "mobile plan", "telco", "mvno", "roaming", "port number", "porting",
    "isp", "broadband", "fibre", "fiber", "onr", "esim",
]
TELCO_CONTEXT = (
    r"telco|telecom|mobile|mvno|sim(?:-only)?|plan|network|roaming|port(?:ing)?|data|gb|"
    r"4g|5g|signal|coverage|singtel|starhub|simba|gomo"
)
_CONTEXT_WINDOW = 60
# DEFAULT_KEYWORDS = ["starhub","5G"]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) RedditScraper/1.0 "
    "(Research; +https://github.com/example/reddit-scraper)"
)

BASE_URL = "https://api.reddit.com"
OAUTH_BASE_URL = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_USING_OAUTH = False


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


def _word_pattern(term: str) -> str:
    return r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"


def strict_telco_match(text: str) -> bool:
    """True if text names a telco brand as a whole word (ambiguous names need a telco
    word within 60 characters) or uses an unambiguous telco topic phrase."""
    t = _normalize_for_match(text)
    if not t:
        return False
    if any(re.search(_word_pattern(term), t) for term in TELCO_TOPIC_TERMS):
        return True
    for brand in STRICT_BRANDS:
        for m in re.finditer(_word_pattern(brand), t):
            if brand not in AMBIGUOUS_BRANDS:
                return True
            # Text around the match, without the match itself ("simba" is also a context word).
            window = t[max(0, m.start() - _CONTEXT_WINDOW): m.start()] + " " + t[m.end(): m.end() + _CONTEXT_WINDOW]
            if re.search(rf"(?<![a-z0-9])(?:{TELCO_CONTEXT})(?![a-z0-9])", window):
                return True
    return False


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
    """Session with application-only OAuth when REDDIT_CLIENT_ID/SECRET are set."""
    global BASE_URL, _USING_OAUTH
    s = requests.Session()
    user_agent = os.getenv("REDDIT_USER_AGENT", "").strip() or USER_AGENT
    s.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        r = s.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        r.raise_for_status()
        token = r.json().get("access_token")
        if not token:
            raise RuntimeError("Reddit OAuth returned no access_token; check the app credentials.")
        s.headers["Authorization"] = f"bearer {token}"
        BASE_URL = OAUTH_BASE_URL
        _USING_OAUTH = True
        print("Reddit auth: application-only OAuth (oauth.reddit.com)")
    else:
        print("Reddit auth: none (public JSON). Set REDDIT_CLIENT_ID/SECRET if you get HTTP 403.")
    return s


def _endpoint(path: str) -> str:
    """Build an API URL; oauth.reddit.com takes paths without the .json suffix."""
    if _USING_OAUTH and path.endswith(".json"):
        path = path[: -len(".json")]
    return urljoin(BASE_URL, path)


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
            if r.status_code == 403 and not _USING_OAUTH:
                raise RuntimeError(
                    "HTTP 403 from Reddit: unauthenticated access is blocked on this network. "
                    "Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT (see module docstring)."
                )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            polite_sleep(2.0, 4.0)
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


def subreddit_listing_url(subreddit: str, sort: str, limit: int, after: Optional[str]) -> str:
    sub = subreddit.strip().lstrip("/r/")
    url = _endpoint(f"/r/{sub}/{sort}.json")
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


def subreddit_search_url(subreddit: str, query: str, limit: int, after: Optional[str]) -> tuple:
    sub = subreddit.strip().lstrip("/r/")
    url = _endpoint(f"/r/{sub}/search.json")
    params = {
        "q": query,
        "restrict_sr": 1,
        "sort": "new",
        "t": "year",
        "limit": min(limit, 100),
        "raw_json": 1,
    }
    if after:
        params["after"] = after
    return url, params


def search_subreddit_posts(
    session: requests.Session,
    subreddit: str,
    queries: List[str],
    limit_per_query: int,
    since_utc: float,
    strict: bool,
    sleep_min: float,
    sleep_max: float,
) -> List[RedditPost]:
    """Run each query as a subreddit search, newest first, stopping at --since.
    Posts are deduplicated by post_id across queries."""
    seen: Dict[str, RedditPost] = {}
    for query in queries:
        after: Optional[str] = None
        kept = 0
        while kept < limit_per_query:
            url, params = subreddit_search_url(subreddit, query, 100, after)
            data = fetch_json(session, url, params=params)
            batch = parse_listing(data, subreddit)
            reached_since = False
            for p in batch:
                if since_utc and p.created_utc < since_utc:
                    reached_since = True
                    continue
                if strict and not strict_telco_match(p.title + " " + p.selftext):
                    continue
                if p.post_id not in seen:
                    seen[p.post_id] = p
                    kept += 1
            after = get_after(data)
            polite_sleep(sleep_min, sleep_max)
            if reached_since or not after or not batch:
                break
        print(f"  r/{subreddit} q={query!r}: {kept} new posts (total {len(seen)})")
    return list(seen.values())


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
    since_utc: float = 0.0,
    strict: bool = False,
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
            if strict and not strict_telco_match(p.title + " " + p.selftext):
                continue
            if since_utc and p.created_utc < since_utc:
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
    path = re.sub(r"^https?://(www\.)?reddit\.com", "", permalink).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    url = _endpoint(path + ".json") if _USING_OAUTH else f"https://www.reddit.com{path}.json"
    try:
        data = fetch_json(session, url, params={"raw_json": 1})
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
    mode: str = "listing",
    queries: Optional[List[str]] = None,
    since_utc: float = 0.0,
    strict: bool = False,
) -> List[Dict]:
    if session is None:
        session = make_session()

    all_posts: List[RedditPost] = []
    for sub in subreddits:
        if mode == "search":
            batch = search_subreddit_posts(
                session, sub, queries or DEFAULT_SEARCH_QUERIES, limit_per_sub, since_utc, strict,
                sleep_min, sleep_max,
            )
        else:
            batch = fetch_subreddit_posts(
                session, sub, sort, limit_per_sub, keywords, sleep_min, sleep_max, since_utc, strict
            )
        all_posts.extend(batch)
        polite_sleep(sleep_min, sleep_max)

    # The same thread can surface in two subreddit runs only by crosspost id; dedupe anyway.
    unique_posts: Dict[str, RedditPost] = {}
    for p in all_posts:
        unique_posts.setdefault(p.post_id, p)
    all_posts = list(unique_posts.values())
    seen_comments: set = set()

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
                if c["comment_id"] in seen_comments:
                    continue
                seen_comments.add(c["comment_id"])
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
        help="Max posts per subreddit (listing) or per query (search).",
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
    ap.add_argument(
        "--mode",
        choices=["listing", "search"],
        default="listing",
        help="listing = subreddit /sort listing (~1,000-post cap); search = one search per query.",
    )
    ap.add_argument(
        "--queries",
        type=str,
        default=",".join(DEFAULT_SEARCH_QUERIES),
        help="Search mode: comma-separated queries (each run separately).",
    )
    ap.add_argument("--since", type=str, default="", help="Keep posts created on/after YYYY-MM-DD (UTC).")
    ap.add_argument(
        "--strict-match",
        action="store_true",
        help="Whole-word brand match; ambiguous names (m1, eight, giga, simba, circles) need a telco word nearby.",
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
    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    since_utc = 0.0
    if args.since:
        since_utc = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    print(f"Mode:       {args.mode}" + (f" ({len(queries)} queries)" if args.mode == "search" else ""))
    print(f"Since:      {args.since or '(no limit)'}   Strict match: {args.strict_match}")

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
        mode=args.mode,
        queries=queries,
        since_utc=since_utc,
        strict=args.strict_match,
    )

    if not rows:
        print("No posts collected.")
        return

    out_prefix = build_output_prefix(args.out, queries[:3] if args.mode == "search" else keywords)
    save_outputs(rows, out_prefix)


if __name__ == "__main__":
    main()
