#!/usr/bin/env python3
import argparse
import os
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

DEFAULT_KEYWORDS = ["singtel", "starhub", "m1", "gomo", "eight"]

# Forum login is optional. Set HWZ_USERNAME and HWZ_PASSWORD in the environment;
# never put credentials in this file.
login_uname = os.getenv("HWZ_USERNAME", "").strip()
password = os.getenv("HWZ_PASSWORD", "")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

@dataclass(frozen=True)
class ThreadMeta:
    title: str
    url: str
    source_forum: str


def clean_text(s: str) -> str:
    # Normalize whitespace
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n\s+", "\n", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def keyword_match(title: str, keywords: List[str]) -> bool:
    t = title.lower()
    return any(k.lower() in t for k in keywords)


def polite_sleep(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    )
    return s


def login_to_forum(session: requests.Session, base_url: str, username: str, password: str) -> bool:
    """
    Login to XenForo forum.
    Returns True if login successful, False otherwise.
    """
    login_url = urljoin(base_url, "/login/login")
    
    try:
        # Step 1: Get login page to extract CSRF token
        login_page = session.get(login_url, timeout=30)
        login_page.raise_for_status()
        
        soup = BeautifulSoup(login_page.text, "lxml")
        
        # Find CSRF token - XenForo uses _xfToken hidden input
        csrf_token = None
        token_input = soup.select_one('input[name="_xfToken"]')
        if token_input:
            csrf_token = token_input.get("value")
        
        if not csrf_token:
            # Try alternative token locations
            token_input = soup.select_one('input[name="csrf_token"]')
            if token_input:
                csrf_token = token_input.get("value")
        
        if not csrf_token:
            print("Warning: Could not find CSRF token. Attempting login without it...")
        
        # Step 2: POST login credentials
        login_data = {
            "login": username,
            "password": password,
            "remember": "1",
        }
        
        if csrf_token:
            login_data["_xfToken"] = csrf_token
        
        login_response = session.post(
            login_url,
            data=login_data,
            timeout=30,
            allow_redirects=True
        )
        
        # Check if login was successful
        # XenForo typically redirects to home page on success
        # Check for common indicators of successful login
        if login_response.status_code == 200 or login_response.status_code == 302:
            # Verify by checking if we can see user-specific content
            # Try accessing a page that requires login
            test_response = session.get(base_url, timeout=30)
            if test_response.status_code == 200:
                # Check for username in response or check cookies
                if session.cookies.get("xf_user") or session.cookies.get("xf_session"):
                    print(f"Login successful for user: {username}")
                    return True
        
        print(f"Login may have failed. Status code: {login_response.status_code}")
        return False
        
    except Exception as e:
        print(f"Error during login: {e}")
        return False


def fetch_html(session: requests.Session, url: str, timeout: int = 30, retries: int = 3) -> str:
    last_err = None
    for _ in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_err = e
            polite_sleep(2.0, 4.0)
    raise RuntimeError(f"Failed to fetch {url}: {last_err}")


# ----------------------------
# XenForo forum parsing
# ----------------------------

def parse_forum_threads(html: str, base_url: str, forum_url: str) -> List[ThreadMeta]:
    """
    XenForo forum listing: thread title links usually in div.structItem-title a
    """
    soup = BeautifulSoup(html, "lxml")
    out: List[ThreadMeta] = []

    for a in soup.select("div.structItem-title a"):
        href = a.get("href", "")
        title = clean_text(a.get_text(" ", strip=True))
        if not href or not title:
            continue

        full_url = urljoin(base_url, href)
        if "/threads/" not in full_url:
            continue

        out.append(ThreadMeta(title=title, url=full_url, source_forum=forum_url))

    # de-dup by URL (preserve order)
    seen = set()
    dedup = []
    for t in out:
        if t.url not in seen:
            seen.add(t.url)
            dedup.append(t)
    return dedup


