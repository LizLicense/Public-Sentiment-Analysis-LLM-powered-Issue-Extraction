#!/usr/bin/env python3
"""
Regenerate dashboard/index.html and dashboard/Dash_README.md from the clean corpus.

Default inputs:
  - data/processed/corpus_posts_mini_sentiment.csv
      (clean corpus + GPT-4o-mini sentiment; written by models/corpus_llm_sentiment.py)
  - falls back to data/processed/corpus_posts.csv with VADER sentiment,
    and says so on the page, if the GPT-4o-mini file does not exist yet
  - data/evaluation/gold_labels.csv (human sentiment check, representative + recent)

The clean corpus is one row per unique post in telco threads (processing/build_clean_corpus.py).
Issue labels are the hybrid (keyword rules, then GPT-4o on unresolved rows).

Usage (from project root):
  python dashboard/generate_dashboard.py
  python dashboard/generate_dashboard.py --corpus data/processed/corpus_posts.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent

MINI_CORPUS = ROOT / "data/processed/corpus_posts_mini_sentiment.csv"
VADER_CORPUS = ROOT / "data/processed/corpus_posts.csv"

BRAND_MAP = [
    ("singtel", "Singtel"), ("starhub", "StarHub"), ("m1", "M1"), ("simba", "SIMBA"),
    ("giga", "Giga"), ("eight", "Eight"), ("zym", "Zym"), ("redone", "redONE"),
]

ISSUE_LABELS = [
    "network_quality",
    "pricing_promotions",
    "mobile_plans",
    "roaming",
    "porting",
    "customer_service",
    "billing_payment",
    "app_account",
    "devices",
    "general_discussion",
]
ISSUE_DISPLAY = {
    "network_quality": "Network Quality",
    "pricing_promotions": "Pricing & Promotions",
    "mobile_plans": "Mobile Plans",
    "roaming": "Roaming",
    "porting": "Porting",
    "customer_service": "Customer Service",
    "billing_payment": "Billing & Payment",
    "app_account": "App & Account",
    "devices": "Devices",
    "general_discussion": "General Discussion",
}
ISSUE_COLORS = {
    "network_quality": "#8b5cf6",
    "pricing_promotions": "#f59e0b",
    "mobile_plans": "#3b82f6",
    "roaming": "#14b8a6",
    "porting": "#06b6d4",
    "customer_service": "#ec4899",
    "billing_payment": "#ef4444",
    "app_account": "#6366f1",
    "devices": "#84cc16",
    "general_discussion": "#64748b",
}

# Owner, action and check for each actionable issue. The page orders them by how
# much not-happy discussion each issue carries, so the order follows the data.
ISSUE_ACTIONS = {
    "network_quality": ("Network", "Join named-location and outage posts to tickets and cell data; publish status and ETA during incidents.",
                        "Tickets fall at that location; fewer “is it down?” threads."),
    "mobile_plans": ("Product", "Show fair-use limits, add-on charges (e.g. Caller ID), recurring price and host network at checkout.",
                     "Fewer “which plan / which backend?” threads."),
    "pricing_promotions": ("Commercial", "Publish intro vs recurring price and promo expiry; audit promotion fulfilment.",
                           "Fewer fulfilment complaints, not just a lower list price."),
    "devices": ("Device support", "Document router, ONR/ONT and eSIM requirements per plan.",
                "Fewer equipment and bridge-mode threads."),
    "billing_payment": ("Billing", "Publish the outage compensation rule with the incident notice; explain charges before the bill lands.",
                        "Fewer compensation and surprise-charge posts."),
    "customer_service": ("Service operations", "Keep a self-service path and callback queue open during incidents; close escalations with a named owner.",
                         "Fewer “cannot reach support” posts after the next incident."),
    "porting": ("MNP operations", "Return a specific port-reject reason and next step.",
                "Lower avoidable-reject rate and median port time."),
    "roaming": ("Roaming", "In-app “travelling to X” checklist: activation, coverage, overage cap.",
                "Fewer destination bill-shock posts."),
    "app_account": ("Digital CX", "Fix login, OTP and chatbot dead-ends; watch posts after each release.",
                    "Fewer “cannot log in” posts after a release."),
}

HUDDLE_ISSUES = ("network_quality", "app_account", "porting")
HUDDLE_THRESHOLD = 20
MIN_BRAND_MENTIONS = 10
# A brand is ranked only with enough threads and enough of the corpus that one thread cannot drive it.
MIN_BRAND_THREADS = 10
MIN_BRAND_SHARE = 0.01


def read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(10**9)
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def norm_sentiment(s: str) -> str:
    s = (s or "").lower().strip().replace(" ", "_")
    if s in ("happy", "positive"):
        return "happy"
    if s in ("not_happy", "negative"):
        return "not_happy"
    if s == "neutral":
        return "neutral"
    return ""


def split_brands(label: str) -> list[str]:
    found: list[str] = []
    for part in re.split(r"[,;/|&]+", label or ""):
        key = part.strip().lower().replace(" ", "")
        for token, name in BRAND_MAP:
            if key == token and name not in found:
                found.append(name)
    return found


def parse_time(row: dict) -> datetime | None:
    for value in (row.get("comment_time"), row.get("timestamp")):
        value = (value or "").strip()
        if not value:
            continue
        for fmt in ("%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def pct(n: float, total: float) -> int:
    return round(100 * n / total) if total else 0


def shares(rows: list[dict], key: str, labels: list[str], thread_equal: bool) -> dict[str, float]:
    """Share of each label; thread_equal gives every thread the same total weight."""
    size = Counter(r["thread_key"] for r in rows)
    totals: dict[str, float] = defaultdict(float)
    for r in rows:
        totals[r[key]] += 1 / size[r["thread_key"]] if thread_equal else 1
    grand = sum(totals.values()) or 1
    return {k: round(100 * totals.get(k, 0) / grand, 1) for k in labels}


def sentiment_pct(rows: list[dict]) -> dict[str, int]:
    c = Counter(r["sentiment_final"] for r in rows)
    out = {k: pct(c[k], len(rows)) for k in ("happy", "not_happy", "neutral")}
    out["n"] = len(rows)
    return out


def load_gold_pct(path: Path | None) -> dict[str, dict[str, int]]:
    """Human sentiment shares from the representative gold set, overall and by source."""
    if not path or not path.exists():
        return {}
    by_source: dict[str, Counter] = defaultdict(Counter)
    for row in read_csv(path):
        if (row.get("telco_relevance_manual") or "").strip().lower() != "yes":
            continue
        if "evaluation_set" in row and row["evaluation_set"] not in ("representative", "recent"):
            continue  # challenge set is deliberately hard, not representative
        label = norm_sentiment(row.get("sentiment_manual") or "")
        if label:
            by_source[(row.get("source") or "").strip().lower()][label] += 1
            by_source["all"][label] += 1
    out = {}
    for src, counts in by_source.items():
        n = sum(counts.values())
        out[src] = {k: pct(counts[k], n) for k in ("happy", "not_happy", "neutral")}
        out[src]["n"] = n
    return out


def short_quote(text: str, max_words: int = 22) -> str:
    words = re.sub(r"\s+", " ", html.unescape(text or "")).strip().split()
    return " ".join(words) if len(words) <= max_words else " ".join(words[:max_words]) + "…"


def pick_quotes(rows: list[dict], issue_order: list[str], n: int = 4) -> list[dict]:
    """One short not-happy quote per leading issue, from different threads."""
    quotes: list[dict] = []
    used_threads: set[str] = set()
    for issue in issue_order:
        candidates = [
            r for r in rows
            if r["issue_final"] == issue and r["sentiment_final"] == "not_happy"
            and 40 <= len(r["post_text"]) <= 220 and r["thread_key"] not in used_threads
            and not re.search(r"please log in|last edited:|https?://", r["post_text"].lower())
        ]
        if not candidates:
            continue
        pick = min(candidates, key=lambda r: (abs(len(r["post_text"]) - 120), r["sample_key"]))
        used_threads.add(pick["thread_key"])
        quotes.append({
            "text": short_quote(pick["post_text"]),
            "source": pick["source"].upper(),
            "context": f"{ISSUE_DISPLAY[issue]} · {', '.join(pick['brands'][:2]) or 'no brand named'}",
        })
        if len(quotes) >= n:
            break
    return quotes


def load_corpus(path: Path) -> tuple[list[dict], str]:
    raw = read_csv(path)
    use_llm = "llm_sentiment" in (raw[0] if raw else {}) and any(r.get("llm_sentiment") for r in raw)
    rows = []
    for i, r in enumerate(raw):
        llm = norm_sentiment(r.get("llm_sentiment", "")) if use_llm else ""
        vader = norm_sentiment(r.get("sentiment_label", ""))
        issue = (r.get("issue_primary") or "").strip()
        rows.append({
            "sample_key": i,
            "source": (r.get("source") or "").strip().lower(),
            "thread_key": r.get("thread_key") or r.get("thread_title", ""),
            "thread_title": r.get("thread_title", ""),
            "post_text": r.get("post_text", ""),
            "brands": split_brands(r.get("telco_label", "")),
            "sentiment_final": llm or vader or "neutral",
            "sentiment_source": "llm" if llm else "vader",
            "sentiment_vader": vader or "neutral",
            "issue_final": issue if issue in ISSUE_DISPLAY else "general_discussion",
            "time": parse_time(r),
        })
    return rows, ("gpt-4o-mini" if use_llm else "vader")


def load_run_meta(corpus_path: Path) -> dict:
    summary = corpus_path.with_name(corpus_path.stem + "_summary.json")
    if not summary.exists():
        summary = corpus_path.parent / "clean_posts_mini_sentiment_summary.json"
    if not summary.exists():
        return {}
    data = json.loads(summary.read_text(encoding="utf-8"))
    return {
        "models": ", ".join(data.get("returned_models", {})) or data.get("requested_model", ""),
        "cost": data.get("cost", {}).get("estimated_total_cost", 0.0),
        "labelled": data.get("labelled", 0),
        "failed": len(data.get("failed_sample_ids", [])),
    }


def weekly_queue(rows: list[dict]) -> list[tuple[str, int]]:
    weeks: Counter = Counter()
    for r in rows:
        if r["time"] and r["sentiment_final"] == "not_happy" and r["issue_final"] in HUDDLE_ISSUES:
            monday = (r["time"] - timedelta(days=r["time"].weekday())).date()
            weeks[monday.isoformat()] += 1
    return sorted(weeks.items())


def resolve_threshold(weeks: list[tuple[str, int]], setting: str) -> tuple[int, str]:
    """Fixed n, or 'auto' = twice the median weekly queue over the last 26 weeks with posts."""
    if str(setting).lower() != "auto":
        n = int(setting)
        return n, f"n ≥ {n}"
    recent = sorted(c for _, c in weeks[-26:]) or [0]
    median = recent[len(recent) // 2] if len(recent) % 2 else (recent[len(recent) // 2 - 1] + recent[len(recent) // 2]) / 2
    n = max(1, round(2 * median))
    return n, f"n ≥ {n} (twice the median week of {median:g} over the last 26 weeks)"


def analyse(
    corpus_path: Path,
    gold_path: Path | None = None,
    threshold: str = str(HUDDLE_THRESHOLD),
    title: str = "",
    extra_limitation: str = "",
) -> tuple[list[dict], dict]:
    rows, labeller = load_corpus(corpus_path)
    n = len(rows)
    threads = Counter(r["thread_key"] for r in rows)
    times = sorted(r["time"] for r in rows if r["time"])
    top3 = sum(c for _, c in threads.most_common(3))
    titles = {r["thread_key"]: r["thread_title"] for r in rows}
    top_thread = titles[threads.most_common(1)[0][0]] if threads else ""

    issue_post = shares(rows, "issue_final", ISSUE_LABELS, thread_equal=False)
    issue_thread = shares(rows, "issue_final", ISSUE_LABELS, thread_equal=True)
    unhappy = [r for r in rows if r["sentiment_final"] == "not_happy"]
    unhappy_counts = Counter(r["issue_final"] for r in unhappy)
    unhappy_thread = shares(unhappy, "issue_final", ISSUE_LABELS, thread_equal=True) if unhappy else {}
    actionable = [k for k in ISSUE_LABELS if k != "general_discussion"]
    action_order = sorted(actionable, key=lambda k: (-unhappy_thread.get(k, 0), -issue_thread[k]))
    volume_order = sorted(actionable, key=lambda k: -issue_thread[k])

    by_source = defaultdict(list)
    for r in rows:
        by_source[r["source"]].append(r)
    source_pct = {src: sentiment_pct(sub) for src, sub in by_source.items()}

    brand_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for b in r["brands"]:
            brand_rows[b].append(r)
    brand_table = []
    for brand, sub in sorted(brand_rows.items(), key=lambda x: -len(x[1])):
        ic = Counter(r["issue_final"] for r in sub if r["issue_final"] != "general_discussion")
        brand_table.append({
            "brand": brand,
            "mentions": len(sub),
            "threads": len({r["thread_key"] for r in sub}),
            "neg_pct": pct(sum(r["sentiment_final"] == "not_happy" for r in sub), len(sub)),
            "top_issues": ", ".join(ISSUE_DISPLAY[k] for k, _ in ic.most_common(2)) or "General Discussion",
        })
    min_posts = max(MIN_BRAND_MENTIONS, round(MIN_BRAND_SHARE * n))
    rankable = lambda b: b["mentions"] >= min_posts and b["threads"] >= MIN_BRAND_THREADS
    ranked = sorted((b for b in brand_table if rankable(b)), key=lambda b: -b["neg_pct"])

    weeks = weekly_queue(rows)
    huddle_n, huddle_rule = resolve_threshold(weeks, threshold)
    stats = {
        "huddle_threshold": huddle_n,
        "huddle_rule": huddle_rule,
        "title_suffix": title,
        "extra_limitation": extra_limitation,
        "llm_missing": sum(r["sentiment_source"] == "vader" for r in rows) if labeller == "gpt-4o-mini" else 0,
        "n": n,
        "n_threads": len(threads),
        "top3_threads_pct": pct(top3, n),
        "top_thread": top_thread,
        "date_from": times[0].date().isoformat() if times else "",
        "date_to": times[-1].date().isoformat() if times else "",
        "share_2026_pct": pct(sum(t.year == 2026 for t in times), len(times)),
        "labeller": labeller,
        "run_meta": load_run_meta(corpus_path) if labeller == "gpt-4o-mini" else {},
        "corpus_path": rel(corpus_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sentiment_counts": dict(Counter(r["sentiment_final"] for r in rows)),
        "sentiment_pct": sentiment_pct(rows),
        "vader_pct": {k: pct(sum(r["sentiment_vader"] == k for r in rows), n) for k in ("happy", "not_happy", "neutral")},
        "gold_pct": load_gold_pct(gold_path),
        "issue_post": issue_post,
        "issue_thread": issue_thread,
        "unhappy_counts": {k: unhappy_counts.get(k, 0) for k in ISSUE_LABELS},
        "unhappy_thread": unhappy_thread,
        "action_order": action_order,
        "volume_order": volume_order,
        "source_pct": source_pct,
        "brand_mentions": [(b["brand"], b["mentions"]) for b in brand_table],
        "brand_table": [b for b in brand_table if b["mentions"] >= 5],
        "brands_ranked": ranked,
        "brand_rank_rule": f"at least {min_posts} posts and {MIN_BRAND_THREADS} threads",
        "weeks": weeks,
        "weeks_over": [w for w in weeks if w[1] >= huddle_n],
        "quotes": pick_quotes(rows, action_order),
    }
    stats["exec_summary"] = build_executive_summary(stats)
    return rows, stats


def labeller_name(stats: dict) -> str:
    return "GPT-4o-mini" if stats["labeller"] == "gpt-4o-mini" else "VADER"


def build_executive_summary(stats: dict) -> str:
    s, v, gold = stats["sentiment_pct"], stats["vader_pct"], stats["gold_pct"].get("all", {})
    src = stats["source_pct"]
    it, ip = stats["issue_thread"], stats["issue_post"]
    first, second = stats["volume_order"][:2]
    hurt = stats["action_order"][0]
    ranked = stats["brands_ranked"][:2]
    who = labeller_name(stats)
    tone = (
        f"GPT-4o-mini, the labeller that best matched human labels (macro F1 0.641 vs VADER 0.380), reads "
        f"<strong>{s['not_happy']}% of posts as not happy</strong> and {s['happy']}% as happy; VADER on the same posts "
        f"says {v['not_happy']}% and {v['happy']}%. "
        if stats["labeller"] == "gpt-4o-mini"
        else f"<strong>Sentiment below is VADER</strong> ({s['happy']}% happy), which human labels show is far too "
             f"positive (humans: {gold.get('happy', 0)}% happy). Run models/corpus_llm_sentiment.py and regenerate. "
    )
    brands = (
        " and ".join(f"{b['brand']} ({b['neg_pct']}% not happy, n={b['mentions']})" for b in ranked)
        if ranked else "no brand"
    )
    weeks_over = stats["weeks_over"]
    huddle = (
        f"{len(weeks_over)} week(s) crossed the huddle threshold ({stats['huddle_rule']}), the largest "
        f"{max(weeks_over, key=lambda w: w[1])[1]} posts in the week of {max(weeks_over, key=lambda w: w[1])[0]}"
        if weeks_over else f"no week crossed the huddle threshold ({stats['huddle_rule']})"
    )
    return (
        f"An <strong>early-warning screen</strong>, not CSAT or NPS: {stats['n']:,} unique posts in {stats['n_threads']} "
        f"telco threads ({stats['date_from']} to {stats['date_to']}; {stats['share_2026_pct']}% from 2026). The three "
        f"largest threads hold {stats['top3_threads_pct']}% of posts; the biggest is “{html.escape(stats['top_thread'])}”. "
        f"{tone}"
        f"<strong>{ISSUE_DISPLAY[first]} leads</strong> ({it[first]}% with every thread weighted equally, {ip[first]}% per post), "
        f"then {ISSUE_DISPLAY[second]} ({it[second]}%). {ISSUE_DISPLAY[hurt]} carries the most not-happy discussion. "
        f"Using the same labeller on both sources, Reddit is {src.get('reddit', {}).get('not_happy', 0)}% not happy and "
        f"HWZ {src.get('hwz', {}).get('not_happy', 0)}% (the platforms also discuss different topics). Among brands with {stats['brand_rank_rule']}, "
        f"{brands} show the highest not-happy share. In the weekly huddle view, {huddle}. "
        f"Sentiment by {who}; issues by keyword rules plus GPT-4o."
    )


def render_readme(stats: dict) -> str:
    s = stats["sentiment_pct"]
    rows = "\n".join(
        f"| {ISSUE_DISPLAY[k]} | {stats['issue_post'][k]}% | {stats['issue_thread'][k]}% | {stats['unhappy_counts'][k]} |"
        for k in ISSUE_LABELS
    )
    meta = stats["run_meta"]
    run = (
        f"Sentiment: `{meta.get('models', 'gpt-4o-mini')}` via `models/corpus_llm_sentiment.py` "
        f"({meta.get('labelled', 0):,} labelled, {meta.get('failed', 0)} failed, ~${meta.get('cost', 0):.2f})."
        if stats["labeller"] == "gpt-4o-mini"
        else "Sentiment: **VADER fallback** — run `models/corpus_llm_sentiment.py`, then regenerate."
    )
    return f"""# Telco Sentiment Dashboard

