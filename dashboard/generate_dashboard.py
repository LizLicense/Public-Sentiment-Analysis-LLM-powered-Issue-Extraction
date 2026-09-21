#!/usr/bin/env python3
"""
Regenerate dashboard/index.html and dashboard/Dash_README.md from labeled CSVs.

Default inputs:
  - data/processed/labeled_sample.csv   (Reddit)
  - hwz_telco_posts_labeled.csv         (HWZ, project root)
  - data/processed/issues_*_gpt4o_hybrid.csv (issue overlay)

Usage (from project root):
  python dashboard/generate_dashboard.py
  python dashboard/generate_dashboard.py --reddit data/processed/labeled_sample.csv --hwz hwz_telco_posts_labeled.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent

TELCO_KEYWORDS = [
    "singtel", "starhub", "m1", "simba", "giga", "eight", "zym",
    "redone", "gomo", "circles", "vivifi", "myrepublic", "maxx", "heya", "zero1", "povo",
]

EIGHT_CONTEXT_TERMS = (
    r"telco|telecom|mobile|mvno|sim(?:-only)?|plan|network|roaming|"
    r"port(?:ing)?|data|gb|4g|5g|starhub|singtel|m1|simba|giga|zym"
)
EIGHT_STRONG_PATTERN = re.compile(
    r"\beight\s+(?:telecom|telco|mobile|sim(?:-only)?|plan)\b|"
    r"\b(?:telecom|telco|mobile|mvno)\s+(?:brand\s+)?eight\b|"
    r"\beight\.sg\b",
    re.IGNORECASE,
)
EIGHT_CONTEXT_PATTERN = re.compile(
    rf"(?:\beight\b.{{0,60}}\b(?:{EIGHT_CONTEXT_TERMS})\b|"
    rf"\b(?:{EIGHT_CONTEXT_TERMS})\b.{{0,60}}\beight\b)",
    re.IGNORECASE | re.DOTALL,
)
EIGHT_NON_BRAND_PATTERN = re.compile(
    r"\beight(?:\s+|-)(?:"
    r"buses?|people|persons?|years?|months?|weeks?|days?|hours?|minutes?|seconds?|"
    r"times?|students?|workers?|cars?|teams?|points?|seats?|stations?|stops?|"
    r"cases?|episodes?|members?|children|men|women"
    r")\b",
    re.IGNORECASE,
)

BRAND_MAP = [
    ("singtel", "Singtel"), ("starhub", "StarHub"), ("m1", "M1"), ("simba", "SIMBA"),
    ("giga", "Giga"), ("eight", "Eight"), ("zym", "Zym"), ("redone", "redONE"),
    ("gomo", "GOMO"), ("circles", "Circles"), ("vivifi", "Vivifi"),
    ("myrepublic", "MyRepublic"), ("maxx", "Maxx"), ("heya", "Heya"), ("zero1", "Zero1"),
]

ISSUE_KW = {
    "network_quality": r"\b(signal|coverage|speed|slow|lte|5g|4g|network|dead spot|dark spot|drop|latency|bandwidth|apn|connection|priority|tier|outage)\b",
    "pricing_promotions": r"\b(price|pricing|cheap|expensive|cost|fee|promo|promotion|discount|deal|value|cashback|voucher)\b|\$\d|s\$",
    "mobile_plans": r"\b(plan|sim[- ]?only|subscription|contract|gb|unlimited|data allowance|minutes|sms|mvno)\b",
    "roaming": r"\b(roam|roaming|malaysia|overseas|travel|idd|international data|apac|worldwide)\b",
    "porting": r"\b(port|porting|port out|port in|number transfer|transfer number|mnp|switch telco)\b",
    "customer_service": r"\b(customer service|support|hotline|agent|complain|frustrat|service cent(?:er|re)|escalat)\b",
    "billing_payment": r"\b(bill|billing|charged|charge|payment|pay|refund|invoice|credit card|giro|auto[- ]?debit)\b",
    "app_account": r"\b(app|application|account|log[ -]?in|sign[ -]?in|password|otp|portal|dashboard|verification)\b",
    "devices": r"\b(device|phone|handset|iphone|android|esim|sim card|router|modem|onr|ont|equipment)\b",
}

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

HUDDLE_ISSUES = ("network_quality", "app_account", "porting")
HUDDLE_THRESHOLD = 20

BRAND_TOP_ISSUE_HINTS = {
    "Eight": "Launch pricing, tiering, porting",
    "StarHub": "Pricing, CS, promo fulfilment",
    "M1": "Network coverage, 4G/5G",
    "Singtel": "ONR/bridge mode, equipment",
    "Zym": "Promotional plan posts",
    "Giga": "Network reliability (small n)",
    "SIMBA": "MVNO price benchmark",
    "GOMO": "Roaming, host-network",
}


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def is_eight_telco_reference(text: str) -> bool:
    if not re.search(r"\beight\b", text or "", re.IGNORECASE):
        return False
    if EIGHT_STRONG_PATTERN.search(text):
        return True
    if EIGHT_NON_BRAND_PATTERN.search(text):
        return False
    return bool(EIGHT_CONTEXT_PATTERN.search(text))


def clean_telco_label(label: str, text: str, title: str) -> str:
    parts = [part.strip() for part in re.split(r"[,;/|&]+", label or "") if part.strip()]
    if any(part.lower().replace(" ", "") == "eight" for part in parts):
        if not is_eight_telco_reference(f"{title} {text}"):
            parts = [part for part in parts if part.lower().replace(" ", "") != "eight"]
    return ",".join(parts)


def text_match_key(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip().lower()[:500]


def load_hybrid_issue_lookup(path: Path) -> dict[str, dict[str, str]]:
    lookup = {"by_comment": {}, "by_text": {}}
    if not path.exists():
        return lookup
    for row in read_csv(path):
        primary = (row.get("issue_primary") or "").strip()
        labels = (row.get("issue_labels") or "").strip()
        if not primary and labels:
            primary = labels.split(",")[0].strip()
        if primary not in ISSUE_DISPLAY:
            continue
        comment_id = str(row.get("comment_id") or "").strip()
        if comment_id and comment_id.lower() not in {"nan", "none"}:
            lookup["by_comment"][comment_id] = primary
        key = text_match_key(row.get("post_text") or "")
        if key:
            lookup["by_text"][key] = primary
    return lookup


def lookup_hybrid_issue(row: dict, lookup: dict[str, dict[str, str]]) -> str:
    comment_id = str(row.get("comment_id") or "").strip()
    if comment_id and comment_id in lookup["by_comment"]:
        return lookup["by_comment"][comment_id]
    key = text_match_key(row.get("post_text") or "")
    if key and key in lookup["by_text"]:
        return lookup["by_text"][key]
    return ""


def normalize_row(row: dict, source: str) -> dict:
    sentiment = (
        row.get("sentiment_label")
        or row.get("sentiment_label_manual")
        or row.get("llm_sentiment_label")
        or ""
    ).strip()
    issue = (row.get("issue_primary") or row.get("issue_manual") or "").strip()
    thread_title = (row.get("thread_title") or row.get("title") or "").strip()
    post_text = (row.get("post_text") or row.get("selftext") or "").strip()
    telco_label = clean_telco_label(
        (row.get("telco_label") or row.get("telco_mentioned") or "").strip(),
        post_text,
        thread_title,
    )
    return {
        "source": source,
        "comment_id": str(row.get("comment_id") or "").strip(),
        "telco_label": telco_label,
        "sentiment": sentiment,
        "issue_primary": issue,
        "thread_title": thread_title,
        "post_text": post_text,
    }


def is_telco_relevant(row: dict) -> bool:
    label = row["telco_label"].lower()
    combined = f"{label} {row['post_text'].lower()} {row['thread_title'].lower()}"
    if label:
        return True
    non_eight_keywords = [keyword for keyword in TELCO_KEYWORDS if keyword != "eight"]
    return any(k in combined for k in non_eight_keywords) or is_eight_telco_reference(combined)


def norm_sentiment(s: str) -> str:
    s = (s or "").lower().strip()
    if s in ("happy", "positive"):
        return "happy"
    if s in ("not_happy", "negative", "not happy"):
        return "not_happy"
    if s == "neutral":
        return "neutral"
    return ""


def infer_sentiment(text: str) -> str:
    s = (text or "").lower()
    neg = len(re.findall(
        r"\b(bad|poor|terrible|awful|frustrat|hate|suck|shit|scam|issue|problem|no thanks|cancel|worst|disappoint|unable|greedy)\b",
        s,
    ))
    pos = len(re.findall(
        r"\b(good|great|awesome|fine|no problem|no issue|happy|love|recommend|promising|lucky|excellent|smooth|works|reliable)\b",
        s,
    ))
    if neg > pos:
        return "not_happy"
    if pos > neg:
        return "happy"
    return "neutral"


def infer_issue(text: str, title: str = "") -> str:
    combined = f"{text} {title}".lower()
    scores = {k: len(re.findall(v, combined, re.I)) for k, v in ISSUE_KW.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general_discussion"


def split_brands(label: str, text: str = "", title: str = "") -> list[str]:
    found: list[str] = []
    if label:
        for part in re.split(r"[,;/|&]+", label):
            pl = part.strip().lower().replace(" ", "")
            for key, name in BRAND_MAP:
                if key in pl:
                    found.append(name)
                    break
    if not found:
        combined = f"{text} {title}".lower()
        for key, name in BRAND_MAP:
            if key == "eight":
                if is_eight_telco_reference(combined):
                    found.append(name)
            elif key in combined:
                found.append(name)
    seen: set[str] = set()
    out: list[str] = []
    for b in found:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def pct(n: int, total: int) -> int:
    return round(100 * n / total) if total else 0


def short_quote(text: str, max_words: int = 22) -> str:
    text = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def pick_quotes(rows: list[dict], n: int = 4) -> list[dict]:
    """Pick short, thematic quotes — prefer not_happy for pain, happy for roaming."""
    candidates: list[tuple[int, dict]] = []
    for row in rows:
        text = row["post_text"]
        if len(text) < 25 or len(text) > 400:
            continue
        if re.search(r"please log in|last edited:", text.lower()):
            continue
        score = 0
        if row["sentiment_final"] == "not_happy":
            score += 2
        if row["issue_final"] in (
            "network_quality",
            "pricing_promotions",
            "billing_payment",
            "customer_service",
            "porting",
        ):
            score += 1
        if 40 <= len(text) <= 180:
            score += 1
        candidates.append((score, row))
    candidates.sort(key=lambda x: (-x[0], len(x[1]["post_text"])))
    seen: set[str] = set()
    quotes: list[dict] = []
    for _, row in candidates:
        q = short_quote(row["post_text"])
        if q in seen:
            continue
        seen.add(q)
        brands = ", ".join(split_brands(row["telco_label"], row["post_text"], row["thread_title"])[:3])
        quotes.append({
            "text": q,
            "source": row["source"].upper(),
            "context": brands or row["issue_final"],
        })
        if len(quotes) >= n:
            break
    return quotes


def build_executive_summary(stats: dict) -> str:
    s = stats["sentiment_pct"]
    src = stats["source_pct"]
    ic = stats["issue_pct"]
    ranked = [b for b in stats["neg_brands"] if b["mentions"] >= 10][:2]
    neg_names = " and ".join(b["brand"] for b in ranked) if ranked else "larger brands"
    app_pct = ic.get("app_account", 0)
    net_pct = ic.get("network_quality", 0)
    return (
        f"This dashboard is an <strong>early-warning screen</strong>, not a CSAT or NPS score. "
        f"About {s['happy']}% of {stats['n']} telco-relevant posts look happy, but VADER under-detects "
        f"complaints, so the true negative share is likely higher. "
        f"<strong>Start complaint review on Reddit</strong> ({src.get('reddit', {}).get('not_happy', 0)}% not-happy vs "
        f"{src.get('hwz', {}).get('not_happy', 0)}% on HWZ); HWZ is launch-thread heavy, not happier customers. "
        f"<strong>Route App &amp; Account ({app_pct}%) and Network Quality ({net_pct}%) first</strong>. "
        f"Among brands with at least 10 mentions, <strong>{neg_names}</strong> warrant deeper review. "
        f"Do not rank Giga, SIMBA or Zym from tiny samples. "
        f"The operating use is a <strong>weekly 30-minute huddle</strong>: "
        f"this sample has {stats['huddle_n']} not-happy Network/App/Porting posts "
        f"(act only if n ≥ {HUDDLE_THRESHOLD}). Never publish a brand league table from n=6."
    )


def analyse(reddit_path: Path, hwz_path: Path, issues_path: Path) -> tuple[list[dict], dict]:
    hybrid_lookup = load_hybrid_issue_lookup(issues_path)
    rows: list[dict] = []
    for path, source in [(reddit_path, "reddit"), (hwz_path, "hwz")]:
        if not path.exists():
            raise FileNotFoundError(f"Missing input: {path}")
        for raw in read_csv(path):
            rows.append(normalize_row(raw, source))

    telco_rows: list[dict] = []
    hybrid_hits = 0
    for row in rows:
        if not is_telco_relevant(row):
            continue
        row = dict(row)
        row["sentiment_final"] = norm_sentiment(row["sentiment"]) or infer_sentiment(row["post_text"])
        hybrid_issue = lookup_hybrid_issue(row, hybrid_lookup)
        if hybrid_issue:
            row["issue_final"] = hybrid_issue
            hybrid_hits += 1
        elif row["issue_primary"] in ISSUE_DISPLAY:
            row["issue_final"] = row["issue_primary"]
        else:
            row["issue_final"] = infer_issue(row["post_text"], row["thread_title"])
        telco_rows.append(row)

    n = len(telco_rows)
    sent_counts = Counter(r["sentiment_final"] for r in telco_rows)
    issue_counts = Counter(r["issue_final"] for r in telco_rows)
    huddle_n = sum(
        1
        for r in telco_rows
        if r["sentiment_final"] == "not_happy" and r["issue_final"] in HUDDLE_ISSUES
    )
    unhappy_issue_counts = Counter(
        r["issue_final"] for r in telco_rows if r["sentiment_final"] == "not_happy"
    )

    source_rows = defaultdict(list)
    for r in telco_rows:
        source_rows[r["source"]].append(r)

    source_pct: dict[str, dict[str, int]] = {}
    for src, sub in source_rows.items():
        sc = Counter(r["sentiment_final"] for r in sub)
        ln = len(sub)
        source_pct[src] = {k: pct(sc[k], ln) for k in ("happy", "not_happy", "neutral")}
        source_pct[src]["n"] = ln

    brand_rows: dict[str, list[dict]] = defaultdict(list)
    for r in telco_rows:
        for b in split_brands(r["telco_label"], r["post_text"], r["thread_title"]):
            brand_rows[b].append(r)

    brand_mentions = sorted(brand_rows.items(), key=lambda x: -len(x[1]))
    neg_brands: list[dict] = []
    brand_table: list[dict] = []
    for brand, sub in brand_mentions:
        ln = len(sub)
        sc = Counter(r["sentiment_final"] for r in sub)
        neg = pct(sc["not_happy"], ln)
        ic = Counter(r["issue_final"] for r in sub)
        top_issues = ", ".join(
            ISSUE_DISPLAY.get(k, k)
            for k, _ in ic.most_common(2)
            if k != "general_discussion"
        )
        brand_table.append({
            "brand": brand,
            "mentions": ln,
            "neg_pct": neg,
            "top_issues": BRAND_TOP_ISSUE_HINTS.get(brand, top_issues or "General discussion"),
        })
        if ln >= 5:
            neg_brands.append({"brand": brand, "neg_pct": neg, "mentions": ln})

    neg_brands.sort(key=lambda x: -x["neg_pct"])
    neg_brands_ranked = [b for b in neg_brands if b["mentions"] >= 10]

    stats = {
        "n": n,
        "huddle_n": huddle_n,
        "huddle_threshold": HUDDLE_THRESHOLD,
        "reddit_path": str(reddit_path.relative_to(ROOT)) if reddit_path.is_relative_to(ROOT) else str(reddit_path),
        "hwz_path": str(hwz_path.relative_to(ROOT)) if hwz_path.is_relative_to(ROOT) else str(hwz_path),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sentiment_counts": {k: sent_counts[k] for k in ("happy", "not_happy", "neutral")},
        "sentiment_pct": {k: pct(sent_counts[k], n) for k in ("happy", "not_happy", "neutral")},
        "issue_counts": {k: issue_counts.get(k, 0) for k in ISSUE_LABELS},
        "issue_pct": {k: pct(issue_counts.get(k, 0), n) for k in ISSUE_LABELS},
        "unhappy_issue_counts": {k: unhappy_issue_counts.get(k, 0) for k in ISSUE_LABELS},
        "neg_brands_ranked": neg_brands_ranked,
        "source_pct": source_pct,
        "brand_mentions": [(b, len(sub)) for b, sub in brand_mentions[:10]],
        "neg_brands": neg_brands,
        "brand_table": [b for b in brand_table if b["mentions"] >= 5][:8],
        "n_brands": len(brand_rows),
        "n_sources": len(source_rows),
        "quotes": pick_quotes(telco_rows),
        "issues_inferred": hybrid_hits == 0 and not any(r["issue_primary"] for r in rows),
        "hybrid_hits": hybrid_hits,
        "issues_path": (
            str(issues_path.relative_to(ROOT)) if issues_path.is_relative_to(ROOT) else str(issues_path)
        ),
    }
    stats["exec_summary"] = build_executive_summary(stats)
    return telco_rows, stats


def render_readme(stats: dict) -> str:
    reddit_n = stats["source_pct"].get("reddit", {}).get("n", 0)
    hwz_n = stats["source_pct"].get("hwz", {}).get("n", 0)
    return f"""# Telco Sentiment Dashboard