def get_forum_page_url(forum_url: str, page_num: int) -> str:
    forum_url = forum_url.rstrip("/")
    if page_num <= 1:
        return forum_url + "/"
    return f"{forum_url}/page-{page_num}"


def parse_thread_title(soup: BeautifulSoup) -> str:
    h = soup.select_one("h1.p-title-value")
    if h:
        return clean_text(h.get_text(" ", strip=True))
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)
    return ""


def parse_thread_max_pages(soup: BeautifulSoup) -> int:
    nums = []
    for a in soup.select("a.pageNav-page"):
        txt = clean_text(a.get_text(" ", strip=True))
        if txt.isdigit():
            nums.append(int(txt))
    return max(nums) if nums else 1


def build_thread_page_url(thread_url: str, page_num: int) -> str:
    thread_url = thread_url.rstrip("/")
    if page_num <= 1:
        return thread_url + "/"
    return f"{thread_url}/page-{page_num}"


def parse_posts_from_thread_page(soup: BeautifulSoup) -> List[Dict]:
    """
    XenForo posts - try multiple selectors for HardwareZone compatibility.
    """
    rows = []
    
    # Try multiple selectors for posts (XenForo variants + legacy)
    post_selectors = [
        "article.message--post",
        "article.message",
        "article[data-author]",
        "div.message",
        "li.message",
        "div.post",
        "div[id^='post_message']",  # Legacy HardwareZone
        "div#posts article",
        "div#posts div.message",
        "div.messageList article",
        "div.messageList div.message",
    ]
    
    posts_found = None
    used_selector = None
    for selector in post_selectors:
        posts_found = soup.select(selector)
        if posts_found:
            used_selector = selector
            break
    
    if not posts_found:
        # Try to find posts by looking for common post containers
        # Check if there's a posts container
        posts_container = soup.select_one("div#posts, div.messageList, div[class*='postList']")
        if posts_container:
            # Try finding articles or divs within the container
            posts_found = posts_container.select("article, div[class*='message'], div[class*='post']")
            if posts_found:
                used_selector = "container-based"
    
    if not posts_found:
        return rows
    
    for post in posts_found:
        # timestamp - try multiple selectors
        ts = None
        time_selectors = [
            "time.u-dt",
            "time[datetime]",
            "time",
            "span.time",
            "abbr.time",
            "span[data-time]",
            "abbr[data-time]",
        ]
        for time_sel in time_selectors:
            time_el = post.select_one(time_sel)
            if time_el:
                ts = time_el.get("datetime") or time_el.get("data-time") or time_el.get("title") or time_el.get_text(strip=True)
                if ts:
                    ts = str(ts).strip()
                    break

        # message text - try multiple selectors
        body = None
        body_selectors = [
            "div.message-body",
            "div.message-content",
            "div.post-content",
            "div.bbWrapper",
            "div.message-body div.bbWrapper",
            "article[data-content]",
            "div[class*='message-body']",
            "div[class*='post-content']",
        ]
        for body_sel in body_selectors:
            body = post.select_one(body_sel)
            if body:
                break
        
        # Fallback: try to find div with substantial text content
        if not body:
            # Look for divs with class containing 'content' or 'body'
            for div in post.select("div"):
                classes = " ".join(div.get("class", []))
                if "content" in classes.lower() or "body" in classes.lower():
                    text_preview = div.get_text(strip=True)
                    if len(text_preview) > 20:  # Substantial content
                        body = div
                        break
        
        # Last resort: get text from the post element itself
        if not body:
            # Check if post itself has substantial text
            direct_text = post.get_text(strip=True)
            if len(direct_text) > 50:
                body = post
        
        if body:
            # Remove quoted blocks, signatures, etc.
            for q in body.select(".bbCodeBlock--quote, blockquote, .quote, .signature, .bbCodeBlock"):
                q.decompose()

            text = clean_text(body.get_text("\n", strip=True))
        else:
            text = ""

        # Skip empty posts
        if not text or len(text.strip()) < 10:
            continue

        rows.append(
            {
                "timestamp": ts,
                "post_text": text,
            }
        )
    return rows