Static HTML dashboard for Singapore telco forum discussion (Reddit + HWZ).

**Auto-generated:** {stats["generated_at"]}

## Generate / refresh

From project root:

```bash
python processing/build_clean_corpus.py        # once: unique posts in telco threads
python models/corpus_llm_sentiment.py          # once: GPT-4o-mini sentiment (~$0.05)
python dashboard/generate_dashboard.py
open dashboard/index.html
```

Without the GPT-4o-mini file the page falls back to VADER sentiment and says so.

## Data

- Input: `{stats["corpus_path"]}`
- {stats["n"]:,} unique posts in {stats["n_threads"]} telco threads, {stats["date_from"]} to {stats["date_to"]}
- Reddit {stats["source_pct"].get("reddit", {}).get("n", 0):,} / HWZ {stats["source_pct"].get("hwz", {}).get("n", 0):,}
- {run}
- Issues: keyword rules, then GPT-4o on unresolved rows (hybrid file).

Sentiment ({labeller_name(stats)}): {s["happy"]}% happy / {s["not_happy"]}% not happy / {s["neutral"]}% neutral.

| Issue | Per post | Thread-weighted | Not-happy posts |
|---|---|---|---|
{rows}

## Contents

- Executive summary and KPI cards
- Weekly huddle queue over time against the threshold: {stats["huddle_rule"]}
- Sentiment (with the human-label check), Reddit vs HWZ on the same labeller
- Issue shares per post and thread-weighted; not-happy posts by issue
- Brand mentions and not-happy share for brands with {stats["brand_rank_rule"]}
- Per-telco table, quotes, recommendations ordered by not-happy share, limitations
"""


def render_html(stats: dict) -> str:
    sp = stats["sentiment_pct"]
    sc = stats["sentiment_counts"]
    gold = stats["gold_pct"]
    who = labeller_name(stats)
    reddit = stats["source_pct"].get("reddit", {"happy": 0, "not_happy": 0, "neutral": 0, "n": 0})
    hwz = stats["source_pct"].get("hwz", {"happy": 0, "not_happy": 0, "neutral": 0, "n": 0})
    first, second = stats["volume_order"][:2]
    hurt = stats["action_order"][0]
    ranked = stats["brands_ranked"]

    issue_labels_js = json.dumps([ISSUE_DISPLAY[k] for k in ISSUE_LABELS])
    issue_post = json.dumps([stats["issue_post"][k] for k in ISSUE_LABELS])
    issue_thread = json.dumps([stats["issue_thread"][k] for k in ISSUE_LABELS])
    unhappy_values = json.dumps([stats["unhappy_counts"][k] for k in ISSUE_LABELS])
    top_brands = stats["brand_mentions"][:8]
    week_labels = json.dumps([w for w, _ in stats["weeks"]])
    week_values = json.dumps([c for _, c in stats["weeks"]])

    if stats["labeller"] == "gpt-4o-mini":
        banner = ""
        tone_sub = (
            f"GPT-4o-mini on all {stats['n']:,} posts. VADER on the same posts: {stats['vader_pct']['happy']}% happy, "
            f"{stats['vader_pct']['not_happy']}% not happy. Human gold labels ({gold.get('all', {}).get('n', 0)} posts): "
            f"{gold.get('all', {}).get('happy', 0)}% happy, {gold.get('all', {}).get('not_happy', 0)}% not happy."
        )
    else:
        banner = (
            '<p class="banner">Sentiment on this page is VADER, which human labels show is far too positive. '
            "Run <code>models/corpus_llm_sentiment.py</code> and regenerate.</p>"
        )
        tone_sub = (
            f"VADER fallback. Human gold labels put the happy share at {gold.get('all', {}).get('happy', 0)}%, "
            "so read this as an upper bound on positivity."
        )
    if stats["labeller"] != "gpt-4o-mini":
        source_title = "Do not read a platform gap from VADER"
    elif abs(reddit["not_happy"] - hwz["not_happy"]) < 10:
        source_title = "Reddit and HWZ read similarly on the same labeller"
    else:
        # A per-post gap mixes platform with topic and period (e.g. an outage on one platform),
        # so the title reports the gap without calling it a platform effect.
        source_title = f"Reddit–HWZ gap of {abs(reddit['not_happy'] - hwz['not_happy'])} points: check topic mix first"

    def brand_cell(row: dict) -> str:
        note = f' <span class="small-n">n&lt;{MIN_BRAND_MENTIONS}</span>' if row["mentions"] < MIN_BRAND_MENTIONS else ""
        return (
            f'            <tr><td>{html.escape(row["brand"])}{note}</td><td>{row["mentions"]}</td>'
            f'<td>{row["threads"]}</td><td>{row["neg_pct"]}%</td><td>{html.escape(row["top_issues"])}</td></tr>'
        )

    table_rows = "\n".join(brand_cell(r) for r in stats["brand_table"])
    quote_blocks = "\n".join(
        f"""        <blockquote>
          "{html.escape(q["text"])}"
          <div class="quote-source">{html.escape(q["source"])} &middot; {html.escape(q["context"])}</div>
        </blockquote>"""
        for q in stats["quotes"]
    )
    rec_items = "\n".join(
        f'          <li><strong>{html.escape(ISSUE_ACTIONS[k][0])}</strong> '
        f'<span class="small-n">{ISSUE_DISPLAY[k]}: {stats["unhappy_thread"].get(k, 0)}% of not-happy, '
        f'{stats["issue_thread"][k]}% of all (thread-weighted)</span><br>'
        f'{html.escape(ISSUE_ACTIONS[k][1])} <em>Check: {html.escape(ISSUE_ACTIONS[k][2])}</em></li>'
        for k in stats["action_order"][:6]
    )
    weeks_over = stats["weeks_over"]
    queue_pill = (
        f"{len(weeks_over)} week(s) at or above threshold; peak {max(c for _, c in weeks_over)} posts"
        if weeks_over else "No week reached the threshold"
    )
    ranked_note = (
        f"% not happy for brands with {stats['brand_rank_rule']}. A brand's share can be driven by one "
        f"event thread, so check the Threads column before reading it as brand-wide."
        if ranked else "No brand has at least 10 mentions."
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Singapore Telco Forum Sentiment Dashboard{html.escape(stats["title_suffix"])}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #0f1419; --surface: #1a2332; --surface-2: #243044; --border: #2d3a4f;
      --text: #e8edf4; --muted: #8b9cb3; --accent: #3b82f6;
      --happy: #22c55e; --not-happy: #ef4444; --neutral: #94a3b8;
      --radius: 12px; --shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
    .page {{ max-width: 1280px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }}
    header {{ margin-bottom: 2rem; padding-bottom: 1.5rem; border-bottom: 1px solid var(--border); }}
    header h1 {{ font-size: 1.75rem; font-weight: 700; margin-bottom: 0.35rem; }}
    header .meta {{ color: var(--muted); font-size: 0.875rem; }}
    .banner {{ background: #3b2a0a; border: 1px solid #f59e0b; color: #fcd34d; border-radius: var(--radius);
      padding: 0.85rem 1.1rem; margin-bottom: 1.5rem; font-size: 0.9rem; }}
    .exec-summary {{ background: linear-gradient(135deg, var(--surface), var(--surface-2)); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 1.25rem 1.5rem; margin-bottom: 1.75rem; box-shadow: var(--shadow); }}
    .exec-summary h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); margin-bottom: 0.75rem; }}
    .huddle {{
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
      padding: 1.25rem 1.5rem; margin-bottom: 1.75rem; box-shadow: var(--shadow);
    }}
    .huddle h2 {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent); margin-bottom: 0.5rem; }}
    .huddle .lead {{ font-size: 0.95rem; color: #c5d0de; margin-bottom: 1rem; }}
    .huddle-steps {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.75rem; margin-bottom: 1rem; }}
    @media (max-width: 900px) {{ .huddle-steps {{ grid-template-columns: 1fr; }} }}
    .huddle-step {{ background: var(--surface-2); border-radius: 10px; padding: 0.85rem 0.9rem; }}
    .huddle-step .num {{ font-size: 0.7rem; font-weight: 700; color: var(--accent); text-transform: uppercase; letter-spacing: 0.06em; }}
    .huddle-step p {{ font-size: 0.8rem; color: #c5d0de; margin-top: 0.35rem; }}
    .huddle-status {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; margin-bottom: 1rem; }}
    .huddle-pill {{ background: var(--bg); border-radius: 999px; padding: 0.35rem 0.8rem; font-size: 0.8rem; color: var(--text); }}
    .huddle-warn {{ color: #f59e0b; font-size: 0.85rem; margin-top: 0.85rem; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-bottom: 1.75rem; }}
    .kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem; text-align: center; }}
    .kpi .value {{ font-size: 1.75rem; font-weight: 700; }}
    .kpi .label {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; margin-top: 0.25rem; }}
    .charts-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.25rem; margin-bottom: 1.75rem; }}
    @media (max-width: 900px) {{ .charts-grid {{ grid-template-columns: 1fr; }} }}
    .chart-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem; box-shadow: var(--shadow); }}
    .chart-card.full-width {{ grid-column: 1 / -1; }}
    .chart-card h3 {{ font-size: 0.9rem; font-weight: 600; }}
    .chart-card .subtitle {{ font-size: 0.78rem; color: var(--muted); margin: 0.35rem 0 1rem; line-height: 1.45; }}
    .small-n {{ color: #f59e0b; font-size: 0.7rem; text-transform: none; letter-spacing: 0; }}
    .chart-wrap {{ position: relative; height: 280px; }}
    .chart-wrap.tall {{ height: 340px; }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; margin-bottom: 1.75rem; }}
    @media (max-width: 768px) {{ .two-col {{ grid-template-columns: 1fr; }} }}
    .panel {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem 1.5rem; box-shadow: var(--shadow); }}
    .panel h2 {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.07em; color: var(--accent); margin-bottom: 1rem; }}
    .panel ul {{ list-style: none; }}
    .panel li {{ padding: 0.5rem 0; border-bottom: 1px solid var(--border); font-size: 0.875rem; color: #c5d0de; }}
    .panel li:last-child {{ border-bottom: none; }}
    .panel li::before {{ content: "▸"; color: var(--accent); margin-right: 0.5rem; }}
    blockquote {{ border-left: 3px solid var(--accent); padding: 0.65rem 1rem; margin: 0.65rem 0;
      background: rgba(59,130,246,0.08); border-radius: 0 8px 8px 0; font-size: 0.85rem; font-style: italic; color: #b8c5d6; }}
    .quote-source {{ font-size: 0.7rem; color: var(--muted); font-style: normal; margin-top: 0.35rem; }}
    .brand-table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
    .brand-table th, .brand-table td {{ padding: 0.55rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
    .brand-table th {{ color: var(--muted); font-size: 0.7rem; text-transform: uppercase; }}
    footer {{ margin-top: 2rem; padding-top: 1.25rem; border-top: 1px solid var(--border); font-size: 0.75rem; color: var(--muted); }}
    footer h3 {{ font-size: 0.7rem; text-transform: uppercase; margin-bottom: 0.5rem; }}
    code {{ background: var(--surface-2); padding: 0 0.3rem; border-radius: 4px; }}
  </style>
</head>
<body>
  <div class="page">
    <header>
      <h1>Singapore Telco Forum Sentiment Dashboard{html.escape(stats["title_suffix"])}</h1>
      <p class="meta">
        Reddit + HWZ &middot; {stats["n"]:,} unique posts in {stats["n_threads"]} telco threads &middot;
        {stats["date_from"]} to {stats["date_to"]} &middot; sentiment: {who} &middot;
        issues: keyword rules + GPT-4o &middot; generated {stats["generated_at"]} &middot; {html.escape(stats["corpus_path"])}
      </p>
    </header>

    {banner}

    <section class="exec-summary">
      <h2>Executive Summary</h2>
      <p>{stats["exec_summary"]}</p>
    </section>

    <section class="huddle">
      <h2>How to use this dashboard</h2>
      <p class="lead">Weekly 30-minute huddle. Charts triage; people decide.</p>
      <div class="huddle-steps">
        <div class="huddle-step"><div class="num">A. Queue</div>
          <p>Not-happy posts in Network Quality, App &amp; Account, or Porting that week. Act only if {html.escape(stats["huddle_rule"])}.</p></div>
        <div class="huddle-step"><div class="num">B. Open 10</div>
          <p>Read ten source posts. Drop sarcasm, mixed-brand, and off-target labels.</p></div>
        <div class="huddle-step"><div class="num">C. Match</div>
          <p>Tie remaining posts to tickets, outages, or billing — not to a vibe.</p></div>
        <div class="huddle-step"><div class="num">D. One owner</div>
          <p>Assign a squad and a response date. No public brand ranking.</p></div>
        <div class="huddle-step"><div class="num">E. Next week</div>
          <p>Check whether that issue share fell. If not, escalate the same owner.</p></div>
      </div>
      <div class="huddle-status">
        <span class="huddle-pill">{len(stats["weeks"])} weeks with queue posts</span>
        <span class="huddle-pill">Threshold: {stats["huddle_threshold"]}</span>
        <span class="huddle-pill">{queue_pill}</span>
      </div>
      <div class="chart-wrap"><canvas id="weekChart"></canvas></div>
      <p class="huddle-warn">Rank only brands with {html.escape(stats["brand_rank_rule"])}. Never publish a brand league table.</p>
    </section>

    <div class="kpi-grid">
      <div class="kpi"><div class="value">{stats["n"]:,}</div><div class="label">Unique posts</div></div>
      <div class="kpi"><div class="value">{stats["n_threads"]}</div><div class="label">Telco threads</div></div>
      <div class="kpi"><div class="value">{sp["not_happy"]}%</div><div class="label">Not happy</div></div>
      <div class="kpi"><div class="value">{sp["happy"]}%</div><div class="label">Happy</div></div>
      <div class="kpi"><div class="value">{sp["neutral"]}%</div><div class="label">Neutral</div></div>
      <div class="kpi"><div class="value">{stats["top3_threads_pct"]}%</div><div class="label">Posts in top 3 threads</div></div>
    </div>

    <div class="charts-grid">
      <div class="chart-card">
        <h3>Forum tone is a screen, not a CSAT score</h3>
        <p class="subtitle">{tone_sub}</p>
        <div class="chart-wrap"><canvas id="sentimentChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>{source_title}</h3>
        <p class="subtitle">
          {who}: Reddit {reddit["not_happy"]}% not happy (n={reddit["n"]:,}) vs HWZ {hwz["not_happy"]}% (n={hwz["n"]:,}).
          Human gold labels: Reddit {gold.get("reddit", {}).get("not_happy", 0)}% vs HWZ {gold.get("hwz", {}).get("not_happy", 0)}%.
          The platforms discuss different topics and periods, so a gap is not a platform effect on its own.
        </p>
        <div class="chart-wrap"><canvas id="sourceChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>{ISSUE_DISPLAY[first]} leads, then {ISSUE_DISPLAY[second]}</h3>
        <p class="subtitle">
          Share of posts per issue, per post and with every thread weighted equally. A finding that holds in both
          is not one big thread talking. General Discussion is a residual, not a team.
        </p>
        <div class="chart-wrap tall"><canvas id="issueChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>{ISSUE_DISPLAY[hurt]} carries the most not-happy discussion</h3>
        <p class="subtitle">
          Count of not-happy posts by primary issue ({who}). Volume is not severity: porting is small but retention-critical.
        </p>
        <div class="chart-wrap tall"><canvas id="unhappyIssueChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Volume of talk is not market share</h3>
        <p class="subtitle">Posts naming each brand. One post can name several brands.</p>
        <div class="chart-wrap tall"><canvas id="brandChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Investigate large-n brands first</h3>
        <p class="subtitle">{ranked_note}</p>
        <div class="chart-wrap tall"><canvas id="negRateChart"></canvas></div>
      </div>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>Per-Telco Highlights</h2>
        <table class="brand-table">
          <thead><tr><th>Telco</th><th>Posts</th><th>Threads</th><th>Not happy</th><th>Top issues</th></tr></thead>
          <tbody>
{table_rows}
          </tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Quotes behind the leading not-happy issues</h2>
{quote_blocks}
      </section>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>What operators should do, in order of not-happy share</h2>
        <ul>
{rec_items}
        </ul>
      </section>
      <section class="panel">
        <h2>How to read the themes</h2>
        <ul>
          <li><strong>Network Quality:</strong> Coverage, dead zones, outages and speed.</li>
          <li><strong>Pricing &amp; Promotions:</strong> Price-value comparisons, discounts and promotion fulfilment.</li>
          <li><strong>Mobile Plans:</strong> SIM-only allowances, contract terms and plan comparisons.</li>
          <li><strong>Roaming:</strong> Regional bundles, activation and overseas use.</li>
          <li><strong>Porting:</strong> Port-in and port-out, rejects and switching.</li>
          <li><strong>Customer Service:</strong> Hotline, agent and escalation experiences.</li>
          <li><strong>Billing &amp; Payment:</strong> Unexpected charges, refunds and payment handling.</li>
          <li><strong>App &amp; Account:</strong> Login, verification and self-service app friction.</li>
          <li><strong>Devices:</strong> Phones, eSIM/SIM cards, routers and operator equipment.</li>
          <li><strong>General Discussion:</strong> Telco news and opinions without a specific service issue.</li>
        </ul>
      </section>
    </div>

    <footer>
      <h3>Limitations</h3>
      <p>
        {stats["n"]:,} unique posts from self-selecting Reddit and HWZ users, not Singapore subscribers.
        {stats["share_2026_pct"]}% are from 2026 and the largest thread is “{html.escape(stats["top_thread"])}”, so brand and
        network shares describe those events as much as the market. Posts in a thread are not independent; compare
        per-post and thread-weighted shares. Sentiment is {who}{", which scored macro F1 0.641 against human labels (VADER 0.380)" if stats["labeller"] == "gpt-4o-mini" else ", which scored macro F1 0.380 against human labels"}.
        One sentiment is copied to every brand a post names. Issue tags are keyword rules plus GPT-4o on unresolved
        rows; the corpus reassignments have no human check. This is a triage queue, not NPS, churn or market share.
        {f"{stats['llm_missing']} post(s) had no GPT-4o-mini label and use VADER." if stats["llm_missing"] else ""}
        {html.escape(stats["extra_limitation"])}
      </p>
    </footer>
  </div>

  <script>
    Chart.defaults.color = "#8b9cb3";
    Chart.defaults.borderColor = "#2d3a4f";
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";

    const sentimentValues = [{sc.get("happy", 0)}, {sc.get("not_happy", 0)}, {sc.get("neutral", 0)}];
    new Chart(document.getElementById("sentimentChart"), {{
      type: "doughnut",
      data: {{ labels: ["Happy", "Not happy", "Neutral"], datasets: [{{ data: sentimentValues,
        backgroundColor: ["#22c55e", "#ef4444", "#94a3b8"], borderWidth: 0 }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, cutout: "58%",
        plugins: {{ legend: {{ position: "right" }}, tooltip: {{ callbacks: {{ label: (ctx) => {{
          const t = sentimentValues.reduce((a,b)=>a+b,0);
          return ` ${{ctx.label}}: ${{ctx.raw}} (${{(100*ctx.raw/t).toFixed(1)}}%)`;
        }} }} }} }} }}
    }});

    new Chart(document.getElementById("sourceChart"), {{
      type: "bar",
      data: {{
        labels: ["Reddit", "HWZ"],
        datasets: [
          {{ label: "Happy", data: [{reddit["happy"]}, {hwz["happy"]}], backgroundColor: "#22c55e" }},
          {{ label: "Not happy", data: [{reddit["not_happy"]}, {hwz["not_happy"]}], backgroundColor: "#ef4444" }},
          {{ label: "Neutral", data: [{reddit["neutral"]}, {hwz["neutral"]}], backgroundColor: "#94a3b8" }}
        ]
      }},
      options: {{ responsive: true, maintainAspectRatio: false,
        scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, max: 100, ticks: {{ callback: v => v+"%" }} }} }},
        plugins: {{ legend: {{ position: "bottom" }} }} }}
    }});

    const issueLabels = {issue_labels_js};
    new Chart(document.getElementById("issueChart"), {{
      type: "bar",
      data: {{ labels: issueLabels, datasets: [
        {{ label: "Per post", data: {issue_post}, backgroundColor: "#3b82f6", borderRadius: 4 }},
        {{ label: "Each thread weighted equally", data: {issue_thread}, backgroundColor: "#f59e0b", borderRadius: 4 }}
      ] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false,
        scales: {{ x: {{ ticks: {{ callback: v => v+"%" }} }} }}, plugins: {{ legend: {{ position: "bottom" }} }} }}
    }});

    new Chart(document.getElementById("unhappyIssueChart"), {{
      type: "bar",
      data: {{ labels: issueLabels, datasets: [{{ data: {unhappy_values}, backgroundColor: "#ef4444", borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    new Chart(document.getElementById("brandChart"), {{
      type: "bar",
      data: {{ labels: {json.dumps([b for b, _ in top_brands])}, datasets: [{{ data: {json.dumps([c for _, c in top_brands])},
        backgroundColor: "#3b82f6", borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const negRates = {json.dumps([b["neg_pct"] for b in ranked])};
    new Chart(document.getElementById("negRateChart"), {{
      type: "bar",
      data: {{ labels: {json.dumps([f"{b['brand']} (n={b['mentions']})" for b in ranked])},
        datasets: [{{ data: negRates, backgroundColor: negRates.map(v => v>=50?"#ef4444":v>=35?"#f59e0b":"#22c55e"), borderRadius: 6 }}] }},
      options: {{ responsive: true, maintainAspectRatio: false,
        scales: {{ y: {{ max: 100, ticks: {{ callback: v => v+"%" }} }} }}, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const weekValues = {week_values};
    new Chart(document.getElementById("weekChart"), {{
      type: "bar",
      data: {{ labels: {week_labels}, datasets: [
        {{ type: "bar", label: "Queue posts (week starting)", data: weekValues,
          backgroundColor: weekValues.map(v => v >= {stats["huddle_threshold"]} ? "#ef4444" : "#3b82f6") }},
        {{ type: "line", label: "Threshold", data: weekValues.map(() => {stats["huddle_threshold"]}),
          borderColor: "#f59e0b", borderDash: [6, 4], pointRadius: 0, borderWidth: 2 }}
      ] }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: "bottom" }} }} }}
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static telco sentiment dashboard HTML + README")
    parser.add_argument(
        "--corpus",
        type=Path,
        default=None,
        help="Clean corpus CSV. Default: the GPT-4o-mini sentiment file if it exists, else the VADER clean corpus.",
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=ROOT / "data/evaluation/gold_labels.csv",
        help="Human-labelled gold set shown next to the corpus sentiment.",
    )
    parser.add_argument("--huddle-threshold", default="auto",
                        help="Weekly queue size that triggers a huddle: a number, or 'auto' (2x the median week).")
    parser.add_argument("--title-suffix", default="", help="Text appended to the page title.")
    parser.add_argument("--extra-limitation", default="", help="Extra sentence for the Limitations footer.")
    parser.add_argument("--out-html", type=Path, default=DASHBOARD_DIR / "index.html")
    parser.add_argument("--out-readme", type=Path, default=DASHBOARD_DIR / "Dash_README.md")
    args = parser.parse_args()

    corpus = args.corpus or (MINI_CORPUS if MINI_CORPUS.exists() else VADER_CORPUS)
    if not corpus.exists():
        raise SystemExit(f"Missing {corpus}. Run: python processing/build_clean_corpus.py")
    for path in (args.out_html, args.out_readme):
        if path.resolve() == corpus.resolve():
            raise SystemExit("Output path equals the corpus path.")
    _, stats = analyse(corpus, args.gold, args.huddle_threshold, args.title_suffix, args.extra_limitation)

    args.out_html.write_text(render_html(stats), encoding="utf-8")
    args.out_readme.write_text(render_readme(stats), encoding="utf-8")

    s = stats["sentiment_pct"]
    print(f"Wrote {args.out_html} ({stats['n']:,} posts, {stats['n_threads']} threads, sentiment: {labeller_name(stats)})")
    print(f"Wrote {args.out_readme}")
    print(f"Sentiment: {s['happy']}% happy / {s['not_happy']}% not_happy / {s['neutral']}% neutral")
    print("Issue share, thread-weighted:", {k: v for k, v in stats["issue_thread"].items() if v})
    print("Action order (not-happy share):", [ISSUE_DISPLAY[k] for k in stats["action_order"]])
    if stats["labeller"] == "vader":
        print("WARNING: VADER fallback. Run models/corpus_llm_sentiment.py, then regenerate.")


if __name__ == "__main__":
    main()