Static HTML summary dashboard for Singapore telco forum sentiment analysis.

**Auto-generated:** {stats["generated_at"]}

## Generate / refresh

From project root:

```bash
python dashboard/generate_dashboard.py
```

Optional custom inputs:

```bash
python dashboard/generate_dashboard.py \\
  --reddit data/processed/labeled_sample.csv \\
  --hwz hwz_telco_posts_labeled.csv \\
  --issues data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv
```

Writes `dashboard/index.html` and this file.

## View

Open in any browser (no server required):

```bash
open dashboard/index.html
```

Or from the project root:

```bash
python3 -m http.server 8080
# then visit http://localhost:8080/dashboard/
```

## Contents

- **Weekly huddle playbook** (queue → 10 posts → tickets → one owner → next week)
- **Executive summary** and KPI cards
- **Charts** with takeaway titles: tone vs CSAT, Reddit-first complaints, issue routing, not-happy themes, mention volume, large-n negative tone
- **Per-telco table** (n<10 flagged), quotes, owner-action recommendations, limitations

## Data source

| File | Rows (telco-relevant) |
|------|----------------------|
| `{stats["reddit_path"]}` | {reddit_n} |
| `{stats["hwz_path"]}` | {hwz_n} |
| **Combined** | **{stats["n"]}** |