# ----------------------------
# Crawlers
# ----------------------------

def crawl_forums_for_threads(
    forum_urls: List[str],
    forum_pages: int,
    keywords: List[str],
    sleep_min: float,
    sleep_max: float,
    max_threads_total: int,
    session: Optional[requests.Session] = None,
) -> List[ThreadMeta]:
    if session is None:
        session = make_session()
    threads: List[ThreadMeta] = []
    seen: Set[str] = set()

    for forum_url in forum_urls:
        base_url = f"{urlparse(forum_url).scheme}://{urlparse(forum_url).netloc}"
        for p in range(1, forum_pages + 1):
            page_url = get_forum_page_url(forum_url, p)
            html = fetch_html(session, page_url)
            found = parse_forum_threads(html, base_url, forum_url)

            for t in found:
                if t.url in seen:
                    continue
                seen.add(t.url)

                if keyword_match(t.title, keywords):
                    threads.append(t)
                    if len(threads) >= max_threads_total:
                        return threads

            polite_sleep(sleep_min, sleep_max)

    return threads


def scrape_threads(
    threads: List[ThreadMeta],
    sleep_min: float,
    sleep_max: float,
    max_thread_pages: int,
    session: Optional[requests.Session] = None,
    debug: bool = False,
) -> List[Dict]:
    if session is None:
        session = make_session()
    all_rows: List[Dict] = []
    scraped_at = datetime.utcnow().isoformat()
    debug_count = 0

    for t in tqdm(threads, desc="Scraping threads"):
        html = fetch_html(session, t.url)
        soup = BeautifulSoup(html, "lxml")

        thread_title = parse_thread_title(soup) or t.title
        max_pages = min(parse_thread_max_pages(soup), max_thread_pages)

        # page 1
        posts = parse_posts_from_thread_page(soup)
        
        # Debug: save first thread's HTML for inspection
        if debug and debug_count == 0 and not posts:
            debug_file = "debug_thread_page.html"
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\nDEBUG: Saved HTML to {debug_file} (found {len(posts)} posts)")
            debug_count += 1
        
        if not posts and debug_count <= 1:
            # Check what we actually got
            all_articles = soup.select("article")
            all_divs_with_message = soup.select("div[class*='message'], div[class*='post']")
            print(f"\nDEBUG: Thread '{thread_title[:50]}...'")
            print(f"  HTML length: {len(html)}")
            print(f"  Found {len(all_articles)} <article> tags")
            print(f"  Found {len(all_divs_with_message)} divs with 'message' or 'post' in class")
            if all_articles:
                print(f"  Sample article classes: {[a.get('class', [])[:2] for a in all_articles[:3]]}")
        
        for post in posts:
            all_rows.append({
                "source_forum": t.source_forum,
                "thread_title": thread_title,
                "thread_url": t.url,
                "thread_page": 1,
                "timestamp": post.get("timestamp"),
                "post_text": post.get("post_text", ""),
                "scraped_at_utc": scraped_at
            })

        # pages 2..N
        for page_num in range(2, max_pages + 1):
            page_url = build_thread_page_url(t.url, page_num)
            page_html = fetch_html(session, page_url)
            page_soup = BeautifulSoup(page_html, "lxml")

            posts = parse_posts_from_thread_page(page_soup)
            for post in posts:
                all_rows.append({
                    "source_forum": t.source_forum,
                    "thread_title": thread_title,
                    "thread_url": t.url,
                    "thread_page": page_num,
                    "timestamp": post.get("timestamp"),
                    "post_text": post.get("post_text", ""),
                    "scraped_at_utc": scraped_at
                })

            polite_sleep(sleep_min, sleep_max)

        polite_sleep(sleep_min, sleep_max)

    return all_rows