Sentiment: {stats["sentiment_pct"]["happy"]}% happy / {stats["sentiment_pct"]["not_happy"]}% not_happy / {stats["sentiment_pct"]["neutral"]}% neutral.

Issue labels: keyword rules, then GPT-4o on unresolved `general_discussion` rows (`{stats.get("issues_path", "")}`; {stats.get("hybrid_hits", 0)} of {stats["n"]} dashboard posts matched).

## Streamlit version

For an interactive filterable dashboard, run:

```bash
pip install streamlit plotly pandas
streamlit run dashboard/app.py
```
"""


def render_html(stats: dict) -> str:
    sc = stats["sentiment_counts"]
    sp = stats["sentiment_pct"]
    ic = stats["issue_counts"]
    issue_labels_js = [ISSUE_DISPLAY[k] for k in ISSUE_LABELS]
    issue_order = ISSUE_LABELS
    issue_values = [ic[k] for k in issue_order]
    issue_colors = [ISSUE_COLORS[k] for k in issue_order]
    unhappy_values = [stats["unhappy_issue_counts"][k] for k in issue_order]

    brand_labels = [b for b, _ in stats["brand_mentions"]]
    brand_values = [n for _, n in stats["brand_mentions"]]

    ranked = stats.get("neg_brands_ranked") or [b for b in stats["neg_brands"] if b["mentions"] >= 10]
    neg_labels = [b["brand"] for b in ranked]
    neg_rates = [b["neg_pct"] for b in ranked]

    reddit = stats["source_pct"].get("reddit", {"happy": 0, "not_happy": 0, "neutral": 0, "n": 0})
    hwz = stats["source_pct"].get("hwz", {"happy": 0, "not_happy": 0, "neutral": 0, "n": 0})

    def brand_cell(row: dict) -> str:
        note = ' <span class="small-n">n&lt;10</span>' if row["mentions"] < 10 else ""
        return (
            f'            <tr><td>{html.escape(row["brand"])}{note}</td>'
            f'<td>{row["mentions"]}</td>'
            f'<td>{row["neg_pct"]}%</td><td>{html.escape(row["top_issues"])}</td></tr>'
        )

    table_rows = "\n".join(brand_cell(r) for r in stats["brand_table"])

    quote_blocks = "\n".join(
        f"""        <blockquote>
          "{html.escape(q["text"])}"
          <div class="quote-source">{html.escape(q["source"])} &middot; {html.escape(q["context"])}</div>
        </blockquote>"""
        for q in stats["quotes"]
    )

    issue_note = (
        f"Issue labels: keyword rules then GPT-4o on unresolved general_discussion "
        f"({stats.get('hybrid_hits', 0)} of {stats['n']} posts matched to "
        f"{stats.get('issues_path', 'hybrid issues file')})"
        if stats.get("hybrid_hits")
        else (
            "Inferred from post_text (issue_primary not in Reddit export)"
            if stats["issues_inferred"]
            else "From issue_primary / issue_manual columns"
        )
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Singapore Telco Forum Sentiment Dashboard</title>
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
    .huddle-status {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; }}
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
    .small-n {{ color: #f59e0b; font-size: 0.65rem; text-transform: none; letter-spacing: 0; }}
    .chart-wrap {{ position: relative; height: 280px; }}
    .chart-wrap.tall {{ height: 320px; }}
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
  </style>
</head>
<body>
  <div class="page">
    <header>
      <h1>Singapore Telco Forum Sentiment Dashboard</h1>
      <p class="meta">
        Scope: All telcos &middot; Sources: Reddit + HWZ &middot;
        Sample: {stats["n"]} telco-relevant posts &middot;
        Generated {stats["generated_at"]} &middot;
        {html.escape(stats["reddit_path"])} + {html.escape(stats["hwz_path"])}
        &middot; issues: {html.escape(stats.get("issues_path", "keyword fallback"))}
      </p>
    </header>

    <section class="exec-summary">
      <h2>Executive Summary</h2>
      <p>{stats["exec_summary"]}</p>
    </section>

    <section class="huddle">
      <h2>How to use this dashboard</h2>
      <p class="lead">
        Weekly 30-minute huddle. Charts triage; people decide. This is the operating purpose of the project.
      </p>
      <div class="huddle-steps">
        <div class="huddle-step">
          <div class="num">A. Queue</div>
          <p>Keep not-happy posts in Network Quality, App &amp; Account, or Porting. Act only if n ≥ {stats["huddle_threshold"]}.</p>
        </div>
        <div class="huddle-step">
          <div class="num">B. Open 10</div>
          <p>Read ten source posts. Drop sarcasm, mixed-brand, and off-target labels.</p>
        </div>
        <div class="huddle-step">
          <div class="num">C. Match</div>
          <p>Tie remaining posts to tickets, outages, or billing — not to a vibe.</p>
        </div>
        <div class="huddle-step">
          <div class="num">D. One owner</div>
          <p>Assign a squad and a response date. No public brand ranking.</p>
        </div>
        <div class="huddle-step">
          <div class="num">E. Next week</div>
          <p>Check whether that issue share fell. If not, escalate the same owner.</p>
        </div>
      </div>
      <div class="huddle-status">
        <span class="huddle-pill">Queue this sample: {stats["huddle_n"]} posts</span>
        <span class="huddle-pill">Threshold: {stats["huddle_threshold"]}</span>
        <span class="huddle-pill">
          {"Hold huddle" if stats["huddle_n"] >= stats["huddle_threshold"] else "Below threshold — do not escalate"}
        </span>
      </div>
      <p class="huddle-warn">Never publish a brand league table from n = 6. Rank only brands with at least 10 mentions.</p>
    </section>

    <div class="kpi-grid">
      <div class="kpi"><div class="value">{stats["n"]}</div><div class="label">Telco posts</div></div>
      <div class="kpi"><div class="value">{sp["happy"]}%</div><div class="label">Happy</div></div>
      <div class="kpi"><div class="value">{sp["not_happy"]}%</div><div class="label">Not happy</div></div>
      <div class="kpi"><div class="value">{sp["neutral"]}%</div><div class="label">Neutral</div></div>
      <div class="kpi"><div class="value">{stats["n_brands"]}</div><div class="label">Brands mentioned</div></div>
      <div class="kpi"><div class="value">{stats["n_sources"]}</div><div class="label">Sources</div></div>
    </div>

    <div class="charts-grid">
      <div class="chart-card">
        <h3>Forum tone is a screen, not a CSAT score</h3>
        <p class="subtitle">
          {sp["happy"]}% happy on n={stats["n"]} (VADER). Independent labels show VADER misses many
          complaints, so treat this mix as an upper bound on positivity.
        </p>
        <div class="chart-wrap"><canvas id="sentimentChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Start complaint review on Reddit</h3>
        <p class="subtitle">
          Reddit {reddit["not_happy"]}% not-happy (n={reddit["n"]}) vs HWZ {hwz["not_happy"]}% (n={hwz["n"]}).
          HWZ over-represents launch threads — not happier customers.
        </p>
        <div class="chart-wrap"><canvas id="sourceChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Route App &amp; Account and Network Quality first</h3>
        <p class="subtitle">
          Largest actionable volumes. Issues are keyword rules, then GPT-4o only where rules left
          General Discussion. That residual is not a team.
        </p>
        <div class="chart-wrap tall"><canvas id="issueChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Volume of talk is not dissatisfaction</h3>
        <p class="subtitle">
          Mention counts are row-expanded and one post can name several brands. Do not read this as market share.
        </p>
        <div class="chart-wrap tall"><canvas id="brandChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Which themes actually hurt?</h3>
        <p class="subtitle">
          Count of not-happy posts by primary issue. Porting can be small but high-severity (rejects, IMDA).
        </p>
        <div class="chart-wrap tall"><canvas id="unhappyIssueChart"></canvas></div>
      </div>
      <div class="chart-card">
        <h3>Investigate large-n brands first</h3>
        <p class="subtitle">
          % not-happy for brands with at least 10 mentions. Giga/SIMBA/Zym are in the table only — too small to rank.
        </p>
        <div class="chart-wrap tall"><canvas id="negRateChart"></canvas></div>
      </div>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>Per-Telco Highlights</h2>
        <table class="brand-table">
          <thead><tr><th>Telco</th><th>Mentions</th><th>Neg %</th><th>Top issues</th></tr></thead>
          <tbody>
{table_rows}
          </tbody>
        </table>
      </section>
      <section class="panel">
        <h2>Quotes that support the charts</h2>
{quote_blocks}
      </section>
    </div>

    <div class="two-col">
      <section class="panel">
        <h2>What operators should do</h2>
        <ul>
          <li><strong>CX / digital:</strong> Own App &amp; Account (login, OTP, chatbot dead-ends). Track time-to-human and login-failure posts after each app release.</li>
          <li><strong>Network:</strong> Pair MRT/building complaints with tickets. Publish indoor/MRT guidance instead of national coverage claims.</li>
          <li><strong>MVNO / product:</strong> Disclose host network, 5G SA and fair-use at checkout (GOMO/Singtel, Eight/StarHub, Zym).</li>
          <li><strong>MNP ops:</strong> Show a specific port-reject reason and next step. Own avoidable-reject rate and median port time.</li>
          <li><strong>Commercial:</strong> Publish intro vs recurring price and promo expiry. Monitor fulfilment complaints, not list price alone.</li>
          <li><strong>Roaming:</strong> In-app “travelling to X” checklist (activation, 3G sunset, divert charges) before the bill.</li>
          <li><strong>Insight huddle:</strong> Follow the five-step playbook at the top of this page. Do not skip to brand ranks.</li>
        </ul>
      </section>
      <section class="panel">
        <h2>How to read the themes</h2>
        <ul>
          <li><strong>Network Quality:</strong> Hyper-local coverage, dead zones, outages and MVNO priority concerns.</li>
          <li><strong>Pricing &amp; Promotions:</strong> Price-value comparisons, discounts and promotion fulfilment.</li>
          <li><strong>Mobile Plans:</strong> SIM-only allowances, contract terms and plan-feature comparisons.</li>
          <li><strong>Roaming:</strong> Regional bundles, activation and Malaysia travel experiences.</li>
          <li><strong>Porting:</strong> Eight port-in limits; brand missing from port dropdowns.</li>
          <li><strong>Customer Service:</strong> Hotline, agent and escalation experiences.</li>
          <li><strong>Billing &amp; Payment:</strong> Unexpected charges, refunds and payment handling.</li>
          <li><strong>App &amp; Account:</strong> Login, verification and self-service app friction.</li>
          <li><strong>Devices:</strong> Phones, eSIM/SIM cards, routers and operator equipment.</li>
          <li><strong>General Discussion:</strong> Telco news, opinions and records without a specific service issue.</li>
        </ul>
      </section>
    </div>

    <footer>
      <h3>Limitations</h3>
      <p>
        n={stats["n"]} telco-relevant posts from Reddit + HWZ — not Singapore subscribers.
        The 15,504-row corpus is ~97% Reddit, with heavy duplicate text and ~150 unique threads.
        Dashboard mix (67 Reddit / 91 HWZ) is not the corpus mix. Sentiment is VADER and likely too positive;
        independent labels show not-happy recall of 0.34. Issue tags are keyword rules plus GPT-4o on unresolved
        rows; all-row GPT-4o still misses Devices, which is why rules are kept first. Brands with n&lt;10 are shown
        in the table only. This is a triage queue, not NPS, churn or market share.
        {html.escape(issue_note)}.
      </p>
    </footer>
  </div>

  <script>
    Chart.defaults.color = "#8b9cb3";
    Chart.defaults.borderColor = "#2d3a4f";
    Chart.defaults.font.family = "'Segoe UI', system-ui, sans-serif";

    const sentimentData = {{ labels: ["Happy", "Not happy", "Neutral"], values: [{sc["happy"]}, {sc["not_happy"]}, {sc["neutral"]}],
      colors: ["#22c55e", "#ef4444", "#94a3b8"] }};

    new Chart(document.getElementById("sentimentChart"), {{
      type: "doughnut",
      data: {{ labels: sentimentData.labels, datasets: [{{ data: sentimentData.values, backgroundColor: sentimentData.colors, borderWidth: 0 }}] }},
      options: {{ responsive: true, maintainAspectRatio: false, cutout: "58%",
        plugins: {{ legend: {{ position: "right" }}, tooltip: {{ callbacks: {{ label: (ctx) => {{
          const t = sentimentData.values.reduce((a,b)=>a+b,0);
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
    const issueValues = {issue_values};
    const issueColors = {issue_colors};
    const unhappyValues = {unhappy_values};

    new Chart(document.getElementById("issueChart"), {{
      type: "bar",
      data: {{ labels: issueLabels, datasets: [{{ data: issueValues, backgroundColor: issueColors, borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    new Chart(document.getElementById("unhappyIssueChart"), {{
      type: "bar",
      data: {{ labels: issueLabels, datasets: [{{ data: unhappyValues, backgroundColor: "#ef4444", borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    new Chart(document.getElementById("brandChart"), {{
      type: "bar",
      data: {{ labels: {brand_labels}, datasets: [{{ data: {brand_values}, backgroundColor: "#3b82f6", borderRadius: 6 }}] }},
      options: {{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
    }});

    const negRates = {neg_rates};
    new Chart(document.getElementById("negRateChart"), {{
      type: "bar",
      data: {{
        labels: {neg_labels},
        datasets: [{{ data: negRates, backgroundColor: negRates.map(v => v>=50?"#ef4444":v>=25?"#f59e0b":"#22c55e"), borderRadius: 6 }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false,
        scales: {{ y: {{ max: 80, ticks: {{ callback: v => v+"%" }} }} }},
        plugins: {{ legend: {{ display: false }} }} }}
    }});
  </script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate static telco sentiment dashboard HTML + README")
    parser.add_argument("--reddit", type=Path, default=ROOT / "data/processed/labeled_sample.csv")
    parser.add_argument("--hwz", type=Path, default=ROOT / "hwz_telco_posts_labeled.csv")
    parser.add_argument(
        "--issues",
        type=Path,
        default=ROOT / "data/processed/issues_posts_labeled_2026-08-21_203752_gpt4o_hybrid.csv",
        help="Hybrid issue file: keyword rules plus GPT-4o on unresolved rows.",
    )
    parser.add_argument("--out-html", type=Path, default=DASHBOARD_DIR / "index.html")
    parser.add_argument("--out-readme", type=Path, default=DASHBOARD_DIR / "Dash_README.md")
    args = parser.parse_args()

    _, stats = analyse(args.reddit, args.hwz, args.issues)

    args.out_html.write_text(render_html(stats), encoding="utf-8")
    args.out_readme.write_text(render_readme(stats), encoding="utf-8")

    print(f"Wrote {args.out_html} ({stats['n']} telco-relevant posts)")
    print(f"Wrote {args.out_readme}")
    print(
        f"Sentiment: {stats['sentiment_pct']['happy']}% happy / "
        f"{stats['sentiment_pct']['not_happy']}% not_happy / "
        f"{stats['sentiment_pct']['neutral']}% neutral"
    )
    print(f"Hybrid issue matches: {stats.get('hybrid_hits', 0)}/{stats['n']}")
    print("Issue counts:", stats["issue_counts"])


if __name__ == "__main__":
    main()