def scrape_seed_threads(seed_thread_urls: List[str], sleep_min: float, sleep_max: float, max_thread_pages: int) -> List[ThreadMeta]:
    """
    Treat seed threads (e.g., deal megathreads) as thread list directly.
    """
    metas = []
    for u in seed_thread_urls:
        metas.append(ThreadMeta(title="(seed)", url=u, source_forum="seed_thread"))
    return metas


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


def main():
    ap = argparse.ArgumentParser(description="HWZ (XenForo) multi-forum + deals thread scraper.")
    ap.add_argument(
        "--forum-urls",
        type=str,
        default="",
        help="Comma-separated forum URLs to crawl (listing pages)."
    )
    ap.add_argument(
        "--seed-threads",
        type=str,
        default="",
        help="Comma-separated thread URLs to always scrape (e.g., deals megathreads)."
    )
    ap.add_argument("--forum-pages", type=int, default=5, help="Forum listing pages per forum URL.")
    ap.add_argument("--max-threads", type=int, default=80, help="Max matched threads across all forums.")
    ap.add_argument("--keywords", type=str, default=",".join(DEFAULT_KEYWORDS), help="Comma-separated keywords.")
    ap.add_argument("--max-thread-pages", type=int, default=3, help="Max pages per thread to scrape.")
    ap.add_argument("--sleep-min", type=float, default=1.2, help="Min seconds between requests.")
    ap.add_argument("--sleep-max", type=float, default=2.5, help="Max seconds between requests.")
    ap.add_argument("--out", type=str, default="data/raw/hwz_multi_posts", help="Output prefix (CSV + JSONL). Writes to data/raw/ by default.")
    ap.add_argument("--debug", action="store_true", help="Enable debug mode (saves sample HTML).")
    args = ap.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    forum_urls = [u.strip() for u in args.forum_urls.split(",") if u.strip()]
    seed_threads = [u.strip() for u in args.seed_threads.split(",") if u.strip()]

    # Create session and login
    session = make_session()
    # Use first forum URL's base URL for login, or default HWZ URL
    if forum_urls:
        base_url = f"{urlparse(forum_urls[0]).scheme}://{urlparse(forum_urls[0]).netloc}"
    else:
        base_url = "https://forums.hardwarezone.com.sg"
    
    if login_uname and password:
        print("Logging in to forum...")
        login_success = login_to_forum(session, base_url, login_uname, password)
    else:
        print("No HWZ_USERNAME/HWZ_PASSWORD set; scraping public pages without login.")
        login_success = False
    if not login_success and login_uname and password:
        print("Warning: Login failed. Continuing without authentication (may have limited access).")
    else:
        polite_sleep(1.0, 2.0)  # Brief pause after login

    threads: List[ThreadMeta] = []

    if forum_urls:
        print(f"Crawling forums ({len(forum_urls)}) for keyword-matched threads…")
        threads.extend(crawl_forums_for_threads(
            forum_urls=forum_urls,
            forum_pages=args.forum_pages,
            keywords=keywords,
            sleep_min=args.sleep_min,
            sleep_max=args.sleep_max,
            max_threads_total=args.max_threads,
            session=session,
        ))

    if seed_threads:
        print(f"Adding seed threads ({len(seed_threads)})…")
        threads.extend(scrape_seed_threads(
            seed_thread_urls=seed_threads,
            sleep_min=args.sleep_min,
            sleep_max=args.sleep_max,
            max_thread_pages=args.max_thread_pages
        ))

    # de-dup threads by url
    seen = set()
    dedup = []
    for t in threads:
        if t.url not in seen:
            seen.add(t.url)
            dedup.append(t)
    threads = dedup

    if not threads:
        print("No threads to scrape. Provide --forum-urls and/or --seed-threads.")
        return

    print(f"Total threads queued: {len(threads)}")
    rows = scrape_threads(
        threads=threads,
        sleep_min=args.sleep_min,
        sleep_max=args.sleep_max,
        max_thread_pages=args.max_thread_pages,
        session=session,
        debug=args.debug,
    )

    save_outputs(rows, args.out)


if __name__ == "__main__":
    main()